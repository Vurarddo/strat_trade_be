from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.bot import router as bot_router
from strat_trade.domain.backtest.models import PortfolioBacktestConfig
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
        rationale="Strong edge",
    )


def _make_pre_trading_plan(
    assets: list[str] | None = None,
    cooldown_bars: int = 3,
    global_cooldown_seconds: int = 30,
    max_consecutive_losses: int = 3,
    max_drawdown_pct_limit: float = 0.08,
    correlation_filter_enabled: bool = True,
    pause_duration_minutes: int = 15,
) -> PreTradingPlan:
    asset_list = assets or ["EURUSD_otc", "GBPUSD_otc", "USDCHF_otc"]
    assignments = [_make_strategy_assignment(a) for a in asset_list]
    return PreTradingPlan(
        assignments=assignments,
        total_assets=len(assignments),
        initial_deposit=Decimal("1000.00"),
        stake_model="flat",
        stake_amount=Decimal("10.00"),
        stake_percent=1.0,
        expiration_seconds=180,
        daily_stop_loss_pct=0.05,
        stop_loss_amount=Decimal("50.00"),
        max_concurrent_trades=3,
        min_payout_rate=0.80,
        cooldown_bars=cooldown_bars,
        global_cooldown_seconds=global_cooldown_seconds,
        max_consecutive_losses=max_consecutive_losses,
        max_drawdown_pct_limit=max_drawdown_pct_limit,
        correlation_filter_enabled=correlation_filter_enabled,
        pause_duration_minutes=pause_duration_minutes,
        session_filter_enabled=False,
    )


class _FakeGateway:
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

    async def get_assets(self) -> list[dict]:
        return [
            {
                "symbol": "EURUSD_otc",
                "name": "EUR/USD OTC",
                "payout": 92,
                "is_otc": True,
                "asset_type": "currency",
            },
            {
                "symbol": "GBPUSD_otc",
                "name": "GBP/USD OTC",
                "payout": 92,
                "is_otc": True,
                "asset_type": "currency",
            },
        ]

    async def get_asset_payout(self, asset: str) -> float:
        return 0.92

    async def open_trade(
        self, asset: str, action: str, amount: float, expiration_seconds: int
    ) -> tuple[str, dict]:
        return "test-order-uuid-12345", {"percentProfit": 92}


def _get_test_client() -> TestClient:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.state.trading_gateway = _FakeGateway()
    app.include_router(bot_router, prefix="/api/v1")
    return TestClient(app)


# =========================================================================
# SUITE 1: Per-Asset Settlement Cooldown & Global Cooldown Timing
# =========================================================================


@pytest.mark.asyncio
async def test_post_settlement_per_asset_cooldown():
    """Verifies that settling a trade puts the specific asset on cooldown for N bars."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan(cooldown_bars=3)
    gateway = AsyncMock()

    await engine.start(plan, gateway)
    now = datetime.now(UTC)

    # Simulate an active trade on EURUSD_otc that expires now
    trade = LiveTradeRecord(
        trade_id="t1",
        asset="EURUSD_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=now - timedelta(seconds=180),
        expiration_seconds=180,
        open_price=Decimal("1.1000"),
        strategy_id="strat1",
        strategy_name="Strat 1",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )
    engine.active_trades["t1"] = trade
    gateway.get_candles.return_value = _make_mock_candles(count=5)

    # Settle active trades
    await engine._check_active_trades()

    # Asset should have a cooldown entry until ~180s from now
    assert "EURUSD_otc" in engine._asset_cooldown_until
    cooldown_until = engine._asset_cooldown_until["EURUSD_otc"]
    assert cooldown_until > now

    # Evaluating EURUSD_otc immediately should skip evaluation
    sem = asyncio.Semaphore(1)
    assignment = plan.assignments[0]
    await engine._evaluate_single_asset(assignment, now, sem)
    # No new trade should be opened
    assert len(engine.active_trades) == 0

    # Advance time past cooldown
    future_time = cooldown_until + timedelta(seconds=1)
    # Mock gateway to return valid candles and payout for signal
    gateway.get_asset_payout.return_value = 0.92
    gateway.get_candles.return_value = _make_mock_candles(count=100)
    gateway.open_trade.return_value = ("broker-123", {"percentProfit": 92})

    # Strategy mock
    mock_strat = MagicMock()
    mock_sig = MagicMock()
    mock_sig.action.value = "CALL"
    mock_sig.confidence = 0.85
    mock_sig.metadata = {"reason": "test_signal"}
    mock_sig.regime = "trending"
    mock_strat.evaluate_candles.return_value = mock_sig
    engine._strategy_instances["EURUSD_otc"] = mock_strat

    await engine._evaluate_single_asset(assignment, future_time, sem)
    assert len(engine.active_trades) == 1
    await engine.stop()


@pytest.mark.asyncio
async def test_global_cooldown_portfolio_delay():
    """Verifies executing order triggers global cooldown preventing immediate other orders."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan(global_cooldown_seconds=30)
    gateway = AsyncMock()
    gateway.get_asset_payout.return_value = 0.92
    gateway.open_trade.return_value = ("broker-123", {"percentProfit": 92})

    await engine.start(plan, gateway)
    now = datetime.now(UTC)
    candles = _make_mock_candles(count=100)

    # First order executes on EURUSD_otc
    await engine._execute_order(
        assignment=plan.assignments[0],
        action="CALL",
        confidence=0.8,
        reason="test1",
        candles=candles,
        live_payout=0.92,
    )
    assert len(engine.active_trades) == 1
    assert engine._last_global_execution_time is not None

    # Attempt to execute GBPUSD_otc 5 seconds later -> blocked by global cooldown
    await engine._execute_order(
        assignment=plan.assignments[1],
        action="CALL",
        confidence=0.8,
        reason="test2",
        candles=candles,
        live_payout=0.92,
    )
    # Still only 1 active trade
    assert len(engine.active_trades) == 1

    # Fast forward last execution time by 35 seconds
    engine._last_global_execution_time = now - timedelta(seconds=35)
    await engine._execute_order(
        assignment=plan.assignments[1],
        action="CALL",
        confidence=0.8,
        reason="test2",
        candles=candles,
        live_payout=0.92,
    )
    assert len(engine.active_trades) == 2
    await engine.stop()


# =========================================================================
# SUITE 2: Currency Pair Correlation & Directional Exposure Filter
# =========================================================================


@pytest.mark.asyncio
async def test_correlation_filter_in_bot_engine():
    """Verifies that LiveDemoBotEngine rejects correlated candidate orders."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan(
        assets=["AUDUSD_otc", "AUDNZD_otc"],
        correlation_filter_enabled=True,
    )
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    now = datetime.now(UTC)
    # Open CALL on AUDUSD_otc (Long AUD, Short USD)
    active_trade = LiveTradeRecord(
        trade_id="t-audusd",
        asset="AUDUSD_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=now,
        expiration_seconds=180,
        open_price=Decimal("0.6500"),
        strategy_id="strat",
        strategy_name="Strat",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )
    engine.active_trades["t-audusd"] = active_trade

    # Setup candidate signal on AUDNZD_otc (CALL -> Long AUD, Short NZD)
    mock_strat = MagicMock()
    mock_sig = MagicMock()
    mock_sig.action.value = "CALL"
    mock_sig.confidence = 0.85
    mock_sig.metadata = {"reason": "test_signal"}
    mock_sig.regime = "trending"
    mock_strat.evaluate_candles.return_value = mock_sig
    engine._strategy_instances["AUDNZD_otc"] = mock_strat

    gateway.get_asset_payout.return_value = 0.92
    gateway.get_candles.return_value = _make_mock_candles(count=100)

    sem = asyncio.Semaphore(1)
    audnzd_assignment = plan.assignments[1]
    await engine._evaluate_single_asset(audnzd_assignment, now, sem)

    # Order should have been rejected by correlation filter (Double Long AUD)
    assert len(engine.active_trades) == 1
    assert "t-audusd" in engine.active_trades
    await engine.stop()


# =========================================================================
# SUITE 3: Consecutive Loss Circuit Breaker State Machine
# =========================================================================


@pytest.mark.asyncio
async def test_consecutive_losses_triggers_pause_state():
    """Verifies that K consecutive losses transitions status to PAUSED."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan(max_consecutive_losses=3, pause_duration_minutes=15)
    gateway = AsyncMock()

    await engine.start(plan, gateway)
    now = datetime.now(UTC)

    # Settle Loss 1
    t1 = LiveTradeRecord(
        trade_id="t1",
        asset="EURUSD_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=now - timedelta(seconds=180),
        expiration_seconds=180,
        open_price=Decimal("1.1000"),
        strategy_id="s",
        strategy_name="s",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )
    engine.active_trades["t1"] = t1
    # Exit price lower -> Loss
    candle_loss = Candle(
        open_time=now,
        open=Decimal("1.0990"),
        high=Decimal("1.0995"),
        low=Decimal("1.0980"),
        close=Decimal("1.0990"),
        volume=Decimal("10"),
    )
    gateway.get_candles.return_value = [candle_loss]

    await engine._check_active_trades()
    assert engine.consecutive_losses == 1
    assert engine.status == BotStatus.RUNNING

    # Settle Loss 2
    t2 = LiveTradeRecord(
        trade_id="t2",
        asset="GBPUSD_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=now - timedelta(seconds=180),
        expiration_seconds=180,
        open_price=Decimal("1.2500"),
        strategy_id="s",
        strategy_name="s",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )
    engine.active_trades["t2"] = t2
    candle_loss2 = Candle(
        open_time=now,
        open=Decimal("1.2490"),
        high=Decimal("1.2495"),
        low=Decimal("1.2480"),
        close=Decimal("1.2490"),
        volume=Decimal("10"),
    )
    gateway.get_candles.return_value = [candle_loss2]
    await engine._check_active_trades()
    assert engine.consecutive_losses == 2
    assert engine.status == BotStatus.RUNNING

    # Settle Loss 3 -> Hits limit!
    t3 = LiveTradeRecord(
        trade_id="t3",
        asset="USDCHF_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=now - timedelta(seconds=180),
        expiration_seconds=180,
        open_price=Decimal("0.9000"),
        strategy_id="s",
        strategy_name="s",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )
    engine.active_trades["t3"] = t3
    candle_loss3 = Candle(
        open_time=now,
        open=Decimal("0.8990"),
        high=Decimal("0.8995"),
        low=Decimal("0.8980"),
        close=Decimal("0.8990"),
        volume=Decimal("10"),
    )
    gateway.get_candles.return_value = [candle_loss3]
    await engine._check_active_trades()

    assert engine.consecutive_losses == 3
    assert engine.status == BotStatus.PAUSED
    assert engine.is_paused() is True
    assert engine.paused_until is not None
    assert engine.paused_until > now

    summary = engine.get_summary()
    assert summary.is_paused is True
    assert summary.consecutive_losses == 3
    assert summary.paused_until is not None
    await engine.stop()


@pytest.mark.asyncio
async def test_consecutive_losses_counter_resets_on_win():
    """Verifies that a winning trade resets consecutive_losses streak to 0."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan(max_consecutive_losses=3)
    gateway = AsyncMock()

    await engine.start(plan, gateway)
    engine.consecutive_losses = 2  # 2 previous losses

    now = datetime.now(UTC)
    t_win = LiveTradeRecord(
        trade_id="twin",
        asset="EURUSD_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=now - timedelta(seconds=180),
        expiration_seconds=180,
        open_price=Decimal("1.1000"),
        strategy_id="s",
        strategy_name="s",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )
    engine.active_trades["twin"] = t_win
    # Exit price higher -> WIN
    candle_win = Candle(
        open_time=now,
        open=Decimal("1.1010"),
        high=Decimal("1.1020"),
        low=Decimal("1.1005"),
        close=Decimal("1.1015"),
        volume=Decimal("10"),
    )
    gateway.get_candles.return_value = [candle_win]
    await engine._check_active_trades()

    assert engine.consecutive_losses == 0
    assert engine.status == BotStatus.RUNNING
    await engine.stop()


# =========================================================================
# SUITE 4: High-Watermark Peak Balance & Drawdown Circuit Breaker
# =========================================================================


@pytest.mark.asyncio
async def test_peak_drawdown_circuit_breaker_halt():
    """Verifies that peak-to-trough drawdown >= max_drawdown_pct_limit halts the bot."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    # Limit = 8.0%
    plan = _make_pre_trading_plan(max_drawdown_pct_limit=0.08)
    gateway = AsyncMock()

    await engine.start(plan, gateway)
    # Simulate deposit grew to $1200 (peak = 1200)
    engine.current_balance = Decimal("1200.00")
    engine.peak_balance = Decimal("1200.00")

    # Settle losses bringing balance to $1100 ($100 loss from $1200 = 8.33% drawdown)
    engine.current_balance = Decimal("1100.00")
    await engine._check_circuit_breakers()

    assert engine.status == BotStatus.HALTED_BY_CIRCUIT_BREAKER
    assert engine.current_drawdown_pct > 8.0
    summary = engine.get_summary()
    assert summary.status == BotStatus.HALTED_BY_CIRCUIT_BREAKER
    assert summary.circuit_breaker_triggered is True
    await engine.stop()


@pytest.mark.asyncio
async def test_resume_from_drawdown_circuit_breaker_resets_baseline_and_continues_running():
    """Verifies that resuming from circuit breaker halt resets peak balance/drawdown
    and avoids immediate re-halt.
    """
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan(max_drawdown_pct_limit=0.08)
    gateway = AsyncMock()

    await engine.start(plan, gateway)
    engine.peak_balance = Decimal("1200.00")
    engine.current_balance = Decimal("1100.00")

    # Trigger circuit breaker halt (8.33% drawdown >= 8.0% limit)
    await engine._check_circuit_breakers()
    assert engine.status == BotStatus.HALTED_BY_CIRCUIT_BREAKER
    assert engine.current_drawdown_pct > 8.0

    # Resume bot
    await engine.resume()
    assert engine.status == BotStatus.RUNNING
    assert engine.peak_balance == Decimal("1100.00")
    assert engine.current_drawdown_pct == 0.0

    # Simulate subsequent loop ticks calling _check_circuit_breakers
    for _ in range(5):
        await engine._check_circuit_breakers()
        assert engine.status == BotStatus.RUNNING
        assert engine.current_drawdown_pct == 0.0

    await engine.stop()


# =========================================================================
# SUITE 5: REST API Lifecycle & Enriched Telemetry
# =========================================================================


def test_api_bot_pause_and_resume_endpoints():
    """Verifies REST endpoints /api/v1/bot/pause, /api/v1/bot/resume, and status telemetry."""
    client = _get_test_client()

    # 1. Auto-assign pre-trading plan with guardrail parameters
    assign_resp = client.post(
        "/api/v1/bot/auto-assign",
        json={
            "assets": ["EURUSD_otc", "GBPUSD_otc"],
            "initial_deposit": 1000.0,
            "stake_model": "flat",
            "stake_amount": 10.0,
            "stake_percent": 1.0,
            "expiration_seconds": 180,
            "daily_stop_loss_pct": 0.05,
            "max_concurrent_trades": 3,
            "min_payout_rate": 0.80,
            "cooldown_bars": 3,
            "global_cooldown_seconds": 30,
            "max_consecutive_losses": 3,
            "max_drawdown_pct_limit": 0.08,
            "correlation_filter_enabled": True,
            "pause_duration_minutes": 15,
        },
    )
    assert assign_resp.status_code == 200
    plan_data = assign_resp.json()
    assert plan_data["cooldown_bars"] == 3
    assert plan_data["correlation_filter_enabled"] is True

    # 2. Start Bot
    start_resp = client.post("/api/v1/bot/start", json={"plan": plan_data})
    assert start_resp.status_code == 200
    status_data = start_resp.json()
    assert status_data["status"] == "RUNNING"
    assert status_data["is_paused"] is False
    assert status_data["consecutive_losses"] == 0

    # 3. Pause Bot with duration
    pause_resp = client.post(
        "/api/v1/bot/pause",
        json={"duration_seconds": 600, "reason": "operator break"},
    )
    assert pause_resp.status_code == 200
    pause_data = pause_resp.json()
    assert pause_data["status"] == "PAUSED"
    assert pause_data["is_paused"] is True
    assert pause_data["paused_until"] is not None

    # 4. Resume Bot
    resume_resp = client.post("/api/v1/bot/resume")
    assert resume_resp.status_code == 200
    resume_data = resume_resp.json()
    assert resume_data["status"] == "RUNNING"
    assert resume_data["is_paused"] is False
    assert resume_data["paused_until"] is None

    # 5. Stop Bot
    stop_resp = client.post("/api/v1/bot/stop")
    assert stop_resp.status_code == 200
    assert stop_resp.json()["status"] == "STOPPED"


# =========================================================================
# SUITE 6: Portfolio Backtester Guardrails Parity
# =========================================================================


def _make_sample_df(n_bars: int = 150, start_price: float = 1.1000) -> pd.DataFrame:
    base_t = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    records = []
    p = start_price
    for i in range(n_bars):
        # Oscillate to generate squeeze and reversion signals
        p += 0.0003 if (i % 8 < 4) else -0.0003
        records.append(
            {
                "timestamp": base_t + timedelta(minutes=i),
                "open": round(p - 0.0001, 5),
                "high": round(p + 0.0004, 5),
                "low": round(p - 0.0004, 5),
                "close": round(p, 5),
                "volume": 150.0,
            }
        )
    return pd.DataFrame(records)


def test_portfolio_backtest_with_correlation_filter():
    """Verifies that correlation filtering in PortfolioBacktestEngine blocks redundant trades."""
    df_eurusd = _make_sample_df(200, 1.1000)
    df_gbpusd = _make_sample_df(200, 1.2500)

    # Config without correlation filter
    cfg_unfiltered = PortfolioBacktestConfig(
        assets=["EURUSD_otc", "GBPUSD_otc"],
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.0"),
        correlation_filter_enabled=False,
        max_concurrent_trades=3,
        strategy_name="hybrid_multifactors",
    )
    engine_unfiltered = PortfolioBacktestEngine(cfg_unfiltered)
    summary_unfiltered = engine_unfiltered.run({"EURUSD_otc": df_eurusd, "GBPUSD_otc": df_gbpusd})

    # Config with correlation filter enabled
    cfg_filtered = PortfolioBacktestConfig(
        assets=["EURUSD_otc", "GBPUSD_otc"],
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.0"),
        correlation_filter_enabled=True,
        max_concurrent_trades=3,
        strategy_name="hybrid_multifactors",
    )
    engine_filtered = PortfolioBacktestEngine(cfg_filtered)
    summary_filtered = engine_filtered.run({"EURUSD_otc": df_eurusd, "GBPUSD_otc": df_gbpusd})

    # Filtered backtest should have <= trades count as unfiltered
    assert summary_filtered.total_trades <= summary_unfiltered.total_trades
    assert summary_filtered.initial_deposit == Decimal("1000.0")


def test_portfolio_backtest_with_settlement_cooldown():
    """Verifies that cooldown_bars prevents immediate re-entries in PortfolioBacktestEngine."""
    df = _make_sample_df(200, 1.1000)

    # 0 cooldown bars
    cfg_no_cooldown = PortfolioBacktestConfig(
        assets=["EURUSD_otc"],
        timeframe_seconds=60,
        cooldown_bars=0,
        strategy_name="hybrid_multifactors",
    )
    sum_no_cd = PortfolioBacktestEngine(cfg_no_cooldown).run({"EURUSD_otc": df})

    # 5 cooldown bars
    cfg_with_cooldown = PortfolioBacktestConfig(
        assets=["EURUSD_otc"],
        timeframe_seconds=60,
        cooldown_bars=5,
        strategy_name="hybrid_multifactors",
    )
    sum_with_cd = PortfolioBacktestEngine(cfg_with_cooldown).run({"EURUSD_otc": df})

    # Cooldown should space out trades and result in <= trades
    assert sum_with_cd.total_trades <= sum_no_cd.total_trades


@pytest.mark.asyncio
async def test_manual_pause_and_resume_lifecycle():
    """Verifies manual pause() and resume() state transitions and signal blocking."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan()
    gateway = AsyncMock()

    await engine.start(plan, gateway)
    assert engine.status == BotStatus.RUNNING
    assert engine.is_running() is True

    # Manual pause
    await engine.pause(duration_seconds=None, reason="manual test")
    assert engine.status == BotStatus.PAUSED
    assert engine.is_paused() is True
    assert engine.paused_until is None

    # When paused, _evaluate_single_asset should not execute any orders
    now = datetime.now(UTC)
    sem = asyncio.Semaphore(1)
    await engine._evaluate_single_asset(plan.assignments[0], now, sem)
    assert len(engine.active_trades) == 0

    # Resume bot
    await engine.resume()
    assert engine.status == BotStatus.RUNNING
    assert engine.is_running() is True
    assert engine.is_paused() is False
    await engine.stop()


def test_portfolio_backtest_drawdown_circuit_breaker_halt():
    """Verifies that max_drawdown_pct_limit halts portfolio backtest early upon drawdown breach."""
    df = _make_sample_df(300, 1.1000)

    cfg_halt = PortfolioBacktestConfig(
        assets=["EURUSD_otc"],
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.0"),
        max_drawdown_pct_limit=Decimal("0.02"),  # 2% max drawdown limit
        strategy_name="hybrid_multifactors",
    )
    summary_halt = PortfolioBacktestEngine(cfg_halt).run({"EURUSD_otc": df})

    cfg_no_halt = PortfolioBacktestConfig(
        assets=["EURUSD_otc"],
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.0"),
        max_drawdown_pct_limit=Decimal("0.50"),  # 50% max drawdown limit
        strategy_name="hybrid_multifactors",
    )
    summary_no_halt = PortfolioBacktestEngine(cfg_no_halt).run({"EURUSD_otc": df})

    # Strict drawdown limit should either match or halt early with <= trades
    assert summary_halt.total_trades <= summary_no_halt.total_trades


def test_portfolio_backtest_consecutive_loss_pause():
    """Verifies consecutive losses circuit breaker pauses trade signals in backtesting."""
    df = _make_sample_df(300, 1.1000)

    cfg_pause = PortfolioBacktestConfig(
        assets=["EURUSD_otc"],
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.0"),
        max_consecutive_losses=2,
        strategy_name="hybrid_multifactors",
    )
    summary_pause = PortfolioBacktestEngine(cfg_pause).run({"EURUSD_otc": df})

    cfg_no_pause = PortfolioBacktestConfig(
        assets=["EURUSD_otc"],
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.0"),
        max_consecutive_losses=0,
        strategy_name="hybrid_multifactors",
    )
    summary_no_pause = PortfolioBacktestEngine(cfg_no_pause).run({"EURUSD_otc": df})

    assert summary_pause.total_trades <= summary_no_pause.total_trades
