from __future__ import annotations

from fastapi import APIRouter

from strat_trade.api.deps import CandleFeedDep, SettingsDep
from strat_trade.api.market_indicators_mapping import (
    build_market_indicators_batch_response,
    resolve_indicator_keys,
)
from strat_trade.api.schemas import MarketIndicatorsBatchRequest, MarketIndicatorsBatchResponse
from strat_trade.use_cases.market_indicators_batch import (
    IndicatorRunSpec,
    compute_market_indicators_batch,
)

router = APIRouter(prefix="/market")


@router.post(
    "/indicators",
    response_model=MarketIndicatorsBatchResponse,
    summary="Compute several indicators on one candle window",
    description=(
        "Same candle page as `GET /api/v1/market/candles`, plus **`indicators`**: array in request "
        "order. Each run's `outputs` maps line names to arrays of `{ open_time, value }` "
        "(`open_time` matches `candles[].open_time`). Warmup omitted. "
        "See `docs/MARKET_INDICATORS_API.md`."
    ),
    operation_id="postMarketIndicatorsBatch",
)
async def compute_market_indicators(
    body: MarketIndicatorsBatchRequest,
    feed: CandleFeedDep,
    settings: SettingsDep,
) -> MarketIndicatorsBatchResponse:
    keys = resolve_indicator_keys(body)
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
    return build_market_indicators_batch_response(
        result=result,
        runs=runs,
        asset=body.asset.strip(),
        timeframe_seconds=body.timeframe_seconds,
    )
