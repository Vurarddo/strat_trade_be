from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from strat_trade.domain.entities import Candle
from strat_trade.domain.trading.asset_filter import is_asset_in_active_session
from strat_trade.domain.trading.bot_engine import LiveDemoBotEngine
from strat_trade.domain.trading.entities import (
    BotStatus,
    PreTradingPlan,
    StrategyAssignment,
)
from strat_trade.domain.trading.trade_store import TradeStore


def _make_strategy_assignment(asset: str = "EURUSD_otc") -> StrategyAssignment:
    return StrategyAssignment(
        asset=asset,
        strategy_id="sr_bounce",
        strategy_name="Support & Resistance Pin-Bar",
        category="reversal",
        parameters={"swing_window": 15, "min_wick_ratio": 0.35, "base_expiration_bars": 3},
        estimated_win_rate_pct=60.0,
        estimated_profit_factor=1.8,
        estimated_trades_count=50,
        quantum_score=85.0,
        rationale="Edge",
    )


def _make_plan(
    assets: list[str],
    min_payout: float = 0.80,
    session_filter_enabled: bool = True,
) -> PreTradingPlan:
    assignments = [_make_strategy_assignment(a) for a in assets]
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
        max_concurrent_trades=5,
        min_payout_rate=min_payout,
        cooldown_bars=3,
        global_cooldown_seconds=0,
        max_consecutive_losses=3,
        max_drawdown_pct_limit=0.08,
        correlation_filter_enabled=False,
        pause_duration_minutes=15,
        session_filter_enabled=session_filter_enabled,
    )


def test_is_asset_in_active_session_matrix() -> None:
    """Verifies that each asset category responds accurately across different UTC times."""
    t_night = datetime(2026, 8, 25, 2, 30, tzinfo=UTC)  # 02:30 UTC
    t_day = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)  # 14:00 UTC
    t_rollover = datetime(2026, 8, 25, 22, 30, tzinfo=UTC)  # 22:30 UTC

    # 1. Asian / Pacific pairs
    act, _ = is_asset_in_active_session("AUD/NZD OTC", t_night)
    assert act is True
    act_jpy, _ = is_asset_in_active_session("USD/JPY OTC", t_night)
    assert act_jpy is True

    # 2. European / US spot pairs at night -> Paused
    act_eur, reason_eur = is_asset_in_active_session("EUR/USD", t_night)
    assert act_eur is False
    assert "outside active london/ny session" in reason_eur.lower()

    # European / US spot pairs during London/NY -> Active
    act_eur_day, _ = is_asset_in_active_session("EUR/USD", t_day)
    assert act_eur_day is True

    # The OTC quote of the same pair is broker-synthesised and runs around the
    # clock, so exchange session windows must not gate it.
    act_eur_otc_night, _ = is_asset_in_active_session("EUR/USD OTC", t_night)
    assert act_eur_otc_night is True

    # 3. Exotic nocturnal dead zone (THB, YER, BRL)
    act_thb_night, reason_thb = is_asset_in_active_session("USD/THB OTC", t_night)
    assert act_thb_night is False
    assert "nocturnal" in reason_thb.lower()

    act_thb_day, _ = is_asset_in_active_session("USD/THB OTC", t_day)
    assert act_thb_day is True

    # 4. Commodities
    act_gold_day, _ = is_asset_in_active_session("Gold OTC", t_day)
    assert act_gold_day is True
    act_gold_roll, reason_gold = is_asset_in_active_session("Gold OTC", t_rollover)
    assert act_gold_roll is False
    assert "rollover" in reason_gold.lower()


@pytest.mark.asyncio
async def test_bot_engine_skips_inactive_session_asset() -> None:
    """Verifies that bot engine suppresses trading on assets outside their active session."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    # Spot EUR/USD is inactive at 02:30 UTC (its OTC twin would still be quoted)
    plan = _make_plan(["EURUSD"], session_filter_enabled=True)
    engine.status = BotStatus.RUNNING
    engine.plan = plan

    now_night = datetime(2026, 8, 25, 2, 30, tzinfo=UTC)
    sem = asyncio.Semaphore(1)

    mock_gw = AsyncMock()
    engine._gateway = mock_gw

    await engine._evaluate_single_asset(plan.assignments[0], now_night, sem)

    # get_candles should not even be called because session filter stopped it early
    mock_gw.get_candles.assert_not_called()
    assert len(engine.active_trades) == 0


@pytest.mark.asyncio
async def test_bot_engine_payout_filter() -> None:
    """Verifies that bot engine suppresses trade if live broker payout is below min_payout_rate."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    # Require 80% payout
    plan = _make_plan(["AUDNZD_otc"], min_payout=0.80, session_filter_enabled=False)
    engine.status = BotStatus.RUNNING
    engine.plan = plan

    now = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)
    sem = asyncio.Semaphore(1)

    mock_gw = AsyncMock()
    # Broker only offers 65% payout (below 80% requirement)
    mock_gw.get_asset_payout.return_value = 0.65
    engine._gateway = mock_gw

    await engine._evaluate_single_asset(plan.assignments[0], now, sem)

    # Signal evaluation should not proceed to open trade
    mock_gw.open_trade.assert_not_called()
    assert len(engine.active_trades) == 0


@pytest.mark.asyncio
async def test_bot_engine_microstructure_filter_rejection() -> None:
    """Verifies that bot engine rejects assets with discrete step-tick price data."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_plan(["AUDNZD_otc"], session_filter_enabled=False)
    engine.status = BotStatus.RUNNING
    engine.plan = plan

    now = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)
    sem = asyncio.Semaphore(1)

    mock_gw = AsyncMock()
    mock_gw.get_asset_payout.return_value = 0.92

    # Discrete step candles (repeating prices)
    base_time = now - timedelta(minutes=100)
    discrete_candles = [
        Candle(
            open_time=base_time + timedelta(minutes=i),
            open=Decimal("1.1000"),
            high=Decimal("1.1000"),
            low=Decimal("1.1000"),
            close=Decimal("1.1000"),
            volume=Decimal("10"),
        )
        for i in range(100)
    ]
    mock_gw.get_candles.return_value = discrete_candles
    engine._gateway = mock_gw

    await engine._evaluate_single_asset(plan.assignments[0], now, sem)

    # Trade should be blocked by qualify_asset_microstructure
    mock_gw.open_trade.assert_not_called()
    assert len(engine.active_trades) == 0
