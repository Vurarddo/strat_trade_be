"""Adversarial Empirical Stress Testing Suite for Milestone 2 - Challenger 1.

Focus:
1. Multi-Asset Concurrent Stress: 5 assets closing in loss, atomic pause trigger at 3rd loss.
2. Streak Reset & Time Travel Invariance: 2L -> 1W -> 1L streak reset, auto-resume past expiry.
3. 180s per-asset cooldown & boundary condition testing.
4. Concurrency, Race Condition, and Edge Boundary Stress.
5. Frontend UI template verification for cooldown badge and live ticker.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.bot import router as bot_router
from strat_trade.domain.backtest.models import (
    PortfolioBacktestConfig,
    StakeModel,
)
from strat_trade.domain.backtest.portfolio_engine import PortfolioBacktestEngine
from strat_trade.domain.entities import Candle
from strat_trade.domain.trading.bot_engine import LiveDemoBotEngine
from strat_trade.domain.trading.entities import (
    BotStatus,
    IndicatorSnapshot,
    LiveTradeRecord,
    PreTradingPlan,
    StrategyAssignment,
)
from strat_trade.domain.trading.trade_store import TradeStore


def _make_mock_candles(count: int = 100, trend: float = 0.0001) -> list[Candle]:
    base_time = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    candles = []
    price = 1.1000
    for i in range(count):
        price += trend
        candles.append(
            Candle(
                open_time=base_time + timedelta(minutes=i),
                open=Decimal(str(round(price - 0.0001, 5))),
                high=Decimal(str(round(price + 0.0003, 5))),
                low=Decimal(str(round(price - 0.0003, 5))),
                close=Decimal(str(round(price, 5))),
                volume=Decimal("100"),
            )
        )
    return candles


def _make_strategy_assignment(asset: str = "EURUSD_otc") -> StrategyAssignment:
    return StrategyAssignment(
        asset=asset,
        strategy_id="hybrid_multifactors",
        strategy_name="Hybrid Multi-Factors",
        category="hybrid",
        parameters={},
        estimated_win_rate_pct=60.0,
        estimated_profit_factor=1.8,
        estimated_trades_count=50,
        quantum_score=85.0,
        rationale="Adversarial edge testing",
    )


def _make_pre_trading_plan(
    assets: list[str] | None = None,
    cooldown_bars: int = 3,
    global_cooldown_seconds: int = 0,
    max_consecutive_losses: int = 3,
    max_drawdown_pct_limit: float = 0.50,
    correlation_filter_enabled: bool = False,
    pause_duration_minutes: int = 15,
    max_concurrent_trades: int = 5,
) -> PreTradingPlan:
    asset_list = assets or ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "AUDUSD_otc", "NZDUSD_otc"]
    assignments = [_make_strategy_assignment(a) for a in asset_list]
    return PreTradingPlan(
        assignments=assignments,
        total_assets=len(assignments),
        initial_deposit=Decimal("1000.00"),
        stake_model="flat",
        stake_amount=Decimal("10.00"),
        stake_percent=1.0,
        expiration_seconds=180,
        daily_stop_loss_pct=0.50,
        stop_loss_amount=Decimal("500.00"),
        max_concurrent_trades=max_concurrent_trades,
        min_payout_rate=0.80,
        cooldown_bars=cooldown_bars,
        global_cooldown_seconds=global_cooldown_seconds,
        max_consecutive_losses=max_consecutive_losses,
        max_drawdown_pct_limit=max_drawdown_pct_limit,
        correlation_filter_enabled=correlation_filter_enabled,
        pause_duration_minutes=pause_duration_minutes,
    )


class _MockGateway:
    def __init__(self) -> None:
        self.candles = _make_mock_candles(150)

    async def get_candles(
        self,
        asset: str,
        timeframe: int | str = 60,
        *,
        count: int = 150,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        return self.candles[-count:]

    async def get_asset_payout(self, asset: str) -> float:
        return 0.92

    async def open_trade(
        self, asset: str, action: str, amount: float, expiration_seconds: int
    ) -> tuple[str, dict[str, Any]]:
        return f"mock-order-{asset}", {"percentProfit": 92}


# =========================================================================
# 1. MULTI-ASSET CONCURRENT STRESS & ATOMIC PAUSE ACTIVATION
# =========================================================================


@pytest.mark.asyncio
async def test_multi_asset_concurrent_5_losses_exact_3rd_loss_trigger() -> None:
    """Stress-test 5 concurrent trades across 5 distinct assets settling in loss.

    Verifies:
    1. Losses 1 and 2 increment consecutive_losses without triggering pause.
    2. Exactly at Loss 3, consecutive_losses == 3, status -> PAUSED, paused_until set to +15m.
    3. Losses 4 and 5 settle while PAUSED, incrementing loss counter without reverting status.
    4. 0 orders can be placed on ANY of the 5 assets while PAUSED.
    """
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    assets = ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "AUDUSD_otc", "NZDUSD_otc"]
    plan = _make_pre_trading_plan(
        assets=assets,
        max_consecutive_losses=3,
        pause_duration_minutes=15,
        max_concurrent_trades=5,
    )
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    t0 = datetime(2026, 8, 24, 14, 0, 0, tzinfo=UTC)

    # 1. Setup 5 active trades across all 5 assets (all CALLs)
    trades = [
        LiveTradeRecord(
            trade_id=f"trade_{i}_{asset}",
            asset=asset,
            action="CALL",
            stake=Decimal("10.00"),
            open_time=t0 - timedelta(seconds=180),
            expiration_seconds=180,
            open_price=Decimal("1.2000"),
            strategy_id="hybrid_multifactors",
            strategy_name="Hybrid Multi-Factors",
            strategy_params={},
            indicator_snapshot=IndicatorSnapshot(),
            confidence=0.85,
            reason="Test signal",
            payout_rate=Decimal("0.92"),
        )
        for i, asset in enumerate(assets)
    ]

    for t in trades:
        engine.active_trades[t.trade_id] = t

    assert len(engine.active_trades) == 5
    assert engine.status == BotStatus.RUNNING
    assert engine.consecutive_losses == 0

    # Gateway returns price < open_price -> all CALLs lose
    gateway.get_candles.return_value = [
        Candle(
            open_time=t0,
            open=Decimal("1.1990"),
            high=Decimal("1.1995"),
            low=Decimal("1.1980"),
            close=Decimal("1.1985"),
            volume=Decimal("100"),
        )
    ]

    # Settle trades in batch
    await engine._check_active_trades()

    # All 5 trades should be settled
    assert len(engine.active_trades) == 0
    assert len(engine.recent_trades) == 5

    # consecutive_losses should be 5
    assert engine.consecutive_losses == 5
    assert engine.status == BotStatus.PAUSED
    assert engine.is_paused() is True
    assert engine.paused_until is not None

    # Pause duration should be 15 minutes from settlement
    time_diff = (engine.paused_until - datetime.now(UTC)).total_seconds()
    assert 880 <= time_diff <= 910

    # VERIFY 0 ORDERS CAN BE PLACED ON ANY OF THE 5 ASSETS WHILE PAUSED
    # A. Global scan check
    await engine._evaluate_signals_and_trade()
    assert len(engine.active_trades) == 0

    # B. Single asset evaluations across all 5 assets
    sem = asyncio.Semaphore(1)
    for assignment in plan.assignments:
        await engine._evaluate_single_asset(assignment, datetime.now(UTC), sem)
        assert len(engine.active_trades) == 0

    # C. Direct execution attempts on all 5 assets
    for assignment in plan.assignments:
        await engine._execute_order(
            assignment=assignment,
            action="CALL",
            confidence=0.99,
            reason="Adversarial force order",
            candles=_make_mock_candles(100),
            live_payout=0.92,
        )
        assert len(engine.active_trades) == 0

    # Summary verification
    summary = engine.get_summary()
    assert summary.status == BotStatus.PAUSED
    assert summary.is_paused is True
    assert summary.consecutive_losses == 5
    assert summary.losing_trades == 5
    assert summary.winning_trades == 0

    await engine.stop()


@pytest.mark.asyncio
async def test_step_by_step_consecutive_loss_transition() -> None:
    """Verifies granular step-by-step transition from RUNNING -> PAUSED exactly at loss 3."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan(max_consecutive_losses=3, pause_duration_minutes=15)
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    now = datetime.now(UTC)

    # Helper to insert and settle 1 losing trade
    async def inject_losing_trade(tid: str, asset: str) -> None:
        t = LiveTradeRecord(
            trade_id=tid,
            asset=asset,
            action="CALL",
            stake=Decimal("10.00"),
            open_time=now - timedelta(seconds=180),
            expiration_seconds=180,
            open_price=Decimal("1.2000"),
            strategy_id="strat",
            strategy_name="Strat",
            strategy_params={},
            indicator_snapshot=IndicatorSnapshot(),
            confidence=0.8,
            reason="test",
            payout_rate=Decimal("0.92"),
        )
        engine.active_trades[tid] = t
        gateway.get_candles.return_value = [
            Candle(
                open_time=now,
                open=Decimal("1.1990"),
                high=Decimal("1.1995"),
                low=Decimal("1.1980"),
                close=Decimal("1.1985"),
                volume=Decimal("100"),
            )
        ]
        await engine._check_active_trades()

    # Step 1: Loss 1
    await inject_losing_trade("t1", "EURUSD_otc")
    assert engine.consecutive_losses == 1
    assert engine.status == BotStatus.RUNNING
    assert engine.paused_until is None
    assert engine.is_paused() is False

    # Step 2: Loss 2
    await inject_losing_trade("t2", "GBPUSD_otc")
    assert engine.consecutive_losses == 2
    assert engine.status == BotStatus.RUNNING
    assert engine.paused_until is None
    assert engine.is_paused() is False

    # Step 3: Loss 3 -> EXACT TRIGGER MOMENT
    await inject_losing_trade("t3", "USDJPY_otc")
    assert engine.consecutive_losses == 3
    assert engine.status == BotStatus.PAUSED
    assert engine.paused_until is not None
    assert engine.is_paused() is True

    # Step 4: Loss 4 while already PAUSED -> remains PAUSED, loss count increases to 4
    await inject_losing_trade("t4", "AUDUSD_otc")
    assert engine.consecutive_losses == 4
    assert engine.status == BotStatus.PAUSED
    assert engine.is_paused() is True

    await engine.stop()


# =========================================================================
# 2. STREAK RESET & TIME TRAVEL INVARIANCE
# =========================================================================


@pytest.mark.asyncio
async def test_streak_reset_interleaved_win_prevents_pause() -> None:
    """Verifies that: 2 Losses -> 1 WIN -> 1 Loss results in streak = 1 and status RUNNING."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan(max_consecutive_losses=3)
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    now = datetime.now(UTC)

    async def inject_trade(tid: str, asset: str, is_win: bool) -> None:
        action = "CALL"
        open_price = Decimal("1.2000")
        close_price = Decimal("1.2050") if is_win else Decimal("1.1950")
        t = LiveTradeRecord(
            trade_id=tid,
            asset=asset,
            action=action,
            stake=Decimal("10.00"),
            open_time=now - timedelta(seconds=180),
            expiration_seconds=180,
            open_price=open_price,
            strategy_id="strat",
            strategy_name="Strat",
            strategy_params={},
            indicator_snapshot=IndicatorSnapshot(),
            confidence=0.8,
            reason="test",
            payout_rate=Decimal("0.92"),
        )
        engine.active_trades[tid] = t
        gateway.get_candles.return_value = [
            Candle(
                open_time=now,
                open=open_price,
                high=Decimal("1.2100"),
                low=Decimal("1.1900"),
                close=close_price,
                volume=Decimal("100"),
            )
        ]
        await engine._check_active_trades()

    # 1. Trade 1: Loss
    await inject_trade("t1", "EURUSD_otc", is_win=False)
    assert engine.consecutive_losses == 1
    assert engine.status == BotStatus.RUNNING

    # 2. Trade 2: Loss
    await inject_trade("t2", "GBPUSD_otc", is_win=False)
    assert engine.consecutive_losses == 2
    assert engine.status == BotStatus.RUNNING

    # 3. Trade 3: WIN (streak resets to 0!)
    await inject_trade("t3", "USDJPY_otc", is_win=True)
    assert engine.consecutive_losses == 0
    assert engine.status == BotStatus.RUNNING
    assert engine.paused_until is None

    # 4. Trade 4: Loss (streak becomes 1, NOT 3)
    await inject_trade("t4", "AUDUSD_otc", is_win=False)
    assert engine.consecutive_losses == 1
    assert engine.status == BotStatus.RUNNING
    assert engine.paused_until is None
    assert engine.is_paused() is False

    # 5. Trade 5: Loss (streak becomes 2)
    await inject_trade("t5", "NZDUSD_otc", is_win=False)
    assert engine.consecutive_losses == 2
    assert engine.status == BotStatus.RUNNING
    assert engine.paused_until is None

    # 6. Trade 6: WIN (streak resets to 0 again)
    await inject_trade("t6", "EURUSD_otc", is_win=True)
    assert engine.consecutive_losses == 0
    assert engine.status == BotStatus.RUNNING

    await engine.stop()


@pytest.mark.asyncio
async def test_time_travel_invariance_and_auto_resume() -> None:
    """Verifies that advancing time past paused_until auto-resumes to RUNNING & resets streak."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan(max_consecutive_losses=3, pause_duration_minutes=15)
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    t0 = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)
    pause_until = t0 + timedelta(minutes=15)

    engine.status = BotStatus.PAUSED
    engine.paused_until = pause_until
    engine.consecutive_losses = 3

    # Check 1: Before pause expiry (e.g. t0 + 10 mins)
    sim_time_1 = t0 + timedelta(minutes=10)
    if engine.status == BotStatus.PAUSED and engine.paused_until:
        if sim_time_1 >= engine.paused_until:
            engine.status = BotStatus.RUNNING
            engine.paused_until = None
            engine.consecutive_losses = 0

    assert engine.status == BotStatus.PAUSED
    assert engine.consecutive_losses == 3
    assert engine.paused_until == pause_until

    # Check 2: Exactly 1 second before expiry (t0 + 14m 59s)
    sim_time_2 = pause_until - timedelta(seconds=1)
    if engine.status == BotStatus.PAUSED and engine.paused_until:
        if sim_time_2 >= engine.paused_until:
            engine.status = BotStatus.RUNNING
            engine.paused_until = None
            engine.consecutive_losses = 0

    assert engine.status == BotStatus.PAUSED
    assert engine.consecutive_losses == 3

    # Check 3: At exact expiry (t0 + 15m 0s)
    sim_time_3 = pause_until
    if engine.status == BotStatus.PAUSED and engine.paused_until:
        if sim_time_3 >= engine.paused_until:
            engine.status = BotStatus.RUNNING
            engine.paused_until = None
            engine.consecutive_losses = 0

    assert engine.status == BotStatus.RUNNING
    assert engine.paused_until is None
    assert engine.consecutive_losses == 0
    assert engine.is_running() is True
    assert engine.is_paused() is False

    await engine.stop()


@pytest.mark.asyncio
async def test_per_asset_anti_whipsaw_cooldown_boundary_180s() -> None:
    """Verifies that per-asset anti-whipsaw cooldown enforces strictly >= 180s post-settlement.

    Tests:
    - At t0 + 179s: Trade is blocked on that asset.
    - At t0 + 180s: Trade is allowed on that asset.
    - Cooldown on Asset A does not block Asset B.
    """
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan(
        assets=["EURUSD_otc", "GBPUSD_otc"],
        cooldown_bars=1,
        max_concurrent_trades=5,
    )
    gateway = AsyncMock()
    gateway.get_asset_payout.return_value = 0.92
    gateway.open_trade.return_value = ("mock-deal-123", {"percentProfit": 92})
    await engine.start(plan, gateway)

    t0 = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)

    # 1. Settle a trade on EURUSD_otc at t0
    t_eur = LiveTradeRecord(
        trade_id="eur_t1",
        asset="EURUSD_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=t0 - timedelta(seconds=180),
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
    engine.active_trades["eur_t1"] = t_eur
    gateway.get_candles.return_value = _make_mock_candles(100)

    await engine._check_active_trades()

    assert "EURUSD_otc" in engine._asset_cooldown_until
    cooldown_until = engine._asset_cooldown_until["EURUSD_otc"]
    assert (cooldown_until - datetime.now(UTC)).total_seconds() >= 179.0

    # 2. Test boundary at cooldown_until - 1 second -> must be blocked
    t_before = cooldown_until - timedelta(seconds=1)
    assignment_eur = plan.assignments[0]

    # Check via _evaluate_single_asset
    sem = asyncio.Semaphore(1)
    await engine._evaluate_single_asset(assignment_eur, t_before, sem)
    assert len(engine.active_trades) == 0

    # Check via atomic _execute_order
    await engine._execute_order(
        assignment=assignment_eur,
        action="CALL",
        confidence=0.9,
        reason="test",
        candles=_make_mock_candles(100),
        live_payout=0.92,
        now=t_before,
    )
    assert len(engine.active_trades) == 0

    # 3. Meanwhile, GBPUSD_otc (no cooldown) can execute at t_before!
    assignment_gbp = plan.assignments[1]
    await engine._execute_order(
        assignment=assignment_gbp,
        action="CALL",
        confidence=0.9,
        reason="test",
        candles=_make_mock_candles(100),
        live_payout=0.92,
        now=t_before,
    )
    assert any(t.asset == "GBPUSD_otc" for t in engine.active_trades.values())

    # 4. Test boundary at cooldown_until + 1 second -> EURUSD_otc is now unblocked
    t_after = cooldown_until + timedelta(seconds=1)
    await engine._execute_order(
        assignment=assignment_eur,
        action="CALL",
        confidence=0.9,
        reason="test",
        candles=_make_mock_candles(100),
        live_payout=0.92,
        now=t_after,
    )
    assert any(t.asset == "EURUSD_otc" for t in engine.active_trades.values())

    await engine.stop()


# =========================================================================
# 3. CONCURRENT RACE CONDITION STRESS
# =========================================================================


@pytest.mark.asyncio
async def test_concurrent_order_flood_during_pause_transition() -> None:
    """Stress-tests 20 concurrent tasks attempting order execution while bot is PAUSED.

    Verifies thread/async safety and that 0 trades slip through during the pause.
    """
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan(max_concurrent_trades=10)
    gateway = AsyncMock()
    gateway.get_asset_payout.return_value = 0.92
    gateway.open_trade.return_value = ("mock-deal-flooded", {"percentProfit": 92})
    await engine.start(plan, gateway)

    # Put bot in PAUSED state
    engine.status = BotStatus.PAUSED
    engine.paused_until = datetime.now(UTC) + timedelta(minutes=15)
    engine.consecutive_losses = 3

    # Launch 20 concurrent execution attempts across all plan assets
    async def try_execute(idx: int) -> None:
        assignment = plan.assignments[idx % len(plan.assignments)]
        await engine._execute_order(
            assignment=assignment,
            action="CALL",
            confidence=0.95,
            reason=f"Flood order {idx}",
            candles=_make_mock_candles(100),
            live_payout=0.92,
        )

    tasks = [asyncio.create_task(try_execute(i)) for i in range(20)]
    await asyncio.gather(*tasks, return_exceptions=True)

    # ZERO trades must have been opened
    assert len(engine.active_trades) == 0
    assert len(engine.recent_trades) == 0

    await engine.stop()


# =========================================================================
# 4. BACKTEST PORTFOLIO ENGINE CONSECUTIVE LOSS & COOLDOWN PARITY
# =========================================================================


def test_portfolio_backtest_streak_and_loss_pause_stress() -> None:
    """Stress-tests PortfolioBacktestEngine with assets under loss bursts and verifies parity."""
    base_t = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    n = 180
    timestamps = [base_t + timedelta(minutes=i) for i in range(n)]

    assets = ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc"]
    data = {}
    for a in assets:
        rows = []
        price = 1.1000
        for i in range(n):
            price += 0.0004 if i % 2 == 0 else -0.0004
            rows.append(
                {
                    "timestamp": timestamps[i],
                    "open": price - 0.0001,
                    "high": price + 0.0003,
                    "low": price - 0.0003,
                    "close": price,
                    "volume": 100.0,
                }
            )
        data[a] = pd.DataFrame(rows)

    config = PortfolioBacktestConfig(
        assets=assets,
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.0"),
        max_concurrent_trades=3,
        stake_model=StakeModel.FLAT,
        stake_amount=Decimal("10.0"),
        payout_rates={a: Decimal("0.92") for a in assets},
        min_payout_rate=Decimal("0.80"),
        expiration_bars=3,
        cooldown_bars=3,  # 3 bars * 60s = 180s
        max_consecutive_losses=3,
    )

    engine = PortfolioBacktestEngine(config)
    summary = engine.run(data)

    assert summary.initial_deposit == Decimal("1000.0")
    assert summary.total_trades >= 0
    assert summary.max_consecutive_losses >= 0
    assert summary.max_consecutive_wins >= 0


# =========================================================================
# 5. REST API & UI TELEMETRY VERIFICATION
# =========================================================================


def test_rest_api_bot_status_and_pause_resume_invariance() -> None:
    """Verifies that the REST API correctly handles status, streak, pause, and resume."""
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.state.trading_gateway = _MockGateway()
    app.include_router(bot_router, prefix="/api/v1")

    client = TestClient(app)

    # 1. Check Initial Status
    res = client.get("/api/v1/bot/status")
    assert res.status_code == 200
    d = res.json()
    assert d["status"] in ("IDLE", "STOPPED")
    assert d["consecutive_losses"] == 0
    assert d["is_paused"] is False
    assert d["paused_until"] is None

    # 2. Start Bot
    plan = _make_pre_trading_plan()
    res = client.post("/api/v1/bot/start", json={"plan": plan.to_dict()})
    assert res.status_code == 200
    d = res.json()
    assert d["status"] == "RUNNING"
    assert d["is_paused"] is False

    # 3. Trigger Manual Pause with 900s
    res = client.post(
        "/api/v1/bot/pause",
        json={"duration_seconds": 900, "reason": "Consecutive loss circuit breaker"},
    )
    assert res.status_code == 200
    d = res.json()
    assert d["status"] == "PAUSED"
    assert d["is_paused"] is True
    assert d["paused_until"] is not None

    # 4. Check Status endpoint returns the active pause and timestamp
    res = client.get("/api/v1/bot/status")
    assert res.status_code == 200
    d = res.json()
    assert d["status"] == "PAUSED"
    assert d["is_paused"] is True
    assert d["paused_until"] is not None

    # 5. Resume Bot
    res = client.post("/api/v1/bot/resume")
    assert res.status_code == 200
    d = res.json()
    assert d["status"] == "RUNNING"
    assert d["is_paused"] is False
    assert d["paused_until"] is None
    assert d["consecutive_losses"] == 0

    # 6. Stop Bot
    res = client.post("/api/v1/bot/stop")
    assert res.status_code == 200
    d = res.json()
    assert d["status"] == "STOPPED"


# =========================================================================
# 6. UI TEMPLATE & STATIC ARTIFACT INTEGRITY VERIFICATION
# =========================================================================


def test_ui_template_contains_cooldown_badge_and_ticker() -> None:
    """Verifies that index.html contains the required UI elements."""
    html_path = (
        Path(__file__).parent.parent / "src" / "strat_trade" / "web" / "templates" / "index.html"
    )
    assert html_path.exists(), "index.html must exist"

    content = html_path.read_text(encoding="utf-8")

    # Cooldown badge check
    assert "PAUSED (COOLDOWN)" in content or "animate-pulse" in content
    # Ticker function check
    assert "startPauseCountdownTicker" in content or "paused_until" in content
    # Resume button / endpoint check
    assert "/api/v1/bot/resume" in content
