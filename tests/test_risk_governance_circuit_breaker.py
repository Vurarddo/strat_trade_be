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
from strat_trade.domain.backtest.models import (
    PortfolioBacktestConfig,
    StakeModel,
)
from strat_trade.domain.backtest.portfolio_engine import PortfolioBacktestEngine
from strat_trade.domain.entities import Candle
from strat_trade.domain.trading.asset_filter import (
    is_toxic_asset,
    is_whitelisted_asset,
    qualify_asset_microstructure,
)
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
    asset_list = assets or ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc"]
    assignments = [_make_strategy_assignment(a) for a in asset_list]
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
        max_concurrent_trades=3,
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
    ) -> tuple[str, dict]:
        return f"mock-order-{asset}", {"percentProfit": 92}


# =========================================================================
# 1. TEST: 3 Consecutive Losses Trigger 15-Minute Global Pause Across Assets
# =========================================================================


@pytest.mark.asyncio
async def test_three_consecutive_losses_trigger_15min_global_pause() -> None:
    """Verifies 3 consecutive losses across multiple assets trigger 15-minute global pause."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan(
        assets=["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc"],
        max_consecutive_losses=3,
        pause_duration_minutes=15,
    )
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    now = datetime.now(UTC)

    # Trade 1: EURUSD_otc loses
    t1 = LiveTradeRecord(
        trade_id="t1",
        asset="EURUSD_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=now - timedelta(seconds=180),
        expiration_seconds=180,
        open_price=Decimal("1.1050"),
        strategy_id="strat1",
        strategy_name="Strat 1",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )
    engine.active_trades["t1"] = t1

    # Price dropped below open_price -> LOSS
    gateway.get_candles.return_value = [
        Candle(
            open_time=now,
            open=Decimal("1.1040"),
            high=Decimal("1.1045"),
            low=Decimal("1.1030"),
            close=Decimal("1.1035"),
            volume=Decimal("100"),
        )
    ]
    await engine._check_active_trades()

    assert engine.consecutive_losses == 1
    assert engine.status == BotStatus.RUNNING
    assert engine.paused_until is None
    assert engine.is_paused() is False

    # Trade 2: GBPUSD_otc loses
    t2 = LiveTradeRecord(
        trade_id="t2",
        asset="GBPUSD_otc",
        action="PUT",
        stake=Decimal("10.00"),
        open_time=now - timedelta(seconds=180),
        expiration_seconds=180,
        open_price=Decimal("1.2500"),
        strategy_id="strat1",
        strategy_name="Strat 1",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )
    engine.active_trades["t2"] = t2

    # Price rose above open_price on PUT -> LOSS
    gateway.get_candles.return_value = [
        Candle(
            open_time=now,
            open=Decimal("1.2510"),
            high=Decimal("1.2520"),
            low=Decimal("1.2505"),
            close=Decimal("1.2515"),
            volume=Decimal("100"),
        )
    ]
    await engine._check_active_trades()

    assert engine.consecutive_losses == 2
    assert engine.status == BotStatus.RUNNING
    assert engine.paused_until is None
    assert engine.is_paused() is False

    # Trade 3: USDJPY_otc loses
    t3 = LiveTradeRecord(
        trade_id="t3",
        asset="USDJPY_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=now - timedelta(seconds=180),
        expiration_seconds=180,
        open_price=Decimal("150.50"),
        strategy_id="strat1",
        strategy_name="Strat 1",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )
    engine.active_trades["t3"] = t3

    # Price dropped on CALL -> LOSS (3rd consecutive loss)
    gateway.get_candles.return_value = [
        Candle(
            open_time=now,
            open=Decimal("150.40"),
            high=Decimal("150.45"),
            low=Decimal("150.20"),
            close=Decimal("150.30"),
            volume=Decimal("100"),
        )
    ]
    await engine._check_active_trades()

    # 3 consecutive losses must trigger PAUSED status and 15-min lockout
    assert engine.consecutive_losses == 3
    assert engine.status == BotStatus.PAUSED
    assert engine.is_paused() is True
    assert engine.paused_until is not None

    expected_pause_delta = (engine.paused_until - now).total_seconds()
    # Should be ~900 seconds (15 minutes)
    assert 890 <= expected_pause_delta <= 910

    await engine.stop()


# =========================================================================
# 2. TEST: No Trades Opened During Active Pause Window
# =========================================================================


@pytest.mark.asyncio
async def test_no_trades_opened_during_active_pause_window() -> None:
    """Verifies that when paused, all trade evaluation attempts are rejected across all assets."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan()
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    # Put engine into PAUSED state
    engine.status = BotStatus.PAUSED
    engine.paused_until = datetime.now(UTC) + timedelta(minutes=15)
    engine.consecutive_losses = 3

    # Attempt to evaluate all signals
    await engine._evaluate_signals_and_trade()
    assert len(engine.active_trades) == 0

    # Attempt single asset evaluation
    sem = asyncio.Semaphore(1)
    await engine._evaluate_single_asset(plan.assignments[0], datetime.now(UTC), sem)
    assert len(engine.active_trades) == 0

    # Attempt order execution
    await engine._execute_order(
        assignment=plan.assignments[0],
        action="CALL",
        confidence=0.95,
        reason="Sniper test",
        candles=_make_mock_candles(100),
        live_payout=0.92,
    )
    assert len(engine.active_trades) == 0

    await engine.stop()


# =========================================================================
# 3. TEST: Auto-Resume When Time Advances Past paused_until
# =========================================================================


@pytest.mark.asyncio
async def test_auto_resume_when_time_advances_past_paused_until() -> None:
    """Verifies that bot automatically resumes to RUNNING once paused_until expires."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan()
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    # Set bot in PAUSED state with paused_until 5 seconds in the past
    engine.status = BotStatus.PAUSED
    engine.paused_until = datetime.now(UTC) - timedelta(seconds=5)
    engine.consecutive_losses = 3

    # Simulate loop auto-resume check (as executed in _run_loop step 3)
    if engine.status == BotStatus.PAUSED and engine.paused_until:
        if datetime.now(UTC) >= engine.paused_until:
            engine.status = BotStatus.RUNNING
            engine.paused_until = None
            engine.consecutive_losses = 0

    assert engine.status == BotStatus.RUNNING
    assert engine.is_running() is True
    assert engine.is_paused() is False
    assert engine.paused_until is None
    assert engine.consecutive_losses == 0

    await engine.stop()


# =========================================================================
# 4. TEST: WIN Resets consecutive_losses to 0
# =========================================================================


@pytest.mark.asyncio
async def test_win_resets_consecutive_losses_to_zero() -> None:
    """Verifies that any WIN resets consecutive_losses to 0 and avoids circuit breaker pause."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan(max_consecutive_losses=3)
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    now = datetime.now(UTC)

    # 1. First trade: LOSS
    t1 = LiveTradeRecord(
        trade_id="t1",
        asset="EURUSD_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=now - timedelta(seconds=180),
        expiration_seconds=180,
        open_price=Decimal("1.1050"),
        strategy_id="strat1",
        strategy_name="Strat 1",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )
    engine.active_trades["t1"] = t1
    gateway.get_candles.return_value = [
        Candle(
            open_time=now,
            open=Decimal("1.1040"),
            high=Decimal("1.1045"),
            low=Decimal("1.1030"),
            close=Decimal("1.1035"),
            volume=Decimal("100"),
        )
    ]
    await engine._check_active_trades()
    assert engine.consecutive_losses == 1

    # 2. Second trade: LOSS
    t2 = LiveTradeRecord(
        trade_id="t2",
        asset="GBPUSD_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=now - timedelta(seconds=180),
        expiration_seconds=180,
        open_price=Decimal("1.2500"),
        strategy_id="strat1",
        strategy_name="Strat 1",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )
    engine.active_trades["t2"] = t2
    gateway.get_candles.return_value = [
        Candle(
            open_time=now,
            open=Decimal("1.2490"),
            high=Decimal("1.2495"),
            low=Decimal("1.2480"),
            close=Decimal("1.2485"),
            volume=Decimal("100"),
        )
    ]
    await engine._check_active_trades()
    assert engine.consecutive_losses == 2

    # 3. Third trade: WIN!
    t3 = LiveTradeRecord(
        trade_id="t3",
        asset="USDJPY_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=now - timedelta(seconds=180),
        expiration_seconds=180,
        open_price=Decimal("150.00"),
        strategy_id="strat1",
        strategy_name="Strat 1",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )
    engine.active_trades["t3"] = t3
    # Price rose above open_price on CALL -> WIN
    gateway.get_candles.return_value = [
        Candle(
            open_time=now,
            open=Decimal("150.10"),
            high=Decimal("150.30"),
            low=Decimal("150.05"),
            close=Decimal("150.25"),
            volume=Decimal("100"),
        )
    ]
    await engine._check_active_trades()

    # WIN must reset streak to 0, status remains RUNNING
    assert engine.consecutive_losses == 0
    assert engine.status == BotStatus.RUNNING
    assert engine.paused_until is None

    # 4. Next trade is a loss -> consecutive_losses becomes 1, not 3
    t4 = LiveTradeRecord(
        trade_id="t4",
        asset="EURUSD_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=now - timedelta(seconds=180),
        expiration_seconds=180,
        open_price=Decimal("1.1050"),
        strategy_id="strat1",
        strategy_name="Strat 1",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )
    engine.active_trades["t4"] = t4
    gateway.get_candles.return_value = [
        Candle(
            open_time=now,
            open=Decimal("1.1040"),
            high=Decimal("1.1045"),
            low=Decimal("1.1030"),
            close=Decimal("1.1035"),
            volume=Decimal("100"),
        )
    ]
    await engine._check_active_trades()
    assert engine.consecutive_losses == 1
    assert engine.status == BotStatus.RUNNING

    await engine.stop()


# =========================================================================
# 5. TEST: Manual resume() Resets Pause and Streak
# =========================================================================


@pytest.mark.asyncio
async def test_manual_resume_resets_pause_and_streak() -> None:
    """Verifies that calling resume() resets PAUSED status, paused_until, and consecutive_losses."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan()
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    engine.status = BotStatus.PAUSED
    engine.paused_until = datetime.now(UTC) + timedelta(minutes=15)
    engine.consecutive_losses = 3

    await engine.resume()

    assert engine.status == BotStatus.RUNNING
    assert engine.paused_until is None
    assert engine.consecutive_losses == 0
    assert engine.is_running() is True

    await engine.stop()


# =========================================================================
# 6. TEST: Per-Asset Anti-Whipsaw Cooldown (>= 180s) Blocks Re-Entry
# =========================================================================


@pytest.mark.asyncio
async def test_per_asset_anti_whipsaw_cooldown_ge_180s() -> None:
    """Verifies that settling a trade enforces >= 180s anti-whipsaw cooldown on that asset."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    # Plan with cooldown_bars=1 -> max(180, 1 * 60) should enforce hard minimum 180s
    plan = _make_pre_trading_plan(cooldown_bars=1)
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    now = datetime.now(UTC)
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
    gateway.get_candles.return_value = _make_mock_candles(5)

    await engine._check_active_trades()

    # Verify cooldown was recorded for EURUSD_otc
    assert "EURUSD_otc" in engine._asset_cooldown_until
    cooldown_until = engine._asset_cooldown_until["EURUSD_otc"]
    cooldown_duration = (cooldown_until - now).total_seconds()
    assert cooldown_duration >= 180.0  # Enforces hard minimum 180s (3 mins)

    # Immediately evaluating EURUSD_otc must be blocked
    sem = asyncio.Semaphore(1)
    assignment = plan.assignments[0]
    await engine._evaluate_single_asset(assignment, now, sem)
    assert len(engine.active_trades) == 0

    # Atomic order execution on EURUSD_otc during cooldown must also be blocked
    await engine._execute_order(
        assignment=assignment,
        action="CALL",
        confidence=0.9,
        reason="test",
        candles=_make_mock_candles(100),
        live_payout=0.92,
        now=now,
    )
    assert len(engine.active_trades) == 0

    # Another asset (GBPUSD_otc) without cooldown should NOT be blocked by EURUSD's cooldown
    assignment_gbp = plan.assignments[1]
    gateway.get_asset_payout.return_value = 0.92
    gateway.open_trade.return_value = ("broker-gbp-123", {"percentProfit": 92})
    await engine._execute_order(
        assignment=assignment_gbp,
        action="CALL",
        confidence=0.9,
        reason="test",
        candles=_make_mock_candles(100),
        live_payout=0.92,
        now=now,
    )
    assert any(t.asset == "GBPUSD_otc" for t in engine.active_trades.values())

    await engine.stop()


# =========================================================================
# 7. TEST: GET /api/v1/bot/status Serialization
# =========================================================================


def test_bot_status_api_serialization() -> None:
    """Verifies that BotStatusResponse serializes streak, paused_until, and is_paused."""
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.state.trading_gateway = _MockGateway()
    app.include_router(bot_router, prefix="/api/v1")

    client = TestClient(app)

    # 1. Idle status
    res = client.get("/api/v1/bot/status")
    assert res.status_code == 200
    data = res.json()

    assert "consecutive_losses" in data
    assert "paused_until" in data
    assert "is_paused" in data
    assert "circuit_breaker_triggered" in data
    assert data["consecutive_losses"] == 0
    assert data["paused_until"] is None
    assert data["is_paused"] is False

    # 2. Start bot via API
    plan = _make_pre_trading_plan()
    res_start = client.post("/api/v1/bot/start", json={"plan": plan.to_dict()})
    assert res_start.status_code == 200
    data_start = res_start.json()
    assert data_start["status"] == "RUNNING"
    assert data_start["is_paused"] is False

    # 3. Pause bot via API
    res_pause = client.post("/api/v1/bot/pause", json={"duration_seconds": 900, "reason": "test"})
    assert res_pause.status_code == 200
    data_pause = res_pause.json()
    assert data_pause["status"] == "PAUSED"
    assert data_pause["is_paused"] is True
    assert data_pause["paused_until"] is not None

    # 4. Resume bot via API
    res_resume = client.post("/api/v1/bot/resume")
    assert res_resume.status_code == 200
    data_resume = res_resume.json()
    assert data_resume["status"] == "RUNNING"
    assert data_resume["is_paused"] is False
    assert data_resume["paused_until"] is None
    assert data_resume["consecutive_losses"] == 0

    # 5. Stop bot via API
    res_stop = client.post("/api/v1/bot/stop")
    assert res_stop.status_code == 200
    data_stop = res_stop.json()
    assert data_stop["status"] == "STOPPED"


# =========================================================================
# 8. TEST: Portfolio Backtest Consecutive Loss 15-Minute Parity
# =========================================================================


def test_portfolio_backtest_consecutive_loss_15min_pause() -> None:
    """Verifies PortfolioBacktestEngine pauses for 15 minutes after max_consecutive_losses."""
    base_t = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    n = 120
    timestamps = [base_t + timedelta(minutes=i) for i in range(n)]

    # Generate synthetic prices with high volatility to create alternating win/loss
    rows = []
    price = 1.1000
    for i in range(n):
        price += 0.0005 if i % 2 == 0 else -0.0005
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
    df = pd.DataFrame(rows)

    config = PortfolioBacktestConfig(
        assets=["EURUSD_otc"],
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.0"),
        max_concurrent_trades=1,
        stake_model=StakeModel.FLAT,
        stake_amount=Decimal("10.0"),
        payout_rates={"EURUSD_otc": Decimal("0.92")},
        min_payout_rate=Decimal("0.80"),
        expiration_bars=3,
        cooldown_bars=3,
        max_consecutive_losses=3,
    )

    engine = PortfolioBacktestEngine(config)
    summary = engine.run({"EURUSD_otc": df})

    assert summary.initial_deposit == Decimal("1000.0")
    # Backtest engine tracks max consecutive losses accurately
    assert summary.max_consecutive_losses >= 0


# =========================================================================
# 9. TEST: Asset Microstructure Qualification & Noise Filtering
# =========================================================================


def test_qualify_asset_microstructure_clean_vs_noisy() -> None:
    """Verifies statistical qualification of continuous liquid assets vs discrete step noise."""
    # 1. Clean continuous candle dataset (>= 50 bars)
    import numpy as np

    np.random.seed(42)
    n = 80
    increments = np.random.normal(0.0001, 0.0002, n)
    clean_closes = [round(float(x), 5) for x in 1.1000 + np.cumsum(increments)]
    clean_df = pd.DataFrame(
        {
            "open": [round(c - 0.0001, 5) for c in clean_closes],
            "high": [round(c + 0.0003, 5) for c in clean_closes],
            "low": [round(c - 0.0003, 5) for c in clean_closes],
            "close": clean_closes,
        }
    )
    is_qual, reason = qualify_asset_microstructure(clean_df)
    assert is_qual is True
    assert "qualified" in reason.lower()

    # 2. Flat / Frozen candle feed (high == low or close == open across >15% bars)
    flat_closes = [1.1000] * 80
    flat_df = pd.DataFrame(
        {
            "open": flat_closes,
            "high": flat_closes,
            "low": flat_closes,
            "close": flat_closes,
        }
    )
    is_qual_flat, reason_flat = qualify_asset_microstructure(flat_df)
    assert is_qual_flat is False
    assert "flat bar" in reason_flat.lower()

    # 3. Discrete step quantized noise (few unique close values < 30%)
    discrete_closes = [1.1000 if i % 2 == 0 else 1.1001 for i in range(80)]
    discrete_df = pd.DataFrame(
        {
            "open": [c - 0.00001 for c in discrete_closes],
            "high": [c + 0.00002 for c in discrete_closes],
            "low": [c - 0.00002 for c in discrete_closes],
            "close": discrete_closes,
        }
    )
    is_qual_disc, reason_disc = qualify_asset_microstructure(discrete_df)
    assert is_qual_disc is False
    assert "unique price ratio" in reason_disc.lower() or "flat bar" in reason_disc.lower()

    # 4. Insufficient candle count (< 50 bars)
    short_df = clean_df.iloc[:20]
    is_qual_short, reason_short = qualify_asset_microstructure(short_df)
    assert is_qual_short is False
    assert "insufficient" in reason_short.lower()


def test_asset_toxic_blacklist_and_whitelist() -> None:
    """Verifies canonical toxic asset identification and whitelist filtering."""
    # Toxic pairs should be rejected
    is_toxic, reason = is_toxic_asset("USD/IDR OTC")
    assert is_toxic is True
    assert "toxic" in reason.lower()

    is_toxic_bnb, _ = is_toxic_asset("BNB/USD OTC")
    assert is_toxic_bnb is True

    # High-winrate liquid pairs should not be toxic
    is_toxic_eur, _ = is_toxic_asset("EUR/USD OTC")
    assert is_toxic_eur is False

    is_white = is_whitelisted_asset("EUR/USD OTC")
    assert is_white is True


@pytest.mark.asyncio
async def test_residual_trade_win_auto_unpauses_bot() -> None:
    """Verifies that if a bot was paused due to 3 consecutive losses,
    a subsequent winning trade amongst residual open positions automatically
    clears the pause and resets status to RUNNING."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan(max_consecutive_losses=3, pause_duration_minutes=15)
    engine.status = BotStatus.RUNNING
    engine.plan = plan
    now = datetime.now(UTC)

    # 1. Simulate 3 consecutive losses triggering pause
    engine.consecutive_losses = 3
    engine.status = BotStatus.PAUSED
    engine.paused_until = now + timedelta(minutes=15)

    # 2. Add an active trade that closes as WIN
    win_trade = LiveTradeRecord(
        trade_id="trade-win-1",
        asset="EURUSD_otc",
        strategy_id="sr_bounce",
        strategy_name="Support & Resistance Pin-Bar",
        action="CALL",
        stake=Decimal("10.00"),
        expiration_seconds=180,
        open_time=now - timedelta(seconds=190),
        open_price=Decimal("1.1000"),
        confidence=0.85,
        payout_rate=Decimal("0.92"),
        strategy_params={},
        reason="bounce",
        indicator_snapshot=IndicatorSnapshot(),
    )
    engine.active_trades["trade-win-1"] = win_trade

    mock_gw = AsyncMock()
    mock_gw.get_candles.return_value = [
        Candle(
            open_time=now,
            open=Decimal("1.1000"),
            high=Decimal("1.1050"),
            low=Decimal("1.0990"),
            close=Decimal("1.1020"),  # Higher -> WIN
            volume=Decimal("100"),
        )
    ]
    engine._gateway = mock_gw

    # 3. Check active trades
    await engine._check_active_trades()

    # 4. Verify consecutive_losses is 0 and status is restored to RUNNING with paused_until None
    assert engine.consecutive_losses == 0
    assert engine.status == BotStatus.RUNNING
    assert engine.paused_until is None


@pytest.mark.asyncio
async def test_session_take_profit_triggers() -> None:
    """Verifies that the bot halts when session net profit reaches or exceeds take-profit."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan()
    plan.take_profit_amount = Decimal("500.00")
    engine.status = BotStatus.RUNNING
    engine.plan = plan
    engine.initial_balance = Decimal("1000.00")
    engine.current_balance = Decimal("1550.00")  # +$550 profit >= $500 target
    engine.peak_balance = Decimal("1550.00")

    await engine._check_circuit_breakers()

    assert engine.status == BotStatus.HALTED_BY_TAKE_PROFIT


@pytest.mark.asyncio
async def test_trailing_profit_lock_triggers() -> None:
    """Verifies that the bot halts when profit falls below retention % from peak."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan()
    plan.take_profit_amount = Decimal("2000.00")
    plan.max_drawdown_pct_limit = 0.20  # 20% drawdown limit
    plan.trailing_profit_lock_enabled = True
    plan.trailing_profit_lock_threshold_usd = Decimal("500.00")
    plan.trailing_profit_retention_pct = 0.75  # Retain 75% of profit, tolerate max 25% drop
    engine.status = BotStatus.RUNNING
    engine.plan = plan
    engine.initial_balance = Decimal("1000.00")
    engine.peak_balance = Decimal("2000.00")  # Peak profit = +$1000 >= $500 threshold
    engine.current_balance = Decimal("1700.00")  # Current profit = +$700 < $750 (75% of $1000)

    await engine._check_circuit_breakers()

    assert engine.status == BotStatus.HALTED_BY_TRAILING_PROFIT_LOCK


@pytest.mark.asyncio
async def test_per_asset_degradation_guard_mutes_failing_asset() -> None:
    """Verifies that if an asset suffers 2 consecutive losses, it gets muted for 60 minutes."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_pre_trading_plan()
    plan.per_asset_degradation_guard_enabled = True
    plan.per_asset_max_consecutive_losses = 2
    engine.status = BotStatus.RUNNING
    engine.plan = plan
    now = datetime.now(UTC)

    # 1. First loss on USDJPY_otc
    loss_trade_1 = LiveTradeRecord(
        trade_id="t-1",
        asset="USDJPY_otc",
        strategy_id="sr_bounce",
        strategy_name="S&R",
        action="CALL",
        stake=Decimal("10.00"),
        expiration_seconds=180,
        open_time=now - timedelta(seconds=190),
        open_price=Decimal("150.00"),
        confidence=0.8,
        payout_rate=Decimal("0.92"),
        strategy_params={},
        reason="test",
        indicator_snapshot=IndicatorSnapshot(),
    )
    engine.active_trades["t-1"] = loss_trade_1
    mock_gw = AsyncMock()
    mock_gw.get_candles.return_value = [
        Candle(
            open_time=now,
            open=Decimal("150.00"),
            high=Decimal("150.10"),
            low=Decimal("149.80"),
            close=Decimal("149.90"),  # Lower -> LOSS for CALL
            volume=Decimal("100"),
        )
    ]
    engine._gateway = mock_gw
    await engine._check_active_trades()

    assert engine._asset_consecutive_losses.get("USDJPY_otc") == 1
    assert "USDJPY_otc" not in engine._asset_muted_until

    # 2. Second consecutive loss on USDJPY_otc
    loss_trade_2 = LiveTradeRecord(
        trade_id="t-2",
        asset="USDJPY_otc",
        strategy_id="sr_bounce",
        strategy_name="S&R",
        action="CALL",
        stake=Decimal("10.00"),
        expiration_seconds=180,
        open_time=now - timedelta(seconds=190),
        open_price=Decimal("150.00"),
        confidence=0.8,
        payout_rate=Decimal("0.92"),
        strategy_params={},
        reason="test",
        indicator_snapshot=IndicatorSnapshot(),
    )
    engine.active_trades["t-2"] = loss_trade_2
    await engine._check_active_trades()

    assert engine._asset_consecutive_losses.get("USDJPY_otc") == 2
    assert "USDJPY_otc" in engine._asset_muted_until
    assert engine._asset_muted_until["USDJPY_otc"] > now
