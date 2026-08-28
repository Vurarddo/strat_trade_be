"""Empirical Challenger 2 Boundary & Confluence Verification Suite for Milestone 1.

Rigorously verifies:
1. Complete deactivation of MACD Divergence & Cross (macd_divergence_break) and
   hybrid_multifactors from automatic strategy matching across ALL asset classes.
2. Optimal Sniper strategy allocation across Commodities, Stocks, Crypto, and Forex.
3. Boundary & confluence stress-testing (adversarial candle shapes, extreme parameters,
   fuzzy asset names, corrupt DataFrames, end-to-end plan generation).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from strat_trade.domain.entities import Candle
from strat_trade.domain.optimizer.auto_matcher import (
    PRIORITY_STRATEGIES,
    StrategyAutoMatcher,
)
from strat_trade.domain.strategies.base import BaseStrategy
from strat_trade.domain.strategies.ema_pullback_trend import EmaPullbackTrendStrategy
from strat_trade.domain.strategies.hybrid_multifactors import HybridMultiFactorsStrategy
from strat_trade.domain.strategies.macd_divergence_break import MacdDivergenceBreakStrategy
from strat_trade.domain.strategies.registry import (
    get_strategy_instance,
    list_available_strategies,
)
from strat_trade.domain.strategies.rsi_stochastic_extreme import RsiStochasticExtremeStrategy
from strat_trade.domain.strategies.support_resistance_bounce import (
    SupportResistanceBounceStrategy,
)
from strat_trade.domain.trading.entities import PreTradingPlan, StrategyAssignment
from strat_trade.ports.candles import CandleFeed
from strat_trade.use_cases.auto_assign_strategies import generate_pre_trading_plan

SNIPER_DUO: frozenset[str] = frozenset(
    {
        "support_resistance_bounce",
        "rsi_stochastic_extreme",
    }
)

DEACTIVATED_LEGACY_STRATEGIES: frozenset[str] = frozenset(
    {
        "macd_divergence_break",
        "hybrid_multifactors",
        "supertrend_adx_momentum",
        "volatility_squeeze_breakout",
        "bollinger_atr_reversion",
        "ema_pullback_trend",
    }
)


class MockCandleFeed(CandleFeed):
    """Deterministic mock candle feed for multi-asset plan generation testing."""

    def __init__(self, candle_count: int = 150) -> None:
        self.candle_count = candle_count

    async def get_candles(self, asset: str, timeframe: int = 60, count: int = 150) -> list[Candle]:
        base_t = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
        candles = []
        base_price = 100.0 if "GOLD" in asset.upper() or "#" in asset else 1.1000
        for i in range(count):
            price = base_price + 0.0005 * np.sin(i * 0.2)
            candles.append(
                Candle(
                    open_time=base_t + timedelta(minutes=i),
                    open=Decimal(str(round(price, 5))),
                    high=Decimal(str(round(price + 0.0008, 5))),
                    low=Decimal(str(round(price - 0.0008, 5))),
                    close=Decimal(str(round(price + 0.0002, 5))),
                    volume=Decimal("100"),
                )
            )
        return candles


@pytest.fixture
def matcher() -> StrategyAutoMatcher:
    return StrategyAutoMatcher(candle_count=150)


# =====================================================================
# SECTION 1: INVARIANCE OF PRIORITY_STRATEGIES & DEACTIVATION
# =====================================================================


class TestDeactivationInvariance:
    """Verify that legacy indicator-spam strategies are NEVER in PRIORITY_STRATEGIES."""

    def test_priority_strategies_contract(self) -> None:
        assert PRIORITY_STRATEGIES == SNIPER_DUO
        assert len(PRIORITY_STRATEGIES) == 2
        for legacy in DEACTIVATED_LEGACY_STRATEGIES:
            assert legacy not in PRIORITY_STRATEGIES, f"{legacy} must NOT be in PRIORITY_STRATEGIES"

    def test_macd_and_hybrid_specifically_excluded(self) -> None:
        assert "macd_divergence_break" not in PRIORITY_STRATEGIES
        assert "hybrid_multifactors" not in PRIORITY_STRATEGIES


# =====================================================================
# SECTION 2: EXHAUSTIVE ASSET UNIVERSE HEURISTIC ROUTING
# =====================================================================


class TestAssetUniverseHeuristicRouting:
    """Empirically test heuristic profile mapping across 50+ real/synthetic assets."""

    COMMODITIES = [
        "Gold_otc",
        "GOLD",
        "XAUUSD",
        "XAUUSD_otc",
        "GOLD_OTC_2026",
        "XAU_EUR",
    ]

    STOCKS = [
        "#AAPL_otc",
        "#TSLA_otc",
        "#NVDA_otc",
        "#INTC",
        "#MSFT_otc",
        "AAPL",
        "TSLA",
        "NVDA",
        "INTC",
        "#AMZN",
        "#GOOGL",
    ]

    CRYPTO = [
        "BTCUSD_otc",
        "ETHUSD_otc",
        "SOLUSD_otc",
        "DOGEUSD_otc",
        "XRPUSD_otc",
        "MATICUSD_otc",
        "BNBUSD_otc",
        "BTC_USDT",
        "ETH_EUR",
    ]

    FOREX_JPY_GBP = [
        "USDJPY_otc",
        "GBPJPY_otc",
        "GBPUSD_otc",
        "EURJPY_otc",
        "GBPAUD_otc",
        "GBPCAD_otc",
        "CHFJPY_otc",
        "CADJPY_otc",
        "EURGBP_otc",
    ]

    FOREX_OTHER = [
        "EURUSD_otc",
        "AUDUSD_otc",
        "NZDUSD_otc",
        "USDCAD_otc",
        "USDCHF_otc",
        "USDCLP_otc",
        "USDBDT_otc",
        "USDEGP_otc",
        "USDARS_otc",
        "USDCNH_otc",
        "AUDCAD_otc",
        "NZDCHF_otc",
    ]

    UNCLASSIFIED = [
        "SYNTHETIC_INDEX_01",
        "CUSTOM_TOKEN_XYZ",
        "RANDOM_PAIR_99",
        "UNKNOWN_ASSET",
        "ALPHA_BETA_COIN",
    ]

    @pytest.mark.parametrize("asset", COMMODITIES)
    def test_commodities_routed_to_support_resistance_bounce(
        self, matcher: StrategyAutoMatcher, asset: str
    ) -> None:
        strategies = list_available_strategies()
        profile = matcher._heuristic_profile_for_asset(asset, strategies, expiration_bars=3)
        assert profile.strategy_id == "support_resistance_bounce"
        assert profile.strategy_id in SNIPER_DUO
        assert profile.strategy_id not in DEACTIVATED_LEGACY_STRATEGIES
        assert "swing_window" in profile.parameters
        assert "min_wick_ratio" in profile.parameters

    @pytest.mark.parametrize("asset", STOCKS)
    def test_stocks_routed_to_support_resistance_bounce(
        self, matcher: StrategyAutoMatcher, asset: str
    ) -> None:
        strategies = list_available_strategies()
        profile = matcher._heuristic_profile_for_asset(asset, strategies, expiration_bars=3)
        assert profile.strategy_id == "support_resistance_bounce"
        assert profile.strategy_id in SNIPER_DUO
        assert profile.strategy_id not in DEACTIVATED_LEGACY_STRATEGIES
        assert "swing_window" in profile.parameters
        assert "min_wick_ratio" in profile.parameters

    @pytest.mark.parametrize("asset", CRYPTO)
    def test_crypto_routed_to_rsi_stochastic_extreme(
        self, matcher: StrategyAutoMatcher, asset: str
    ) -> None:
        strategies = list_available_strategies()
        profile = matcher._heuristic_profile_for_asset(asset, strategies, expiration_bars=3)
        assert profile.strategy_id == "rsi_stochastic_extreme"
        assert profile.strategy_id in SNIPER_DUO
        assert profile.strategy_id not in DEACTIVATED_LEGACY_STRATEGIES
        assert "rsi_oversold" in profile.parameters
        assert "stoch_oversold" in profile.parameters

    @pytest.mark.parametrize("asset", FOREX_JPY_GBP)
    def test_forex_jpy_gbp_routed_to_support_resistance_bounce(
        self, matcher: StrategyAutoMatcher, asset: str
    ) -> None:
        strategies = list_available_strategies()
        profile = matcher._heuristic_profile_for_asset(asset, strategies, expiration_bars=3)
        assert profile.strategy_id == "support_resistance_bounce"
        assert profile.strategy_id in SNIPER_DUO
        assert profile.strategy_id not in DEACTIVATED_LEGACY_STRATEGIES

    @pytest.mark.parametrize("asset", FOREX_OTHER)
    def test_forex_other_routed_to_rsi_stochastic_extreme(
        self, matcher: StrategyAutoMatcher, asset: str
    ) -> None:
        strategies = list_available_strategies()
        profile = matcher._heuristic_profile_for_asset(asset, strategies, expiration_bars=3)
        assert profile.strategy_id == "rsi_stochastic_extreme"
        assert profile.strategy_id in SNIPER_DUO
        assert profile.strategy_id not in DEACTIVATED_LEGACY_STRATEGIES

    @pytest.mark.parametrize("asset", UNCLASSIFIED)
    def test_unclassified_routed_to_support_resistance_bounce(
        self, matcher: StrategyAutoMatcher, asset: str
    ) -> None:
        strategies = list_available_strategies()
        profile = matcher._heuristic_profile_for_asset(asset, strategies, expiration_bars=3)
        assert profile.strategy_id == "support_resistance_bounce"
        assert profile.strategy_id in SNIPER_DUO
        assert profile.strategy_id not in DEACTIVATED_LEGACY_STRATEGIES


# =====================================================================
# SECTION 3: ADVERSARIAL MARKET DATA & BACKTEST AUTO-MATCHING
# =====================================================================


class TestAdversarialMarketDataAutoMatching:
    """Stress test find_optimal_strategy_for_asset under extreme market conditions."""

    @pytest.mark.asyncio
    async def test_macd_engineered_data_never_selects_macd(
        self, matcher: StrategyAutoMatcher
    ) -> None:
        """Even with data crafted to maximize MACD divergence, MACD is never allocated."""
        # Create 150 bars of cyclical swing data with divergence
        t = np.linspace(0, 10 * np.pi, 150)
        p = 1.0500 + 0.0030 * np.sin(t) + 0.0001 * t
        df_macd = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=150, freq="min"),
                "open": p,
                "high": p + 0.0006,
                "low": p - 0.0006,
                "close": p + 0.0002 * np.cos(t),
                "volume": [100.0] * 150,
            }
        )

        res = await matcher.find_optimal_strategy_for_asset("EURUSD_otc", df_macd)
        assert res.strategy_id != "macd_divergence_break"
        assert res.strategy_id != "hybrid_multifactors"
        assert res.strategy_id in SNIPER_DUO

    @pytest.mark.asyncio
    async def test_strong_trending_data_strictly_allocates_sniper(
        self, matcher: StrategyAutoMatcher
    ) -> None:
        """Strong trending momentum data must allocate a Sniper strategy."""
        t = np.arange(150)
        p = 1.0000 + 0.0005 * t + 0.0001 * np.sin(t)
        df_trend = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=150, freq="min"),
                "open": p,
                "high": p + 0.0005,
                "low": p - 0.0002,
                "close": p + 0.0004,
                "volume": [200.0] * 150,
            }
        )

        res = await matcher.find_optimal_strategy_for_asset("#AAPL_otc", df_trend)
        assert res.strategy_id in SNIPER_DUO
        assert res.strategy_id not in DEACTIVATED_LEGACY_STRATEGIES

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "candle_length",
        [0, 1, 10, 34, 35, 36, 100, 200],
    )
    async def test_candle_length_boundary_conditions(
        self, matcher: StrategyAutoMatcher, candle_length: int
    ) -> None:
        """Check all candle length boundaries (empty, sub-threshold, exact threshold, large)."""
        base_t = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        candles = [
            Candle(
                open_time=base_t + timedelta(minutes=i),
                open=Decimal("1.1000"),
                high=Decimal("1.1010"),
                low=Decimal("1.0990"),
                close=Decimal("1.1005"),
                volume=Decimal("100"),
            )
            for i in range(candle_length)
        ]

        res = await matcher.find_optimal_strategy_for_asset("USDJPY_otc", candles)
        assert isinstance(res, StrategyAssignment)
        assert res.strategy_id in SNIPER_DUO
        assert res.strategy_id not in DEACTIVATED_LEGACY_STRATEGIES
        if candle_length < 35:
            # Fallback path taken
            assert res.strategy_id == "support_resistance_bounce"

    @pytest.mark.asyncio
    async def test_corrupt_data_graceful_fallback(self, matcher: StrategyAutoMatcher) -> None:
        """Corrupted data with NaNs, Infs, and negative prices must fall back cleanly."""
        df_corrupt = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=60, freq="min"),
                "open": [np.nan] * 30 + [1.0] * 30,
                "high": [np.inf] * 20 + [1.5] * 40,
                "low": [-np.inf] * 10 + [0.5] * 50,
                "close": [np.nan] * 60,
                "volume": [0.0] * 60,
            }
        )

        res = await matcher.find_optimal_strategy_for_asset("Gold_otc", df_corrupt)
        assert isinstance(res, StrategyAssignment)
        assert res.strategy_id in SNIPER_DUO
        assert res.strategy_id == "support_resistance_bounce"


# =====================================================================
# SECTION 4: REGISTRY FALLBACK & BACKWARD COMPATIBILITY
# =====================================================================


class TestRegistryFallbackSafety:
    """Verify registry fallback behavior, case insensitivity, and legacy compatibility."""

    def test_legacy_strategies_accessible_by_direct_id(self) -> None:
        """Legacy strategies can still be instantiated directly for backwards compatibility."""
        inst_macd = get_strategy_instance("macd_divergence_break")
        assert isinstance(inst_macd, MacdDivergenceBreakStrategy)

        inst_hybrid = get_strategy_instance("hybrid_multifactors")
        assert isinstance(inst_hybrid, HybridMultiFactorsStrategy)

    @pytest.mark.parametrize(
        "unknown_name",
        [
            "macd_divergence",
            "hybrid_v2",
            "unknown_strat",
            "",
            "   ",
            "!!!",
            "NONEXISTENT",
        ],
    )
    def test_unknown_names_fallback_to_support_resistance_bounce(self, unknown_name: str) -> None:
        inst = get_strategy_instance(unknown_name)
        assert isinstance(inst, SupportResistanceBounceStrategy)
        assert isinstance(inst, BaseStrategy)

    @pytest.mark.parametrize(
        ("case_variant", "expected_cls"),
        [
            ("SUPPORT_RESISTANCE_BOUNCE", SupportResistanceBounceStrategy),
            ("Support_Resistance_Bounce", SupportResistanceBounceStrategy),
            ("  support_resistance_bounce  ", SupportResistanceBounceStrategy),
            ("RSI_STOCHASTIC_EXTREME", RsiStochasticExtremeStrategy),
            ("rsi_stochastic_extreme", RsiStochasticExtremeStrategy),
            ("EMA_PULLBACK_TREND", EmaPullbackTrendStrategy),
            ("ema_pullback_trend", EmaPullbackTrendStrategy),
        ],
    )
    def test_case_insensitive_resolution(
        self, case_variant: str, expected_cls: type[BaseStrategy]
    ) -> None:
        inst = get_strategy_instance(case_variant)
        assert isinstance(inst, expected_cls)


# =====================================================================
# SECTION 5: USE CASE & END-TO-END PRE-TRADING PLAN VERIFICATION
# =====================================================================


class TestPreTradingPlanIntegration:
    """Verify generate_pre_trading_plan across 20+ diverse assets."""

    @pytest.mark.asyncio
    async def test_generate_pre_trading_plan_strictly_allocates_sniper_trio(self) -> None:
        feed = MockCandleFeed(candle_count=150)
        assets = [
            "EURUSD_otc",
            "GBPUSD_otc",
            "USDJPY_otc",
            "AUDUSD_otc",
            "NZDUSD_otc",
            "USDCLP_otc",
            "USDBDT_otc",
            "USDEGP_otc",
            "Gold_otc",
            "#AAPL_otc",
            "#TSLA_otc",
            "#NVDA_otc",
            "BTCUSD_otc",
            "ETHUSD_otc",
            "SOLUSD_otc",
            "GBPJPY_otc",
        ]

        plan: PreTradingPlan = await generate_pre_trading_plan(
            feed=feed,
            assets=assets,
            initial_deposit=1000.0,
            expiration_seconds=180,
            toxic_filter_enabled=True,
        )

        assert plan.total_assets == len(plan.assignments)
        assert len(plan.assignments) > 0

        for assignment in plan.assignments:
            # 1. Must strictly belong to the Sniper Trio
            assert assignment.strategy_id in SNIPER_DUO, (
                f"Asset {assignment.asset} assigned non-sniper strategy {assignment.strategy_id}"
            )
            # 2. Must NEVER be MACD or Hybrid
            assert assignment.strategy_id not in DEACTIVATED_LEGACY_STRATEGIES, (
                f"Asset {assignment.asset} assigned legacy strategy {assignment.strategy_id}"
            )
            # 3. Must have valid parameters
            assert len(assignment.parameters) > 0
            assert "base_expiration_bars" in assignment.parameters
            # 4. Quantum score and win rate sanity
            assert assignment.quantum_score > 0
            assert assignment.estimated_win_rate_pct >= 50.0
