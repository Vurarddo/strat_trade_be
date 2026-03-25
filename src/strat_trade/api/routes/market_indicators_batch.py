from __future__ import annotations

from fastapi import APIRouter

from strat_trade.api.deps import CandleFeedDep, SettingsDep
from strat_trade.api.schemas import (
    CandleBarResponse,
    IndicatorRunSnapshotResponse,
    MarketIndicatorsBatchRequest,
    MarketIndicatorsBatchResponse,
)
from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import InvalidMarketParametersError
from strat_trade.use_cases.market_indicators_batch import (
    IndicatorRunSpec,
    build_indicator_rows_by_time_key,
    compute_market_indicators_batch,
)


def _candles_to_bars(candles: list[Candle]) -> list[CandleBarResponse]:
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


def _open_time_keys_aligned_with_json_candles(bars: list[CandleBarResponse]) -> list[str]:
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


router = APIRouter(prefix="/market")


def _resolve_indicator_keys(body: MarketIndicatorsBatchRequest) -> list[str]:
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


@router.post(
    "/indicators",
    response_model=MarketIndicatorsBatchResponse,
    summary="Compute several indicators on one candle window",
    description=(
        "Same candle page as `GET /api/v1/market/candles`, plus **`indicators`**: an array in the "
        "same order as the request body. Values are keyed by **`align_by`** (`open_time`): each "
        "map key equals `candles[i].open_time` in this JSON response. Warmup points are omitted. "
        "See `docs/MARKET_INDICATORS_API.md` for JSON examples."
    ),
    operation_id="postMarketIndicatorsBatch",
)
async def compute_market_indicators(
    body: MarketIndicatorsBatchRequest,
    feed: CandleFeedDep,
    settings: SettingsDep,
) -> MarketIndicatorsBatchResponse:
    keys = _resolve_indicator_keys(body)
    runs = [
        IndicatorRunSpec(
            indicator_id=r.indicator_id.strip(),
            params=dict(r.params),
            response_key=k,
        )
        for r, k in zip(body.indicators, keys, strict=True)
    ]
    result = await compute_market_indicators_batch(
        feed,
        asset=body.asset.strip(),
        timeframe_seconds=body.timeframe_seconds,
        count=body.count,
        max_count=settings.max_candles_per_request,
        max_indicator_runs=settings.max_indicators_per_market_request,
        runs=runs,
        end_at=body.end_at,
        cursor=body.cursor,
    )
    candles = _candles_to_bars(result.candles)
    time_keys = _open_time_keys_aligned_with_json_candles(candles)
    rows = build_indicator_rows_by_time_key(time_keys, runs, result.indicator_blocks)
    indicators = [
        IndicatorRunSnapshotResponse(indicator_id=iid, params=p, outputs=o)
        for _, iid, p, o in rows
    ]
    return MarketIndicatorsBatchResponse(
        asset=body.asset.strip(),
        timeframe_seconds=body.timeframe_seconds,
        align_by="open_time",
        candles=candles,
        indicators=indicators,
        has_more=result.has_more,
        next_cursor=result.next_cursor,
    )
