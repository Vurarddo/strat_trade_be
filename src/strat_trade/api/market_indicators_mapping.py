from __future__ import annotations

from strat_trade.api.schemas import (
    CandleBarResponse,
    IndicatorOutputPoint,
    IndicatorRunSnapshotResponse,
    MarketIndicatorsBatchRequest,
    MarketIndicatorsBatchResponse,
)
from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import InvalidMarketParametersError
from strat_trade.use_cases.market_indicators_batch import (
    IndicatorRunSpec,
    MarketIndicatorsBatchResult,
    build_indicator_rows_by_time_key,
)


def resolve_indicator_keys(body: MarketIndicatorsBatchRequest) -> list[str]:
    seen: set[str] = set()
    keys: list[str] = []
    for i, item in enumerate(body.indicators):
        raw = (item.key or "").strip()
        k = raw or f"run_{i}"
        if k in seen:
            raise InvalidMarketParametersError(f"Duplicate indicator key: {k!r}.")
        seen.add(k)
        keys.append(k)
    return keys


def candles_to_bars(candles: list[Candle]) -> list[CandleBarResponse]:
    return [
        CandleBarResponse(
            open_time=c.open_time,
            open=float(c.open),
            high=float(c.high),
            low=float(c.low),
            close=float(c.close),
            volume=None if c.volume is None else float(c.volume),
        )
        for c in candles
    ]


def open_time_keys_aligned_with_json_candles(bars: list[CandleBarResponse]) -> list[str]:
    """Keys must match `candles[].open_time` strings in the final JSON body."""
    keys: list[str] = []
    for b in bars:
        dumped = b.model_dump(mode="json")
        ts = dumped["open_time"]
        if not isinstance(ts, str):
            msg = f"Expected JSON open_time string, got {type(ts)}"
            raise TypeError(msg)
        keys.append(ts)
    return keys


def build_market_indicators_batch_response(
    *,
    result: MarketIndicatorsBatchResult,
    runs: list[IndicatorRunSpec],
    asset: str,
    timeframe_seconds: int,
) -> MarketIndicatorsBatchResponse:
    candles = candles_to_bars(result.candles)
    time_keys = open_time_keys_aligned_with_json_candles(candles)
    rows = build_indicator_rows_by_time_key(time_keys, runs, result.indicator_blocks)
    indicators = [
        IndicatorRunSnapshotResponse(
            indicator_id=iid,
            params=p,
            outputs={
                name: [IndicatorOutputPoint(open_time=ts, value=v) for ts, v in pts]
                for name, pts in o.items()
            },
        )
        for _, iid, p, o in rows
    ]
    return MarketIndicatorsBatchResponse(
        asset=asset,
        timeframe_seconds=timeframe_seconds,
        align_by="open_time",
        candles=candles,
        indicators=indicators,
        has_more=result.has_more,
        next_cursor=result.next_cursor,
    )
