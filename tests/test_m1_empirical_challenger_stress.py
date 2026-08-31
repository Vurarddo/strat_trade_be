"""Empirical Challenger Stress & Adversarial Verification Suite for Milestone 1.

Verifies:
1. Strict Sniper Trio priority allocation invariance.
2. Exhaustive asset taxonomy heuristic mapping.
3. Fuzzing, missing columns, corrupt data, and boundary condition resilience.
4. Strategy registry instance resolution, case insensitivity, kwargs filtering, and fallback.
5. All catalog strategies integrity and backwards compatibility.
6. Variation generation validity across all strategies.
7. Flatline/zero-volatility candle data resilience.
8. Asynchronous concurrency safety.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pandas as pd
import pytest

from strat_trade.domain.entities import Candle
from strat_trade.domain.optimizer.auto_matcher import (
    PRIORITY_STRATEGIES,
    StrategyAutoMatcher,
)
from strat_trade.domain.strategies.base import BaseStrategy
from strat_trade.domain.strategies.bollinger_atr_reversion import BollingerAtrReversionStrategy
from strat_trade.domain.strategies.ema_pullback_trend import EmaPullbackTrendStrategy
from strat_trade.domain.strategies.hybrid_multifactors import HybridMultiFactorsStrategy
from strat_trade.domain.strategies.macd_divergence_break import MacdDivergenceBreakStrategy
from strat_trade.domain.strategies.registry import (
    _STRATEGIES,
    get_strategy_instance,
    list_available_strategies,
)
from strat_trade.domain.strategies.rsi_stochastic_extreme import RsiStochasticExtremeStrategy
from strat_trade.domain.strategies.supertrend_adx_momentum import SupertrendAdxMomentumStrategy
from strat_trade.domain.strategies.support_resistance_bounce import (
    SupportResistanceBounceStrategy,
)
from strat_trade.domain.strategies.volatility_squeeze_breakout import (
    VolatilitySqueezeBreakoutStrategy,
)
from strat_trade.domain.trading.entities import StrategyAssignment


class TestMilestone1SniperTrioInvariants:
    """Empirically test that Milestone 1 priority strategy invariants hold."""

    def test_priority_strategies_exact_composition(self) -> None:
        """Confirm PRIORITY_STRATEGIES contains strictly the Sniper Trio and nothing else."""
        expected = frozenset(
            {
                "support_resistance_bounce",
                "rsi_stochastic_extreme",
            }
        )
        assert PRIORITY_STRATEGIES == expected
        assert len(PRIORITY_STRATEGIES) == 2

    def test_legacy_strategies_excluded_from_priority(self) -> None:
        """Confirm legacy indicator-spam strategies are completely excluded from priority."""
        legacy_strategies = [
            "hybrid_multifactors",
            "bollinger_atr_reversion",
            "macd_divergence_break",
            "volatility_squeeze_breakout",
            "supertrend_adx_momentum",
            "ema_pullback_trend",
        ]
        for strat_id in legacy_strategies:
            assert strat_id not in PRIORITY_STRATEGIES, (
                f"Legacy strategy {strat_id} must not be in PRIORITY_STRATEGIES"
            )

    def test_all_priority_strategies_exist_in_registry(self) -> None:
        """Verify each priority strategy is registered with valid metadata and class."""
        available_ids = {s["id"] for s in list_available_strategies()}
        for strat_id in PRIORITY_STRATEGIES:
            assert strat_id in available_ids
            meta = _STRATEGIES[strat_id]
            assert issubclass(meta.cls, BaseStrategy)
            assert len(meta.cls.get_parameter_definitions()) > 0


class TestRegistryInstanceResolutionStress:
    """Empirically test get_strategy_instance edge cases, backwards compatibility,
    and fallback safety.
    """

    @pytest.mark.parametrize(
        ("input_name", "expected_cls"),
        [
            ("support_resistance_bounce", SupportResistanceBounceStrategy),
            ("rsi_stochastic_extreme", RsiStochasticExtremeStrategy),
            ("ema_pullback_trend", EmaPullbackTrendStrategy),
            ("SUPPORT_RESISTANCE_BOUNCE", SupportResistanceBounceStrategy),
            ("  rsi_stochastic_extreme  ", RsiStochasticExtremeStrategy),
            ("Ema_Pullback_Trend", EmaPullbackTrendStrategy),
            # Backwards compatibility checks for legacy strategies
            ("hybrid_multifactors", HybridMultiFactorsStrategy),
            ("bollinger_atr_reversion", BollingerAtrReversionStrategy),
            ("macd_divergence_break", MacdDivergenceBreakStrategy),
            ("volatility_squeeze_breakout", VolatilitySqueezeBreakoutStrategy),
            ("supertrend_adx_momentum", SupertrendAdxMomentumStrategy),
        ],
    )
    def test_direct_and_case_insensitive_instantiation(
        self, input_name: str, expected_cls: type[BaseStrategy]
    ) -> None:
        instance = get_strategy_instance(input_name)
        assert isinstance(instance, expected_cls)
        assert isinstance(instance, BaseStrategy)

    @pytest.mark.parametrize(
        "invalid_or_unknown_name",
        [
            "unknown_random_strategy",
            "",
            "   ",
            "__invalid__",
            "macd_divergence_break_v2",
            None,
            12345,
            {"nested": "dict"},
            ["list", "name"],
            object(),
        ],
    )
    def test_fallback_on_unknown_or_invalid_types(self, invalid_or_unknown_name: object) -> None:
        """Invalid or unknown strategy names must cleanly fall back
        to SupportResistanceBounceStrategy.
        """
        instance = get_strategy_instance(invalid_or_unknown_name)  # type: ignore[arg-type]
        assert isinstance(instance, SupportResistanceBounceStrategy)
        assert isinstance(instance, BaseStrategy)

    def test_kwargs_filtering_and_injection_safety(self) -> None:
        """Unrecognized kwargs should be safely ignored without raising TypeError."""
        instance = get_strategy_instance(
            "support_resistance_bounce",
            params={"swing_window": 18},
            unknown_injection_param="dangerous_payload",
            unexpected_int=9999,
        )
        assert isinstance(instance, SupportResistanceBounceStrategy)
        assert getattr(instance, "swing_window", None) == 18

    def test_parameter_override_precedence(self) -> None:
        """Explicit kwargs should override params dict keys."""
        instance = get_strategy_instance(
            "rsi_stochastic_extreme",
            params={"rsi_period": 14, "rsi_oversold": 20.0},
            rsi_oversold=30.0,
        )
        assert isinstance(instance, RsiStochasticExtremeStrategy)
        assert getattr(instance, "rsi_period", None) == 14
        assert getattr(instance, "rsi_oversold", None) == 30.0


class TestHeuristicAssetTaxonomyStress:
    """Empirically test heuristic profile mapping for all asset categories."""

    @pytest.fixture
    def matcher(self) -> StrategyAutoMatcher:
        return StrategyAutoMatcher()

    @pytest.fixture
    def strategies(self) -> list[dict]:
        return list_available_strategies()

    @pytest.mark.parametrize(
        "gold_asset",
        ["GOLD", "GOLD_otc", "XAUUSD", "XAUUSD_otc", "xau_usd", "gold_spot"],
    )
    def test_gold_and_commodities_map_to_sr_bounce(
        self, matcher: StrategyAutoMatcher, strategies: list[dict], gold_asset: str
    ) -> None:
        profile = matcher._heuristic_profile_for_asset(gold_asset, strategies, expiration_bars=3)
        assert profile.strategy_id == "support_resistance_bounce"
        assert profile.strategy_id in PRIORITY_STRATEGIES
        assert "підтримки/опору" in profile.rationale or "Pin-Bar" in profile.rationale
        assert profile.parameters.get("base_expiration_bars") == 3

    @pytest.mark.parametrize(
        "stock_asset",
        ["AAPL", "TSLA", "NVDA", "INTC", "#AAPL_otc", "#US_TECH", "#NVDA_stock"],
    )
    def test_stocks_map_to_support_resistance_bounce(
        self, matcher: StrategyAutoMatcher, strategies: list[dict], stock_asset: str
    ) -> None:
        profile = matcher._heuristic_profile_for_asset(stock_asset, strategies, expiration_bars=3)
        assert profile.strategy_id == "support_resistance_bounce"
        assert profile.strategy_id in PRIORITY_STRATEGIES
        assert "підтримки/опору" in profile.rationale or "Pin-Bar" in profile.rationale
        assert profile.parameters.get("base_expiration_bars") == 3

    @pytest.mark.parametrize(
        "crypto_asset",
        [
            "BTCUSD_otc",
            "ETHUSD_otc",
            "BNBUSD_otc",
            "SOLUSD_otc",
            "DOGEUSD_otc",
            "XRPUSD_otc",
            "MATICUSD_otc",
        ],
    )
    def test_crypto_maps_to_rsi_stoch_extreme(
        self, matcher: StrategyAutoMatcher, strategies: list[dict], crypto_asset: str
    ) -> None:
        profile = matcher._heuristic_profile_for_asset(crypto_asset, strategies, expiration_bars=2)
        assert profile.strategy_id == "rsi_stochastic_extreme"
        assert profile.strategy_id in PRIORITY_STRATEGIES
        assert "осциляторів" in profile.rationale
        assert profile.parameters.get("base_expiration_bars") == 2

    @pytest.mark.parametrize(
        "jpy_gbp_forex",
        ["USDJPY_otc", "GBPJPY_otc", "EURGBP_otc", "GBPUSD_otc", "AUDJPY_otc", "CADJPY"],
    )
    def test_jpy_gbp_forex_maps_to_sr_bounce(
        self, matcher: StrategyAutoMatcher, strategies: list[dict], jpy_gbp_forex: str
    ) -> None:
        profile = matcher._heuristic_profile_for_asset(jpy_gbp_forex, strategies, expiration_bars=3)
        assert profile.strategy_id == "support_resistance_bounce"
        assert profile.strategy_id in PRIORITY_STRATEGIES
        assert "відбою" in profile.rationale or "підтримки" in profile.rationale

    @pytest.mark.parametrize(
        "other_forex",
        [
            "EURUSD_otc",
            "AUDUSD_otc",
            "NZDUSD_otc",
            "USDCAD_otc",
            "USDCHF_otc",
            "USDARS_otc",
            "USDCNH_otc",
            "USDCLP_otc",
            "USDBDT_otc",
            "USDEGP_otc",
        ],
    )
    def test_other_forex_maps_to_rsi_stoch_extreme(
        self, matcher: StrategyAutoMatcher, strategies: list[dict], other_forex: str
    ) -> None:
        profile = matcher._heuristic_profile_for_asset(other_forex, strategies, expiration_bars=3)
        assert profile.strategy_id == "rsi_stochastic_extreme"
        assert profile.strategy_id in PRIORITY_STRATEGIES
        assert "осциляторів" in profile.rationale

    @pytest.mark.parametrize(
        "unclassified_asset",
        ["UNKNOWN_COMMODITY", "RANDOM_SYMBOL", "XYZ123", "", "___$$$%%%", "123456"],
    )
    def test_unclassified_asset_fallback_strictly_in_priority(
        self, matcher: StrategyAutoMatcher, strategies: list[dict], unclassified_asset: str
    ) -> None:
        profile = matcher._heuristic_profile_for_asset(
            unclassified_asset, strategies, expiration_bars=4
        )
        assert profile.strategy_id in PRIORITY_STRATEGIES
        assert profile.strategy_id in ("support_resistance_bounce", "rsi_stochastic_extreme")
        assert profile.parameters.get("base_expiration_bars") == 4


class TestAutoMatcherFuzzAndBoundaryResilience:
    """Empirically test find_optimal_strategy_for_asset against malformed inputs and fuzzing."""

    @pytest.fixture
    def matcher(self) -> StrategyAutoMatcher:
        return StrategyAutoMatcher()

    @pytest.mark.asyncio
    async def test_empty_candle_list(self, matcher: StrategyAutoMatcher) -> None:
        res = await matcher.find_optimal_strategy_for_asset("EURUSD_otc", [])
        assert isinstance(res, StrategyAssignment)
        assert res.strategy_id in PRIORITY_STRATEGIES
        assert res.asset == "EURUSD_otc"

    @pytest.mark.asyncio
    async def test_empty_dataframe(self, matcher: StrategyAutoMatcher) -> None:
        df_empty = pd.DataFrame()
        res = await matcher.find_optimal_strategy_for_asset("EURUSD_otc", df_empty)
        assert isinstance(res, StrategyAssignment)
        assert res.strategy_id in PRIORITY_STRATEGIES

    @pytest.mark.asyncio
    @pytest.mark.parametrize("n_rows", [1, 5, 10, 25, 34])
    async def test_insufficient_candle_count_triggers_heuristic(
        self, matcher: StrategyAutoMatcher, n_rows: int
    ) -> None:
        candles = [
            Candle(
                open_time=1700000000 + i * 60,
                open=1.1000 + i * 0.0001,
                high=1.1010 + i * 0.0001,
                low=1.0990 + i * 0.0001,
                close=1.1005 + i * 0.0001,
                volume=100.0,
            )
            for i in range(n_rows)
        ]
        res = await matcher.find_optimal_strategy_for_asset("USDJPY_otc", candles)
        assert isinstance(res, StrategyAssignment)
        assert res.strategy_id in PRIORITY_STRATEGIES
        assert res.strategy_id == "support_resistance_bounce"

    @pytest.mark.asyncio
    async def test_missing_or_corrupted_columns_in_dataframe(
        self, matcher: StrategyAutoMatcher
    ) -> None:
        """DataFrames missing essential OHLC columns fail microstructure qualification
        and return None.
        """
        df_missing_close = pd.DataFrame(
            {
                "open": [1.10 + i * 0.001 for i in range(50)],
                "high": [1.11 + i * 0.001 for i in range(50)],
                "low": [1.09 + i * 0.001 for i in range(50)],
            }
        )
        res = await matcher.find_optimal_strategy_for_asset("EURUSD_otc", df_missing_close)
        assert res is None

    @pytest.mark.asyncio
    async def test_nan_and_inf_resilience(self, matcher: StrategyAutoMatcher) -> None:
        """DataFrames with NaN or Infinite values fail microstructure qualification
        and return None.
        """
        df_corrupt = pd.DataFrame(
            {
                "open": [1.10] * 50,
                "high": [np.nan] * 25 + [np.inf] * 25,
                "low": [-np.inf] * 25 + [1.08] * 25,
                "close": [1.09] * 50,
                "volume": [0.0] * 50,
            }
        )
        res = await matcher.find_optimal_strategy_for_asset("GOLD_otc", df_corrupt)
        assert res is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "toxic_asset", ["USDIDR_otc", "USDVND_otc", "EURCHF_otc", "USDDZD_otc"]
    )
    async def test_toxic_asset_blacklist_guard(
        self, matcher: StrategyAutoMatcher, toxic_asset: str
    ) -> None:
        """Toxic OTC assets should immediately be rejected with None."""
        candles = [
            Candle(
                open_time=1700000000 + i * 60,
                open=100.0 + i * 0.1,
                high=101.0 + i * 0.1,
                low=99.0 + i * 0.1,
                close=100.5 + i * 0.1,
                volume=50.0,
            )
            for i in range(100)
        ]
        res = await matcher.find_optimal_strategy_for_asset(toxic_asset, candles)
        assert res is None

    @pytest.mark.asyncio
    async def test_backtest_matching_strictly_selects_sniper_trio(
        self, matcher: StrategyAutoMatcher
    ) -> None:
        """When candles produce trades, winner must be strictly in PRIORITY_STRATEGIES."""
        # Generate 150 oscillating sine wave candles
        t = np.linspace(0, 8 * np.pi, 150)
        prices = 1.1000 + 0.0050 * np.sin(t)
        df_osc = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=150, freq="min"),
                "open": prices,
                "high": prices + 0.0008,
                "low": prices - 0.0008,
                "close": prices + 0.0002 * np.cos(t),
                "volume": [150.0] * 150,
            }
        )

        res = await matcher.find_optimal_strategy_for_asset("EURUSD_otc", df_osc)
        assert isinstance(res, StrategyAssignment)
        assert res.strategy_id in PRIORITY_STRATEGIES, (
            f"Selected strategy {res.strategy_id} must be in PRIORITY_STRATEGIES"
        )
        assert res.strategy_id in (
            "support_resistance_bounce",
            "rsi_stochastic_extreme",
            "ema_pullback_trend",
        )

    @pytest.mark.asyncio
    async def test_flatline_zero_volatility_candles(self, matcher: StrategyAutoMatcher) -> None:
        """Flat / zero volatility candles fail microstructure qualification and return None."""
        df_flat = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=100, freq="min"),
                "open": [1.1000] * 100,
                "high": [1.1000] * 100,
                "low": [1.1000] * 100,
                "close": [1.1000] * 100,
                "volume": [0.0] * 100,
            }
        )
        res = await matcher.find_optimal_strategy_for_asset("EURUSD_otc", df_flat)
        assert res is None


class TestStrategyVariationsGeneration:
    """Empirically test variation generator for every registered strategy."""

    def test_variations_for_all_registered_strategies(self) -> None:
        matcher = StrategyAutoMatcher()
        strategies = list_available_strategies()
        for strat in strategies:
            strat_id = strat["id"]
            def_params = {p["name"]: p["default"] for p in strat["parameters"]}
            variations = matcher._generate_strategy_variations(
                strat_id=strat_id,
                def_params=def_params,
                base_expiration_bars=3,
            )
            assert len(variations) >= 1, f"Strategy {strat_id} must have at least 1 variation"
            for var in variations:
                assert "base_expiration_bars" in var
                assert var["base_expiration_bars"] >= 1


class TestConcurrencyAndAsyncSafety:
    """Empirically test concurrent execution of find_optimal_strategy_for_asset."""

    @pytest.mark.asyncio
    async def test_concurrent_matching_runs(self) -> None:
        matcher = StrategyAutoMatcher()
        assets = [
            "EURUSD_otc",
            "USDJPY_otc",
            "GOLD_otc",
            "AAPL",
            "BTCUSD_otc",
            "GBPUSD_otc",
            "AUDUSD_otc",
            "NVDA",
        ]

        async def run_one(asset: str) -> StrategyAssignment | None:
            candles = [
                Candle(
                    open_time=1700000000 + i * 60,
                    open=1.10 + (i % 30) * 0.001,
                    high=1.11 + (i % 30) * 0.001,
                    low=1.09 + (i % 30) * 0.001,
                    close=1.105 + (i % 30) * 0.001,
                    volume=100.0,
                )
                for i in range(50)
            ]
            return await matcher.find_optimal_strategy_for_asset(asset, candles)

        # Run 40 concurrent tasks
        tasks = [run_one(assets[i % len(assets)]) for i in range(40)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 40
        for res in results:
            assert isinstance(res, StrategyAssignment)
            assert res.strategy_id in PRIORITY_STRATEGIES
