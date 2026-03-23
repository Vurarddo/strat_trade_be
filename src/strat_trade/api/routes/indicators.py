from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body

from strat_trade.api.deps import CandleFeedDep, SettingsDep
from strat_trade.api.indicator_payload import trim_leading_none_indicator_values
from strat_trade.api.schemas import (
    CandleBarResponse,
    IndicatorSeriesResponse,
    MarketIndicatorsRequest,
    MarketIndicatorsResponse,
    RangeIndicatorWindow,
    RecentIndicatorWindow,
)
from strat_trade.domain.indicators import default_indicator_registry
from strat_trade.use_cases.compute_market_indicators import (
    ClientIndicatorSpec,
    compute_market_indicators,
)

router = APIRouter(prefix="/market")

_MARKET_INDICATORS_BODY_EXAMPLES: dict[str, dict[str, object]] = {
    "recent_first_page": {
        "summary": "Recent window — first page",
        "description": (
            "Omit both `end_at` and `cursor` for broker “now”, or set only `end_at` to anchor "
            "the end. **Never send `end_at` and `cursor` together.**"
        ),
        "value": {
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "window": {"type": "recent", "count": 100},
            "indicators": [
                {"key": "rsi_14", "id": "rsi", "params": {"period": 14}},
            ],
            "include_candles": True,
        },
    },
    "recent_older_page": {
        "summary": "Recent window — next page (cursor only)",
        "value": {
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "window": {
                "type": "recent",
                "count": 100,
                "cursor": "2026-03-22T00:34:07.000Z",
            },
            "indicators": [
                {"key": "rsi_14", "id": "rsi", "params": {"period": 14}},
            ],
            "include_candles": True,
        },
    },
    "range_window": {
        "summary": "Fixed UTC range",
        "value": {
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "window": {
                "type": "range",
                "from": "2026-03-22T00:00:00Z",
                "to": "2026-03-22T01:00:00Z",
            },
            "indicators": [
                {"key": "rsi_14", "id": "rsi", "params": {"period": 14}},
            ],
            "include_candles": True,
        },
    },
}


@router.post(
    "/indicators",
    response_model=MarketIndicatorsResponse,
    summary="Compute indicators on a candle window",
    description=(
        "Fetches the same candle window as **GET /market/candles** (recent) or "
        "**GET /market/candles/range** (fixed interval), then evaluates every requested "
        "indicator on that series. Values are aligned by index with `open_times` "
        "Leading undefined bars are omitted from each `values` array; use `start_index` to "
        "align with `open_times`. Add new indicators by registering "
        "them in the domain registry — clients only pass `id` + `params` per instance.\n\n"
        "**Recent `window`:** `end_at` and `cursor` are mutually exclusive (identical to "
        "GET `/api/v1/market/candles`)."
    ),
    operation_id="postMarketIndicators",
)
async def compute_indicators(
    body: Annotated[
        MarketIndicatorsRequest,
        Body(openapi_examples=_MARKET_INDICATORS_BODY_EXAMPLES),
    ],
    feed: CandleFeedDep,
    settings: SettingsDep,
) -> MarketIndicatorsResponse:
    registry = default_indicator_registry()
    specs = [
        ClientIndicatorSpec(
            key=s.key.strip(),
            indicator_id=s.indicator_id.strip(),
            params=dict(s.params),
        )
        for s in body.indicators
    ]

    if isinstance(body.window, RecentIndicatorWindow):
        recent = (body.window.count, body.window.end_at, body.window.cursor)
        range_window = None
    else:
        assert isinstance(body.window, RangeIndicatorWindow)
        recent = None
        range_window = (body.window.range_from, body.window.range_to)

    result = await compute_market_indicators(
        feed,
        registry,
        asset=body.asset.strip(),
        timeframe_seconds=body.timeframe_seconds,
        include_candles=body.include_candles,
        specs=specs,
        recent=recent,
        range_window=range_window,
        max_candles_per_request=settings.max_candles_per_request,
        max_candles_range_total=settings.max_candles_range_total,
    )

    page = result.page
    open_times = [c.open_time for c in page.candles]
    candles_out = None
    if result.include_candles:
        candles_out = [
            CandleBarResponse(
                open_time=c.open_time,
                open=float(c.open),
                high=float(c.high),
                low=float(c.low),
                close=float(c.close),
                volume=None if c.volume is None else float(c.volume),
            )
            for c in page.candles
        ]

    indicators_out = {}
    for key, series in result.indicators.items():
        start_idx, vals = trim_leading_none_indicator_values(list(series.values))
        indicators_out[key] = IndicatorSeriesResponse(
            indicator_id=series.indicator_id,
            params={k: v for k, v in series.params.items()},
            start_index=start_idx,
            values=vals,
        )

    return MarketIndicatorsResponse(
        asset=body.asset.strip(),
        timeframe_seconds=body.timeframe_seconds,
        open_times=open_times,
        candles=candles_out,
        indicators=indicators_out,
        has_more=page.has_more,
        next_cursor=page.next_cursor,
        total=page.total,
        broker_chunk_oldest=page.broker_chunk_oldest,
        broker_chunk_newest=page.broker_chunk_newest,
        broker_overlap=page.broker_overlap,
    )
