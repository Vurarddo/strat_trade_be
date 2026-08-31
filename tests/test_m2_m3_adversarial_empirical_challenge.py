"""Empirical Adversarial Stress & Verification Harness for Milestones M2 & M3.

Exhaustively challenges and verifies:
1. Microstructure Noise Filter (asset_filter.py):
   - Synthetic flatline feeds (100% flat, >15% flat, body-flat Doji spam).
   - Step-tick quantization feeds (2-5 unique prices, <30% unique price ratio).
   - High-frequency micro-whipsaw noise (100% sign-flip alternation, >80% sign flips).
   - Zero/Dead volatility feeds (Relative ATR < 0.000030, large scale invariant).
   - Corrupted & malformed inputs (<50 bars, NaN, Inf, non-positive prices).
   - Clean continuous Forex and OTC pairs (EURUSD, GBPUSD, USDJPY, Gold, BTCUSD).
2. Anti-Whipsaw Post-Settlement Cooldown (bot_engine.py):
   - Hard minimum 180s floor across all cooldown_bars configs (0, 1, 2, 3, 5).
   - Atomic order drop inside _order_lock mutex during cooldown window.
   - Massive concurrent race condition stress (50 simultaneous order attempts).
   - Order execution resumption upon cooldown expiration.
   - Multi-asset independence (Asset A cooldown does not block Asset B).
3. Strategy Auto-Expiration Calibration & UI Simplification (M2):
   - Absence of #botCfgExpiration in index.html.
   - Absence of expiration_seconds serialization in prepareLiveBotLaunch().
   - AutoAssignRequest and PreTradingPlan default to 180s (3 bars).
   - RsiStochasticExtremeStrategy defaults to 3 bars (180s) in __init__.
   - LiveDemoBotEngine opens orders with 180s expiration.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from strat_trade.api.schemas import AutoAssignRequest
from strat_trade.domain.entities import Candle
from strat_trade.domain.optimizer.auto_matcher import StrategyAutoMatcher
from strat_trade.domain.strategies.ema_pullback_trend import EmaPullbackTrendStrategy
from strat_trade.domain.strategies.rsi_stochastic_extreme import RsiStochasticExtremeStrategy
from strat_trade.domain.strategies.support_resistance_bounce import SupportResistanceBounceStrategy
from strat_trade.domain.trading.asset_filter import (
    qualify_asset_microstructure,
)
from strat_trade.domain.trading.bot_engine import LiveDemoBotEngine
from strat_trade.domain.trading.entities import (
    BotStatus,
    IndicatorSnapshot,
    LiveTradeRecord,
    PreTradingPlan,
    StrategyAssignment,
    TradeOutcome,
)
from strat_trade.use_cases.auto_assign_strategies import generate_pre_trading_plan

# ============================================================================
# 1. Microstructure Filter Generator Harness & Boundary Stress
# ============================================================================


class TestMicrostructureNoiseFilterEmpiricalHarness:
    """Adversarially tests qualify_asset_microstructure against synthetic degenerate feeds."""

    def test_pure_flatline_candles_rejection(self):
        """100% flatline candle series (High == Low == Open == Close) must be rejected."""
        n = 80
        df = pd.DataFrame(
            {
                "open": [1.1000] * n,
                "high": [1.1000] * n,
                "low": [1.1000] * n,
                "close": [1.1000] * n,
            }
        )
        qual, reason = qualify_asset_microstructure(df)
        assert qual is False
        assert "Flat bar ratio" in reason
        assert "exceeds threshold 15.00%" in reason

    def test_body_flatline_doji_spam_rejection(self):
        """High > Low with wicks, but Close == Open on > 15% of bars (doji spam)."""
        n = 100
        opens = [1.0850 + (i * 0.0001) for i in range(n)]
        closes = [op + (0.0 if i % 4 == 0 else 0.0002) for i, op in enumerate(opens)]
        highs = [max(o, c) + 0.0003 for o, c in zip(opens, closes, strict=False)]
        lows = [min(o, c) - 0.0003 for o, c in zip(opens, closes, strict=False)]

        df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})
        qual, reason = qualify_asset_microstructure(df)
        assert qual is False
        assert "Flat bar ratio" in reason

    def test_flat_bar_ratio_boundary_precision(self):
        """Verify strict thresholding around 15.00% flat bar ratio."""
        n = 100
        # Exactly 14 flat bars out of 100 = 14.0% (< 15.0%) -> passes
        opens = [1.2000 + np.sin(i / 5.0) * 0.0050 for i in range(n)]
        closes = [op + (0.0 if i < 14 else 0.0005) for i, op in enumerate(opens)]
        highs = [
            max(o, c) + (0.0 if i < 14 else 0.0008)
            for i, o, c in zip(range(n), opens, closes, strict=False)
        ]
        lows = [
            min(o, c) - (0.0 if i < 14 else 0.0008)
            for i, o, c in zip(range(n), opens, closes, strict=False)
        ]

        df_pass = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})
        qual_pass, _ = qualify_asset_microstructure(df_pass)
        assert qual_pass is True

        # Exactly 16 flat bars out of 100 = 16.0% (> 15.0%) -> fails
        closes_fail = [op + (0.0 if i < 16 else 0.0005) for i, op in enumerate(opens)]
        highs_fail = [
            max(o, c) + (0.0 if i < 16 else 0.0008)
            for i, o, c in zip(range(n), opens, closes_fail, strict=False)
        ]
        lows_fail = [
            min(o, c) - (0.0 if i < 16 else 0.0008)
            for i, o, c in zip(range(n), opens, closes_fail, strict=False)
        ]

        df_fail = pd.DataFrame(
            {"open": opens, "high": highs_fail, "low": lows_fail, "close": closes_fail}
        )
        qual_fail, reason_fail = qualify_asset_microstructure(df_fail)
        assert qual_fail is False
        assert "Flat bar ratio 16.00%" in reason_fail

    def test_discrete_step_tick_quantization_rejection(self):
        """Exotic feeds jumping only between 3 discrete price levels."""
        n = 120
        grid = [10.00, 10.05, 10.10]
        closes = [grid[i % len(grid)] for i in range(n)]
        opens = [c - 0.01 for c in closes]
        highs = [c + 0.02 for c in closes]
        lows = [c - 0.02 for c in closes]

        df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})
        qual, reason = qualify_asset_microstructure(df)
        assert qual is False
        assert "Unique price ratio" in reason
        assert "below threshold 30.00%" in reason

    def test_unique_price_ratio_boundary_precision(self):
        """Verify strict thresholding around 30.00% unique close price ratio."""
        n = 100
        # 28 unique close prices out of 100 = 28.0% (< 30.0%) -> reject
        unique_pool_28 = [1.5000 + i * 0.0010 for i in range(28)]
        closes_28 = [unique_pool_28[i % 28] for i in range(n)]
        opens_28 = [c - 0.0002 for c in closes_28]
        highs_28 = [c + 0.0005 for c in closes_28]
        lows_28 = [c - 0.0005 for c in closes_28]

        df_28 = pd.DataFrame(
            {"open": opens_28, "high": highs_28, "low": lows_28, "close": closes_28}
        )
        qual_28, reason_28 = qualify_asset_microstructure(df_28)
        assert qual_28 is False
        assert "Unique price ratio 28.00%" in reason_28

        # 35 unique close prices out of 100 = 35.0% (>= 30.0%) -> pass
        unique_pool_35 = [1.5000 + np.sin(i / 3.0) * 0.0050 for i in range(35)]
        closes_35 = [unique_pool_35[i % 35] for i in range(n)]
        opens_35 = [c - 0.0002 for c in closes_35]
        highs_35 = [c + 0.0008 for c in closes_35]
        lows_35 = [c - 0.0008 for c in closes_35]

        df_35 = pd.DataFrame(
            {"open": opens_35, "high": highs_35, "low": lows_35, "close": closes_35}
        )
        qual_35, _ = qualify_asset_microstructure(df_35)
        assert qual_35 is True

    def test_high_frequency_micro_whipsaw_noise_rejection(self):
        """100% sign-flip alternation on every bar (non-directional jitter noise)."""
        n = 100
        closes = []
        p = 1.1000
        for i in range(n):
            p += 0.0020 if (i % 2 == 0) else -0.0019
            closes.append(p + (i * 0.000001))

        opens = [c - 0.0002 for c in closes]
        highs = [c + 0.0005 for c in closes]
        lows = [c - 0.0005 for c in closes]

        df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})
        qual, reason = qualify_asset_microstructure(df)
        assert qual is False
        assert "Whipsaw sign flip ratio" in reason
        assert "exceeds threshold 80.00%" in reason

    def test_dead_zero_volatility_relative_atr_rejection(self):
        """Test relative ATR < 0.000030 rejection across small and large price scales."""
        n = 80
        df_small = pd.DataFrame(
            {
                "open": [1.0000 + i * 0.000001 for i in range(n)],
                "high": [1.0000 + i * 0.000001 + 0.000002 for i in range(n)],
                "low": [1.0000 + i * 0.000001 - 0.000002 for i in range(n)],
                "close": [1.0000 + i * 0.000001 + 0.000001 for i in range(n)],
            }
        )
        qual_small, reason_small = qualify_asset_microstructure(df_small)
        assert qual_small is False
        assert "Relative ATR" in reason_small

        # Large asset price scale (BTC $60,000) with tiny ticks ($0.20 ATR)
        df_large = pd.DataFrame(
            {
                "open": [60000.0 + i * 0.10 for i in range(n)],
                "high": [60000.0 + i * 0.10 + 0.20 for i in range(n)],
                "low": [60000.0 + i * 0.10 - 0.20 for i in range(n)],
                "close": [60000.0 + i * 0.10 + 0.15 for i in range(n)],
            }
        )
        qual_large, reason_large = qualify_asset_microstructure(df_large)
        assert qual_large is False
        assert "Relative ATR" in reason_large
        assert "below threshold 0.000030" in reason_large

    @pytest.mark.parametrize(
        "bad_input,expected_msg",
        [
            (None, "Insufficient candle history"),
            (pd.DataFrame(), "0 < 50 bars required"),
            (
                pd.DataFrame(
                    {
                        "open": [1.0] * 49,
                        "high": [1.1] * 49,
                        "low": [0.9] * 49,
                        "close": [1.0] * 49,
                    }
                ),
                "49 < 50 bars required",
            ),
            (
                pd.DataFrame(
                    {
                        "open": [1.0] * 60,
                        "high": [1.1] * 60,
                        "close": [1.0] * 60,
                    }
                ),
                "Missing required column 'low'",
            ),
            (
                pd.DataFrame(
                    {
                        "open": [1.0] * 60,
                        "high": [1.1] * 60,
                        "low": [0.9] * 60,
                        "close": [1.0] * 59 + [float("nan")],
                    }
                ),
                "NaN or non-numeric",
            ),
            (
                pd.DataFrame(
                    {
                        "open": [1.0] * 60,
                        "high": [1.1] * 60,
                        "low": [0.9] * 60,
                        "close": [1.0] * 59 + [0.0],
                    }
                ),
                "non-positive price",
            ),
            (
                pd.DataFrame(
                    {
                        "open": [1.0] * 60,
                        "high": [1.1] * 60,
                        "low": [0.9] * 60,
                        "close": [1.0] * 59 + [-1.5],
                    }
                ),
                "non-positive price",
            ),
        ],
    )
    def test_corrupted_and_malformed_inputs_safety(self, bad_input, expected_msg):
        """Verify robust error handling for malformed dataframes without uncaught exceptions."""
        qual, reason = qualify_asset_microstructure(bad_input)
        assert qual is False
        assert expected_msg in reason


class TestContinuousLiquidPairsEmpiricalPassMatrix:
    """Verifies that all continuous liquid Forex & OTC pairs qualify without false rejection."""

    def test_all_liquid_forex_and_otc_pairs_pass(self):
        """Simulate realistic price processes across 10 liquid Forex and OTC assets."""
        np.random.seed(1337)

        test_pairs = {
            "EURUSD": {"base": 1.0850, "vol": 0.0004},
            "GBPUSD": {"base": 1.2650, "vol": 0.0006},
            "USDJPY": {"base": 154.20, "vol": 0.0500},
            "AUDUSD": {"base": 0.6550, "vol": 0.0003},
            "USDCLP": {"base": 920.0, "vol": 0.5000},
            "USDBDT": {"base": 110.0, "vol": 0.0800},
            "USDEGP": {"base": 48.50, "vol": 0.0300},
            "GOLD": {"base": 2350.0, "vol": 1.2000},
            "XAUUSD": {"base": 2350.0, "vol": 1.2000},
            "BTCUSD": {"base": 65000.0, "vol": 50.0000},
        }

        n = 120
        for pair_name, cfg in test_pairs.items():
            base = cfg["base"]
            vol = cfg["vol"]

            shocks = np.random.normal(0, vol, size=n)
            closes = base + np.cumsum(shocks)
            highs = closes + np.abs(np.random.normal(vol * 0.8, vol * 0.3, size=n))
            lows = closes - np.abs(np.random.normal(vol * 0.8, vol * 0.3, size=n))
            opens = closes - shocks * 0.6

            df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})
            qual, reason = qualify_asset_microstructure(df)
            assert qual is True, f"Liquid continuous pair {pair_name} failed: {reason}"
            assert "qualified" in reason

    @pytest.mark.asyncio
    async def test_automatcher_microstructure_integration(self):
        """Verify StrategyAutoMatcher assigns low quantum score when microstructure fails."""
        matcher = StrategyAutoMatcher(candle_count=100)

        n = 80
        df_dead = pd.DataFrame(
            {
                "open": [1.1000] * n,
                "high": [1.1000] * n,
                "low": [1.1000] * n,
                "close": [1.1000] * n,
            }
        )

        assignment = await matcher.find_optimal_strategy_for_asset("SYNTHETIC_DEAD_PAIR", df_dead)
        assert assignment is None


# ============================================================================
# 2. Anti-Whipsaw Post-Settlement Cooldown & Concurrency Stress
# ============================================================================


class TestAntiWhipsawCooldownEmpiricalStressHarness:
    """Stress tests post-settlement cooldown floor (min 180s) and concurrency safety."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "requested_bars,expected_min_sec",
        [
            (0, 180),
            (1, 180),
            (2, 180),
            (3, 180),
            (4, 240),
            (5, 300),
        ],
    )
    async def test_cooldown_hard_floor_formula(self, requested_bars, expected_min_sec):
        """cooldown_sec = max(180, cooldown_bars * 60) must enforce at least 180s."""
        engine = LiveDemoBotEngine()
        mock_gateway = AsyncMock()
        mock_gateway.get_candles = AsyncMock(return_value=[])

        plan = PreTradingPlan(
            assignments=[],
            total_assets=0,
            initial_deposit=Decimal("1000.00"),
            stake_model="flat",
            stake_amount=Decimal("10.00"),
            stake_percent=1.0,
            expiration_seconds=180,
            daily_stop_loss_pct=0.05,
            stop_loss_amount=Decimal("50.00"),
            max_concurrent_trades=3,
            min_payout_rate=0.80,
            cooldown_bars=requested_bars,
            bar_edge_guard_seconds=0.0,
        )
        engine.plan = plan
        engine.status = BotStatus.RUNNING
        engine._gateway = mock_gateway

        now_utc = datetime.now(UTC)
        trade = LiveTradeRecord(
            trade_id="t-cooldown-test",
            asset="EURUSD_otc",
            action="CALL",
            stake=Decimal("10.00"),
            open_time=now_utc - timedelta(seconds=180),
            expiration_seconds=180,
            open_price=Decimal("1.0850"),
            strategy_id="support_resistance_bounce",
            strategy_name="S&R Bounce",
            strategy_params={},
            indicator_snapshot=IndicatorSnapshot(),
            confidence=0.85,
            reason="test",
            payout_rate=Decimal("0.92"),
            outcome=TradeOutcome.PENDING,
        )
        engine.active_trades[trade.trade_id] = trade

        await engine._check_active_trades()

        cooldown_until = engine._asset_cooldown_until.get("EURUSD_otc")
        assert cooldown_until is not None
        delta_sec = (cooldown_until - trade.close_time).total_seconds()
        assert delta_sec == float(expected_min_sec), (
            f"Expected {expected_min_sec}s for bars={requested_bars}, got {delta_sec}s"
        )

    @pytest.mark.asyncio
    async def test_massive_concurrent_order_lock_rejection_during_cooldown(self):
        """Stress-test 50 concurrent coroutines attempting order placement during cooldown."""
        engine = LiveDemoBotEngine()
        mock_gateway = AsyncMock()
        mock_gateway.open_trade = AsyncMock(return_value=("order-123", {"percentProfit": 92}))

        plan = PreTradingPlan(
            assignments=[
                StrategyAssignment(
                    asset="EURUSD_otc",
                    strategy_id="support_resistance_bounce",
                    strategy_name="S&R Bounce",
                    category="Price Action",
                    parameters={},
                    estimated_win_rate_pct=65.0,
                    estimated_profit_factor=1.6,
                    estimated_trades_count=5,
                    quantum_score=85.0,
                )
            ],
            total_assets=1,
            initial_deposit=Decimal("1000.00"),
            stake_model="flat",
            stake_amount=Decimal("10.00"),
            stake_percent=1.0,
            expiration_seconds=180,
            daily_stop_loss_pct=0.05,
            stop_loss_amount=Decimal("50.00"),
            max_concurrent_trades=10,
            min_payout_rate=0.80,
            cooldown_bars=3,
            bar_edge_guard_seconds=0.0,
        )

        engine.plan = plan
        engine.status = BotStatus.RUNNING
        engine._gateway = mock_gateway

        t_now = datetime.now(UTC)
        engine._asset_cooldown_until["EURUSD_otc"] = t_now + timedelta(seconds=180)

        dummy_candle = Candle(
            open_time=t_now,
            open=Decimal("1.0850"),
            high=Decimal("1.0860"),
            low=Decimal("1.0840"),
            close=Decimal("1.0855"),
            volume=Decimal("100.0"),
        )

        async def worker_attempt():
            await engine._execute_order(
                plan.assignments[0],
                action="CALL",
                confidence=0.85,
                reason="concurrency_stress",
                candles=[dummy_candle],
                live_payout=0.92,
                now=t_now,
            )

        tasks = [worker_attempt() for _ in range(50)]
        await asyncio.gather(*tasks)

        assert len(engine.active_trades) == 0
        mock_gateway.open_trade.assert_not_called()

    @pytest.mark.asyncio
    async def test_order_execution_resumes_after_cooldown_expires(self):
        """Verify that order execution succeeds immediately once cooldown has elapsed."""
        engine = LiveDemoBotEngine()
        mock_gateway = AsyncMock()
        mock_gateway.open_trade = AsyncMock(
            return_value=("order-resumed-999", {"percentProfit": 92})
        )

        plan = PreTradingPlan(
            assignments=[
                StrategyAssignment(
                    asset="EURUSD_otc",
                    strategy_id="support_resistance_bounce",
                    strategy_name="S&R Bounce",
                    category="Price Action",
                    parameters={},
                    estimated_win_rate_pct=65.0,
                    estimated_profit_factor=1.6,
                    estimated_trades_count=5,
                    quantum_score=85.0,
                )
            ],
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
            cooldown_bars=3,
            bar_edge_guard_seconds=0.0,
        )

        engine.plan = plan
        engine.status = BotStatus.RUNNING
        engine._gateway = mock_gateway

        t_now = datetime.now(UTC)
        engine._asset_cooldown_until["EURUSD_otc"] = t_now - timedelta(seconds=1)

        dummy_candle = Candle(
            open_time=t_now,
            open=Decimal("1.0850"),
            high=Decimal("1.0860"),
            low=Decimal("1.0840"),
            close=Decimal("1.0855"),
            volume=Decimal("100.0"),
        )

        await engine._execute_order(
            plan.assignments[0],
            action="CALL",
            confidence=0.85,
            reason="resumed_test",
            candles=[dummy_candle],
            live_payout=0.92,
            now=t_now,
        )

        assert len(engine.active_trades) == 1
        mock_gateway.open_trade.assert_called_once()

    @pytest.mark.asyncio
    async def test_multi_asset_cooldown_independence(self):
        """Asset A on cooldown does NOT prevent Asset B from placing orders."""
        engine = LiveDemoBotEngine()
        mock_gateway = AsyncMock()
        mock_gateway.open_trade = AsyncMock(return_value=("order-asset-b", {"percentProfit": 92}))

        assign_a = StrategyAssignment(
            asset="EURUSD_otc",
            strategy_id="support_resistance_bounce",
            strategy_name="S&R Bounce",
            category="Price Action",
            parameters={},
            estimated_win_rate_pct=65.0,
            estimated_profit_factor=1.6,
            estimated_trades_count=5,
            quantum_score=85.0,
        )
        assign_b = StrategyAssignment(
            asset="GBPUSD_otc",
            strategy_id="ema_pullback_trend",
            strategy_name="EMA Trend",
            category="Trend",
            parameters={},
            estimated_win_rate_pct=64.0,
            estimated_profit_factor=1.5,
            estimated_trades_count=5,
            quantum_score=84.0,
        )

        plan = PreTradingPlan(
            assignments=[assign_a, assign_b],
            total_assets=2,
            initial_deposit=Decimal("1000.00"),
            stake_model="flat",
            stake_amount=Decimal("10.00"),
            stake_percent=1.0,
            expiration_seconds=180,
            daily_stop_loss_pct=0.05,
            stop_loss_amount=Decimal("50.00"),
            max_concurrent_trades=3,
            min_payout_rate=0.80,
            cooldown_bars=3,
            bar_edge_guard_seconds=0.0,
        )

        engine.plan = plan
        engine.status = BotStatus.RUNNING
        engine._gateway = mock_gateway

        t_now = datetime.now(UTC)
        engine._asset_cooldown_until["EURUSD_otc"] = t_now + timedelta(seconds=180)

        dummy_candle = Candle(
            open_time=t_now,
            open=Decimal("1.2650"),
            high=Decimal("1.2660"),
            low=Decimal("1.2640"),
            close=Decimal("1.2655"),
            volume=Decimal("100.0"),
        )

        await engine._execute_order(
            assign_b,
            action="CALL",
            confidence=0.82,
            reason="independent_asset_b",
            candles=[dummy_candle],
            live_payout=0.92,
            now=t_now,
        )

        assert len(engine.active_trades) == 1
        opened_trade = list(engine.active_trades.values())[0]
        assert opened_trade.asset == "GBPUSD_otc"


# ============================================================================
# 3. Strategy Auto-Expiration Calibration & UI Simplification Verification
# ============================================================================


class TestStrategyAutoExpirationAndUiSimplificationHarness:
    """Verifies UI simplification and default 180s (3-bar) expiration across stack."""

    def test_ui_index_html_has_no_bot_cfg_expiration_select(self):
        """Assert index.html contains zero occurrences of botCfgExpiration select input."""
        with open("src/strat_trade/web/templates/index.html", encoding="utf-8") as f:
            content = f.read()

        assert "botCfgExpiration" not in content, (
            "index.html must not contain botCfgExpiration element"
        )
        assert "prepareLiveBotLaunch" in content

    def test_ui_js_prepare_live_bot_launch_payload_omits_expiration(self):
        """Assert JS prepareLiveBotLaunch does not serialize expiration_seconds."""
        with open("src/strat_trade/web/templates/index.html", encoding="utf-8") as f:
            content = f.read()

        start_idx = content.find("async function prepareLiveBotLaunch()")
        assert start_idx != -1
        end_idx = content.find("function renderBotConfirmationModal", start_idx)
        fn_code = content[start_idx:end_idx]

        assert "expiration_seconds" not in fn_code, (
            "prepareLiveBotLaunch() JS payload must not pass manual expiration_seconds"
        )

    def test_auto_assign_request_schema_defaults_180s(self):
        """Verify AutoAssignRequest defaults expiration_seconds to 180s without client field."""
        req = AutoAssignRequest(
            assets=["EURUSD_otc", "USDCLP_otc"],
            initial_deposit=1000.0,
            stake_model="flat",
            stake_amount=10.0,
            stake_percent=1.0,
            daily_stop_loss_pct=0.05,
            max_concurrent_trades=3,
            min_payout_rate=0.80,
        )
        assert req.expiration_seconds == 180

    @pytest.mark.asyncio
    async def test_generate_pre_trading_plan_uniform_180s_assignment(self):
        """Verify pre-trading plan generation configures 180s plan and 3-bar strategy params."""
        mock_feed = AsyncMock()
        mock_feed.get_candles = AsyncMock(return_value=[])

        plan = await generate_pre_trading_plan(
            assets=["EURUSD_otc", "USDCLP_otc", "Gold_otc", "USDJPY_otc"],
            initial_deposit=1000.0,
            stake_model="flat",
            stake_amount=10.0,
            stake_percent=1.0,
            feed=mock_feed,
        )

        assert plan.expiration_seconds == 180
        assert len(plan.assignments) >= 3
        for a in plan.assignments:
            assert a.parameters.get("base_expiration_bars") == 3, (
                f"Assignment for {a.asset} ({a.strategy_id}) must have base_expiration_bars = 3"
            )

    def test_sniper_strategies_default_to_3_bars_expiration(self):
        """Verify all core sniper strategies instantiate with base_expiration_bars = 3."""
        sr = SupportResistanceBounceStrategy()
        assert sr.base_expiration_bars == 3

        rsi_stoch = RsiStochasticExtremeStrategy()
        assert rsi_stoch.base_expiration_bars == 3
        param_defs = {p.name: p for p in rsi_stoch.get_parameter_definitions()}
        assert param_defs["base_expiration_bars"].default_value == 3

        ema = EmaPullbackTrendStrategy()
        assert ema.base_expiration_bars == 3

    @pytest.mark.asyncio
    async def test_live_demo_bot_engine_opens_trade_with_plan_expiration(self):
        """Verify LiveDemoBotEngine dispatches orders to gateway with plan expiration (180s)."""
        engine = LiveDemoBotEngine()
        mock_gateway = AsyncMock()
        mock_gateway.open_trade = AsyncMock(return_value=("order-exp-180", {"percentProfit": 92}))

        assign = StrategyAssignment(
            asset="EURUSD_otc",
            strategy_id="support_resistance_bounce",
            strategy_name="S&R Bounce",
            category="Price Action",
            parameters={"base_expiration_bars": 3},
            estimated_win_rate_pct=65.0,
            estimated_profit_factor=1.6,
            estimated_trades_count=5,
            quantum_score=85.0,
        )

        plan = PreTradingPlan(
            assignments=[assign],
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
            cooldown_bars=3,
            bar_edge_guard_seconds=0.0,
        )

        engine.plan = plan
        engine.status = BotStatus.RUNNING
        engine._gateway = mock_gateway

        # Mid-bar, so the bar-edge guard does not suppress the order
        t_now = datetime.now(UTC).replace(second=30, microsecond=0)
        dummy_candle = Candle(
            open_time=t_now,
            open=Decimal("1.0850"),
            high=Decimal("1.0860"),
            low=Decimal("1.0840"),
            close=Decimal("1.0855"),
            volume=Decimal("100.0"),
        )

        await engine._execute_order(
            assign,
            action="CALL",
            confidence=0.85,
            reason="exp_verification",
            candles=[dummy_candle],
            live_payout=0.92,
            now=t_now,
        )

        # OTC is on probation by default, so the $10 flat stake is risked at 25%.
        mock_gateway.open_trade.assert_called_once_with(
            asset="EURUSD_otc",
            action="CALL",
            amount=2.5,
            expiration_seconds=180,
        )
        opened_record = list(engine.active_trades.values())[0]
        assert opened_record.expiration_seconds == 180
        assert opened_record.stake_multiplier == 0.25
        assert opened_record.asset_tier == "PROBATION"
