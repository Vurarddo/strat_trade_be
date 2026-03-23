from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import InvalidMarketParametersError
from strat_trade.ports.candles import CandleFeed


@dataclass(frozen=True, slots=True)
class CandlesPageResult:
    """One HTTP page; range-only fields stay None for GET /market/candles."""

    candles: list[Candle]
    has_more: bool
    next_cursor: datetime | None
    total: int | None = None
    broker_chunk_oldest: datetime | None = None
    broker_chunk_newest: datetime | None = None
    broker_overlap: bool | None = None


def _utc(dt: datetime) -> datetime:
    """Broker/API may mix naive and aware timestamps; compare and key everything in UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _dedupe_by_open_time(candles: list[Candle]) -> list[Candle]:
    seen: set[datetime] = set()
    out: list[Candle] = []
    for c in sorted(candles, key=lambda x: x.open_time):
        if c.open_time in seen:
            continue
        seen.add(c.open_time)
        out.append(c)
    return out


async def fetch_recent_candles(
    feed: CandleFeed,
    *,
    asset: str,
    timeframe_seconds: int,
    count: int,
    max_count: int,
    end_at: datetime | None = None,
    cursor: datetime | None = None,
) -> CandlesPageResult:
    """
    Latest `count` bars ending at `end_at` (or broker “now”), walking backward with `cursor`
    for older pages (cursor = exclusive upper bound on open_time).
    """
    if cursor is not None and end_at is not None:
        raise InvalidMarketParametersError(
            "Use either `cursor` (older pages) or `end_at` (first page anchor), not both."
        )
    if timeframe_seconds < 1:
        raise InvalidMarketParametersError("timeframe_seconds must be >= 1.")
    if count > max_count:
        raise InvalidMarketParametersError(
            f"count must be <= {max_count}. Raise STRAT_TRADE_MAX_CANDLES_PER_REQUEST "
            f"(or MAX_CANDLES_PER_REQUEST) up to 5000 if you need a higher server cap."
        )
    asset_clean = asset.strip()
    if not asset_clean:
        raise InvalidMarketParametersError("asset must be a non-empty symbol.")

    if cursor is not None:
        effective_end = cursor - timedelta(microseconds=1)
    else:
        effective_end = end_at

    raw = await feed.get_candles(
        asset_clean,
        timeframe_seconds,
        count=count,
        end_time=effective_end,
    )
    ordered = _dedupe_by_open_time(raw)
    if cursor is not None:
        cu = _utc(cursor)
        ordered = [c for c in ordered if _utc(c.open_time) < cu]

    if len(ordered) > count:
        ordered = ordered[-count:]

    has_more = len(ordered) == count
    next_cursor = _utc(ordered[0].open_time) if has_more and ordered else None

    return CandlesPageResult(
        candles=ordered,
        has_more=has_more,
        next_cursor=next_cursor,
    )


def _range_broker_overlap(
    *,
    rs: datetime,
    re: datetime,
    total: int,
    chunk_old: datetime | None,
    chunk_new: datetime | None,
) -> bool | None:
    if chunk_old is None or chunk_new is None:
        return None
    overlaps = not (re < chunk_old or rs > chunk_new)
    if total > 0:
        return overlaps
    if not overlaps:
        return False
    return True


def _raw_chunk_open_bounds(raw: list[Candle]) -> tuple[datetime | None, datetime | None]:
    deduped = _dedupe_by_open_time(raw)
    if not deduped:
        return None, None
    times = [_utc(c.open_time) for c in deduped]
    return min(times), max(times)


async def _load_range_window(
    feed: CandleFeed,
    *,
    asset_clean: str,
    timeframe_seconds: int,
    range_start: datetime,
    range_end: datetime,
    max_chunk: int,
    max_bars_in_range: int,
    max_fetch_rounds: int,
) -> tuple[list[Candle], datetime | None, datetime | None]:
    """
    Load all bars in `[range_start, range_end]` by paging backward from `range_end`.

    A single broker call only returns up to `max_chunk` bars ending near `end_time`; widening `to`
    without paging would shift that tail window and can **drop** the start of `[from, to]`.
    We repeat with `end_time` just before the oldest bar of the previous page until `from` is
    covered, history ends, or `max_fetch_rounds` is reached.
    """
    rs = _utc(range_start)
    re = _utc(range_end)
    now = datetime.now(UTC)
    skew = timedelta(seconds=60)
    if rs > now + skew:
        raise InvalidMarketParametersError(
            "`from` is in the future (UTC); there is no historical data there yet."
        )
    if re > now + skew:
        raise InvalidMarketParametersError(
            "`to` is in the future (UTC). Pocket Option only has candles up to about “now”; "
            "use an end time at or before the current moment, or GET /api/v1/market/candles."
        )

    span_sec = (re - rs).total_seconds()
    approx_bars = int(span_sec // timeframe_seconds) + 3
    if approx_bars > max_bars_in_range:
        raise InvalidMarketParametersError(
            f"Requested window spans ~{approx_bars} bars (>{max_bars_in_range}); "
            "narrow the range or increase STRAT_TRADE_MAX_CANDLES_RANGE_TOTAL."
        )

    max_loadable = max_chunk * max_fetch_rounds if max_chunk >= 1 else max_fetch_rounds
    if approx_bars > max_loadable:
        raise InvalidMarketParametersError(
            f"Requested window spans ~{approx_bars} bars; with chunk={max_chunk} and "
            f"{max_fetch_rounds} fetch rounds at most ~{max_loadable} bars can be loaded. "
            "Increase STRAT_TRADE_MAX_CANDLES_PER_REQUEST or STRAT_TRADE_MAX_CANDLES_RANGE_FETCH_ROUNDS, "
            "or narrow [from, to]."
        )

    by_ts: dict[datetime, Candle] = {}
    batch_bounds: list[tuple[datetime, datetime]] = []
    end_cap = re
    rounds = 0
    prev_batch_min: datetime | None = None

    while rounds < max_fetch_rounds:
        raw = await feed.get_candles(
            asset_clean,
            timeframe_seconds,
            count=max_chunk,
            end_time=end_cap,
        )
        rounds += 1
        if not raw:
            break

        deduped = _dedupe_by_open_time(raw)
        if not deduped:
            break

        times = [_utc(c.open_time) for c in deduped]
        batch_min, batch_max = min(times), max(times)
        batch_bounds.append((batch_min, batch_max))

        if prev_batch_min is not None and batch_min >= prev_batch_min:
            break
        prev_batch_min = batch_min

        for c in deduped:
            ts = _utc(c.open_time)
            if rs <= ts <= re:
                by_ts[ts] = replace(c, open_time=ts)

        if batch_min <= rs:
            break

        end_cap = batch_min - timedelta(microseconds=1)
        if end_cap < rs:
            break

    if batch_bounds:
        chunk_old = min(b[0] for b in batch_bounds)
        chunk_new = max(b[1] for b in batch_bounds)
    else:
        chunk_old, chunk_new = None, None

    return sorted(by_ts.values(), key=lambda c: c.open_time), chunk_old, chunk_new


async def fetch_candles_in_range(
    feed: CandleFeed,
    *,
    asset: str,
    timeframe_seconds: int,
    range_start: datetime,
    range_end: datetime,
    max_chunk: int,
    max_bars_in_range: int,
    max_fetch_rounds: int,
) -> CandlesPageResult:
    """All bars in [range_start, range_end] inclusive, ascending by open_time (single response)."""
    if timeframe_seconds < 1:
        raise InvalidMarketParametersError("timeframe_seconds must be >= 1.")
    if _utc(range_start) >= _utc(range_end):
        raise InvalidMarketParametersError("from must be strictly before to (ISO range).")
    asset_clean = asset.strip()
    if not asset_clean:
        raise InvalidMarketParametersError("asset must be a non-empty symbol.")

    window_sorted, chunk_old, chunk_new = await _load_range_window(
        feed,
        asset_clean=asset_clean,
        timeframe_seconds=timeframe_seconds,
        range_start=range_start,
        range_end=range_end,
        max_chunk=max_chunk,
        max_bars_in_range=max_bars_in_range,
        max_fetch_rounds=max_fetch_rounds,
    )
    total = len(window_sorted)
    rs = _utc(range_start)
    re = _utc(range_end)
    overlap = _range_broker_overlap(
        rs=rs,
        re=re,
        total=total,
        chunk_old=chunk_old,
        chunk_new=chunk_new,
    )

    return CandlesPageResult(
        candles=window_sorted,
        has_more=False,
        next_cursor=None,
        total=total,
        broker_chunk_oldest=chunk_old,
        broker_chunk_newest=chunk_new,
        broker_overlap=overlap,
    )
