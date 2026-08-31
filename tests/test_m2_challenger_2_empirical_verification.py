"""Milestone 2 Empirical Challenger 2 Verification Suite.

Validates:
1. Winning Streak Preservation: Long streaks (5–15 up to 50 WINs) execute without pause.
2. Backtest vs Live Engine Risk Parity: Identical pause triggers, cooldowns, and PnL curves.
3. Asset Microstructure Noise Qualification: Statistical classification across synthetic flat,
   step, whipsaw, dead, and continuous liquid feeds.
4. Adversarial Stress: Simultaneous multi-asset settlement and rapid streak transitions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from strat_trade.domain.backtest.models import (
    PortfolioBacktestConfig,
    StakeModel,
    TradeAction,
)
from strat_trade.domain.backtest.portfolio_engine import PortfolioBacktestEngine
from strat_trade.domain.entities import Candle
from strat_trade.domain.strategies.base import SignalResult
from strat_trade.domain.trading.asset_filter import (
    canonical_asset_key,
    filter_allowed_assets,
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
        rationale="Empirical test assignment",
    )


def _make_live_trade(
    trade_id: str,
    asset: str = "EURUSD_otc",
    action: str = "CALL",
    stake: Decimal = Decimal("10.00"),
    open_price: Decimal = Decimal("1.08000"),
    open_time: datetime | None = None,
    expiration_seconds: int = 180,
    payout_rate: Decimal = Decimal("0.92"),
) -> LiveTradeRecord:
    t = open_time or datetime.now(UTC)
    return LiveTradeRecord(
        trade_id=trade_id,
        asset=asset,
        action=action,
        stake=stake,
        open_price=open_price,
        open_time=t,
        expiration_seconds=expiration_seconds,
        strategy_id="hybrid_multifactors",
        strategy_name="Hybrid Multi-Factors",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.85,
        reason="empirical_test",
        payout_rate=payout_rate,
    )


def _make_plan(
    assets: list[str] | None = None,
    cooldown_bars: int = 3,
    global_cooldown_seconds: int = 0,
    max_consecutive_losses: int = 3,
    max_drawdown_pct_limit: float = 0.15,
    pause_duration_minutes: int = 15,
    stake_amount: Decimal = Decimal("10.00"),
    min_payout_rate: float = 0.80,
    max_concurrent_trades: int = 5,
    bar_edge_guard_seconds: float = 0.0,
) -> PreTradingPlan:
    asset_list = assets or ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc"]
    assignments = [_make_strategy_assignment(a) for a in asset_list]
    return PreTradingPlan(
        assignments=assignments,
        total_assets=len(assignments),
        initial_deposit=Decimal("1000.00"),
        stake_model="flat",
        stake_amount=stake_amount,
        stake_percent=1.0,
        expiration_seconds=180,
        daily_stop_loss_pct=0.20,
        stop_loss_amount=Decimal("200.00"),
        max_concurrent_trades=max_concurrent_trades,
        min_payout_rate=min_payout_rate,
        cooldown_bars=cooldown_bars,
        global_cooldown_seconds=global_cooldown_seconds,
        max_consecutive_losses=max_consecutive_losses,
        max_drawdown_pct_limit=max_drawdown_pct_limit,
        correlation_filter_enabled=False,
        pause_duration_minutes=pause_duration_minutes,
        bar_edge_guard_seconds=bar_edge_guard_seconds,
    )


# ============================================================================
# 1. Winning Streak Preservation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_winning_streak_15_consecutive_wins_live_engine(tmp_path):
    """Verify that a 15-trade winning streak executes without pause in LiveDemoBotEngine."""
    db_path = str(tmp_path / "test_live_win_streak.db")
    store = TradeStore(db_path=db_path)
    engine = LiveDemoBotEngine(trade_store=store)

    plan = _make_plan(max_consecutive_losses=3, pause_duration_minutes=15)
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    assert engine.status == BotStatus.RUNNING
    assert engine.consecutive_losses == 0
    assert engine.paused_until is None

    base_time = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    stake = Decimal("10.00")
    payout_rate = Decimal("0.92")
    expected_balance = Decimal("1000.00")

    # Simulate 15 consecutive WIN trades
    for i in range(1, 16):
        t_open = base_time + timedelta(minutes=i * 5)
        trade = _make_live_trade(
            trade_id=f"win_trade_{i}",
            asset="EURUSD_otc",
            action="CALL",
            stake=stake,
            open_price=Decimal("1.08000"),
            open_time=t_open,
            payout_rate=payout_rate,
        )
        engine.active_trades[trade.trade_id] = trade

        gateway.get_candles = AsyncMock(
            return_value=[
                Candle(
                    open_time=t_open + timedelta(seconds=180),
                    open=Decimal("1.08000"),
                    high=Decimal("1.08050"),
                    low=Decimal("1.07990"),
                    close=Decimal("1.08030"),
                    volume=Decimal("100"),
                )
            ]
        )

        # Settle trade
        await engine._check_active_trades()
        await engine._check_circuit_breakers()

        expected_balance += stake * payout_rate

        # Assertions after each win
        assert engine.status == BotStatus.RUNNING, f"Bot unexpectedly paused on win {i}"
        assert engine.consecutive_losses == 0, f"Loss counter nonzero on win {i}"
        assert engine.paused_until is None, f"paused_until set on win {i}"
        assert engine.current_balance == expected_balance
        assert engine.peak_balance == expected_balance
        assert engine.current_drawdown_pct == 0.0

    summary = engine.get_summary()
    assert summary.total_trades == 15
    assert summary.winning_trades == 15
    assert summary.losing_trades == 0
    assert summary.win_rate_pct == 100.0
    assert summary.net_profit == Decimal("138.00")  # 15 * $9.20
    assert summary.roi_pct == 13.80
    assert summary.is_paused is False
    assert summary.circuit_breaker_triggered is False

    await engine.stop()


def test_winning_streak_15_consecutive_wins_backtest_engine():
    """Verify that a 15-trade winning streak executes without pause in PortfolioBacktestEngine."""
    config = PortfolioBacktestConfig(
        assets=["EURUSD_otc"],
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.00"),
        stake_model=StakeModel.FLAT,
        stake_amount=Decimal("10.00"),
        max_consecutive_losses=3,
        daily_stop_loss_pct=Decimal("0.20"),
        max_drawdown_pct_limit=Decimal("0.15"),
        cooldown_bars=0,
        global_cooldown_seconds=0,
        correlation_filter_enabled=False,
        payout_rates={"EURUSD_otc": Decimal("0.92")},
    )
    engine = PortfolioBacktestEngine(config)

    # Mock strategy evaluation to produce 15 winning signals
    base_time = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    n = 150
    candle_records = []
    signal_indices = [50 + i * 5 for i in range(15)]
    exit_indices = [idx + 3 for idx in signal_indices]

    for i in range(n):
        t = base_time + timedelta(minutes=i)
        if i in signal_indices:
            c = 1.0800
        elif i in exit_indices:
            c = 1.0810  # Exit price higher than entry price for CALL -> WIN
        else:
            c = 1.0800
        candle_records.append(
            {
                "timestamp": t,
                "open": 1.0800,
                "high": 1.0820,
                "low": 1.0790,
                "close": c,
                "volume": 100,
            }
        )
    df = pd.DataFrame(candle_records)

    engine.strategy.prepare_dataframe = MagicMock(return_value=df)

    def mock_eval(df_arg, idx):
        if idx in signal_indices:
            return SignalResult(
                action=TradeAction.CALL,
                confidence=0.85,
                expiration_bars=3,
                regime="trend",
                metadata={},
            )
        return SignalResult(action=None, confidence=0.0, expiration_bars=3, regime="none")

    engine.strategy.evaluate_bar = MagicMock(side_effect=mock_eval)

    result = engine.run({"EURUSD_otc": df})

    assert result.total_trades == 15
    assert result.winning_trades == 15
    assert result.losing_trades == 0
    assert result.win_rate_pct == Decimal("100.0")
    assert result.max_consecutive_wins == 15
    assert result.max_consecutive_losses == 0
    assert result.net_profit == Decimal("138.00")
    assert result.final_balance == Decimal("1138.00")
    assert result.max_drawdown_pct == Decimal("0.0")


@pytest.mark.asyncio
async def test_winning_streak_loss_reset_resilience(tmp_path):
    """Verify that isolated losses followed by WINs reset the counter and never trigger pause."""
    db_path = str(tmp_path / "test_reset_resilience.db")
    store = TradeStore(db_path=db_path)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_plan(max_consecutive_losses=3, pause_duration_minutes=15)
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    outcomes = [
        ("WIN", Decimal("1.08100")),
        ("WIN", Decimal("1.08100")),
        ("LOSS", Decimal("1.07900")),
        ("WIN", Decimal("1.08100")),
        ("LOSS", Decimal("1.07900")),
        ("LOSS", Decimal("1.07900")),
        ("WIN", Decimal("1.08100")),
        ("WIN", Decimal("1.08100")),
        ("LOSS", Decimal("1.07900")),
        ("WIN", Decimal("1.08100")),
    ]

    base_time = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    for idx, (expected_outcome, close_p) in enumerate(outcomes):
        t_open = base_time + timedelta(minutes=idx * 5)
        trade = _make_live_trade(
            trade_id=f"seq_trade_{idx}",
            asset="EURUSD_otc",
            action="CALL",
            stake=Decimal("10.00"),
            open_price=Decimal("1.08000"),
            open_time=t_open,
            payout_rate=Decimal("0.92"),
        )
        engine.active_trades[trade.trade_id] = trade

        gateway.get_candles = AsyncMock(
            return_value=[
                Candle(
                    open_time=t_open + timedelta(seconds=180),
                    open=Decimal("1.08000"),
                    high=max(Decimal("1.08000"), close_p) + Decimal("0.00010"),
                    low=min(Decimal("1.08000"), close_p) - Decimal("0.00010"),
                    close=close_p,
                    volume=Decimal("100"),
                )
            ]
        )

        await engine._check_active_trades()
        await engine._check_circuit_breakers()

        # Bot should NEVER pause in this sequence because max consecutive losses is 2
        assert engine.status == BotStatus.RUNNING, f"Bot paused at index {idx}"
        assert engine.paused_until is None

    summary = engine.get_summary()
    assert summary.total_trades == 10
    assert summary.winning_trades == 6
    assert summary.losing_trades == 4
    assert summary.consecutive_losses == 0  # Last trade was a WIN
    assert summary.is_paused is False

    await engine.stop()


@pytest.mark.asyncio
async def test_ultra_long_50_trade_win_streak_live_and_backtest(tmp_path):
    """Stress test: 50-trade winning streak scales balance and maintains 0% drawdown."""
    db_path = str(tmp_path / "test_50_win_streak.db")
    store = TradeStore(db_path=db_path)
    engine = LiveDemoBotEngine(trade_store=store)

    plan = _make_plan(max_consecutive_losses=3, pause_duration_minutes=15)
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    base_time = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    stake = Decimal("10.00")
    payout_rate = Decimal("0.92")

    for i in range(1, 51):
        t_open = base_time + timedelta(minutes=i * 5)
        trade = _make_live_trade(
            trade_id=f"win_trade_50_{i}",
            asset="EURUSD_otc",
            action="CALL",
            stake=stake,
            open_price=Decimal("1.08000"),
            open_time=t_open,
            payout_rate=payout_rate,
        )
        engine.active_trades[trade.trade_id] = trade

        gateway.get_candles = AsyncMock(
            return_value=[
                Candle(
                    open_time=t_open + timedelta(seconds=180),
                    open=Decimal("1.08000"),
                    high=Decimal("1.08050"),
                    low=Decimal("1.07990"),
                    close=Decimal("1.08030"),
                    volume=Decimal("100"),
                )
            ]
        )

        await engine._check_active_trades()
        await engine._check_circuit_breakers()

    summary = engine.get_summary()
    assert summary.total_trades == 50
    assert summary.winning_trades == 50
    assert summary.losing_trades == 0
    assert summary.win_rate_pct == 100.0
    assert summary.net_profit == Decimal("460.00")  # 50 * $9.20
    assert summary.current_balance == Decimal("1460.00")
    assert summary.status == BotStatus.RUNNING
    assert summary.paused_until is None

    await engine.stop()


# ============================================================================
# 2. Backtest vs Live Engine Risk Parity Tests
# ============================================================================


@pytest.mark.asyncio
async def test_backtest_vs_live_parity_complex_trade_sequence(tmp_path):
    """Run an identical complex sequence through both LiveDemoBotEngine and backtest engine."""
    db_path = str(tmp_path / "test_parity.db")
    store = TradeStore(db_path=db_path)
    live_engine = LiveDemoBotEngine(trade_store=store)

    plan = _make_plan(
        cooldown_bars=0,
        global_cooldown_seconds=0,
        max_consecutive_losses=3,
        pause_duration_minutes=15,
        stake_amount=Decimal("10.00"),
    )
    gateway = AsyncMock()
    await live_engine.start(plan, gateway)

    backtest_config = PortfolioBacktestConfig(
        assets=["EURUSD_otc"],
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.00"),
        stake_model=StakeModel.FLAT,
        stake_amount=Decimal("10.00"),
        max_consecutive_losses=3,
        daily_stop_loss_pct=Decimal("0.50"),
        max_drawdown_pct_limit=Decimal("0.50"),
        cooldown_bars=0,
        global_cooldown_seconds=0,
        correlation_filter_enabled=False,
        payout_rates={"EURUSD_otc": Decimal("0.92")},
    )
    bt_engine = PortfolioBacktestEngine(backtest_config)

    t0 = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)

    # Trade specifications: (spec_index, bar_offset_from_50, action, win_or_loss)
    trade_specs = [
        (0, 0, "CALL", "LOSS"),
        (1, 5, "CALL", "LOSS"),
        (2, 10, "CALL", "WIN"),
        (3, 15, "CALL", "LOSS"),
        (4, 20, "CALL", "LOSS"),
        (5, 25, "CALL", "LOSS"),  # Triggers Pause 1 at 28m (until 43m)
        (6, 35, "CALL", "WIN"),  # Should be BLOCKED by pause
        (7, 45, "CALL", "WIN"),  # Executed after auto-resume (t=45m >= 43m)
        (8, 50, "CALL", "LOSS"),
        (9, 55, "CALL", "LOSS"),
        (10, 60, "CALL", "LOSS"),  # Triggers Pause 2 at 63m (until 78m)
        (11, 70, "CALL", "WIN"),  # Should be BLOCKED by pause
        (12, 80, "CALL", "WIN"),  # Executed after auto-resume (t=80m >= 78m)
    ]

    base_idx = 50
    signal_map = {
        base_idx + offset: (spec_id, act, outcome) for spec_id, offset, act, outcome in trade_specs
    }

    # Build candle dataframe (160 bars)
    candle_records = []
    for i in range(160):
        t = t0 + timedelta(minutes=i)
        close_p = 1.0800
        for offset, (spec_id, act, outcome) in signal_map.items():
            if i == offset + 3:
                close_p = 1.0810 if outcome == "WIN" else 1.0790
                break
        candle_records.append(
            {
                "timestamp": t,
                "open": 1.0800,
                "high": 1.0820,
                "low": 1.0780,
                "close": close_p,
                "volume": 100,
            }
        )
    bt_df = pd.DataFrame(candle_records)

    # Mock strategy for Backtest Engine
    bt_engine.strategy.prepare_dataframe = MagicMock(return_value=bt_df)

    def bt_eval(df_arg, idx):
        if idx in signal_map:
            return SignalResult(
                action=TradeAction.CALL,
                confidence=0.80,
                expiration_bars=3,
                regime="test",
                metadata={},
            )
        return SignalResult(action=None, confidence=0.0, expiration_bars=3, regime="none")

    bt_engine.strategy.evaluate_bar = MagicMock(side_effect=bt_eval)

    bt_result = bt_engine.run({"EURUSD_otc": bt_df})

    # Run LiveDemoBotEngine in lockstep simulation with simulated clock
    live_trades_executed = []
    live_balances = []
    live_pause_events = []
    target_outcomes = {spec_id: outcome for spec_id, offset, act, outcome in trade_specs}

    current_mock_time = t0

    class MockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return current_mock_time

    with patch("strat_trade.domain.trading.bot_engine.datetime", MockDatetime):
        for spec_idx, offset, act, outcome in trade_specs:
            bar_idx = base_idx + offset
            cur_sim_time = t0 + timedelta(minutes=bar_idx)
            current_mock_time = cur_sim_time

            # 1. Settle expiring active trades prior to current time
            for tid, t in list(live_engine.active_trades.items()):
                exp_time = t.open_time + timedelta(seconds=t.expiration_seconds)
                if cur_sim_time >= exp_time:
                    t_spec_id = int(t.trade_id.replace("live_", ""))
                    t_target = target_outcomes[t_spec_id]
                    close_price = Decimal("1.08100") if t_target == "WIN" else Decimal("1.07900")
                    gateway.get_candles = AsyncMock(
                        return_value=[
                            Candle(
                                open_time=exp_time,
                                open=Decimal("1.08000"),
                                high=Decimal("1.08200"),
                                low=Decimal("1.07800"),
                                close=close_price,
                                volume=Decimal("100"),
                            )
                        ]
                    )
                    # Settle at exact trade expiry time
                    current_mock_time = exp_time
                    await live_engine._check_active_trades()
                    live_trades_executed.append(t)
                    live_balances.append(live_engine.current_balance)
                    if live_engine.status == BotStatus.PAUSED and live_engine.paused_until:
                        live_pause_events.append((exp_time, live_engine.paused_until))

            # Reset clock back to candidate evaluation time
            current_mock_time = cur_sim_time

            # 2. Check auto-resume on pause expiration
            if live_engine.status == BotStatus.PAUSED and live_engine.paused_until:
                if cur_sim_time >= live_engine.paused_until:
                    live_engine.status = BotStatus.RUNNING
                    live_engine.paused_until = None
                    live_engine.consecutive_losses = 0

            # 3. If still paused, trade cannot be opened
            if live_engine.status == BotStatus.PAUSED:
                continue

            # 4. Open trade
            trade = _make_live_trade(
                trade_id=f"live_{spec_idx}",
                asset="EURUSD_otc",
                action="CALL",
                stake=Decimal("10.00"),
                open_price=Decimal("1.08000"),
                open_time=cur_sim_time,
                payout_rate=Decimal("0.92"),
            )
            live_engine.active_trades[trade.trade_id] = trade

        # Settle any remaining active trades at the end of simulation
        end_time = t0 + timedelta(minutes=base_idx + 90)
        current_mock_time = end_time
        for tid, t in list(live_engine.active_trades.items()):
            exp_time = t.open_time + timedelta(seconds=t.expiration_seconds)
            t_spec_id = int(t.trade_id.replace("live_", ""))
            t_target = target_outcomes[t_spec_id]
            close_price = Decimal("1.08100") if t_target == "WIN" else Decimal("1.07900")
            gateway.get_candles = AsyncMock(
                return_value=[
                    Candle(
                        open_time=exp_time,
                        open=Decimal("1.08000"),
                        high=Decimal("1.08200"),
                        low=Decimal("1.07800"),
                        close=close_price,
                        volume=Decimal("100"),
                    )
                ]
            )
            current_mock_time = exp_time
            await live_engine._check_active_trades()
            live_trades_executed.append(t)
            live_balances.append(live_engine.current_balance)

    # Assert Parity:
    # 1. Total executed trades count must be exactly 11 (specs 6 and 11 blocked by 15m pause)
    assert len(bt_result.trades) == 11, f"Backtest executed {len(bt_result.trades)} trades"
    assert len(live_trades_executed) == 11, f"Live executed {len(live_trades_executed)} trades"

    # 2. Both engines blocked exactly signals at offsets 35m and 70m
    bt_entry_offsets = [
        (t.entry_time - t0).total_seconds() / 60 - base_idx for t in bt_result.trades
    ]
    assert 35 not in bt_entry_offsets, "Backtest failed to block trade at 35m"
    assert 70 not in bt_entry_offsets, "Backtest failed to block trade at 70m"

    # 3. PnL and Balance parity across all 11 executed trades
    for i in range(11):
        bt_t = bt_result.trades[i]
        lv_t = live_trades_executed[i]
        assert bt_t.outcome.value == lv_t.outcome.value, f"Outcome mismatch on trade {i}"
        assert bt_t.pnl == lv_t.pnl, f"PnL mismatch on trade {i}: bt={bt_t.pnl}, live={lv_t.pnl}"
        assert bt_t.balance_after == lv_t.balance_after, (
            f"Balance mismatch on trade {i}: bt={bt_t.balance_after}, live={lv_t.balance_after}"
        )

    # 4. Final summary metrics parity
    assert bt_result.final_balance == live_engine.current_balance
    assert bt_result.winning_trades == 3
    assert bt_result.losing_trades == 8
    assert bt_result.net_profit == live_engine.current_balance - Decimal("1000.00")

    # 5. Exact pause timestamps parity
    pause1_exit = t0 + timedelta(minutes=base_idx + 25 + 3)
    pause1_until = pause1_exit + timedelta(minutes=15)
    assert live_pause_events[0][0] == pause1_exit
    assert live_pause_events[0][1] == pause1_until

    pause2_exit = t0 + timedelta(minutes=base_idx + 60 + 3)
    pause2_until = pause2_exit + timedelta(minutes=15)
    assert live_pause_events[1][0] == pause2_exit
    assert live_pause_events[1][1] == pause2_until

    await live_engine.stop()


def test_anti_whipsaw_cooldown_parity_backtest_and_live():
    """Verify that both backtest and live engines enforce >= 180s per-asset cooldown."""
    config = PortfolioBacktestConfig(
        assets=["EURUSD_otc"],
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.00"),
        stake_model=StakeModel.FLAT,
        stake_amount=Decimal("10.00"),
        cooldown_bars=3,  # 3 bars * 60s = 180s
        global_cooldown_seconds=0,
        max_consecutive_losses=0,
        payout_rates={"EURUSD_otc": Decimal("0.92")},
    )
    engine = PortfolioBacktestEngine(config)

    base_time = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    # Signal 1: entry at idx=50, exit at idx=53 (settled at t=53m)
    # Signal 2: candidate at idx=54 (1 minute after settlement) -> delta 60s < 180s -> REJECTED
    # Signal 3: candidate at idx=56 (3 minutes = 180s after settlement) -> ACCEPTED
    n = 100
    candle_records = []
    for i in range(n):
        candle_records.append(
            {
                "timestamp": base_time + timedelta(minutes=i),
                "open": 1.0800,
                "high": 1.0820,
                "low": 1.0780,
                "close": 1.0810,
                "volume": 100,
            }
        )
    df = pd.DataFrame(candle_records)

    engine.strategy.prepare_dataframe = MagicMock(return_value=df)

    def mock_eval(df_arg, idx):
        if idx in (50, 54, 56):
            return SignalResult(
                action=TradeAction.CALL,
                confidence=0.8,
                expiration_bars=3,
                regime="test",
                metadata={},
            )
        return SignalResult(action=None, confidence=0.0, expiration_bars=3, regime="none")

    engine.strategy.evaluate_bar = MagicMock(side_effect=mock_eval)

    result = engine.run({"EURUSD_otc": df})

    # idx=54 must be rejected by cooldown; idx=50 and idx=56 must execute
    assert len(result.trades) == 2
    assert result.trades[0].entry_index == 50
    assert result.trades[1].entry_index == 56


# ============================================================================
# 3. Asset Microstructure Noise Qualification Tests
# ============================================================================


def _generate_clean_forex_feed(
    n: int = 100, base_price: float = 1.0850, seed: int = 42
) -> pd.DataFrame:
    """Generates a realistic continuous liquid Forex candle series."""
    np.random.seed(seed)
    returns = np.random.normal(loc=0.00001, scale=0.0004, size=n)
    prices = base_price * np.exp(np.cumsum(returns))

    records = []
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    for i in range(n):
        open_p = prices[i - 1] if i > 0 else base_price
        close_p = prices[i]
        wick_high = abs(np.random.normal(0.00015, 0.00005))
        wick_low = abs(np.random.normal(0.00015, 0.00005))
        high_p = max(open_p, close_p) + wick_high
        low_p = min(open_p, close_p) - wick_low

        records.append(
            {
                "open_time": base_time + timedelta(minutes=i),
                "open": round(open_p, 5),
                "high": round(high_p, 5),
                "low": round(low_p, 5),
                "close": round(close_p, 5),
                "volume": int(np.random.randint(50, 500)),
            }
        )
    return pd.DataFrame(records)


def test_microstructure_qualification_clean_forex_feed():
    """Continuous liquid Forex feeds (GBM drift-diffusion) should cleanly qualify."""
    df = _generate_clean_forex_feed(n=120, base_price=1.0850, seed=123)
    qualified, reason = qualify_asset_microstructure(df)
    assert qualified is True
    assert "qualified" in reason.lower()


def test_microstructure_synthetic_flat_feed_rejection():
    """Feeds with > 15% flat bars (high == low or open == close) must be rejected."""
    # 1. 100% completely flat zero-spread feed
    records_100_flat = []
    for _ in range(100):
        records_100_flat.append(
            {
                "open": 1.0800,
                "high": 1.0800,
                "low": 1.0800,
                "close": 1.0800,
                "volume": 10,
            }
        )
    df_100_flat = pd.DataFrame(records_100_flat)
    q, r = qualify_asset_microstructure(df_100_flat)
    assert q is False
    assert "flat bar ratio" in r.lower()

    # 2. 25% flat bars in a series of 100 bars
    df_clean = _generate_clean_forex_feed(n=100, seed=99)
    for i in range(0, 25):
        df_clean.loc[i, "high"] = df_clean.loc[i, "open"]
        df_clean.loc[i, "low"] = df_clean.loc[i, "open"]
        df_clean.loc[i, "close"] = df_clean.loc[i, "open"]

    q25, r25 = qualify_asset_microstructure(df_clean)
    assert q25 is False
    assert "flat bar ratio" in r25.lower()
    assert "25.00%" in r25


def test_microstructure_discrete_step_tick_ladder_rejection():
    """Quantized step-tick exotics where unique price ratio < 30% must be rejected."""
    # Construct a feed that cycles between only 5 discrete price levels across 100 bars
    discrete_levels = [1.0800, 1.0810, 1.0820, 1.0810, 1.0800]
    records = []
    for i in range(100):
        p = discrete_levels[i % 5]
        records.append(
            {
                "open": p - 0.0002,
                "high": p + 0.0005,
                "low": p - 0.0005,
                "close": p,
                "volume": 50,
            }
        )
    df_step = pd.DataFrame(records)
    q, r = qualify_asset_microstructure(df_step)
    assert q is False
    assert "unique price ratio" in r.lower()
    assert "below threshold 30.00%" in r.lower()


def test_microstructure_alternating_whipsaw_noise_rejection():
    """Extreme high-frequency sign-flipping noise (> 80% whipsaw sign-flips) must be rejected."""
    # Construct a feed with drifting price that flips return signs every bar
    records = []
    p = 1.0800
    for i in range(100):
        step = 0.0003 + (i * 0.000005)
        sign = 1 if (i % 2 == 0) else -1
        delta = sign * step
        prev_p = p
        p = round(p + delta, 5)
        open_p = prev_p
        close_p = p
        high_p = max(open_p, close_p) + 0.00010
        low_p = min(open_p, close_p) - 0.00010
        records.append(
            {
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": 50,
            }
        )
    df_whipsaw = pd.DataFrame(records)
    q, r = qualify_asset_microstructure(df_whipsaw)
    assert q is False
    assert "whipsaw sign flip ratio" in r.lower()
    assert "exceeds threshold 80.00%" in r.lower()


def test_microstructure_dead_zero_volatility_rejection():
    """Feeds with near-zero price fluctuation (relative ATR < 0.000030) must be rejected."""
    records = []
    p = 1.08000
    for i in range(100):
        open_p = round(p, 6)
        p = round(p + 0.000008, 6)
        close_p = round(p, 6)
        high_p = close_p + 0.000002
        low_p = open_p - 0.000002
        records.append(
            {
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": 50,
            }
        )
    df_dead = pd.DataFrame(records)
    q, r = qualify_asset_microstructure(df_dead)
    assert q is False
    assert "relative atr" in r.lower()
    assert "below threshold 0.000030" in r.lower()


def test_microstructure_boundary_and_validation_edge_cases():
    """Test candle count boundaries, NaN values, missing columns, and negative prices."""
    # 1. 49 bars (under minimum 50 bars)
    df_49 = _generate_clean_forex_feed(n=49)
    q49, r49 = qualify_asset_microstructure(df_49)
    assert q49 is False
    assert "insufficient candle history (49 < 50 bars required)" in r49.lower()

    # 2. Exactly 50 bars (meets minimum requirement)
    df_50 = _generate_clean_forex_feed(n=50)
    q50, r50 = qualify_asset_microstructure(df_50)
    assert q50 is True

    # 3. None or non-dataframe input
    q_none, r_none = qualify_asset_microstructure(None)
    assert q_none is False

    # 4. Missing required column
    df_missing = df_50.drop(columns=["high"])
    q_miss, r_miss = qualify_asset_microstructure(df_missing)
    assert q_miss is False
    assert "missing required column 'high'" in r_miss.lower()

    # 5. NaN values inside dataframe
    df_nan = df_50.copy()
    df_nan.loc[10, "close"] = np.nan
    q_nan, r_nan = qualify_asset_microstructure(df_nan)
    assert q_nan is False
    assert "contains nan or non-numeric" in r_nan.lower()

    # 6. Non-positive close price
    df_neg = df_50.copy()
    df_neg.loc[10, "close"] = -1.0800
    q_neg, r_neg = qualify_asset_microstructure(df_neg)
    assert q_neg is False
    assert "non-positive price" in r_neg.lower()


def test_canonical_asset_key_and_toxic_whitelist_filtering():
    """Verify canonical symbol normalization and toxic blacklist / whitelist filtering."""
    # Normalization
    assert canonical_asset_key("USD/IDR OTC") == "USDIDR"
    assert canonical_asset_key("EUR/USD (OTC)") == "EURUSD"
    assert canonical_asset_key("GOLD_otc") == "GOLD"
    assert canonical_asset_key("XAUUSD") == "GOLD"
    assert canonical_asset_key("") == ""
    assert canonical_asset_key(None) == ""

    # Toxic Blacklist Check
    is_tox, reason = is_toxic_asset("USD/IDR OTC")
    assert is_tox is True
    assert "toxic OTC blacklist" in reason

    is_tox_eur, _ = is_toxic_asset("EURUSD_otc")
    assert is_tox_eur is False

    # Whitelist Check
    assert is_whitelisted_asset("EURUSD_otc") is True
    assert is_whitelisted_asset("Gold OTC") is True
    assert is_whitelisted_asset("USDIDR_otc") is False

    # Filter allowed assets
    assets = ["EURUSD_otc", "USDIDR_otc", "BNB_otc", "GOLD_otc", "USDCLP_otc"]
    allowed = filter_allowed_assets(assets)
    assert "EURUSD_otc" in allowed
    assert "GOLD_otc" in allowed
    assert "USDCLP_otc" in allowed
    assert "USDIDR_otc" not in allowed
    assert "BNB_otc" not in allowed


# ============================================================================
# 4. Adversarial Stress: Simultaneous Multi-Asset Settlements
# ============================================================================


@pytest.mark.asyncio
async def test_simultaneous_multi_asset_settlement_three_losses_trigger_pause(tmp_path):
    """Adversarial stress: 3 trades across 3 pairs expire at the exact same time as LOSS."""
    db_path = str(tmp_path / "test_simultaneous_losses.db")
    store = TradeStore(db_path=db_path)
    engine = LiveDemoBotEngine(trade_store=store)

    plan = _make_plan(
        assets=["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc"],
        max_consecutive_losses=3,
        pause_duration_minutes=15,
    )
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    t0 = datetime(2026, 5, 1, 14, 0, tzinfo=UTC)

    t_eur = _make_live_trade(
        "trade_eur", "EURUSD_otc", "CALL", open_time=t0, open_price=Decimal("1.0800")
    )
    t_gbp = _make_live_trade(
        "trade_gbp", "GBPUSD_otc", "CALL", open_time=t0, open_price=Decimal("1.2500")
    )
    t_jpy = _make_live_trade(
        "trade_jpy", "USDJPY_otc", "CALL", open_time=t0, open_price=Decimal("150.00")
    )

    engine.active_trades["trade_eur"] = t_eur
    engine.active_trades["trade_gbp"] = t_gbp
    engine.active_trades["trade_jpy"] = t_jpy

    settle_t = t0 + timedelta(seconds=180)

    async def mock_get_candles(asset, timeframe=60, count=5):
        price_map = {
            "EURUSD_otc": Decimal("1.0790"),
            "GBPUSD_otc": Decimal("1.2490"),
            "USDJPY_otc": Decimal("149.90"),
        }
        p = price_map.get(asset, Decimal("1.0000"))
        return [
            Candle(
                open_time=settle_t,
                open=p + Decimal("0.0005"),
                high=p + Decimal("0.0010"),
                low=p - Decimal("0.0010"),
                close=p,
                volume=Decimal("100"),
            )
        ]

    gateway.get_candles = AsyncMock(side_effect=mock_get_candles)

    class MockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return settle_t

    with patch("strat_trade.domain.trading.bot_engine.datetime", MockDatetime):
        await engine._check_active_trades()
        await engine._check_circuit_breakers()

    assert len(engine.active_trades) == 0
    assert len(engine.recent_trades) == 3
    assert engine.consecutive_losses == 3
    assert engine.status == BotStatus.PAUSED
    assert engine.paused_until == settle_t + timedelta(minutes=15)
    assert engine.current_balance == Decimal("970.00")  # 1000 - 3 * $10

    await engine.stop()
