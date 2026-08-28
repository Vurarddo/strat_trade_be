"""M1 Empirical Challenger Stress Test Suite.

Adversarial testing for:
1. Multi-regime backtesting with HybridMultiFactorsStrategy (ADX >= 22.0 gating vs baseline).
2. Strategy registry robustness, parameter filtering, and fallback behavior.
3. StrategyAutoMatcher heuristic fallback hierarchy and edge-case asset routing.
4. Strict 3-way concordance and volatility spike gating in HybridMultiFactorsStrategy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import BacktestConfig, StakeModel
from strat_trade.domain.entities import Candle
from strat_trade.domain.optimizer.auto_matcher import StrategyAutoMatcher
from strat_trade.domain.strategies.base import BaseStrategy
from strat_trade.domain.strategies.hybrid_multifactors import HybridMultiFactorsStrategy
from strat_trade.domain.strategies.macd_divergence_break import MacdDivergenceBreakStrategy
from strat_trade.domain.strategies.registry import (
    get_strategy_instance,
    list_available_strategies,
)
from strat_trade.domain.strategies.supertrend_adx_momentum import SupertrendAdxMomentumStrategy
from strat_trade.domain.strategies.support_resistance_bounce import SupportResistanceBounceStrategy

# ============================================================================
# Synthetic Dataset Generators for Multi-Regime Backtesting
# ============================================================================


def _create_synthetic_choppy_noise_df(
    n: int = 300, base_price: float = 1.1000, seed: int = 42
) -> pd.DataFrame:
    """Generates pure mean-reverting oscillating noise with low directional momentum (ADX < 20)."""
    np.random.seed(seed)
    base_t = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    timestamps = [base_t + timedelta(minutes=i) for i in range(n)]

    t = np.linspace(0, 40 * np.pi, n)
    closes = base_price + 0.00012 * np.sin(t) + np.random.normal(0, 0.00004, n)

    rows = []
    for i in range(n):
        c = float(closes[i])
        o = float(closes[i - 1]) if i > 0 else c
        h = max(o, c) + 0.00005
        low_p = min(o, c) - 0.00005
        rows.append(
            {
                "timestamp": timestamps[i],
                "open": o,
                "high": h,
                "low": low_p,
                "close": c,
                "volume": 100.0,
            }
        )
    return pd.DataFrame(rows)


def _create_synthetic_pullback_trend_df(
    n: int = 400, base_price: float = 1.1000, seed: int = 42
) -> pd.DataFrame:
    """Generates realistic upward trend with rhythmic pullbacks and momentum expansion."""
    np.random.seed(seed)
    base_t = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    timestamps = [base_t + timedelta(minutes=i) for i in range(n)]

    closes = [base_price]
    for i in range(1, n):
        cycle = 0.0003 * np.sin(i * 0.2)
        step = 0.00008
        noise = np.random.normal(0, 0.00003)
        closes.append(closes[-1] + step + cycle + noise)

    rows = []
    for i in range(n):
        c = float(closes[i])
        o = float(closes[i - 1]) if i > 0 else c
        h = max(o, c) + 0.0001
        low_p = min(o, c) - 0.0001
        rows.append(
            {
                "timestamp": timestamps[i],
                "open": o,
                "high": h,
                "low": low_p,
                "close": c,
                "volume": 150.0,
            }
        )
    return pd.DataFrame(rows)


# ============================================================================
# 1. Multi-Regime Empirical Backtest Stress Tests
# ============================================================================


def test_empirical_hybrid_multifactors_adx_gating_eliminates_choppy_whipsaws():
    """Empirically test that ADX >= 22.0 gating eliminates whipsaw trades in choppy regime.

    Comparison across 10 Monte Carlo choppy noise seeds:
    - Gated (adx_min_threshold=22.0, default): ADX check suppresses choppy noise -> 0 trades.
    - Ungated Baseline (adx_min_threshold=0.0): Unfiltered triggers cause repeated loss entries.
    """
    total_ungated_trades = 0
    total_ungated_losses = 0
    total_gated_trades = 0
    total_gated_losses = 0

    for seed in range(1, 11):
        df_choppy = _create_synthetic_choppy_noise_df(n=300, seed=seed)

        # 1. Gated Strategy (Default: ADX >= 22.0)
        cfg_gated = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            initial_deposit=1000.0,
            stake_model=StakeModel.FLAT,
            stake_amount=10.0,
            payout_rate=0.92,
            expiration_bars=3,
            strategy_name="hybrid_multifactors",
            strategy_params={
                "adx_min_threshold": 22.0,
                "base_expiration_bars": 3,
            },
        )
        res_gated = BinaryBacktestEngine(cfg_gated).run(df_choppy)
        total_gated_trades += res_gated.total_trades
        total_gated_losses += res_gated.losing_trades

        # 2. Ungated Strategy (Baseline: ADX >= 0.0)
        cfg_ungated = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            initial_deposit=1000.0,
            stake_model=StakeModel.FLAT,
            stake_amount=10.0,
            payout_rate=0.92,
            expiration_bars=3,
            strategy_name="hybrid_multifactors",
            strategy_params={
                "adx_min_threshold": 0.0,  # ungated
                "base_expiration_bars": 3,
            },
        )
        res_ungated = BinaryBacktestEngine(cfg_ungated).run(df_choppy)
        total_ungated_trades += res_ungated.total_trades
        total_ungated_losses += res_ungated.losing_trades

    # Verify that ungated strategy generated significant whipsaws (>50 trades across 10 seeds)
    assert total_ungated_trades >= 50, (
        f"Ungated baseline expected >= 50 whipsaw trades, got {total_ungated_trades}"
    )
    # Verify that gated strategy eliminated >= 95% of choppy trades
    assert total_gated_trades <= 2, (
        f"Gated allowed {total_gated_trades} choppy trades; expected near-zero suppression."
    )
    assert total_gated_losses == 0, f"Gated strategy suffered {total_gated_losses} losses in noise!"


def test_empirical_hybrid_multifactors_trending_regime_execution():
    """Verify in trending regimes with pullbacks, HybridMultiFactorsStrategy generates wins."""
    df_trending = _create_synthetic_pullback_trend_df(n=400, seed=42)

    cfg = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        initial_deposit=1000.0,
        stake_model=StakeModel.FLAT,
        stake_amount=10.0,
        payout_rate=0.92,
        expiration_bars=3,
        strategy_name="hybrid_multifactors",
        strategy_params={
            "adx_min_threshold": 22.0,
            "base_expiration_bars": 3,
        },
    )
    engine = BinaryBacktestEngine(cfg)
    summary = engine.run(df_trending)

    # In trending dataset with pullbacks, strategy should generate profitable trades
    assert summary.total_trades >= 10, f"Expected >= 10 trades in trend, got {summary.total_trades}"
    assert summary.win_rate_pct >= Decimal("55.0"), f"Win rate {summary.win_rate_pct}% < 55%"
    assert summary.net_profit > Decimal("0.0"), f"Net profit {summary.net_profit} <= 0"


# ============================================================================
# 2. Strategy Registry Robustness & Fuzz Testing
# ============================================================================


def test_registry_fallback_arbitrary_and_malformed_names():
    """Fuzz test get_strategy_instance with invalid, non-existent, and malformed strings.

    Invariants:
    1. NEVER raises an unhandled exception or KeyError.
    2. Always returns a valid BaseStrategy instance.
    3. Defaults to SupportResistanceBounceStrategy as primary fallback.
    """
    fuzz_inputs = [
        "non_existent_strategy_xyz",
        "INVALID_STRATEGY_12345",
        "!!!@@@###$$$",
        "   ",
        "",
        "unknown_bot_algo",
        "bollinger_non_existent",
        "supertrend_typo_version",
    ]

    for name in fuzz_inputs:
        strat = get_strategy_instance(name)
        assert isinstance(strat, BaseStrategy), f"Failed for name '{name}'"
        assert isinstance(strat, SupportResistanceBounceStrategy), (
            f"Expected fallback SupportResistanceBounceStrategy for '{name}', got {type(strat)}"
        )


def test_registry_mixed_case_handling():
    """Verify get_strategy_instance correctly handles mixed casing and whitespace."""
    test_cases = [
        ("  hybrid_multifactors  ", HybridMultiFactorsStrategy),
        ("HYBRID_MULTIFACTORS", HybridMultiFactorsStrategy),
        ("SuperTrend_ADX_Momentum", SupertrendAdxMomentumStrategy),
        ("MACD_DIVERGENCE_BREAK", MacdDivergenceBreakStrategy),
        ("   macd_divergence_break   ", MacdDivergenceBreakStrategy),
    ]

    for raw_name, expected_cls in test_cases:
        strat = get_strategy_instance(raw_name)
        assert isinstance(strat, expected_cls), (
            f"Expected {expected_cls} for '{raw_name}', got {type(strat)}"
        )


def test_registry_unexpected_parameters_filtering():
    """Verify get_strategy_instance safely filters unknown keyword arguments without crashing."""
    bogus_params = {
        "non_existent_param_1": 12345,
        "bogus_multiplier": 99.9,
        "invalid_flag": True,
        "rsi_period": 14,
    }

    # Should not raise TypeError: unexpected keyword argument
    strat = get_strategy_instance("hybrid_multifactors", params=bogus_params)
    assert isinstance(strat, HybridMultiFactorsStrategy)
    assert strat.rsi_period == 14

    # Direct kwargs override
    strat_kw = get_strategy_instance(
        "supertrend_adx_momentum",
        params={"atr_period": 10},
        atr_multiplier=3.5,
        unknown_kwarg_x=100,
    )
    assert isinstance(strat_kw, SupertrendAdxMomentumStrategy)
    assert strat_kw.atr_multiplier == 3.5


# ============================================================================
# 3. StrategyAutoMatcher Fallback Hierarchy & Asset Heuristic Tests
# ============================================================================


@pytest.mark.asyncio
async def test_automatcher_unclassified_asset_primary_and_secondary_fallback():
    """Verify StrategyAutoMatcher fallback hierarchy when matching unclassified assets."""
    matcher = StrategyAutoMatcher(candle_count=150)

    # 1. Primary fallback: support_resistance_bounce
    res_primary = matcher._heuristic_profile_for_asset(
        asset="UNKNOWN_SYNTHETIC_ASSET_1",
        strategies=list_available_strategies(),
        expiration_bars=3,
    )
    assert res_primary.strategy_id == "support_resistance_bounce"
    assert res_primary.parameters["swing_window"] == 20
    assert res_primary.parameters["min_wick_ratio"] == 0.35
    assert res_primary.parameters["rsi_period"] == 14

    # 2. Secondary fallback when support_resistance_bounce is excluded
    strategies_no_sr = [
        s for s in list_available_strategies() if s["id"] != "support_resistance_bounce"
    ]
    res_secondary = matcher._heuristic_profile_for_asset(
        asset="UNKNOWN_SYNTHETIC_ASSET_1",
        strategies=strategies_no_sr,
        expiration_bars=3,
    )
    assert res_secondary.strategy_id == "rsi_stochastic_extreme"
    assert res_secondary.parameters["rsi_period"] == 14
    assert res_secondary.parameters["stoch_k"] == 14
    assert res_secondary.parameters["stoch_d"] == 3

    # 3. Tertiary fallback when both are excluded
    strategies_tertiary = [
        s
        for s in list_available_strategies()
        if s["id"] not in ("support_resistance_bounce", "rsi_stochastic_extreme")
    ]
    res_tertiary = matcher._heuristic_profile_for_asset(
        asset="UNKNOWN_SYNTHETIC_ASSET_1",
        strategies=strategies_tertiary,
        expiration_bars=3,
    )
    assert res_tertiary.strategy_id == strategies_tertiary[0]["id"]
    assert res_tertiary.parameters["base_expiration_bars"] == 3


@pytest.mark.asyncio
async def test_automatcher_find_optimal_strategy_edge_case_inputs():
    """Verify find_optimal_strategy_for_asset handles edge case inputs gracefully."""
    matcher = StrategyAutoMatcher(candle_count=150)

    # 1. Empty candle list
    res_empty = await matcher.find_optimal_strategy_for_asset("CUSTOM_ASSET", [])
    assert res_empty.strategy_id == "support_resistance_bounce"

    # 2. Sparse candle list (<35 candles)
    sparse_candles = [
        Candle(
            open_time=datetime(2026, 8, 20, 10, i, tzinfo=UTC),
            open=Decimal("1.1000"),
            high=Decimal("1.1005"),
            low=Decimal("1.0995"),
            close=Decimal("1.1001"),
            volume=Decimal("50"),
        )
        for i in range(10)
    ]
    res_sparse = await matcher.find_optimal_strategy_for_asset("CUSTOM_ASSET", sparse_candles)
    assert res_sparse.strategy_id == "support_resistance_bounce"

    # 3. Sparse DataFrame (<35 rows)
    df_sparse = pd.DataFrame(
        [{"close": 1.1000, "open": 1.1000, "high": 1.1005, "low": 1.0995}] * 20
    )
    res_df_sparse = await matcher.find_optimal_strategy_for_asset("CUSTOM_ASSET", df_sparse)
    assert res_df_sparse.strategy_id == "support_resistance_bounce"


# ============================================================================
# 4. Hybrid Multi-Factors Strict Concordance & Volatility Spike Tests
# ============================================================================


def _create_bar_eval_df(
    *,
    close: float = 1.0500,
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
) -> pd.DataFrame:
    rows = []
    base_t = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    for i in range(60):
        rows.append(
            {
                "timestamp": base_t + timedelta(minutes=i),
                "open": close,
                "high": close + 0.0002,
                "low": close - 0.0002,
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


def test_hybrid_strategy_volatility_spike_suppression():
    """Verify extreme volatility spikes (atr / atr_sma > 2.5) suppress signals."""
    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0)
    # Volatility spike: atr = 0.0030, atr_sma = 0.0010 -> ratio = 3.0 > 2.5
    df_spike = _create_bar_eval_df(
        close=1.0505,
        ema_fast=1.0500,
        ema_mid=1.0485,
        rsi=56.0,
        stoch_k=65.0,
        stoch_d=48.0,
        adx=26.5,
        adx_pos=29.0,
        adx_neg=11.0,
        atr=0.0030,
        atr_sma=0.0010,
    )
    res = strat.evaluate_bar(df_spike, 55)

    assert res.action is None
    assert res.confidence == 0.0
    assert res.regime == "volatility_spike_suppressed"


def test_hybrid_strategy_directional_di_conflict_suppression():
    """Verify bullish setup with conflicting bearish ADX (-DI > +DI) is suppressed."""
    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0)

    # Bullish setup but adx_neg > adx_pos
    df_di_conflict = _create_bar_eval_df(
        close=1.0505,
        ema_fast=1.0500,
        ema_mid=1.0485,
        rsi=56.0,
        stoch_k=65.0,
        stoch_d=48.0,
        adx=26.5,
        adx_pos=14.0,
        adx_neg=28.0,  # conflicting bearish directional index
    )
    res = strat.evaluate_bar(df_di_conflict, 55)
    assert res.action is None
    assert res.confidence == 0.0


def test_hybrid_strategy_stochastic_crossover_conflict_suppression():
    """Verify bullish setup with conflicting Stochastic (stoch_k < stoch_d) is suppressed."""
    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0)

    # Bullish setup but stoch_k < stoch_d
    df_stoch_conflict = _create_bar_eval_df(
        close=1.0505,
        ema_fast=1.0500,
        ema_mid=1.0485,
        rsi=56.0,
        stoch_k=48.0,
        stoch_d=65.0,  # bearish stoch cross
        adx=26.5,
        adx_pos=29.0,
        adx_neg=11.0,
    )
    res = strat.evaluate_bar(df_stoch_conflict, 55)
    assert res.action is None
    assert res.confidence == 0.0
