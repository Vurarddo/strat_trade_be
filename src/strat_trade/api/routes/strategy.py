from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body

from strat_trade.api.deps import CandleFeedDep, SettingsDep
from strat_trade.api.schemas import TestStrategyWinrateRequest, TestStrategyWinrateResponse
from strat_trade.domain.indicators import default_indicator_registry
from strat_trade.use_cases.strategy_winrate import (
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
    "cci_level_cross_range": {
        "summary": "CCI ±100 level cross backtest over UTC range",
        "value": {
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "expiry_seconds": 120,
            "window": {
                "type": "range",
                "from": "2026-03-22T00:00:00Z",
                "to": "2026-03-22T04:00:00Z",
            },
            "indicators": [
                {
                    "key": "cci_20",
                    "id": "cci",
                    "params": {"period": 20, "constant": 0.015},
                }
            ],
            "strategy": {
                "type": "cci_level_cross",
                "signal_on_close": True,
                "conditions": [{"indicator_key": "cci_20", "operator": "cci_level_cross"}],
            },
        },
    },
    "composite_psar_and_cci": {
        "summary": "Composite AND — PSAR reversal + CCI cross on same bar & side",
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
                },
                {
                    "key": "cci_20",
                    "id": "cci",
                    "params": {"period": 20, "constant": 0.015},
                },
            ],
            "strategy": {
                "type": "composite",
                "combinator": "all",
                "signal_on_close": True,
                "conditions": [
                    {"indicator_key": "psar_main", "operator": "psar_reversal"},
                    {"indicator_key": "cci_20", "operator": "cci_level_cross"},
                ],
            },
        },
    },
    "ema_cross_range": {
        "summary": "EMA fast/slow cross (strict) over UTC range",
        "value": {
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "expiry_seconds": 120,
            "window": {
                "type": "range",
                "from": "2026-03-22T00:00:00Z",
                "to": "2026-03-22T04:00:00Z",
            },
            "indicators": [
                {"key": "ema_fast", "id": "ema", "params": {"period": 9}},
                {"key": "ema_slow", "id": "ema", "params": {"period": 21}},
            ],
            "strategy": {
                "type": "ema_cross",
                "signal_on_close": True,
                "conditions": [
                    {
                        "indicator_key": "ema_fast",
                        "slow_indicator_key": "ema_slow",
                        "operator": "ema_cross",
                    }
                ],
            },
        },
    },
    "preset_rsi_stoch_ema_composite": {
        "summary": "Preset-style composite: RSI + Stoch + EMA trend/cross",
        "value": {
            "asset": "EURUSD_otc",
            "timeframe_seconds": 300,
            "expiry_seconds": 600,
            "window": {
                "type": "range",
                "from": "2026-03-22T00:00:00Z",
                "to": "2026-03-23T00:00:00Z",
            },
            "indicators": [
                {"key": "rsi_7", "id": "rsi", "params": {"period": 7}},
                {
                    "key": "stoch_k_5_3",
                    "id": "stochastic",
                    "params": {"period": 5, "smooth_window": 3, "component": "k"},
                },
                {
                    "key": "stoch_d_5_3",
                    "id": "stochastic",
                    "params": {"period": 5, "smooth_window": 3, "component": "d"},
                },
                {"key": "ema_8", "id": "ema", "params": {"period": 8}},
                {"key": "ema_21", "id": "ema", "params": {"period": 21}},
            ],
            "strategy": {
                "type": "composite",
                "combinator": "all",
                "signal_on_close": True,
                "conditions": [
                    {"indicator_key": "rsi_7", "operator": "rsi_threshold", "params": {"lower": 18, "upper": 82}},
                    {
                        "indicator_key": "stoch_k_5_3",
                        "slow_indicator_key": "stoch_d_5_3",
                        "operator": "stochastic_dual_threshold",
                        "params": {"lower": 15, "upper": 85},
                    },
                    {
                        "indicator_key": "ema_8",
                        "slow_indicator_key": "ema_21",
                        "operator": "ema_cross_or_trend",
                        "params": {"max_ema_separation": 0.003},
                    },
                ],
            },
        },
    },
    "composite_macd_psar": {
        "summary": "Composite AND — MACD/signal cross (zero half-plane) + PSAR reversal",
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
                    "key": "macd_line",
                    "id": "macd",
                    "params": {"fast_period": 12, "slow_period": 26, "signal_period": 9, "component": "macd"},
                },
                {
                    "key": "macd_signal",
                    "id": "macd",
                    "params": {"fast_period": 12, "slow_period": 26, "signal_period": 9, "component": "signal"},
                },
                {
                    "key": "psar_main",
                    "id": "psar",
                    "params": {"step": 0.02, "max_step": 0.2, "component": "sar"},
                },
            ],
            "strategy": {
                "type": "composite",
                "combinator": "all",
                "signal_on_close": True,
                "conditions": [
                    {
                        "indicator_key": "macd_line",
                        "slow_indicator_key": "macd_signal",
                        "operator": "macd_signal_cross",
                    },
                    {"indicator_key": "psar_main", "operator": "psar_reversal"},
                ],
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
        "Single-indicator: **`psar_reversal`**, **`cci_level_cross`**, or **`ema_cross`** (fast/slow EMA "
        "cross with `indicator_key` + `slow_indicator_key`). "
        "**`composite`** with `combinator=all`: every condition must fire on the **same bar** with the "
        "**same side**; conditions may mix `psar_reversal`, `cci_level_cross`, `ema_cross`, "
        "`rsi_threshold`, `stochastic_dual_threshold`, `ema_cross_or_trend`, and `macd_signal_cross` "
        "(MACD line vs signal line, two `macd` instances). "
        "Outcome rule: BUY wins when `close[i+N] > close[i]`, SELL wins when `close[i+N] < close[i]`; "
        "**equal close at expiry counts as loss**. "
        "Signals without enough future candles for expiry are counted as `skipped_signals`."
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
        combinator=body.strategy.combinator,
        conditions=[
            StrategyConditionSpec(
                indicator_key=item.indicator_key.strip(),
                operator=item.operator,
                slow_indicator_key=item.slow_indicator_key.strip() if item.slow_indicator_key else None,
                params=dict(item.params),
            )
            for item in body.strategy.conditions
        ],
        max_candles_per_request=settings.max_candles_per_request,
        max_candles_range_total=settings.max_candles_range_total,
        max_candles_range_fetch_rounds=settings.max_candles_range_fetch_rounds,
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
