from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body

from strat_trade.api.deps import CandleFeedDep, SettingsDep
from strat_trade.api.schemas import TestStrategyWinrateRequest, TestStrategyWinrateResponse
from strat_trade.domain.indicators import default_indicator_registry
from strat_trade.use_cases.test_strategy_winrate import (
    StrategyConditionSpec,
    StrategyIndicatorSpec,
    run_strategy_winrate_test,
)

router = APIRouter(prefix="/strategy")

_TEST_WINRATE_BODY_EXAMPLES: dict[str, dict[str, object]] = {
    "psar_reversal_range": {
        "summary": "PSAR reversal backtest over UTC range",
        "value": {
            "asset": "EURUSD_otc",
            "timeframe_seconds": 15,
            "expiry_seconds": 30,
            "window": {
                "type": "range",
                "from": "2026-03-22T00:00:00Z",
                "to": "2026-03-22T02:00:00Z",
            },
            "indicators": [
                {
                    "key": "psar_main",
                    "id": "psar",
                    "params": {"step": 0.02, "max_step": 0.2, "component": "sar"},
                }
            ],
            "strategy": {
                "type": "psar_reversal",
                "signal_on_close": True,
                "conditions": [{"indicator_key": "psar_main", "operator": "psar_reversal"}],
            },
        },
    },
}


@router.post(
    "/test-winrate",
    response_model=TestStrategyWinrateResponse,
    summary="Test strategy winrate on historical candles",
    description=(
        "Runs a strategy against historical candles in a fixed UTC range and returns winrate stats. "
        "MVP supports `psar_reversal` only. "
        "Outcome rule: BUY wins when `close[i+N] > close[i]`, SELL wins when `close[i+N] < close[i]`; "
        "equal close is treated as loss. Signals without future candles are counted as `skipped_signals`."
    ),
    operation_id="postStrategyTestWinrate",
)
async def post_test_strategy_winrate(
    body: Annotated[
        TestStrategyWinrateRequest,
        Body(openapi_examples=_TEST_WINRATE_BODY_EXAMPLES),
    ],
    feed: CandleFeedDep,
    settings: SettingsDep,
) -> TestStrategyWinrateResponse:
    registry = default_indicator_registry()
    result = await run_strategy_winrate_test(
        feed,
        registry,
        asset=body.asset.strip(),
        timeframe_seconds=body.timeframe_seconds,
        expiry_seconds=body.expiry_seconds,
        range_start=body.window.range_from,
        range_end=body.window.range_to,
        indicators=[
            StrategyIndicatorSpec(
                key=item.key.strip(),
                indicator_id=item.indicator_id.strip(),
                params=dict(item.params),
            )
            for item in body.indicators
        ],
        strategy_type=body.strategy.type,
        signal_on_close=body.strategy.signal_on_close,
        conditions=[
            StrategyConditionSpec(
                indicator_key=item.indicator_key.strip(),
                operator=item.operator,
            )
            for item in body.strategy.conditions
        ],
        max_candles_per_request=settings.max_candles_per_request,
        max_candles_range_total=settings.max_candles_range_total,
    )
    return TestStrategyWinrateResponse(
        asset=result.asset,
        timeframe_seconds=result.timeframe_seconds,
        expiry_seconds=result.expiry_seconds,
        total_signals=result.total_signals,
        wins=result.wins,
        losses=result.losses,
        skipped_signals=result.skipped_signals,
        winrate_percent=result.winrate_percent,
        period_from=result.period_from,
        period_to=result.period_to,
    )
