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

    effective_end: datetime | None
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
) -> tuple[list[Candle], datetime | None, datetime | None]:
    """
    Fetch up to `max_chunk` bars ending at `range_end` via the adapter, then keep only
    `[range_start, range_end]` in memory. Depth is still bounded by the broker and
    `max_chunk` / native PO periods (see gateway).
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
    if approx_bars > max_chunk:
        raise InvalidMarketParametersError(
            f"This interval needs up to ~{approx_bars} bars, but the broker returns at most "
            f"{max_chunk} recent bars per call. Narrow [from, to] or raise "
            "STRAT_TRADE_MAX_CANDLES_PER_REQUEST."
        )

    raw = await feed.get_candles(
        asset_clean,
        timeframe_seconds,
        count=max_chunk,
        end_time=re,
    )
    chunk_old, chunk_new = _raw_chunk_open_bounds(raw)
    by_ts: dict[datetime, Candle] = {}
    for c in _dedupe_by_open_time(raw):
        ts = _utc(c.open_time)
        if rs <= ts <= re:
            by_ts[ts] = replace(c, open_time=ts)

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
