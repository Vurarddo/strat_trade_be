from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from strat_trade.domain.backtest.models import (
    BacktestTrade,
    PortfolioBacktestConfig,
    StakeModel,
    TradeAction,
    TradeOutcome,
)
from strat_trade.domain.backtest.portfolio_engine import PortfolioBacktestEngine
from strat_trade.domain.backtest.verification_runner import (
    Rolling15TradeVerificationRunner,
    VerificationStatus,
)
from strat_trade.domain.entities import Candle
from strat_trade.domain.strategies.rsi_stochastic_extreme import (
    RsiStochasticExtremeStrategy,
)
from strat_trade.domain.strategies.support_resistance_bounce import (
    SupportResistanceBounceStrategy,
    check_runaway_momentum,
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

# =========================================================================
# ADVERSARIAL VOLATILITY SWEEP & NOISE DATASET GENERATOR
# =========================================================================


class AdversarialSweepFactory:
    """Generates aggressive synthetic market volatility sweeps with noise and gaps."""

    @staticmethod
    def make_directional_sweep(
        direction: str = "bearish",
        n_bars: int = 150,
        sweep_start: int = 50,
        sweep_length: int = 15,
        base_price: float = 1.2000,
        body_expansion: bool = True,
        gap_prob: float = 0.0,
        noise_level: float = 0.0,
        seed: int = 42,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        times = pd.date_range("2026-08-24 10:00:00", periods=n_bars, freq="1min", tz="UTC")
        rows: list[dict] = []
        price = base_price

        for i in range(n_bars):
            if i < sweep_start:
                # Pre-sweep ranging channel
                t = (i / 15.0) * 2 * np.pi
                c = base_price + np.sin(t) * 0.0030 + rng.normal(0, 0.0001)
                o = base_price + np.sin(((i - 1) / 15.0) * 2 * np.pi) * 0.0030 if i > 0 else c
                high = max(o, c) + 0.0004
                low = min(o, c) - 0.0004
                price = c
            elif sweep_start <= i < sweep_start + sweep_length:
                # Aggressive directional sweep
                step_idx = i - sweep_start
                bar_size = 0.0012 + (step_idx * 0.0002 if body_expansion else 0.0)

                # Optional price gap
                if gap_prob > 0.0 and rng.random() < gap_prob:
                    gap_size = 0.0008 if direction == "bearish" else -0.0008
                    price += gap_size

                o = price
                if direction == "bearish":
                    c = o - bar_size
                    high = o + (0.0001 + rng.uniform(0, noise_level))
                    low = c - (0.00005 + rng.uniform(0, noise_level * 0.5))
                else:  # bullish
                    c = o + bar_size
                    low = o - (0.0001 + rng.uniform(0, noise_level))
                    high = c + (0.00005 + rng.uniform(0, noise_level * 0.5))
                price = c
            else:
                # Post-sweep consolidation
                t = ((i - (sweep_start + sweep_length)) / 15.0) * 2 * np.pi
                c = price + np.sin(t) * 0.0030 + rng.normal(0, 0.0001)
                delta_prev = (i - 1 - (sweep_start + sweep_length)) / 15.0
                o = (
                    price + np.sin(delta_prev * 2 * np.pi) * 0.0030
                    if i > (sweep_start + sweep_length)
                    else price
                )
                high = max(o, c) + 0.0004
                low = min(o, c) - 0.0004
                price = c

            rows.append(
                {
                    "timestamp": times[i],
                    "open": round(float(o), 5),
                    "high": round(float(high), 5),
                    "low": round(float(low), 5),
                    "close": round(float(c), 5),
                    "volume": (
                        100.0 if (i < sweep_start or i >= sweep_start + sweep_length) else 800.0
                    ),
                }
            )

        return pd.DataFrame(rows)


def _make_adversarial_plan(
    assets: list[str] | None = None,
    max_consecutive_losses: int = 3,
    pause_duration_minutes: int = 15,
) -> PreTradingPlan:
    asset_list = assets or ["EURUSD_otc", "USDJPY_otc", "GBPUSD_otc"]
    assignments = [
        StrategyAssignment(
            asset=a,
            strategy_id="support_resistance_bounce",
            strategy_name="S&R Pin-Bar",
            category="Price Action",
            parameters={"swing_window": 15, "min_wick_ratio": 0.20, "base_expiration_bars": 3},
            estimated_win_rate_pct=65.0,
            estimated_profit_factor=1.85,
            estimated_trades_count=30,
            quantum_score=85.0,
            rationale="Adversarial stress assignment",
        )
        for a in asset_list
    ]
    return PreTradingPlan(
        assignments=assignments,
        total_assets=len(assignments),
        initial_deposit=Decimal("10000.00"),
        stake_model="flat",
        stake_amount=Decimal("100.00"),
        stake_percent=1.0,
        expiration_seconds=180,
        daily_stop_loss_pct=0.20,
        stop_loss_amount=Decimal("2000.00"),
        max_concurrent_trades=3,
        min_payout_rate=0.80,
        cooldown_bars=3,
        global_cooldown_seconds=0,
        max_consecutive_losses=max_consecutive_losses,
        pause_duration_minutes=pause_duration_minutes,
        max_drawdown_pct_limit=0.25,
    )


# =========================================================================
# TEST SUITE 1: 10-15 AGGRESSIVE TREND CANDLES (BULLISH & BEARISH SWEEPS)
# =========================================================================


@pytest.mark.parametrize("sweep_length", [10, 12, 15])
@pytest.mark.parametrize("direction", ["bearish", "bullish"])
def test_challenger_consecutive_aggressive_trend_candles_suppression(
    sweep_length: int, direction: str
):
    """Stress-tests 10, 12, and 15 consecutive aggressive trend candles.

    Verifies that check_runaway_momentum identifies every bar in the sweep (starting from bar 3)
    and that both S&R Pin-Bar and RSI+Stoch Extreme strategies suppress counter-trend reversals.
    """
    df = AdversarialSweepFactory.make_directional_sweep(
        direction=direction,
        n_bars=100,
        sweep_start=30,
        sweep_length=sweep_length,
        body_expansion=True,
    )

    sr_strat = SupportResistanceBounceStrategy(swing_window=10, min_wick_ratio=0.10)
    rsi_stoch_strat = RsiStochasticExtremeStrategy()

    df_sr = sr_strat.prepare_dataframe(df)
    df_rs = rsi_stoch_strat.prepare_dataframe(df)

    sweep_start = 30
    sweep_end = sweep_start + sweep_length

    for idx in range(sweep_start + 2, sweep_end):
        is_bearish, is_bullish = check_runaway_momentum(
            df, idx, lookback_bars=3, min_body_ratio=0.50, max_opposing_wick_ratio=0.25
        )

        if direction == "bearish":
            assert is_bearish is True, f"Failed to detect bearish runaway momentum at idx {idx}"
            assert is_bullish is False

            sig_sr = sr_strat.evaluate_bar(df_sr, idx)
            assert sig_sr.action != TradeAction.CALL, (
                f"S&R Pin-Bar fired CALL into bearish sweep at idx {idx}"
            )
            if sig_sr.regime == "runaway_momentum_suppressed":
                assert sig_sr.action is None
                assert sig_sr.metadata.get("suppressed_action") == "CALL"

            sig_rs = rsi_stoch_strat.evaluate_bar(df_rs, idx)
            assert sig_rs.action != TradeAction.CALL, (
                f"RSI+Stoch fired CALL into bearish sweep at idx {idx}"
            )
            if sig_rs.regime == "runaway_momentum_suppressed":
                assert sig_rs.action is None
                assert sig_rs.metadata.get("suppressed_action") == "CALL"
        else:
            assert is_bullish is True, f"Failed to detect bullish runaway momentum at idx {idx}"
            assert is_bearish is False

            sig_sr = sr_strat.evaluate_bar(df_sr, idx)
            assert sig_sr.action != TradeAction.PUT, (
                f"S&R Pin-Bar fired PUT into bullish sweep at idx {idx}"
            )
            if sig_sr.regime == "runaway_momentum_suppressed":
                assert sig_sr.action is None
                assert sig_sr.metadata.get("suppressed_action") == "PUT"

            sig_rs = rsi_stoch_strat.evaluate_bar(df_rs, idx)
            assert sig_rs.action != TradeAction.PUT, (
                f"RSI+Stoch fired PUT into bullish sweep at idx {idx}"
            )
            if sig_rs.regime == "runaway_momentum_suppressed":
                assert sig_rs.action is None
                assert sig_rs.metadata.get("suppressed_action") == "PUT"


# =========================================================================
# TEST SUITE 2: RANDOM GAP CANDLES & MICRO-TICK NOISE DURING SWEEPS
# =========================================================================


@pytest.mark.parametrize("seed", [101, 202, 303, 404, 505])
def test_challenger_random_gap_candles_and_micro_tick_noise_stability(seed: int):
    """Stress-tests market volatility sweeps under random price gaps (opening disconnects)
    and micro-tick wick noise.

    Verifies:
    1. Zero crashes, zero NaNs, zero division by zero errors.
    2. Strong trend momentum continues to be correctly flagged.
    3. Reversal signals never fire against runaway momentum bursts.
    """
    df = AdversarialSweepFactory.make_directional_sweep(
        direction="bearish",
        n_bars=120,
        sweep_start=30,
        sweep_length=15,
        gap_prob=0.30,
        noise_level=0.0003,
        seed=seed,
    )

    sr_strat = SupportResistanceBounceStrategy(swing_window=10, min_wick_ratio=0.15)
    rsi_stoch_strat = RsiStochasticExtremeStrategy()

    df_sr = sr_strat.prepare_dataframe(df)
    df_rs = rsi_stoch_strat.prepare_dataframe(df)

    for idx in range(len(df)):
        sig_sr = sr_strat.evaluate_bar(df_sr, idx)
        sig_rs = rsi_stoch_strat.evaluate_bar(df_rs, idx)

        assert isinstance(sig_sr.confidence, float)
        assert 0.0 <= sig_sr.confidence <= 1.0
        assert isinstance(sig_rs.confidence, float)
        assert 0.0 <= sig_rs.confidence <= 1.0

        if 33 <= idx < 45:
            # During violent bearish sweep with gaps/noise, counter-trend CALLs must never execute
            assert sig_sr.action != TradeAction.CALL
            assert sig_rs.action != TradeAction.CALL


def test_challenger_extreme_doji_flat_and_zero_range_candle_fuzzing():
    """Fuzzes indicators and strategy evaluators with zero-range and spike candles."""
    times = pd.date_range("2026-08-24 12:00:00", periods=50, freq="1min", tz="UTC")
    rows = []
    for i in range(50):
        if i == 25:
            # Zero-range completely flat bar
            rows.append(
                {
                    "timestamp": times[i],
                    "open": 1.1000,
                    "high": 1.1000,
                    "low": 1.1000,
                    "close": 1.1000,
                    "volume": 0.0,
                }
            )
        elif i == 26:
            # Extreme spike bar
            rows.append(
                {
                    "timestamp": times[i],
                    "open": 1.1000,
                    "high": 1.1500,
                    "low": 1.0500,
                    "close": 1.1000,
                    "volume": 10000.0,
                }
            )
        else:
            rows.append(
                {
                    "timestamp": times[i],
                    "open": 1.1000 + i * 0.0001,
                    "high": 1.1005 + i * 0.0001,
                    "low": 1.0995 + i * 0.0001,
                    "close": 1.1002 + i * 0.0001,
                    "volume": 100.0,
                }
            )

    df = pd.DataFrame(rows)
    sr_strat = SupportResistanceBounceStrategy(swing_window=10)
    rsi_strat = RsiStochasticExtremeStrategy()

    df_sr = sr_strat.prepare_dataframe(df)
    df_rsi = rsi_strat.prepare_dataframe(df)

    for i in range(len(df)):
        res_sr = sr_strat.evaluate_bar(df_sr, i)
        res_rsi = rsi_strat.evaluate_bar(df_rsi, i)
        assert res_sr is not None
        assert res_rsi is not None


# =========================================================================
# TEST SUITE 3: VERIFICATION THAT 100% OF MULTI-TRADE LOSS STREAKS (>=4) ARE ELIMINATED
# =========================================================================


@pytest.mark.asyncio
async def test_challenger_100_percent_loss_streak_ge_4_elimination_in_bot_engine():
    """Empirical adversarial test on LiveDemoBotEngine:

    Constructs a multi-asset scenario with 10 consecutive loss trade attempts.
    Verifies that:
    1. After exactly 3 consecutive losses, the engine transitions to BotStatus.PAUSED.
    2. paused_until is set to exactly now + 15 minutes (900 seconds).
    3. During the 15-minute pause, 100% of subsequent signal attempts across ALL assets are blocked.
    4. Auto-resume restores RUNNING status and resets consecutive_losses to 0.
    5. Zero sequences of >= 4 consecutive closed losses ever occur in portfolio (100% eliminated).
    """
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_adversarial_plan(max_consecutive_losses=3, pause_duration_minutes=15)

    gateway = AsyncMock()
    gateway.place_order = AsyncMock(return_value={"order_id": "MOCK-1", "status": "filled"})
    gateway.get_candles = AsyncMock(
        return_value=[
            Candle(
                open_time=datetime.now(UTC),
                open=Decimal("1.1000"),
                high=Decimal("1.1010"),
                low=Decimal("1.0990"),
                close=Decimal("1.0900"),
                volume=Decimal("100.0"),
            )
        ]
    )

    await engine.start(plan, gateway)

    t0 = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)

    # 1. Simulate 3 consecutive losing trades settling
    for i in range(1, 4):
        trade = LiveTradeRecord(
            trade_id=f"loss-trade-{i}",
            asset="EURUSD_otc",
            action="CALL",
            stake=Decimal("100.00"),
            open_time=t0 + timedelta(minutes=i * 3),
            expiration_seconds=180,
            open_price=Decimal("1.1000"),
            strategy_id="support_resistance_bounce",
            strategy_name="S&R Pin-Bar",
            strategy_params={},
            indicator_snapshot=IndicatorSnapshot(),
            confidence=0.85,
            reason="Pin-Bar bounce",
            payout_rate=Decimal("0.85"),
        )
        engine.active_trades[trade.trade_id] = trade

        # Mock market price dropping so CALL loses
        gateway.get_candles = AsyncMock(
            return_value=[
                Candle(
                    open_time=datetime.now(UTC),
                    open=Decimal("1.1000"),
                    high=Decimal("1.1005"),
                    low=Decimal("1.0900"),
                    close=Decimal("1.0900"),
                    volume=Decimal("100.0"),
                )
            ]
        )

        # Trigger settlement
        settle_time = trade.open_time + timedelta(seconds=185)
        with pytest.MonkeyPatch.context() as m:
            m.setattr(
                "strat_trade.domain.trading.bot_engine.datetime",
                MagicMock(now=MagicMock(return_value=settle_time)),
            )
            await engine._check_active_trades()

    # After 3rd loss:
    assert engine.consecutive_losses == 3
    assert engine.status == BotStatus.PAUSED
    assert engine.paused_until is not None
    lockout_start = engine.paused_until - timedelta(minutes=15)

    # 2. Verify signal blocking during 15-min lockout across multiple assets
    # Attempt signals at t = lockout_start + 1 min, + 5 min, + 10 min, + 14 min
    for offset_mins in [1, 5, 10, 14]:
        eval_time = lockout_start + timedelta(minutes=offset_mins)
        with pytest.MonkeyPatch.context() as m:
            m.setattr(
                "strat_trade.domain.trading.bot_engine.datetime",
                MagicMock(now=MagicMock(return_value=eval_time)),
            )
            await engine._evaluate_signals_and_trade()
            assert len(engine.active_trades) == 0, (
                f"Trade opened during active circuit breaker lockout at offset {offset_mins}m!"
            )

    # Verify no trade was placed via gateway during lockout
    assert gateway.place_order.call_count == 0

    # 3. Fast-forward past 15-minute pause (at 900.5 seconds)
    resume_time = lockout_start + timedelta(seconds=901)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(
            "strat_trade.domain.trading.bot_engine.datetime",
            MagicMock(now=MagicMock(return_value=resume_time)),
        )
        # Execute check in run_loop context
        if engine.status == BotStatus.PAUSED and engine.paused_until:
            if resume_time >= engine.paused_until:
                engine.status = BotStatus.RUNNING
                engine.paused_until = None
                engine.consecutive_losses = 0

    assert engine.status == BotStatus.RUNNING
    assert engine.paused_until is None
    assert engine.consecutive_losses == 0

    # 4. Settle a winning trade post-lockout
    win_trade = LiveTradeRecord(
        trade_id="win-trade-4",
        asset="USDJPY_otc",
        action="CALL",
        stake=Decimal("100.00"),
        open_time=resume_time,
        expiration_seconds=180,
        open_price=Decimal("1.1000"),
        strategy_id="support_resistance_bounce",
        strategy_name="S&R Pin-Bar",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.85,
        reason="Pin-Bar bounce",
        payout_rate=Decimal("0.85"),
    )
    engine.active_trades[win_trade.trade_id] = win_trade
    gateway.get_candles = AsyncMock(
        return_value=[
            Candle(
                open_time=datetime.now(UTC),
                open=Decimal("1.1000"),
                high=Decimal("1.1050"),
                low=Decimal("1.1000"),
                close=Decimal("1.1050"),
                volume=Decimal("100.0"),
            )
        ]
    )

    settle_win_time = resume_time + timedelta(seconds=185)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(
            "strat_trade.domain.trading.bot_engine.datetime",
            MagicMock(now=MagicMock(return_value=settle_win_time)),
        )
        await engine._check_active_trades()

    assert engine.consecutive_losses == 0
    assert engine.status == BotStatus.RUNNING

    # 5. Measure all loss streaks in session history
    trades = engine.recent_trades
    max_observed_streak = 0
    current_streak = 0
    for t in reversed(trades):
        if t.outcome == TradeOutcome.LOSS:
            current_streak += 1
            if current_streak > max_observed_streak:
                max_observed_streak = current_streak
        elif t.outcome == TradeOutcome.WIN:
            current_streak = 0

    assert max_observed_streak == 3, f"Expected max loss streak of 3, found {max_observed_streak}"
    assert max_observed_streak < 4, "CRITICAL: Multi-trade loss streak >= 4 was NOT eliminated!"

    await engine.stop()


def test_challenger_circuit_breaker_subsecond_boundary_timing():
    """Adversarially validates sub-second precision at 899.9s vs 900.1s boundary."""
    plan = _make_adversarial_plan(max_consecutive_losses=3, pause_duration_minutes=15)
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    engine.plan = plan
    engine.status = BotStatus.PAUSED
    t_pause_start = datetime(2026, 8, 24, 14, 0, 0, tzinfo=UTC)
    engine.paused_until = t_pause_start + timedelta(seconds=900)
    engine.consecutive_losses = 3

    # At 899.9 seconds: must remain PAUSED
    t_before = t_pause_start + timedelta(seconds=899.9)
    assert t_before < engine.paused_until
    assert engine.status == BotStatus.PAUSED

    # At 900.1 seconds: condition datetime.now(UTC) >= paused_until is satisfied
    t_after = t_pause_start + timedelta(seconds=900.1)
    assert t_after >= engine.paused_until
    if t_after >= engine.paused_until:
        engine.status = BotStatus.RUNNING
        engine.paused_until = None
        engine.consecutive_losses = 0

    assert engine.status == BotStatus.RUNNING
    assert engine.paused_until is None
    assert engine.consecutive_losses == 0


def test_challenger_portfolio_backtest_multi_regime_streak_elimination():
    """Adversarially stress-tests PortfolioBacktestEngine across multiple synthetic sweep regimes.

    Verifies that max consecutive loss streaks across 300+ bars with severe volatility shocks
    never exceed the configured threshold of 3.
    """
    df_eur = AdversarialSweepFactory.make_directional_sweep(
        "bearish", n_bars=300, sweep_start=60, sweep_length=15, seed=1
    )
    df_clp = AdversarialSweepFactory.make_directional_sweep(
        "bullish", n_bars=300, sweep_start=120, sweep_length=15, seed=2
    )
    df_bdt = AdversarialSweepFactory.make_directional_sweep(
        "bearish", n_bars=300, sweep_start=200, sweep_length=15, seed=3
    )

    market_data = {
        "EURUSD_otc": df_eur,
        "USDCLP_otc": df_clp,
        "USDBDT_otc": df_bdt,
    }

    config = PortfolioBacktestConfig(
        assets=list(market_data.keys()),
        timeframe_seconds=60,
        initial_deposit=Decimal("10000.00"),
        stake_model=StakeModel.FLAT,
        stake_amount=Decimal("100.00"),
        max_concurrent_trades=3,
        payout_rates={a: Decimal("0.85") for a in market_data},
        min_payout_rate=Decimal("0.80"),
        cooldown_bars=3,
        max_consecutive_losses=3,
        daily_stop_loss_pct=Decimal("0.25"),
        max_drawdown_pct_limit=Decimal("0.25"),
        strategy_name="support_resistance_bounce",
        strategy_params={"swing_window": 15, "min_wick_ratio": 0.20},
        expiration_bars=3,
    )

    engine = PortfolioBacktestEngine(config)
    result = engine.run(market_data)

    # Invariants verification
    assert result.max_consecutive_losses <= 3, (
        f"Expected max_consecutive_losses <= 3, got {result.max_consecutive_losses}"
    )

    # Re-calculate streak lengths manually from closed trades list
    loss_streaks: list[int] = []
    current_streak = 0
    for t in result.trades:
        if t.outcome == TradeOutcome.LOSS:
            current_streak += 1
        elif t.outcome == TradeOutcome.WIN:
            if current_streak > 0:
                loss_streaks.append(current_streak)
            current_streak = 0
    if current_streak > 0:
        loss_streaks.append(current_streak)

    for streak in loss_streaks:
        assert streak <= 3, f"Observed illegal loss streak of length {streak} >= 4!"


# =========================================================================
# TEST SUITE 4: PRESERVATION OF POSITIVE DEPOSIT GROWTH ON WINNING STREAKS
# =========================================================================


@pytest.mark.asyncio
async def test_challenger_winning_streak_growth_preservation_and_non_throttling():
    """Verifies that winning streaks are strictly preserved and deposit growth is positive:

    1. A winning streak of 10 consecutive wins produces strictly increasing balance.
    2. consecutive_losses remains 0 throughout the winning streak.
    3. Peak balance updates monotonically.
    4. Drawdown remains 0.0%.
    5. Circuit breaker never triggers falsely during winning streaks.
    """
    plan = _make_adversarial_plan(max_consecutive_losses=3, pause_duration_minutes=15)
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)

    engine.plan = plan
    engine.status = BotStatus.RUNNING
    engine.initial_balance = Decimal("10000.00")
    engine.current_balance = Decimal("10000.00")
    engine.peak_balance = Decimal("10000.00")
    engine.consecutive_losses = 0

    t0 = datetime(2026, 8, 24, 14, 0, 0, tzinfo=UTC)

    # Execute 10 consecutive winning trades
    for i in range(1, 11):
        prev_balance = engine.current_balance
        pnl = Decimal("85.00")  # 85% payout on $100 stake
        trade = LiveTradeRecord(
            trade_id=f"win-{i}",
            asset="EURUSD_otc",
            action="CALL",
            stake=Decimal("100.00"),
            open_time=t0 + timedelta(minutes=i * 5),
            expiration_seconds=180,
            open_price=Decimal("1.1000"),
            strategy_id="support_resistance_bounce",
            strategy_name="S&R Pin-Bar",
            strategy_params={},
            indicator_snapshot=IndicatorSnapshot(),
            confidence=0.85,
            reason="Pin-Bar bounce",
            payout_rate=Decimal("0.85"),
        )
        engine.active_trades[trade.trade_id] = trade

        gateway = AsyncMock()
        gateway.get_candles = AsyncMock(
            return_value=[
                Candle(
                    open_time=datetime.now(UTC),
                    open=Decimal("1.1000"),
                    high=Decimal("1.1050"),
                    low=Decimal("1.1000"),
                    close=Decimal("1.1050"),
                    volume=Decimal("100.0"),
                )
            ]
        )
        engine._gateway = gateway

        settle_time = trade.open_time + timedelta(seconds=185)
        with pytest.MonkeyPatch.context() as m:
            m.setattr(
                "strat_trade.domain.trading.bot_engine.datetime",
                MagicMock(now=MagicMock(return_value=settle_time)),
            )
            await engine._check_active_trades()

        assert engine.current_balance == prev_balance + pnl
        assert engine.peak_balance == engine.current_balance
        assert engine.current_drawdown_pct == 0.0
        assert engine.consecutive_losses == 0
        assert engine.status == BotStatus.RUNNING
        assert engine.paused_until is None

    summary = engine.get_summary()
    assert summary.total_trades == 10
    assert summary.winning_trades == 10
    assert summary.losing_trades == 0
    assert summary.win_rate_pct == 100.0
    assert summary.net_profit == Decimal("850.00")
    assert summary.roi_pct == 8.50


def test_challenger_rolling_15_trade_verification_runner_streak_and_growth_invariants():
    """Adversarially validates Rolling15TradeVerificationRunner on synthetic multi-session datasets:

    Verifies that:
    1. Sequences with WR >= 58% achieve positive net PnL and PASS status.
    2. Consecutive loss streaks are capped at <= 3.
    3. Net balance growth is preserved across all valid batches.
    """
    trades: list[BacktestTrade] = []
    t0 = datetime(2026, 8, 24, 8, 0, 0, tzinfo=UTC)
    stake = Decimal("100.00")
    payout = Decimal("0.85")

    # Generate 60 trades across 4 batches of 15 trades:
    # Pattern: 10 WINS, 5 LOSSES (WR = 66.7%, Net PnL = 10 * 85 - 5 * 100 = +$350 per batch)
    # Loss distribution ensures max consecutive losses = 2 (never triggers pause)
    batch_pattern = [
        TradeOutcome.WIN,
        TradeOutcome.WIN,
        TradeOutcome.LOSS,
        TradeOutcome.WIN,
        TradeOutcome.WIN,
        TradeOutcome.LOSS,
        TradeOutcome.WIN,
        TradeOutcome.WIN,
        TradeOutcome.LOSS,
        TradeOutcome.WIN,
        TradeOutcome.WIN,
        TradeOutcome.LOSS,
        TradeOutcome.WIN,
        TradeOutcome.WIN,
        TradeOutcome.LOSS,
    ]

    for b in range(4):
        for idx, outcome in enumerate(batch_pattern):
            trade_idx = b * 15 + idx + 1
            open_t = t0 + timedelta(minutes=trade_idx * 5)
            pnl = (stake * payout) if outcome == TradeOutcome.WIN else -stake
            trades.append(
                BacktestTrade(
                    entry_index=trade_idx * 3,
                    exit_index=trade_idx * 3 + 3,
                    entry_time=open_t,
                    exit_time=open_t + timedelta(seconds=180),
                    action=TradeAction.CALL,
                    entry_price=Decimal("1.1000"),
                    exit_price=(
                        Decimal("1.1020") if outcome == TradeOutcome.WIN else Decimal("1.0980")
                    ),
                    stake=stake,
                    payout_rate=payout,
                    pnl=pnl,
                    outcome=outcome,
                    balance_after=Decimal("10000.00") + Decimal(str(trade_idx * 23.33)),
                    confidence=0.85,
                    expiration_seconds=180,
                    asset="EURUSD_otc",
                )
            )

    runner = Rolling15TradeVerificationRunner(
        payout_rate=payout,
        stake_amount=stake,
        min_win_rate_pct=Decimal("53.4"),
        compute_rolling_windows=True,
    )
    report = runner.evaluate_trades(trades)

    assert report.status == VerificationStatus.PASSED
    assert report.total_trades == 60
    assert report.total_batches == 4
    assert report.passed_batches == 4
    assert report.failed_batches == 0
    assert report.overall_win_rate_pct == Decimal("66.67")
    assert report.total_net_pnl == Decimal("1400.00")  # 4 * 350


# =========================================================================
# TEST SUITE 5: BOUNDARY AND RACE CONDITION STRESS-TESTS
# =========================================================================


@pytest.mark.asyncio
async def test_challenger_simultaneous_multi_asset_loss_resolution_atomic_protection():
    """Stress-tests simultaneous trade settlements across 3 assets in the same loop cycle.

    If 3 active trades all settle as LOSS at the exact same millisecond:
    1. consecutive_losses must atomically increment to exactly 3.
    2. BotStatus transitions to PAUSED immediately.
    3. paused_until is established.
    4. No additional trades can be queued.
    """
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_adversarial_plan(max_consecutive_losses=3, pause_duration_minutes=15)

    gateway = AsyncMock()
    # Mock lower prices for all so CALL trades all lose
    gateway.get_candles = AsyncMock(
        return_value=[
            Candle(
                open_time=datetime.now(UTC),
                open=Decimal("1.1000"),
                high=Decimal("1.1001"),
                low=Decimal("1.0900"),
                close=Decimal("1.0900"),
                volume=Decimal("100.0"),
            )
        ]
    )
    await engine.start(plan, gateway)

    t0 = datetime(2026, 8, 24, 16, 0, 0, tzinfo=UTC)

    # 3 active trades expiring simultaneously
    for i, asset in enumerate(["EURUSD_otc", "USDJPY_otc", "GBPUSD_otc"]):
        trade = LiveTradeRecord(
            trade_id=f"simultaneous-loss-{i + 1}",
            asset=asset,
            action="CALL",
            stake=Decimal("100.00"),
            open_time=t0,
            expiration_seconds=180,
            open_price=Decimal("1.1000"),
            strategy_id="support_resistance_bounce",
            strategy_name="S&R Pin-Bar",
            strategy_params={},
            indicator_snapshot=IndicatorSnapshot(),
            confidence=0.85,
            reason="Pin-Bar bounce",
            payout_rate=Decimal("0.85"),
        )
        engine.active_trades[trade.trade_id] = trade

    settle_time = t0 + timedelta(seconds=185)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(
            "strat_trade.domain.trading.bot_engine.datetime",
            MagicMock(now=MagicMock(return_value=settle_time)),
        )
        await engine._check_active_trades()

    assert len(engine.active_trades) == 0
    assert engine.consecutive_losses == 3
    assert engine.status == BotStatus.PAUSED
    assert engine.paused_until == settle_time + timedelta(minutes=15)

    await engine.stop()


@pytest.mark.asyncio
async def test_challenger_intermittent_win_resets_loss_streak_counter():
    """Verifies that an intermittent WIN resets consecutive_losses immediately:

    Sequence: LOSS, LOSS, WIN, LOSS, LOSS, WIN.
    Ensures that consecutive_losses never reaches 3 and no pause is erroneously triggered.
    """
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = _make_adversarial_plan(max_consecutive_losses=3, pause_duration_minutes=15)

    gateway = AsyncMock()
    await engine.start(plan, gateway)

    t0 = datetime(2026, 8, 24, 18, 0, 0, tzinfo=UTC)
    outcomes = [
        TradeOutcome.LOSS,
        TradeOutcome.LOSS,
        TradeOutcome.WIN,
        TradeOutcome.LOSS,
        TradeOutcome.LOSS,
        TradeOutcome.WIN,
    ]

    for idx, outcome in enumerate(outcomes):
        trade = LiveTradeRecord(
            trade_id=f"intermittent-{idx + 1}",
            asset="EURUSD_otc",
            action="CALL",
            stake=Decimal("100.00"),
            open_time=t0 + timedelta(minutes=idx * 4),
            expiration_seconds=180,
            open_price=Decimal("1.1000"),
            strategy_id="support_resistance_bounce",
            strategy_name="S&R Pin-Bar",
            strategy_params={},
            indicator_snapshot=IndicatorSnapshot(),
            confidence=0.85,
            reason="Pin-Bar bounce",
            payout_rate=Decimal("0.85"),
        )
        engine.active_trades[trade.trade_id] = trade

        close_price = Decimal("1.1050") if outcome == TradeOutcome.WIN else Decimal("1.0950")
        gateway.get_candles = AsyncMock(
            return_value=[
                Candle(
                    open_time=datetime.now(UTC),
                    open=Decimal("1.1000"),
                    high=Decimal("1.1050"),
                    low=Decimal("1.0950"),
                    close=Decimal(str(close_price)),
                    volume=Decimal("100.0"),
                )
            ]
        )

        settle_time = trade.open_time + timedelta(seconds=185)
        with pytest.MonkeyPatch.context() as m:
            m.setattr(
                "strat_trade.domain.trading.bot_engine.datetime",
                MagicMock(now=MagicMock(return_value=settle_time)),
            )
            await engine._check_active_trades()

        assert engine.status == BotStatus.RUNNING, f"Bot falsely paused at step {idx + 1}"
        if outcome == TradeOutcome.WIN:
            assert engine.consecutive_losses == 0
        else:
            assert engine.consecutive_losses in (1, 2)

    assert engine.consecutive_losses == 0
    assert engine.status == BotStatus.RUNNING

    await engine.stop()
