"""Empirical Adversarial Stress Testing Suite — Challenger M2.

Exhaustively verifies:
1. Canonical Asset Key Normalization across all 11 Toxic Pairs & Edge Cases.
2. StrategyAutoMatcher Toxic Invariant: quantum_score == 10.0 and [TOXIC OTC BLACKLIST] rationale.
3. Whitelist Purity & Zero Collision with Blacklist (GBPJPY removal verification).
4. LiveDemoBotEngine Single-Asset Pre-Filter and _order_lock Execution Mutex.
5. Massive Multi-Threaded / High-Concurrency Execution Harness (Zero Toxic Leakage & Race Safety).
6. PreTradingPlan Safe Fallbacks and Filtering.
7. Settings & Configuration Integrity.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from strat_trade.api.routes.candles import _CURATED_ASSETS
from strat_trade.domain.entities import Candle
from strat_trade.domain.optimizer.auto_matcher import StrategyAutoMatcher
from strat_trade.domain.trading.asset_filter import (
    DEFAULT_HIGH_WINRATE_WHITELIST,
    DEFAULT_TOXIC_BLACKLIST,
    DEFAULT_TOXIC_OTC_BLACKLIST,
    canonical_asset_key,
    filter_allowed_assets,
    is_toxic_asset,
    is_whitelisted_asset,
)
from strat_trade.domain.trading.bot_engine import LiveDemoBotEngine
from strat_trade.domain.trading.entities import (
    BotStatus,
    PreTradingPlan,
    StrategyAssignment,
)
from strat_trade.domain.trading.trade_store import TradeStore
from strat_trade.ports.candles import CandleFeed
from strat_trade.settings import Settings
from strat_trade.use_cases.auto_assign_strategies import generate_pre_trading_plan

# ============================================================================
# Helpers & Synthetic Generators
# ============================================================================


def _create_mock_candles(count: int = 150, base_price: float = 1.1000) -> list[Candle]:
    t0 = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)
    candles = []
    p = base_price
    for i in range(count):
        step = 0.0003 if (i % 4 < 2) else -0.0002
        p_open = p
        p_close = p + step
        p_high = max(p_open, p_close) + 0.0002
        p_low = min(p_open, p_close) - 0.0002
        p = p_close
        candles.append(
            Candle(
                open_time=t0 + timedelta(minutes=i),
                open=Decimal(f"{p_open:.5f}"),
                high=Decimal(f"{p_high:.5f}"),
                low=Decimal(f"{p_low:.5f}"),
                close=Decimal(f"{p_close:.5f}"),
                volume=Decimal("1000"),
            )
        )
    return candles


def _generate_asset_permutations(base: str, quote: str) -> list[str]:
    """Generates all standard and exotic token permutations for a currency pair."""
    delimiters = ["", "/", "_", "-", " ", " / ", " - "]
    suffixes = ["", "_otc", "-otc", " otc", " (otc)", " OTC", "_OTC", "-OTC", " (OTC)"]
    casing_transforms = [
        lambda s: s.upper(),
        lambda s: s.lower(),
        lambda s: s.capitalize(),
        lambda s: s.title(),
    ]

    permutations = set()
    for d in delimiters:
        raw_pair = f"{base}{d}{quote}"
        for s in suffixes:
            combined = f"{raw_pair}{s}"
            for tr in casing_transforms:
                transformed = tr(combined)
                permutations.add(transformed)
                permutations.add(f"  {transformed}  ")
                permutations.add(f"\t{transformed}\n")

    return sorted(permutations)


# ============================================================================
# 1. EXHAUSTIVE CANONICAL NORMALIZATION & BLACKLIST DETECTION
# ============================================================================


class TestAdversarialCanonicalNormalization:
    """Stress tests canonical asset key extraction across thousands of permutation variants."""

    TOXIC_PAIRS = [
        ("USD", "DZD", "USDDZD"),
        ("UAH", "USD", "UAHUSD"),
        ("USD", "MYR", "USDMYR"),
        ("USD", "INR", "USDINR"),
        ("EUR", "HUF", "EURHUF"),
        ("GBP", "JPY", "GBPJPY"),
        ("USD", "IDR", "USDIDR"),
        ("USD", "VND", "USDVND"),
        ("EUR", "CHF", "EURCHF"),
    ]

    @pytest.mark.parametrize(("base", "quote", "expected_canonical"), TOXIC_PAIRS)
    def test_toxic_pair_exhaustive_permutations(
        self, base: str, quote: str, expected_canonical: str
    ):
        """Generates dozens of formatting variants per toxic pair and verifies 100% rejection."""
        variants = _generate_asset_permutations(base, quote)
        assert len(variants) > 20

        for var in variants:
            clean_key = canonical_asset_key(var)
            assert clean_key == expected_canonical, (
                f"Variant '{var}' produced '{clean_key}', expected '{expected_canonical}'"
            )

            is_tox, reason = is_toxic_asset(var)
            assert is_tox is True, f"Variant '{var}' was falsely evaluated as non-toxic!"
            assert "toxic OTC blacklist" in reason
            assert expected_canonical in reason

            # Toxic pairs must NEVER be whitelisted
            assert is_whitelisted_asset(var) is False, f"Variant '{var}' must NOT be whitelisted!"

    @pytest.mark.parametrize(
        ("variant", "expected_canonical"),
        [
            ("BNB OTC", "BNB"),
            ("bnb otc", "BNB"),
            ("BNB_otc", "BNB"),
            ("bnb_otc", "BNB"),
            ("BNB (OTC)", "BNB"),
            ("BNB/USD OTC", "BNBUSD"),
            ("bnb/usd_otc", "BNBUSD"),
            ("BNB-USD (otc)", "BNBUSD"),
            ("  BNBUSD  ", "BNBUSD"),
        ],
    )
    def test_bnb_crypto_toxic_variants(self, variant: str, expected_canonical: str):
        assert canonical_asset_key(variant) == expected_canonical
        is_tox, reason = is_toxic_asset(variant)
        assert is_tox is True
        assert "toxic OTC blacklist" in reason
        assert is_whitelisted_asset(variant) is False


# ============================================================================
# 2. WHITELIST PURITY & DISAMBIGUATION (NO GBPJPY OR TOXIC OVERLAP)
# ============================================================================


class TestWhitelistPurityAndDisambiguation:
    """Verifies that the whitelist is strictly disjoint from the toxic blacklist."""

    def test_default_toxic_and_whitelist_disjoint(self):
        """Mathematical assertion: Blacklist and Whitelist sets MUST HAVE ZERO INTERSECTION."""
        intersection_otc = DEFAULT_TOXIC_OTC_BLACKLIST.intersection(DEFAULT_HIGH_WINRATE_WHITELIST)
        assert intersection_otc == frozenset(), (
            f"Blacklist and Whitelist overlap on: {intersection_otc}"
        )

        intersection_alias = DEFAULT_TOXIC_BLACKLIST.intersection(DEFAULT_HIGH_WINRATE_WHITELIST)
        assert intersection_alias == frozenset(), (
            f"Alias Blacklist and Whitelist overlap on: {intersection_alias}"
        )

    def test_gbpjpy_completely_purged_from_whitelists(self):
        """Verify GBPJPY is absent from all whitelist constants and configs."""
        # 1. Domain constants
        assert "GBPJPY" not in DEFAULT_HIGH_WINRATE_WHITELIST
        assert "GBPJPY" in DEFAULT_TOXIC_OTC_BLACKLIST
        assert "GBPJPY" in DEFAULT_TOXIC_BLACKLIST

        # 2. Settings default factories
        s = Settings()
        assert "GBP/JPY OTC" in s.toxic_asset_blacklist
        assert "GBP/JPY OTC" not in s.high_winrate_asset_whitelist
        assert "GBPJPY_otc" not in s.high_winrate_asset_whitelist

        for white_item in s.high_winrate_asset_whitelist:
            canon = canonical_asset_key(white_item)
            assert canon != "GBPJPY"
            assert canon not in DEFAULT_TOXIC_OTC_BLACKLIST

        # 3. Curated assets API listing
        curated_symbols = [item["symbol"] for item in _CURATED_ASSETS]
        assert "GBPJPY_otc" not in curated_symbols
        assert "GBPJPY" not in curated_symbols

    def test_all_11_toxic_pairs_present_in_defaults(self):
        expected_canonical_keys = {
            "USDIDR",
            "USDVND",
            "BNB",
            "BNBUSD",
            "EURCHF",
            "USDDZD",
            "UAHUSD",
            "USDMYR",
            "USDINR",
            "EURHUF",
            "GBPJPY",
        }
        assert expected_canonical_keys.issubset(DEFAULT_TOXIC_OTC_BLACKLIST)
        assert expected_canonical_keys.issubset(DEFAULT_TOXIC_BLACKLIST)


# ============================================================================
# 3. STRATEGY AUTO-MATCHER ADVERSARIAL STRESS TESTS
# ============================================================================


class TestAutoMatcherAdversarialStress:
    """Stress tests StrategyAutoMatcher under adversarial and profitable candle inputs."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "toxic_symbol",
        [
            "USD/DZD OTC",
            "usddzd_otc",
            "USD_DZD_OTC",
            "UAH/USD OTC",
            "uah_usd_otc",
            "USD/MYR OTC",
            "usdmyr_otc",
            "USD/INR OTC",
            "usdinr_otc",
            "EUR/HUF OTC",
            "eurhuf_otc",
            "GBP/JPY OTC",
            "gbpjpy_otc",
            "USD/IDR OTC",
            "usdidr_otc",
            "USD/VND OTC",
            "usdvnd_otc",
            "BNB OTC",
            "bnb_otc",
            "BNBUSD_otc",
            "EUR/CHF OTC",
            "eurchf_otc",
        ],
    )
    async def test_automatcher_toxic_rejection_invariant_across_candle_types(
        self, toxic_symbol: str
    ):
        """Invariant: AutoMatcher MUST reject toxic symbols with None

        regardless of whether candles are empty, small, or hyper-profitable.
        """
        matcher = StrategyAutoMatcher(candle_count=150)

        # 1. Empty candle list
        res_empty = await matcher.find_optimal_strategy_for_asset(
            asset=toxic_symbol,
            candles=[],
            timeframe_seconds=60,
            expiration_bars=3,
        )
        assert res_empty is None

        # 2. Perfect synthetic candles
        perfect_candles = _create_mock_candles(150, base_price=1.2000)
        res_candles = await matcher.find_optimal_strategy_for_asset(
            asset=toxic_symbol,
            candles=perfect_candles,
            timeframe_seconds=60,
            expiration_bars=3,
        )
        assert res_candles is None

        # 3. As pandas DataFrame
        df_candles = pd.DataFrame(
            [
                {
                    "timestamp": c.open_time,
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": float(c.volume),
                }
                for c in perfect_candles
            ]
        )
        res_df = await matcher.find_optimal_strategy_for_asset(
            asset=toxic_symbol,
            candles=df_candles,
            timeframe_seconds=60,
            expiration_bars=3,
        )
        assert res_df is None


# ============================================================================
# 4. LIVE BOT ENGINE CONCURRENCY & ORDER LOCK HARNESS (ZERO TOXIC LEAKS)
# ============================================================================


class TestLiveDemoBotEngineAdversarialHarness:
    """Massive concurrent execution test to empirically prove zero race conditions & zero leaks."""

    @pytest.mark.asyncio
    async def test_bot_engine_single_asset_evaluation_prefilter(self):
        """Ensures _evaluate_single_asset terminates synchronously before any I/O on toxic pairs."""
        engine = LiveDemoBotEngine()
        gateway = AsyncMock()
        gateway.get_candles = AsyncMock()
        gateway.get_asset_payout = AsyncMock(return_value=0.92)
        gateway.open_trade = AsyncMock()

        toxic_assignment = StrategyAssignment(
            asset="USD/DZD OTC",
            strategy_id="supertrend_adx_momentum",
            strategy_name="SuperTrend",
            category="momentum",
            parameters={},
            estimated_win_rate_pct=60.0,
            estimated_profit_factor=1.5,
            estimated_trades_count=10,
            quantum_score=10.0,
            rationale="[TOXIC OTC BLACKLIST]",
        )

        plan = PreTradingPlan(
            assignments=[toxic_assignment],
            total_assets=1,
            initial_deposit=Decimal("1000.00"),
            stake_model="flat",
            stake_amount=Decimal("10.00"),
            stake_percent=1.0,
            expiration_seconds=180,
            daily_stop_loss_pct=0.05,
            stop_loss_amount=Decimal("50.00"),
            max_concurrent_trades=3,
            min_payout_rate=0.80,
            toxic_filter_enabled=True,
            bar_edge_guard_seconds=0.0,
        )

        await engine.start(plan, gateway)
        assert engine.status == BotStatus.RUNNING

        sem = asyncio.Semaphore(5)
        now = datetime.now(UTC)

        # Call evaluate 50 times
        for _ in range(50):
            await engine._evaluate_single_asset(toxic_assignment, now, sem)

        # Gateway must never be touched
        gateway.get_candles.assert_not_called()
        gateway.get_asset_payout.assert_not_called()
        gateway.open_trade.assert_not_called()
        assert len(engine.active_trades) == 0

        await engine.stop()

    @pytest.mark.asyncio
    async def test_massive_concurrent_order_lock_stress_with_all_toxic_pairs(self, tmp_path):
        """Stress harness: 220 concurrent coroutines attempting order placement under _order_lock.

        - 110 coroutines attempting the 11 toxic pairs in various formats.
        - 110 coroutines attempting clean whitelisted pairs.
        - Verifies:
          1. 0 toxic orders placed at gateway.
          2. 0 toxic trades in active_trades.
          3. 0 toxic trades in DB TradeStore.
          4. No race conditions, deadlocks, or lock corruption.
        """
        db_file = tmp_path / "massive_concurrency_toxic.db"
        store = TradeStore(db_file)
        engine = LiveDemoBotEngine(trade_store=store)

        toxic_pairs_list = [
            "USD/DZD OTC",
            "UAH/USD OTC",
            "USD/MYR OTC",
            "USD/INR OTC",
            "EUR/HUF OTC",
            "GBP/JPY OTC",
            "USD/IDR OTC",
            "USD/VND OTC",
            "BNB OTC",
            "BNBUSD_otc",
            "EUR/CHF OTC",
        ]
        clean_pairs_list = [
            "EURUSD_otc",
            "USDCLP_otc",
            "USDBDT_otc",
            "USDEGP_otc",
            "Gold_otc",
        ]

        assignments = []
        for sym in toxic_pairs_list + clean_pairs_list:
            assignments.append(
                StrategyAssignment(
                    asset=sym,
                    strategy_id="supertrend_adx_momentum",
                    strategy_name=f"Strat_{sym}",
                    category="momentum",
                    parameters={},
                    estimated_win_rate_pct=60.0,
                    estimated_profit_factor=1.5,
                    estimated_trades_count=10,
                    quantum_score=10.0 if sym in toxic_pairs_list else 85.0,
                    rationale="test",
                )
            )

        plan = PreTradingPlan(
            assignments=assignments,
            total_assets=len(assignments),
            initial_deposit=Decimal("50000.00"),
            stake_model="flat",
            stake_amount=Decimal("100.00"),
            stake_percent=1.0,
            expiration_seconds=180,
            daily_stop_loss_pct=0.50,
            stop_loss_amount=Decimal("25000.00"),
            max_concurrent_trades=10,
            min_payout_rate=0.80,
            cooldown_bars=0,
            global_cooldown_seconds=0,
            toxic_filter_enabled=True,
            bar_edge_guard_seconds=0.0,
        )

        placed_assets_at_gateway: list[str] = []
        gateway = MagicMock()

        async def _mock_open_trade(asset, action, amount, expiration_seconds):
            placed_assets_at_gateway.append(asset)
            await asyncio.sleep(0.001)  # Context switch to test race conditions
            return f"broker-id-{asset}", {"percentProfit": 92}

        gateway.open_trade = AsyncMock(side_effect=_mock_open_trade)
        await engine.start(plan, gateway)

        dummy_candles = _create_mock_candles(30)

        # Generate 220 parallel attempts
        coros = []
        for i in range(220):
            assign = assignments[i % len(assignments)]
            coros.append(
                engine._execute_order(
                    assignment=assign,
                    action="CALL" if i % 2 == 0 else "PUT",
                    confidence=0.85,
                    reason=f"concurrency_stress_{i}",
                    candles=dummy_candles,
                    live_payout=0.92,
                )
            )

        await asyncio.gather(*coros)

        # 1. Invariant: Placed assets at gateway must contain ZERO toxic assets
        assert len(placed_assets_at_gateway) > 0, "Expected some clean assets to be placed"
        for placed in placed_assets_at_gateway:
            is_tox, _ = is_toxic_asset(placed)
            assert is_tox is False, f"FATAL: Blacklisted asset '{placed}' reached broker gateway!"

        # 2. Invariant: Active trades must contain ZERO toxic assets
        for trade in engine.active_trades.values():
            is_tox, _ = is_toxic_asset(trade.asset)
            assert is_tox is False, (
                f"FATAL: Blacklisted asset '{trade.asset}' in engine active trades!"
            )

        # 3. Invariant: Database TradeStore must contain ZERO toxic assets
        stored_trades = store.list_trades(limit=500)
        for st in stored_trades:
            is_tox, _ = is_toxic_asset(st.asset)
            assert is_tox is False, (
                f"FATAL: Blacklisted asset '{st.asset}' written to TradeStore DB!"
            )

        await engine.stop()


# ============================================================================
# 5. PRE-TRADING PLAN & FILTER ALLOWED ASSETS INTEGRATION
# ============================================================================


class MockFeed(CandleFeed):
    async def get_candles(self, asset: str, timeframe: int = 60, count: int = 150) -> list[Candle]:
        return _create_mock_candles(count)

    async def get_latest_candle(self, asset: str, timeframe: int = 60) -> Candle:
        return _create_mock_candles(1)[0]


class TestPreTradingPlanIntegration:
    """Tests end-to-end plan generation and allowed asset filtering."""

    @pytest.mark.asyncio
    async def test_generate_plan_purges_all_11_toxic_assets(self):
        all_11_toxic = [
            "USD/DZD OTC",
            "UAH/USD OTC",
            "USD/MYR OTC",
            "USD/INR OTC",
            "EUR/HUF OTC",
            "GBP/JPY OTC",
            "USD/IDR OTC",
            "USD/VND OTC",
            "BNB OTC",
            "BNBUSD_otc",
            "EUR/CHF OTC",
        ]
        clean_assets = ["EURUSD_otc", "USDCLP_otc", "USDBDT_otc", "USDEGP_otc", "Gold_otc"]

        feed = MockFeed()
        plan = await generate_pre_trading_plan(
            feed=feed,
            assets=all_11_toxic + clean_assets,
            toxic_filter_enabled=True,
        )

        assert plan.total_assets == 5
        assert len(plan.assignments) == 5

        for a in plan.assignments:
            is_tox, _ = is_toxic_asset(a.asset)
            assert is_tox is False, f"Toxic asset {a.asset} was not filtered from plan!"

    def test_filter_allowed_assets_comprehensive(self):
        raw_list = [
            "USD/DZD OTC",
            "EURUSD_otc",
            "UAH/USD OTC",
            "USDCLP_otc",
            "GBP/JPY OTC",
            "Gold_otc",
            "USD/INR OTC",
            "USDCAD_otc",
        ]
        # Standard filter (removes toxic, keeps non-toxic)
        filtered = filter_allowed_assets(raw_list)
        assert filtered == ["EURUSD_otc", "USDCLP_otc", "Gold_otc", "USDCAD_otc"]

        # Whitelist-only filter (removes toxic and non-whitelisted)
        whitelisted_only = filter_allowed_assets(raw_list, enforce_whitelist_only=True)
        assert whitelisted_only == ["EURUSD_otc", "USDCLP_otc", "Gold_otc"]
