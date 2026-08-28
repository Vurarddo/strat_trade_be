from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from strat_trade.domain.entities import Candle
from strat_trade.domain.optimizer.auto_matcher import StrategyAutoMatcher


def _generate_candles(n: int = 150) -> list[Candle]:
    base = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    candles = []
    price = 1.0850
    for i in range(n):
        price += 0.0002 if (i % 6 < 3) else -0.0002
        candles.append(
            Candle(
                open_time=base + timedelta(minutes=i),
                open=Decimal(str(price)),
                high=Decimal(str(price + 0.0004)),
                low=Decimal(str(price - 0.0004)),
                close=Decimal(str(price + 0.0001)),
                volume=Decimal("150"),
            )
        )
    return candles


@pytest.mark.asyncio
async def test_strategy_auto_matcher():
    matcher = StrategyAutoMatcher(candle_count=150)
    candles = _generate_candles(150)

    assignment = await matcher.find_optimal_strategy_for_asset(
        asset="EURUSD_otc",
        candles=candles,
        timeframe_seconds=60,
        expiration_bars=3,
        payout_rate=0.92,
    )

    assert assignment.asset == "EURUSD_otc"
    assert assignment.strategy_id != ""
    assert assignment.strategy_name != ""
    assert assignment.estimated_win_rate_pct >= 0.0
    assert assignment.quantum_score is not None
    assert len(assignment.parameters) > 0


@pytest.mark.asyncio
async def test_strategy_auto_matcher_fallback_hierarchy():
    """Verify default heuristic fallback prioritizes S&R Bounce then RSI+Stoch."""
    matcher = StrategyAutoMatcher(candle_count=150)

    # 1. Primary fallback: support_resistance_bounce
    res_primary = await matcher.find_optimal_strategy_for_asset("UNCLASSIFIED_TOKEN_XYZ", [])
    assert res_primary.strategy_id == "support_resistance_bounce"
    assert res_primary.parameters["swing_window"] == 20
    assert res_primary.parameters["min_wick_ratio"] == 0.35
    assert res_primary.parameters["rsi_period"] == 14

    # 2. Secondary fallback when support_resistance_bounce is excluded
    custom_strategies = [
        {"id": "rsi_stochastic_extreme", "name": "RSI Extreme", "category": "Scalping"},
        {"id": "bollinger_atr_reversion", "name": "Bollinger ATR", "category": "Mean Reversion"},
    ]
    res_secondary = matcher._heuristic_profile_for_asset(
        "UNCLASSIFIED_TOKEN_XYZ", custom_strategies, expiration_bars=3
    )
    assert res_secondary.strategy_id == "rsi_stochastic_extreme"
    assert res_secondary.parameters["rsi_period"] == 14
    assert res_secondary.parameters["stoch_k"] == 14
    assert res_secondary.parameters["stoch_d"] == 3

    # 3. Tertiary fallback to strategies[0] when both are omitted
    custom_fallback_only = [
        {"id": "bollinger_atr_reversion", "name": "Bollinger ATR", "category": "Mean Reversion"},
    ]
    res_tertiary = matcher._heuristic_profile_for_asset(
        "UNCLASSIFIED_TOKEN_XYZ", custom_fallback_only, expiration_bars=3
    )
    assert res_tertiary.strategy_id == "bollinger_atr_reversion"
    assert res_tertiary.parameters["base_expiration_bars"] == 3


@pytest.mark.asyncio
async def test_strategy_auto_matcher_with_allowed_strategies():
    """Verify that allowed_strategies restricts matching strictly to chosen strategy IDs."""
    matcher = StrategyAutoMatcher(candle_count=150)
    candles = _generate_candles(150)

    # 1. Restrict exclusively to RSI + Stoch
    assignment_rsi = await matcher.find_optimal_strategy_for_asset(
        asset="EURUSD_otc",
        candles=candles,
        allowed_strategies=["rsi_stochastic_extreme"],
    )
    assert assignment_rsi.strategy_id == "rsi_stochastic_extreme"

    # 2. Restrict exclusively to EMA Ribbon Trend
    assignment_ema = await matcher.find_optimal_strategy_for_asset(
        asset="EURUSD_otc",
        candles=candles,
        allowed_strategies=["ema_pullback_trend"],
    )
    assert assignment_ema.strategy_id == "ema_pullback_trend"

    # 3. Empty data fallback with allowed_strategies
    fallback_assignment = await matcher.find_optimal_strategy_for_asset(
        asset="ANY_ASSET_XYZ",
        candles=[],
        allowed_strategies=["ema_pullback_trend"],
    )
    assert fallback_assignment.strategy_id == "ema_pullback_trend"
