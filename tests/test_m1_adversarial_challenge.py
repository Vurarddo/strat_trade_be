from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.entities import Candle
from strat_trade.domain.optimizer.auto_matcher import StrategyAutoMatcher
from strat_trade.domain.strategies.hybrid_multifactors import HybridMultiFactorsStrategy
from strat_trade.domain.strategies.registry import (
    get_strategy_instance,
    list_available_strategies,
)
from strat_trade.domain.strategies.support_resistance_bounce import SupportResistanceBounceStrategy


def _create_mock_bar_df(
    *,
    close: float = 1.0500,
    open_: float = 1.0500,
    high: float = 1.0510,
    low: float = 1.0490,
    ema_fast: float = 1.0500,
    ema_mid: float = 1.0490,
    ema_slow: float = 1.0480,
    rsi: float = 55.0,
    stoch_k: float = 60.0,
    stoch_d: float = 50.0,
    bb_high: float = 1.0550,
    bb_low: float = 1.0450,
    bb_mid: float = 1.0500,
    bb_pband: float = 0.50,
    adx: float = 26.0,
    adx_pos: float = 28.0,
    adx_neg: float = 14.0,
    atr: float = 0.0005,
    atr_sma: float = 0.0005,
    bars_count: int = 60,
) -> pd.DataFrame:
    """Constructs a deterministic prepared DataFrame for unit & boundary testing."""
    base_t = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    rows = []
    for i in range(bars_count):
        rows.append(
            {
                "timestamp": base_t + timedelta(minutes=i),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100.0,
                "ema_fast": ema_fast,
                "ema_mid": ema_mid,
                "ema_slow": ema_slow,
                "rsi": rsi,
                "stoch_k": stoch_k,
                "stoch_d": stoch_d,
                "bb_high": bb_high,
                "bb_low": bb_low,
                "bb_mid": bb_mid,
                "bb_pband": bb_pband,
                "adx": adx,
                "adx_pos": adx_pos,
                "adx_neg": adx_neg,
                "atr": atr,
                "atr_sma": atr_sma,
            }
        )
    return pd.DataFrame(rows)


# =====================================================================
# 1. ADX Boundary Conditions Testing (21.99, 22.00, 22.01)
# =====================================================================


@pytest.mark.parametrize(
    "adx_val,expected_action,expected_regime",
    [
        (21.99, None, "adx_sub_threshold_choppy"),
        (22.00, TradeAction.CALL, "transitional"),
        (22.01, TradeAction.CALL, "transitional"),
        (24.99, TradeAction.CALL, "transitional"),
        (25.00, TradeAction.CALL, "trending"),
    ],
)
def test_hybrid_adx_boundary_call(
    adx_val: float, expected_action: TradeAction | None, expected_regime: str
):
    """Empirically verify exact ADX boundary behaviors around 22.0 for CALL signals."""
    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0, adx_trend_threshold=25.0)
    df = _create_mock_bar_df(
        close=1.0505,
        ema_fast=1.0500,
        ema_mid=1.0485,
        rsi=55.0,
        stoch_k=65.0,
        stoch_d=50.0,
        adx=adx_val,
        adx_pos=28.0,
        adx_neg=12.0,
    )
    res = strat.evaluate_bar(df, 55)
    assert res.action == expected_action
    assert res.regime == expected_regime
    if expected_action is not None:
        assert res.confidence >= 0.70
    else:
        assert res.confidence == 0.0


@pytest.mark.parametrize(
    "adx_val,expected_action,expected_regime",
    [
        (21.99, None, "adx_sub_threshold_choppy"),
        (22.00, TradeAction.PUT, "transitional"),
        (22.01, TradeAction.PUT, "transitional"),
        (24.99, TradeAction.PUT, "transitional"),
        (25.00, TradeAction.PUT, "trending"),
    ],
)
def test_hybrid_adx_boundary_put(
    adx_val: float, expected_action: TradeAction | None, expected_regime: str
):
    """Empirically verify exact ADX boundary behaviors around 22.0 for PUT signals."""
    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0, adx_trend_threshold=25.0)
    df = _create_mock_bar_df(
        close=1.0475,
        ema_fast=1.0480,
        ema_mid=1.0495,
        rsi=40.0,
        stoch_k=30.0,
        stoch_d=45.0,
        adx=adx_val,
        adx_pos=12.0,
        adx_neg=28.0,
    )
    res = strat.evaluate_bar(df, 55)
    assert res.action == expected_action
    assert res.regime == expected_regime
    if expected_action is not None:
        assert res.confidence >= 0.70
    else:
        assert res.confidence == 0.0


# =====================================================================
# 2. RSI Corridor Boundary Testing (CALL: 44.9, 45.0, 68.0, 68.1; PUT: 31.9, 32.0, 55.0, 55.1)
# =====================================================================


@pytest.mark.parametrize(
    "rsi_val,expected_action",
    [
        (44.9, None),
        (45.0, TradeAction.CALL),
        (56.5, TradeAction.CALL),
        (68.0, TradeAction.CALL),
        (68.1, None),
    ],
)
def test_hybrid_rsi_boundary_call(rsi_val: float, expected_action: TradeAction | None):
    """Empirically verify RSI corridor boundaries [45.0, 68.0] for CALL."""
    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0)
    df = _create_mock_bar_df(
        close=1.0505,
        ema_fast=1.0500,
        ema_mid=1.0485,
        rsi=rsi_val,
        stoch_k=65.0,
        stoch_d=50.0,
        adx=26.0,
        adx_pos=28.0,
        adx_neg=12.0,
    )
    res = strat.evaluate_bar(df, 55)
    assert res.action == expected_action
    if expected_action is None:
        assert res.confidence == 0.0


@pytest.mark.parametrize(
    "rsi_val,expected_action",
    [
        (31.9, None),
        (32.0, TradeAction.PUT),
        (43.5, TradeAction.PUT),
        (55.0, TradeAction.PUT),
        (55.1, None),
    ],
)
def test_hybrid_rsi_boundary_put(rsi_val: float, expected_action: TradeAction | None):
    """Empirically verify RSI corridor boundaries [32.0, 55.0] for PUT."""
    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0)
    df = _create_mock_bar_df(
        close=1.0475,
        ema_fast=1.0480,
        ema_mid=1.0495,
        rsi=rsi_val,
        stoch_k=30.0,
        stoch_d=45.0,
        adx=26.0,
        adx_pos=12.0,
        adx_neg=28.0,
    )
    res = strat.evaluate_bar(df, 55)
    assert res.action == expected_action
    if expected_action is None:
        assert res.confidence == 0.0


# =====================================================================
# 3. Conflicting Indicator Scenarios & Stress Grid
# =====================================================================


@pytest.mark.parametrize(
    "scenario_name,override_kwargs",
    [
        ("bullish_adx_bearish_ema", {"ema_fast": 1.0480, "ema_mid": 1.0500}),
        ("bullish_ema_bearish_adx_di", {"adx_pos": 10.0, "adx_neg": 25.0}),
        ("bullish_ema_overbought_rsi", {"rsi": 69.5}),
        ("bullish_ema_oversold_rsi", {"rsi": 35.0}),
        ("bullish_ema_bearish_stoch", {"stoch_k": 40.0, "stoch_d": 60.0}),
        # close < ema_f * 0.9990
        ("bullish_close_below_tolerance", {"close": 1.0485, "ema_fast": 1.0500}),
        # vol_ratio = 3.0 > 2.5
        ("extreme_volatility_spike", {"atr": 0.0030, "atr_sma": 0.0010}),
    ],
)
def test_hybrid_call_conflicting_indicators_suppression(
    scenario_name: str, override_kwargs: dict[str, Any]
):
    """Verify that when any bullish indicator conflicts, CALL signal is completely suppressed."""
    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0)
    base_kwargs: dict[str, Any] = {
        "close": 1.0505,
        "ema_fast": 1.0500,
        "ema_mid": 1.0485,
        "rsi": 55.0,
        "stoch_k": 65.0,
        "stoch_d": 50.0,
        "adx": 26.0,
        "adx_pos": 28.0,
        "adx_neg": 12.0,
        "atr": 0.0005,
        "atr_sma": 0.0005,
    }
    base_kwargs.update(override_kwargs)
    df = _create_mock_bar_df(**base_kwargs)
    res = strat.evaluate_bar(df, 55)

    assert res.action is None, f"Scenario '{scenario_name}' fired unauthorized trade: {res.action}"
    assert res.confidence == 0.0


@pytest.mark.parametrize(
    "scenario_name,override_kwargs",
    [
        ("bearish_adx_bullish_ema", {"ema_fast": 1.0500, "ema_mid": 1.0480}),
        ("bearish_ema_bullish_adx_di", {"adx_pos": 28.0, "adx_neg": 12.0}),
        ("bearish_ema_oversold_rsi", {"rsi": 28.0}),
        ("bearish_ema_overbought_rsi", {"rsi": 60.0}),
        ("bearish_ema_bullish_stoch", {"stoch_k": 60.0, "stoch_d": 40.0}),
        # close > ema_f * 1.0010
        ("bearish_close_above_tolerance", {"close": 1.0495, "ema_fast": 1.0480}),
        # vol_ratio = 3.0 > 2.5
        ("extreme_volatility_spike_put", {"atr": 0.0030, "atr_sma": 0.0010}),
    ],
)
def test_hybrid_put_conflicting_indicators_suppression(
    scenario_name: str, override_kwargs: dict[str, Any]
):
    """Verify that when any bearish indicator conflicts, PUT signal is completely suppressed."""
    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0)
    base_kwargs: dict[str, Any] = {
        "close": 1.0475,
        "ema_fast": 1.0480,
        "ema_mid": 1.0495,
        "rsi": 40.0,
        "stoch_k": 30.0,
        "stoch_d": 45.0,
        "adx": 26.0,
        "adx_pos": 12.0,
        "adx_neg": 28.0,
        "atr": 0.0005,
        "atr_sma": 0.0005,
    }
    base_kwargs.update(override_kwargs)
    df = _create_mock_bar_df(**base_kwargs)
    res = strat.evaluate_bar(df, 55)

    assert res.action is None, f"Scenario '{scenario_name}' fired unauthorized trade: {res.action}"
    assert res.confidence == 0.0


def test_hybrid_incomplete_indicators_and_warmup():
    """Verify NaN / incomplete indicator rows and warm-up bars return 0 confidence and None."""
    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0)
    df = _create_mock_bar_df(bars_count=60)

    # 1. Warm-up bar (< 50)
    res_warmup = strat.evaluate_bar(df, 45)
    assert res_warmup.action is None
    assert res_warmup.regime == "warming_up"
    assert res_warmup.confidence == 0.0

    # 2. Incomplete indicators (NaN in rsi)
    df_nan = df.copy()
    df_nan.loc[55, "rsi"] = None
    res_nan = strat.evaluate_bar(df_nan, 55)
    assert res_nan.action is None
    assert res_nan.regime == "incomplete_indicators"
    assert res_nan.confidence == 0.0


# =====================================================================
# 4. StrategyAutoMatcher Fallback Precedence Stress Testing
# =====================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "symbol",
    [
        "UNKNOWN_ASSET_1",
        "XYZ_TOKEN",
        "RANDOM_PAIR_99",
        "SYNTHETIC_INDEX_01",
        "NONEXISTENT",
        "CUSTOM_COIN",
        "FOOBAR",
    ],
)
async def test_auto_matcher_unclassified_symbols_primary_fallback(symbol: str):
    """Stress-test StrategyAutoMatcher with unclassified assets to verify S&R fallback."""
    matcher = StrategyAutoMatcher(candle_count=150)

    # Case A: Empty candles list
    res_empty = await matcher.find_optimal_strategy_for_asset(symbol, [])
    assert res_empty.strategy_id == "support_resistance_bounce"
    assert res_empty.parameters["swing_window"] == 20
    assert res_empty.parameters["min_wick_ratio"] == 0.35
    assert res_empty.parameters["rsi_period"] == 14

    # Case B: Insufficient candles list (< 35 bars)
    short_candles = [
        Candle(
            open_time=datetime(2026, 1, 1, 10, i, tzinfo=UTC),
            open=Decimal("1.0000"),
            high=Decimal("1.0010"),
            low=Decimal("0.9990"),
            close=Decimal("1.0005"),
            volume=Decimal("50"),
        )
        for i in range(20)
    ]
    res_short = await matcher.find_optimal_strategy_for_asset(symbol, short_candles)
    assert res_short.strategy_id == "support_resistance_bounce"
    assert res_short.parameters["min_wick_ratio"] == 0.35

    # Case C: Insufficient DataFrame (< 35 rows)
    short_df = pd.DataFrame(
        {
            "close": [1.0] * 30,
            "open": [1.0] * 30,
            "high": [1.001] * 30,
            "low": [0.999] * 30,
            "volume": [10.0] * 30,
        }
    )
    res_df = await matcher.find_optimal_strategy_for_asset(symbol, short_df)
    assert res_df.strategy_id == "support_resistance_bounce"


def test_auto_matcher_limited_strategy_pools_fallback_hierarchy():
    """Verify fallback precedence when strategy catalogue is restricted."""
    matcher = StrategyAutoMatcher()

    all_strats = list_available_strategies()

    # 1. Full catalog -> support_resistance_bounce
    res_full = matcher._heuristic_profile_for_asset("RANDOM_ASSET", all_strats, 3)
    assert res_full.strategy_id == "support_resistance_bounce"
    assert res_full.parameters["min_wick_ratio"] == 0.35

    # 2. Pool without support_resistance_bounce -> rsi_stochastic_extreme
    pool_no_sr = [s for s in all_strats if s["id"] != "support_resistance_bounce"]
    res_no_sr = matcher._heuristic_profile_for_asset("RANDOM_ASSET", pool_no_sr, 3)
    assert res_no_sr.strategy_id == "rsi_stochastic_extreme"
    assert res_no_sr.parameters["rsi_period"] == 14
    assert res_no_sr.parameters["stoch_k"] == 14
    assert res_no_sr.parameters["stoch_d"] == 3

    # 3. Pool without both -> first available strategy
    pool_tertiary = [
        s
        for s in all_strats
        if s["id"] not in ("support_resistance_bounce", "rsi_stochastic_extreme")
    ]
    res_tertiary = matcher._heuristic_profile_for_asset("RANDOM_ASSET", pool_tertiary, 3)
    assert res_tertiary.strategy_id == pool_tertiary[0]["id"]
    assert res_tertiary.parameters["base_expiration_bars"] == 3

    # 4. Single-item pool
    single_pool = [
        {"id": "volatility_squeeze_breakout", "name": "TTM Squeeze", "category": "Breakout"}
    ]
    res_single = matcher._heuristic_profile_for_asset("RANDOM_ASSET", single_pool, 4)
    assert res_single.strategy_id == "volatility_squeeze_breakout"
    assert res_single.parameters["base_expiration_bars"] == 4


def test_auto_matcher_variations_generator_hybrid_params():
    """Verify strategy variations generator sets ADX thresholds for hybrid_multifactors."""
    matcher = StrategyAutoMatcher()
    def_params = {
        "rsi_period": 14,
        "rsi_oversold": 30.0,
        "rsi_overbought": 70.0,
        "ema_fast": 9,
        "ema_mid": 21,
        "ema_slow": 50,
        "bb_length": 20,
        "bb_std": 2.0,
        "atr_period": 14,
        "adx_period": 14,
        "adx_trend_threshold": 25.0,
        "adx_range_threshold": 20.0,
        "adx_min_threshold": 22.0,
        "base_expiration_bars": 3,
    }
    variations = matcher._generate_strategy_variations("hybrid_multifactors", def_params, 3)

    assert len(variations) == 3
    # Variation 1: Base
    assert variations[0]["adx_min_threshold"] == 22.0
    # Variation 2: Fast scalp
    assert variations[1]["adx_trend_threshold"] == 22.0
    assert variations[1]["adx_min_threshold"] == 22.0
    # Variation 3: Trend filter
    assert variations[2]["adx_trend_threshold"] == 28.0


# =====================================================================
# 5. Registry Fallback Precedence Stress Testing
# =====================================================================


def test_registry_fallback_to_support_resistance_bounce():
    """Verify registry get_strategy_instance falls back to S&R Bounce on unknown strategy."""
    inst_unknown = get_strategy_instance("nonexistent_unknown_strategy_xyz")
    assert isinstance(inst_unknown, SupportResistanceBounceStrategy)

    inst_empty = get_strategy_instance("")
    assert isinstance(inst_empty, SupportResistanceBounceStrategy)

    inst_whitespace = get_strategy_instance("   ")
    assert isinstance(inst_whitespace, SupportResistanceBounceStrategy)


# =====================================================================
# 6. End-to-End Backtest Engine Gating Verification
# =====================================================================


def test_hybrid_backtest_choppy_zero_trades():
    """Verify backtest on perfectly flat/choppy series yields 0 trades under ADX >= 22.0 gating."""
    from strat_trade.domain.backtest.engine import BinaryBacktestEngine
    from strat_trade.domain.backtest.models import BacktestConfig, StakeModel

    # Generate 150 bars of flat micro-noise where ADX stays ~10-15
    base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    rows = []
    import numpy as np

    np.random.seed(99)
    for i in range(150):
        noise = np.random.uniform(-0.00005, 0.00005)
        p = 1.0500 + noise
        rows.append(
            {
                "timestamp": base_t + timedelta(minutes=i),
                "open": 1.0500,
                "high": p + 0.0001,
                "low": p - 0.0001,
                "close": p,
                "volume": 50.0,
            }
        )
    df_choppy = pd.DataFrame(rows)

    cfg = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        initial_deposit=1000.0,
        stake_model=StakeModel.FLAT,
        stake_amount=10.0,
        payout_rate=0.92,
        min_payout_rate=0.80,
        expiration_bars=3,
        strategy_name="hybrid_multifactors",
        strategy_params={"adx_min_threshold": 22.0},
    )

    engine = BinaryBacktestEngine(cfg)
    summary = engine.run(df_choppy)

    assert summary.total_trades == 0, (
        f"Expected 0 trades in choppy noise, got {summary.total_trades}"
    )
    assert summary.win_rate_pct == 0.0
    assert summary.net_profit == 0.0
