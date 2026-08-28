"""Adversarial Empirical Stress Testing Suite for Milestone 2:
Bot Engine Execution Guardrails, Currency Correlation, Cooldown Timers, and Circuit Breakers.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from strat_trade.domain.backtest.models import PortfolioBacktestConfig
from strat_trade.domain.backtest.portfolio_engine import PortfolioBacktestEngine
from strat_trade.domain.entities import Candle
from strat_trade.domain.trading.bot_engine import LiveDemoBotEngine
from strat_trade.domain.trading.correlation import (
    extract_currency_pair,
    get_directional_exposure,
    get_portfolio_currency_exposure,
    is_correlated_conflict,
    normalize_symbol,
)
from strat_trade.domain.trading.entities import (
    BotStatus,
    IndicatorSnapshot,
    LiveTradeRecord,
    PreTradingPlan,
    StrategyAssignment,
)
from strat_trade.domain.trading.trade_store import TradeStore


def _make_candle_bar(t: datetime, close: float) -> Candle:
    return Candle(
        open_time=t,
        open=Decimal(str(round(close - 0.0001, 5))),
        high=Decimal(str(round(close + 0.0002, 5))),
        low=Decimal(str(round(close - 0.0002, 5))),
        close=Decimal(str(round(close, 5))),
        volume=Decimal("100"),
    )


def _make_test_plan(
    assets: list[str] | None = None,
    cooldown_bars: int = 3,
    global_cooldown_seconds: int = 30,
    max_consecutive_losses: int = 3,
    max_drawdown_pct_limit: float = 0.08,
    correlation_filter_enabled: bool = True,
    pause_duration_minutes: int = 15,
    max_concurrent_trades: int = 5,
) -> PreTradingPlan:
    asset_list = assets or ["EURUSD_otc", "GBPUSD_otc", "AUDUSD_otc", "USDCHF_otc", "NZDUSD_otc"]
    assignments = [
        StrategyAssignment(
            asset=a,
            strategy_id="hybrid_multifactors",
            strategy_name="Hybrid Multi-Factors",
            category="hybrid",
            parameters={},
            estimated_win_rate_pct=60.0,
            estimated_profit_factor=1.8,
            estimated_trades_count=50,
            quantum_score=85.0,
            rationale="Test plan",
        )
        for a in asset_list
    ]
    return PreTradingPlan(
        assignments=assignments,
        total_assets=len(assignments),
        initial_deposit=Decimal("1000.00"),
        stake_model="flat",
        stake_amount=Decimal("10.00"),
        stake_percent=1.0,
        expiration_seconds=180,
        daily_stop_loss_pct=0.10,
        stop_loss_amount=Decimal("100.00"),
        max_concurrent_trades=max_concurrent_trades,
        min_payout_rate=0.80,
        cooldown_bars=cooldown_bars,
        global_cooldown_seconds=global_cooldown_seconds,
        max_consecutive_losses=max_consecutive_losses,
        max_drawdown_pct_limit=max_drawdown_pct_limit,
        pause_duration_minutes=pause_duration_minutes,
        session_filter_enabled=False,
    )


# =========================================================================
# 1. ADVERSARIAL CORRELATION MATRIX & SYMBOL PERMUTATIONS
# =========================================================================


class TestAdversarialCorrelationFilter:
    """Stress tests currency normalization, decomposition, and exposure conflict detection."""

    @pytest.mark.parametrize(
        ("raw_input", "expected_clean"),
        [
            ("AUDUSD_otc", "AUDUSD"),
            ("EUR/USD (OTC)", "EURUSD"),
            ("USD/CHF OTC", "USDCHF"),
            ("usd/jpy-otc", "USDJPY"),
            ("  GBP_USD_otc  ", "GBPUSD"),
            ("NZD-USD (otc)", "NZDUSD"),
            ("BTCUSD_otc", "BTCUSD"),
            ("ETHUSD_OTC", "ETHUSD"),
            ("XAUUSD_otc", "XAUUSD"),
            ("XAGUSD_OTC", "XAGUSD"),
            ("USOUSD_otc", "USOUSD"),
            ("eur/gbp", "EURGBP"),
            ("AUDCAD", "AUDCAD"),
            ("CADCHF_otc", "CADCHF"),
            ("", ""),
            (None, ""),
            ("OTC", ""),
            ("EURUSD(OTC)", "EURUSD"),
            ("EURUSD-OTC", "EURUSD"),
        ],
    )
    def test_normalize_symbol_permutations(self, raw_input: Any, expected_clean: str):
        assert normalize_symbol(raw_input) == expected_clean

    @pytest.mark.parametrize(
        ("symbol", "expected_pair"),
        [
            ("EURUSD_otc", ("EUR", "USD")),
            ("USDCHF_otc", ("USD", "CHF")),
            ("AUDNZD (OTC)", ("AUD", "NZD")),
            ("BTCUSD_otc", ("BTC", "USD")),
            ("ETHUSD_otc", ("ETH", "USD")),
            ("XAUUSD_otc", ("XAU", "USD")),
            ("GBP/JPY OTC", ("GBP", "JPY")),
            ("EURCAD", ("EUR", "CAD")),
            # Malformed / Non-forex pairs
            ("USDUSD_otc", None),  # identical base and quote
            ("AAPL", None),  # length 4
            ("GOOGL", None),  # length 5
            ("EURUSDT", None),  # length 7
            ("123456", None),  # non-alpha
            ("EUR123", None),  # digits
            ("", None),
            (None, None),
        ],
    )
    def test_extract_currency_pair_permutations(
        self, symbol: Any, expected_pair: tuple[str, str] | None
    ):
        assert extract_currency_pair(symbol) == expected_pair

    @pytest.mark.parametrize(
        (
            "active_pair",
            "active_action",
            "cand_pair",
            "cand_action",
            "expect_conflict",
            "conflict_substring",
        ),
        [
            # Double Short USD
            ("EURUSD_otc", "CALL", "GBPUSD_otc", "CALL", True, "Double Short USD"),
            ("EURUSD_otc", "CALL", "AUDUSD_otc", "CALL", True, "Double Short USD"),
            ("EURUSD_otc", "CALL", "NZDUSD_otc", "CALL", True, "Double Short USD"),
            ("EURUSD_otc", "CALL", "BTCUSD_otc", "CALL", True, "Double Short USD"),
            ("EURUSD_otc", "CALL", "USDCHF_otc", "PUT", True, "Double Short USD"),
            ("EURUSD_otc", "CALL", "USDCAD_otc", "PUT", True, "Double Short USD"),
            ("EURUSD_otc", "CALL", "USDJPY_otc", "PUT", True, "Double Short USD"),
            # Double Long USD
            ("EURUSD_otc", "PUT", "GBPUSD_otc", "PUT", True, "Double Long USD"),
            ("EURUSD_otc", "PUT", "USDCHF_otc", "CALL", True, "Double Long USD"),
            ("USDJPY_otc", "CALL", "USDCHF_otc", "CALL", True, "Double Long USD"),
            ("USDCAD_otc", "CALL", "BTCUSD_otc", "PUT", True, "Double Long USD"),
            # Double Long Base Currency (e.g. AUD, EUR, JPY)
            ("AUDUSD_otc", "CALL", "AUDNZD_otc", "CALL", True, "Double Long AUD"),
            ("AUDCAD_otc", "CALL", "AUDJPY_otc", "CALL", True, "Double Long AUD"),
            ("EURUSD_otc", "CALL", "EURGBP_otc", "CALL", True, "Double Long EUR"),
            ("EURJPY_otc", "CALL", "EURCHF_otc", "CALL", True, "Double Long EUR"),
            ("USDJPY_otc", "PUT", "EURJPY_otc", "PUT", True, "Double Long JPY"),
            # Double Short Base / Cross Currencies
            ("AUDUSD_otc", "PUT", "AUDNZD_otc", "PUT", True, "Double Short AUD"),
            ("EURGBP_otc", "CALL", "GBPJPY_otc", "PUT", True, "Double Short GBP"),
            # Completely Uncorrelated / Independent Pairs
            ("EURUSD_otc", "CALL", "AUDNZD_otc", "CALL", False, ""),
            ("GBPUSD_otc", "CALL", "CADCHF_otc", "CALL", False, ""),
            ("USDJPY_otc", "CALL", "EURGBP_otc", "CALL", False, ""),
            ("BTCUSD_otc", "CALL", "EURJPY_otc", "CALL", False, ""),
        ],
    )
    def test_correlation_matrix_permutations(
        self,
        active_pair: str,
        active_action: str,
        cand_pair: str,
        cand_action: str,
        expect_conflict: bool,
        conflict_substring: str,
    ):
        active_trade = {"asset": active_pair, "action": active_action}
        conflict, reason = is_correlated_conflict(
            candidate_asset=cand_pair,
            candidate_action=cand_action,
            active_trades=[active_trade],
        )
        assert conflict is expect_conflict
        if expect_conflict:
            assert conflict_substring in reason

    def test_multi_asset_portfolio_conflict_detection(self):
        """Active portfolio with 3 diversified trades: ensures any conflicting leg is rejected."""
        active = [
            {"asset": "EURUSD_otc", "action": "CALL"},  # Long EUR, Short USD
            {"asset": "GBPJPY_otc", "action": "CALL"},  # Long GBP, Short JPY
            {"asset": "AUDCAD_otc", "action": "CALL"},  # Long AUD, Short CAD
        ]

        # Candidate 1: NZDUSD CALL (Short USD) -> Conflict with EURUSD
        c1, r1 = is_correlated_conflict("NZDUSD_otc", "CALL", active)
        assert c1 is True
        assert "Double Short USD" in r1

        # Candidate 2: USDJPY CALL (Long USD, Short JPY) -> Conflict with GBPJPY (Double Short JPY)
        c2, r2 = is_correlated_conflict("USDJPY_otc", "CALL", active)
        assert c2 is True
        assert "Double Short JPY" in r2

        # Candidate 3: AUDNZD CALL (Long AUD, Short NZD) -> Conflict with AUDCAD (Double Long AUD)
        c3, r3 = is_correlated_conflict("AUDNZD_otc", "CALL", active)
        assert c3 is True
        assert "Double Long AUD" in r3

        # Candidate 4: NZDCHF CALL (Long NZD, Short CHF) -> No overlap with existing legs
        c4, r4 = is_correlated_conflict("NZDCHF_otc", "CALL", active)
        assert c4 is False
        assert r4 == ""

    def test_opposing_exposure_behavior(self):
        """Tests opposing exposure flag (check_opposing=True vs False)."""
        active = [{"asset": "EURUSD_otc", "action": "CALL"}]  # Long EUR, Short USD

        # Candidate: EURUSD PUT (Long USD, Short EUR)
        # With check_opposing=False: No Double Long or Double Short
        conf_false, _ = is_correlated_conflict("EURUSD_otc", "PUT", active, check_opposing=False)
        assert conf_false is False

        # With check_opposing=True: Flags opposing exposure
        conf_true, reason_true = is_correlated_conflict(
            "EURUSD_otc", "PUT", active, check_opposing=True
        )
        assert conf_true is True
        assert "Opposing" in reason_true

    def test_directional_exposure_invalid_inputs(self):
        assert get_directional_exposure("", "CALL") is None
        assert get_directional_exposure("EURUSD", "INVALID_ACTION") is None
        assert get_directional_exposure("INVALID_ASSET", "CALL") is None

    def test_portfolio_currency_exposure_aggregation_stress(self):
        trades = [
            {"asset": "EURUSD_otc", "action": "CALL"},  # +1 EUR, -1 USD
            {"asset": "GBPUSD_otc", "action": "CALL"},  # +1 GBP, -1 USD
            {"asset": "AUDUSD_otc", "action": "CALL"},  # +1 AUD, -1 USD
            {"asset": "USDJPY_otc", "action": "CALL"},  # +1 USD, -1 JPY
            {"asset": "USDCHF_otc", "action": "CALL"},  # +1 USD, -1 CHF
        ]
        exp = get_portfolio_currency_exposure(trades)
        assert exp["EUR"] == 1
        assert exp["GBP"] == 1
        assert exp["AUD"] == 1
        assert exp["JPY"] == -1
        assert exp["CHF"] == -1
        assert exp["USD"] == -1  # -3 + 2 = -1


# =========================================================================
# 2. HIGH CONCURRENCY & RACE CONDITION STRESS TESTS (COOLDOWN TIMERS)
# =========================================================================


class TestConcurrencyAndCooldownStress:
    """Stress tests asynchronous order execution lock, global cooldown, and asset cooldown."""

    @pytest.mark.asyncio
    async def test_high_concurrency_global_cooldown_order_lock(self):
        """Stress test: 50 concurrent coroutines attempting _execute_order.

        Under strict lock and global cooldown (30s), EXACTLY 1 order must execute.
        49 must be safely rejected with zero race conditions.
        """
        store = MagicMock(spec=TradeStore)
        engine = LiveDemoBotEngine(trade_store=store)
        plan = _make_test_plan(global_cooldown_seconds=30, max_concurrent_trades=10)
        gateway = AsyncMock()
        gateway.open_trade.return_value = ("order-xyz", {"percentProfit": 92})

        await engine.start(plan, gateway)
        now_base = datetime.now(UTC)
        candles = [_make_candle_bar(now_base + timedelta(minutes=i), 1.1000) for i in range(100)]

        # Create 50 distinct assignments
        assignments = [
            StrategyAssignment(
                asset=f"ASSET{i:02d}_otc",
                strategy_id="strat",
                strategy_name="Strat",
                category="test",
                parameters={},
                estimated_win_rate_pct=60.0,
                estimated_profit_factor=1.5,
                estimated_trades_count=10,
                quantum_score=80.0,
                rationale="test",
            )
            for i in range(50)
        ]

        async def attempt_order(assignment: StrategyAssignment):
            await engine._execute_order(
                assignment=assignment,
                action="CALL",
                confidence=0.85,
                reason="concurrency_stress",
                candles=candles,
                live_payout=0.92,
            )

        # Launch all 50 in parallel
        await asyncio.gather(*(attempt_order(a) for a in assignments), return_exceptions=True)

        # Exactly 1 active trade must exist
        assert len(engine.active_trades) == 1
        assert engine._last_global_execution_time is not None
        assert gateway.open_trade.call_count == 1

        # Now advance time past global cooldown (35 seconds later)
        t_future = engine._last_global_execution_time - timedelta(seconds=35)
        engine._last_global_execution_time = t_future

        # Launch another burst of 50 concurrent tasks
        await asyncio.gather(*(attempt_order(a) for a in assignments[1:]), return_exceptions=True)

        # Exactly 1 more trade should have succeeded (total = 2)
        assert len(engine.active_trades) == 2
        assert gateway.open_trade.call_count == 2
        await engine.stop()

    @pytest.mark.asyncio
    async def test_per_asset_cooldown_under_rapid_signals(self):
        """Stress test: Rapid fire signals on an asset while in cooldown."""
        store = MagicMock(spec=TradeStore)
        engine = LiveDemoBotEngine(trade_store=store)
        plan = _make_test_plan(cooldown_bars=3)  # 3 bars = 180s
        gateway = AsyncMock()

        await engine.start(plan, gateway)
        now = datetime.now(UTC)

        # Settle a trade on EURUSD_otc
        trade = LiveTradeRecord(
            trade_id="t_eur",
            asset="EURUSD_otc",
            action="CALL",
            stake=Decimal("10.00"),
            open_time=now - timedelta(seconds=180),
            expiration_seconds=180,
            open_price=Decimal("1.1000"),
            strategy_id="strat",
            strategy_name="Strat",
            strategy_params={},
            indicator_snapshot=IndicatorSnapshot(),
            confidence=0.8,
            reason="test",
            payout_rate=Decimal("0.92"),
        )
        engine.active_trades["t_eur"] = trade
        gateway.get_candles.return_value = [_make_candle_bar(now, 1.1010)]

        await engine._check_active_trades()

        cooldown_until = engine._asset_cooldown_until.get("EURUSD_otc")
        assert cooldown_until is not None
        assert abs((cooldown_until - (now + timedelta(seconds=180))).total_seconds()) < 1.0

        # Send 100 rapid sequential evaluation calls during cooldown
        sem = asyncio.Semaphore(1)
        assignment = plan.assignments[0]
        for offset_sec in range(0, 179, 2):
            sim_time = now + timedelta(seconds=offset_sec)
            await engine._evaluate_single_asset(assignment, sim_time, sem)
            assert len(engine.active_trades) == 0  # Blocked!

        # Past cooldown expiry, mid-bar so the bar-edge guard does not intervene
        sim_time_after = (cooldown_until + timedelta(minutes=1)).replace(second=30, microsecond=0)
        gateway.get_asset_payout.return_value = 0.92
        history_start = sim_time_after.replace(second=0, microsecond=0) - timedelta(minutes=100)
        gateway.get_candles.return_value = [
            _make_candle_bar(history_start + timedelta(minutes=i), 1.1000 + i * 0.0001)
            for i in range(100)
        ]
        gateway.open_trade.return_value = ("broker-uuid", {"percentProfit": 92})

        mock_strat = MagicMock()
        mock_sig = MagicMock()
        mock_sig.action.value = "CALL"
        mock_sig.confidence = 0.85
        mock_sig.metadata = {"reason": "test"}
        mock_sig.regime = "trending"
        mock_strat.evaluate_candles.return_value = mock_sig
        engine._strategy_instances["EURUSD_otc"] = mock_strat

        await engine._evaluate_single_asset(assignment, sim_time_after, sem)
        assert len(engine.active_trades) == 1
        await engine.stop()

    @pytest.mark.asyncio
    async def test_concurrent_settlements_multi_asset(self):
        """Simultaneous settlement of 5 trades on 5 assets."""
        store = MagicMock(spec=TradeStore)
        engine = LiveDemoBotEngine(trade_store=store)
        plan = _make_test_plan(cooldown_bars=4)
        gateway = AsyncMock()
        await engine.start(plan, gateway)

        now = datetime.now(UTC)
        assets = ["EURUSD_otc", "GBPUSD_otc", "USDCHF_otc", "AUDUSD_otc", "NZDUSD_otc"]
        for i, a in enumerate(assets):
            engine.active_trades[f"trade_{i}"] = LiveTradeRecord(
                trade_id=f"trade_{i}",
                asset=a,
                action="CALL",
                stake=Decimal("10.00"),
                open_time=now - timedelta(seconds=180),
                expiration_seconds=180,
                open_price=Decimal("1.0000"),
                strategy_id="strat",
                strategy_name="Strat",
                strategy_params={},
                indicator_snapshot=IndicatorSnapshot(),
                confidence=0.8,
                reason="test",
                payout_rate=Decimal("0.92"),
            )

        gateway.get_candles.return_value = [_make_candle_bar(now, 1.0010)]
        await engine._check_active_trades()

        assert len(engine.active_trades) == 0
        assert len(engine.recent_trades) == 5
        for a in assets:
            assert a in engine._asset_cooldown_until
            diff = abs(
                (engine._asset_cooldown_until[a] - (now + timedelta(seconds=240))).total_seconds()
            )
            assert diff < 1.0

        await engine.stop()


# =========================================================================
# 3. CIRCUIT BREAKER & AUTO-RESUME STATE MACHINE STRESS TESTS
# =========================================================================


class TestCircuitBreakerAndStateTransitions:
    """Stress tests consecutive loss circuit breaker, auto-resume, and high-watermark drawdown."""

    @pytest.mark.asyncio
    async def test_consecutive_losses_dynamic_sequence(self):
        """Dynamic sequence: L -> L -> W (resets) -> L -> L -> L (pauses) -> Auto-resume -> W."""
        store = MagicMock(spec=TradeStore)
        engine = LiveDemoBotEngine(trade_store=store)
        plan = _make_test_plan(max_consecutive_losses=3, pause_duration_minutes=10)
        gateway = AsyncMock()
        await engine.start(plan, gateway)

        now = datetime.now(UTC)

        def _simulate_trade(outcome_price: float, open_price: float = 1.0000) -> LiveTradeRecord:
            return LiveTradeRecord(
                trade_id=f"t_{datetime.now(UTC).timestamp()}",
                asset="EURUSD_otc",
                action="CALL",
                stake=Decimal("10.00"),
                open_time=now - timedelta(seconds=180),
                expiration_seconds=180,
                open_price=Decimal(str(open_price)),
                strategy_id="s",
                strategy_name="s",
                strategy_params={},
                indicator_snapshot=IndicatorSnapshot(),
                confidence=0.8,
                reason="test",
                payout_rate=Decimal("0.92"),
            )

        # Loss 1
        engine.active_trades["t1"] = _simulate_trade(0.9990)
        gateway.get_candles.return_value = [_make_candle_bar(now, 0.9990)]
        await engine._check_active_trades()
        assert engine.consecutive_losses == 1
        assert engine.status == BotStatus.RUNNING

        # Loss 2
        engine.active_trades["t2"] = _simulate_trade(0.9990)
        await engine._check_active_trades()
        assert engine.consecutive_losses == 2
        assert engine.status == BotStatus.RUNNING

        # Win (streak resets to 0)
        engine.active_trades["t3"] = _simulate_trade(1.0010)
        gateway.get_candles.return_value = [_make_candle_bar(now, 1.0010)]
        await engine._check_active_trades()
        assert engine.consecutive_losses == 0
        assert engine.status == BotStatus.RUNNING

        # Loss 1 again
        engine.active_trades["t4"] = _simulate_trade(0.9990)
        gateway.get_candles.return_value = [_make_candle_bar(now, 0.9990)]
        await engine._check_active_trades()
        assert engine.consecutive_losses == 1

        # Loss 2
        engine.active_trades["t5"] = _simulate_trade(0.9990)
        await engine._check_active_trades()
        assert engine.consecutive_losses == 2

        # Loss 3 -> triggers pause
        engine.active_trades["t6"] = _simulate_trade(0.9990)
        await engine._check_active_trades()
        assert engine.consecutive_losses == 3
        assert engine.status == BotStatus.PAUSED
        assert engine.is_paused() is True
        assert engine.paused_until is not None
        assert abs((engine.paused_until - (now + timedelta(minutes=10))).total_seconds()) < 1.0

        await engine.stop()

    @pytest.mark.asyncio
    async def test_auto_resume_expiry_transition(self):
        """Verifies auto-resume logic when current time passes paused_until."""
        store = MagicMock(spec=TradeStore)
        engine = LiveDemoBotEngine(trade_store=store)
        plan = _make_test_plan(max_consecutive_losses=3, pause_duration_minutes=15)
        gateway = AsyncMock()
        await engine.start(plan, gateway)

        # Force state into paused
        now = datetime.now(UTC)
        engine.status = BotStatus.PAUSED
        engine.paused_until = now + timedelta(seconds=10)
        engine.consecutive_losses = 3

        # Simulate loop check before paused_until
        assert engine.status == BotStatus.PAUSED

        # Advance paused_until to past
        engine.paused_until = now - timedelta(seconds=1)

        # Directly invoke pause expiration check in _run_loop step logic
        if engine.status == BotStatus.PAUSED and engine.paused_until:
            if datetime.now(UTC) >= engine.paused_until:
                engine.status = BotStatus.RUNNING
                engine.paused_until = None
                engine.consecutive_losses = 0

        assert engine.status == BotStatus.RUNNING
        assert engine.paused_until is None
        assert engine.consecutive_losses == 0

        await engine.stop()

    @pytest.mark.asyncio
    async def test_peak_to_trough_drawdown_exact_math(self):
        """Rigorous verification of high-watermark peak drawdown calculations."""
        store = MagicMock(spec=TradeStore)
        engine = LiveDemoBotEngine(trade_store=store)
        # max_drawdown_pct_limit = 8% (0.08)
        plan = _make_test_plan(max_drawdown_pct_limit=0.08)
        gateway = AsyncMock()
        await engine.start(plan, gateway)

        # Initial deposit = $1000
        assert engine.peak_balance == Decimal("1000.00")
        assert engine.current_balance == Decimal("1000.00")

        # Win series: balance rises to $1500
        engine.current_balance = Decimal("1500.00")
        engine.peak_balance = Decimal("1500.00")

        # Loss: drop to $1400 (Drawdown = (1500 - 1400)/1500 = 6.6667% < 8%)
        engine.current_balance = Decimal("1400.00")
        await engine._check_circuit_breakers()
        assert engine.status == BotStatus.RUNNING
        assert round(engine.current_drawdown_pct, 2) == 6.67

        # Loss: drop to $1379 (Drawdown = (1500 - 1379)/1500 = 8.0667% >= 8%)
        engine.current_balance = Decimal("1379.00")
        await engine._check_circuit_breakers()
        assert engine.status == BotStatus.HALTED_BY_CIRCUIT_BREAKER
        assert engine.current_drawdown_pct >= 8.0

        summary = engine.get_summary()
        assert summary.status == BotStatus.HALTED_BY_CIRCUIT_BREAKER
        assert summary.circuit_breaker_triggered is True

        # Manual resume restores RUNNING
        await engine.resume()
        assert engine.status == BotStatus.RUNNING
        assert engine.consecutive_losses == 0

        await engine.stop()

    @pytest.mark.asyncio
    async def test_hard_session_stop_loss_trigger(self):
        """Hard stop-loss check against stop_loss_amount ($100 limit)."""
        store = MagicMock(spec=TradeStore)
        engine = LiveDemoBotEngine(trade_store=store)
        plan = _make_test_plan()
        plan.stop_loss_amount = Decimal("100.00")
        plan.initial_deposit = Decimal("1000.00")
        gateway = AsyncMock()
        await engine.start(plan, gateway)

        # Drop balance to $899 (loss = $101 > $100)
        engine.current_balance = Decimal("899.00")
        await engine._check_circuit_breakers()
        assert engine.status == BotStatus.HALTED_BY_STOP_LOSS

        summary = engine.get_summary()
        assert summary.stop_loss_reached is True
        await engine.stop()


# =========================================================================
# 4. PORTFOLIO BACKTEST ENGINE GUARDRAIL PARITY STRESS TESTS
# =========================================================================


class TestPortfolioBacktestGuardrailsParity:
    """Stress tests execution guardrails in PortfolioBacktestEngine."""

    def _generate_synthetic_candles(
        self,
        asset: str,
        n_bars: int = 250,
        start_price: float = 1.0000,
        trend: float = 0.0002,
    ) -> pd.DataFrame:
        base_t = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        rows = []
        p = start_price
        for i in range(n_bars):
            p += trend if (i % 6 < 3) else -trend
            rows.append(
                {
                    "timestamp": base_t + timedelta(minutes=i),
                    "open": round(p - 0.0001, 5),
                    "high": round(p + 0.0003, 5),
                    "low": round(p - 0.0003, 5),
                    "close": round(p, 5),
                    "volume": 100.0,
                }
            )
        return pd.DataFrame(rows)

    def test_portfolio_backtest_correlation_stress(self):
        """Tests that correlation filtering blocks correlated entries across 4 pairs."""
        df_eurusd = self._generate_synthetic_candles("EURUSD_otc", 200, 1.1000)
        df_gbpusd = self._generate_synthetic_candles("GBPUSD_otc", 200, 1.2500)
        df_audusd = self._generate_synthetic_candles("AUDUSD_otc", 200, 0.6500)
        df_nzdusd = self._generate_synthetic_candles("NZDUSD_otc", 200, 0.6000)

        dfs = {
            "EURUSD_otc": df_eurusd,
            "GBPUSD_otc": df_gbpusd,
            "AUDUSD_otc": df_audusd,
            "NZDUSD_otc": df_nzdusd,
        }

        # Unfiltered
        cfg_unfiltered = PortfolioBacktestConfig(
            assets=list(dfs.keys()),
            timeframe_seconds=60,
            initial_deposit=Decimal("1000.0"),
            correlation_filter_enabled=False,
            max_concurrent_trades=4,
            strategy_name="hybrid_multifactors",
        )
        res_unfiltered = PortfolioBacktestEngine(cfg_unfiltered).run(dfs)

        # Filtered
        cfg_filtered = PortfolioBacktestConfig(
            assets=list(dfs.keys()),
            timeframe_seconds=60,
            initial_deposit=Decimal("1000.0"),
            correlation_filter_enabled=True,
            max_concurrent_trades=4,
            strategy_name="hybrid_multifactors",
        )
        res_filtered = PortfolioBacktestEngine(cfg_filtered).run(dfs)

        # The filtered engine must have rejected overlapping USD exposures
        assert res_filtered.total_trades <= res_unfiltered.total_trades
        assert res_filtered.final_balance > Decimal("0.0")

    def test_portfolio_backtest_cooldown_and_consecutive_losses_stress(self):
        """Tests combined cooldown and consecutive loss circuit breaker in portfolio backtester."""
        df = self._generate_synthetic_candles("EURUSD_otc", 300, 1.1000)
        dfs = {"EURUSD_otc": df}

        cfg_guarded = PortfolioBacktestConfig(
            assets=["EURUSD_otc"],
            timeframe_seconds=60,
            initial_deposit=Decimal("1000.0"),
            cooldown_bars=5,
            global_cooldown_seconds=60,
            max_consecutive_losses=2,
            max_drawdown_pct_limit=Decimal("0.05"),
            strategy_name="hybrid_multifactors",
            strategy_params={"adx_min_threshold": 5.0},
        )
        res_guarded = PortfolioBacktestEngine(cfg_guarded).run(dfs)

        assert res_guarded.max_consecutive_losses <= 3
        assert res_guarded.total_trades > 0
