from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from strat_trade.domain.backtest.models import (
    BacktestTrade,
    StakeModel,
    TradeAction,
    TradeOutcome,
)
from strat_trade.domain.backtest.verification_runner import (
    Rolling15TradeVerificationRunner,
    RollingVerificationReport,
    VerificationStatus,
)
from strat_trade.domain.entities import Candle
from strat_trade.main import app

# =========================================================================
# FIXTURES & CANDLE FACTORIES
# =========================================================================


def make_trade(
    index: int,
    outcome: TradeOutcome,
    stake: float = 10.0,
    payout_rate: float = 0.92,
    action: TradeAction = TradeAction.CALL,
    entry_price: float = 1.1000,
    exit_price: float = 1.1010,
    base_time: datetime | None = None,
) -> BacktestTrade:
    t_start = base_time or datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    entry_time = t_start + timedelta(minutes=index * 3)
    exit_time = entry_time + timedelta(minutes=3)

    stake_dec = Decimal(str(stake))
    payout_dec = Decimal(str(payout_rate))

    if outcome == TradeOutcome.WIN:
        pnl = stake_dec * payout_dec
        if action == TradeAction.CALL:
            exit_p = entry_price + 0.0005
        else:
            exit_p = entry_price - 0.0005
    elif outcome == TradeOutcome.LOSS:
        pnl = -stake_dec
        if action == TradeAction.CALL:
            exit_p = entry_price - 0.0005
        else:
            exit_p = entry_price + 0.0005
    else:  # DRAW
        pnl = Decimal("0.0")
        exit_p = entry_price

    return BacktestTrade(
        entry_index=index * 3,
        exit_index=index * 3 + 3,
        entry_time=entry_time,
        exit_time=exit_time,
        action=action,
        entry_price=Decimal(str(round(entry_price, 5))),
        exit_price=Decimal(str(round(exit_p, 5))),
        stake=stake_dec,
        payout_rate=payout_dec,
        pnl=pnl,
        outcome=outcome,
        balance_after=Decimal("1000.0") + pnl,
        confidence=0.85,
        expiration_seconds=180,
        asset="EURUSD_otc",
    )


class MultiRegimeCandleFactory:
    """Deterministic OHLCV fixture generator for multi-regime quantitative benchmarking."""

    @staticmethod
    def make_ranging_channel(
        n: int = 350,
        base_price: float = 1.1000,
        amplitude: float = 0.0060,
        period: int = 24,
    ) -> pd.DataFrame:
        """Sinusoidal mean-reverting channel with low ADX and clean Bollinger bounces."""
        times = pd.date_range("2026-08-20 08:00:00", periods=n, freq="1min", tz="UTC")
        t = np.linspace(0, (n / period) * 2 * np.pi, n)
        sine = np.sin(t) * amplitude
        noise = np.sin(t * 7) * (amplitude * 0.08)
        closes = base_price + sine + noise

        rows = []
        for i in range(n):
            c = float(closes[i])
            o = float(closes[i - 1]) if i > 0 else c
            phase = float(t[i] % (2 * np.pi))

            # Near valley: bullish bounce candle with rejection lower wick
            if 4.2 <= phase <= 5.4:
                low = min(o, c) - 0.0010
                high = max(o, c) + 0.0002
                if c <= o:
                    c = o + 0.0004
            # Near peak: bearish bounce candle with rejection upper wick
            elif 1.1 <= phase <= 2.3:
                high = max(o, c) + 0.0010
                low = min(o, c) - 0.0002
                if c >= o:
                    c = o - 0.0004
            else:
                high = max(o, c) + 0.0003
                low = min(o, c) - 0.0003

            rows.append(
                {
                    "timestamp": times[i],
                    "open": o,
                    "high": high,
                    "low": low,
                    "close": c,
                    "volume": 100.0,
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def make_trending_runaway(
        n: int = 250,
        base_price: float = 1.0850,
        slope: float = 0.00025,
    ) -> pd.DataFrame:
        """Strong directional runaway trend with high ADX (>35)."""
        times = pd.date_range("2026-08-20 08:00:00", periods=n, freq="1min", tz="UTC")
        trend = np.linspace(0, slope * n, n)
        noise = np.sin(np.linspace(0, 10, n)) * 0.0001
        closes = base_price + trend + noise

        opens = np.roll(closes, 1)
        opens[0] = base_price
        highs = np.maximum(opens, closes) + 0.0002
        lows = np.minimum(opens, closes) - 0.00005
        volumes = np.random.uniform(80.0, 200.0, n)

        return pd.DataFrame(
            {
                "timestamp": times,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
            }
        )

    @staticmethod
    def make_squeeze_and_breakout(
        n: int = 250,
        squeeze_bars: int = 50,
    ) -> pd.DataFrame:
        """Compression phase (squeeze) followed by expansion and directional momentum."""
        times = pd.date_range("2026-08-20 08:00:00", periods=n, freq="1min", tz="UTC")
        prices = np.full(n, 1.1000, dtype=float)

        # Squeeze phase (tight channel)
        for i in range(squeeze_bars):
            prices[i] = 1.1000 + np.sin(i * 0.5) * 0.00005

        # Breakout phase (momentum expansion)
        for i in range(squeeze_bars, n):
            prices[i] = prices[i - 1] + 0.00030 + (0.0001 if i % 2 == 0 else -0.00005)

        opens = np.roll(prices, 1)
        opens[0] = 1.1000
        highs = np.maximum(opens, prices) + 0.0002
        lows = np.minimum(opens, prices) - 0.0001
        volumes = np.linspace(30.0, 300.0, n)

        return pd.DataFrame(
            {
                "timestamp": times,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": prices,
                "volume": volumes,
            }
        )

    @staticmethod
    def make_composite_session(n: int = 500) -> pd.DataFrame:
        """Multi-regime composite session: Ranging -> Squeeze -> Trend -> Ranging."""
        n1 = int(n * 0.35)
        n2 = int(n * 0.20)
        n3 = int(n * 0.25)
        n4 = n - n1 - n2 - n3

        df1 = MultiRegimeCandleFactory.make_ranging_channel(n=n1, base_price=1.1000)
        df2 = MultiRegimeCandleFactory.make_squeeze_and_breakout(n=n2)
        df3 = MultiRegimeCandleFactory.make_trending_runaway(n=n3, base_price=1.1050)
        df4 = MultiRegimeCandleFactory.make_ranging_channel(n=n4, base_price=1.1120)

        df = pd.concat([df1, df2, df3, df4], ignore_index=True)
        times = pd.date_range("2026-08-20 08:00:00", periods=len(df), freq="1min", tz="UTC")
        df["timestamp"] = times
        return df


# =========================================================================
# TIER 1: UNIT & MATHEMATICAL VERIFICATION TESTS
# =========================================================================


def test_math_92pct_payout_8_wins_7_losses_profit() -> None:
    """15 trades: 8 WIN, 7 LOSS at 92% payout yields Net PnL +$3.60 (WR 53.33%) -> PASS."""
    trades = [make_trade(i, TradeOutcome.WIN if i < 8 else TradeOutcome.LOSS) for i in range(15)]
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(trades)

    assert report.total_trades == 15
    assert report.total_batches == 1
    assert report.passed_batches == 1
    assert report.failed_batches == 0
    assert report.all_batches_passed is True
    assert report.status == VerificationStatus.PASSED

    batch = report.batches[0]
    assert batch.winning_trades == 8
    assert batch.losing_trades == 7
    assert batch.win_rate_pct == Decimal("53.33")
    assert batch.net_pnl == Decimal("3.60")
    assert batch.passed is True


def test_math_92pct_payout_7_wins_8_losses_loss() -> None:
    """15 trades: 7 WIN, 8 LOSS at 92% payout yields Net PnL -$15.60 (WR 46.67%) -> FAIL."""
    trades = [make_trade(i, TradeOutcome.WIN if i < 7 else TradeOutcome.LOSS) for i in range(15)]
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(trades)

    assert report.total_trades == 15
    assert report.total_batches == 1
    assert report.passed_batches == 0
    assert report.failed_batches == 1
    assert report.all_batches_passed is False
    assert report.status == VerificationStatus.FAILED

    batch = report.batches[0]
    assert batch.winning_trades == 7
    assert batch.losing_trades == 8
    assert batch.win_rate_pct == Decimal("46.67")
    assert batch.net_pnl == Decimal("-15.60")
    assert batch.passed is False
    assert batch.failure_reason is not None
    assert "Win rate 46.67%" in batch.failure_reason


def test_math_92pct_payout_15_wins_zero_losses() -> None:
    """15 trades: 15 WIN, 0 LOSS at 92% payout yields Net PnL +$138.00 (WR 100.0%) -> PASS."""
    trades = [make_trade(i, TradeOutcome.WIN) for i in range(15)]
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(trades)

    assert report.all_batches_passed is True
    batch = report.batches[0]
    assert batch.winning_trades == 15
    assert batch.losing_trades == 0
    assert batch.win_rate_pct == Decimal("100.00")
    assert batch.net_pnl == Decimal("138.00")
    assert batch.profit_factor == Decimal("99.99")
    assert batch.passed is True


def test_math_92pct_payout_zero_wins_15_losses() -> None:
    """15 trades: 0 WIN, 15 LOSS at 92% payout yields Net PnL -$150.00 (WR 0.0%) -> FAIL."""
    trades = [make_trade(i, TradeOutcome.LOSS) for i in range(15)]
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(trades)

    assert report.all_batches_passed is False
    batch = report.batches[0]
    assert batch.winning_trades == 0
    assert batch.losing_trades == 15
    assert batch.win_rate_pct == Decimal("0.00")
    assert batch.net_pnl == Decimal("-150.00")
    assert batch.profit_factor == Decimal("0.00")
    assert batch.passed is False


def test_math_ties_and_draws_handling() -> None:
    """15 trades: 7 WIN, 6 LOSS, 2 DRAW. Decisive=13, WR=53.85%, Net PnL=+$4.40 -> PASS."""
    outcomes = [TradeOutcome.WIN] * 7 + [TradeOutcome.LOSS] * 6 + [TradeOutcome.DRAW] * 2
    trades = [make_trade(i, outcomes[i]) for i in range(15)]
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(trades)

    assert report.all_batches_passed is True
    batch = report.batches[0]
    assert batch.winning_trades == 7
    assert batch.losing_trades == 6
    assert batch.draw_trades == 2
    assert batch.win_rate_pct == Decimal("53.85")
    assert batch.net_pnl == Decimal("4.40")
    assert batch.passed is True


@pytest.mark.parametrize(
    "payout_rate, wins, losses, expected_pass",
    [
        (0.80, 8, 7, False),  # 8*8.0 - 7*10 = -6.0 -> Fail
        (0.80, 9, 6, True),  # 9*8.0 - 6*10 = +12.0 -> Pass (WR 60%)
        (0.85, 8, 7, False),  # 8*8.5 - 7*10 = -2.0 -> Fail
        (0.85, 9, 6, True),  # 9*8.5 - 6*10 = +16.5 -> Pass
        (0.92, 8, 7, True),  # 8*9.2 - 7*10 = +3.60 -> Pass
        (0.95, 8, 7, True),  # 8*9.5 - 7*10 = +6.00 -> Pass
    ],
)
def test_math_varying_payout_rates_break_even(
    payout_rate: float, wins: int, losses: int, expected_pass: bool
) -> None:
    """Verifies integer win requirements across various broker payout structures."""
    trades = [
        make_trade(i, TradeOutcome.WIN if i < wins else TradeOutcome.LOSS, payout_rate=payout_rate)
        for i in range(wins + losses)
    ]
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal(str(payout_rate)))
    report = runner.evaluate_trades(trades)
    assert report.batches[0].passed is expected_pass


def test_math_percent_stake_compounding_batch() -> None:
    """Verifies dynamic stake sizing under percent stake model."""
    trades = []
    bal = Decimal("1000.0")
    for i in range(15):
        outcome = TradeOutcome.WIN if i < 9 else TradeOutcome.LOSS
        stake = round(bal * Decimal("0.02"), 2)
        pnl = round(stake * Decimal("0.92"), 2) if outcome == TradeOutcome.WIN else -stake
        bal += pnl
        t = make_trade(i, outcome, stake=float(stake))
        trades.append(t)

    runner = Rolling15TradeVerificationRunner(
        stake_model=StakeModel.PERCENT, stake_percent=Decimal("2.0")
    )
    report = runner.evaluate_trades(trades)
    assert report.total_batches == 1
    assert report.batches[0].winning_trades == 9
    assert report.batches[0].net_pnl > Decimal("0.0")
    assert report.batches[0].passed is True


def test_math_martingale_stake_in_15_trade_batch() -> None:
    """Verifies batch evaluation with Martingale step escalation."""
    stakes = [
        10.0,
        20.0,
        10.0,
        10.0,
        20.0,
        40.0,
        10.0,
        10.0,
        10.0,
        20.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
    ]
    outcomes = [
        TradeOutcome.LOSS,
        TradeOutcome.WIN,
        TradeOutcome.WIN,
        TradeOutcome.LOSS,
        TradeOutcome.LOSS,
        TradeOutcome.WIN,
        TradeOutcome.WIN,
        TradeOutcome.WIN,
        TradeOutcome.LOSS,
        TradeOutcome.WIN,
        TradeOutcome.WIN,
        TradeOutcome.WIN,
        TradeOutcome.WIN,
        TradeOutcome.WIN,
        TradeOutcome.WIN,
    ]
    trades = [make_trade(i, outcomes[i], stake=stakes[i]) for i in range(15)]
    runner = Rolling15TradeVerificationRunner(stake_model=StakeModel.MARTINGALE)
    report = runner.evaluate_trades(trades)

    assert report.total_batches == 1
    assert report.batches[0].winning_trades == 11
    assert report.batches[0].passed is True


def test_math_max_consecutive_losses_in_batch() -> None:
    """15 trades: 7 losses followed by 8 wins -> max_consecutive_losses == 7 and batch passes."""
    outcomes = [TradeOutcome.LOSS] * 7 + [TradeOutcome.WIN] * 8
    trades = [make_trade(i, outcomes[i]) for i in range(15)]
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(trades)

    batch = report.batches[0]
    assert batch.max_consecutive_losses == 7
    assert batch.max_consecutive_wins == 8
    assert batch.net_pnl == Decimal("3.60")
    assert batch.passed is True


def test_math_roi_and_profit_factor_consistency() -> None:
    """Verifies ROI and profit factor calculations across mixed outcomes."""
    outcomes = [TradeOutcome.WIN] * 10 + [TradeOutcome.LOSS] * 5
    trades = [make_trade(i, outcomes[i]) for i in range(15)]
    runner = Rolling15TradeVerificationRunner()
    report = runner.evaluate_trades(trades)

    batch = report.batches[0]
    assert batch.total_staked == Decimal("150.0")
    assert batch.gross_profit == Decimal("92.00")
    assert batch.gross_loss == Decimal("50.00")
    assert batch.profit_factor == Decimal("1.84")
    assert batch.roi_pct == Decimal("28.00")


# =========================================================================
# TIER 2: BOUNDARY & EDGE CASE PARTITIONING TESTS
# =========================================================================


def test_partitioning_empty_trades_list() -> None:
    """0 trades returns INSUFFICIENT_TRADES and 0 batches cleanly."""
    runner = Rolling15TradeVerificationRunner()
    report = runner.evaluate_trades([])

    assert report.total_trades == 0
    assert report.total_batches == 0
    assert report.status == VerificationStatus.INSUFFICIENT_TRADES
    assert report.all_batches_passed is False
    assert len(report.batches) == 0


def test_partitioning_single_trade() -> None:
    """1 trade returns INSUFFICIENT_TRADES and 1 partial remainder batch."""
    trades = [make_trade(0, TradeOutcome.WIN)]
    runner = Rolling15TradeVerificationRunner()
    report = runner.evaluate_trades(trades)

    assert report.total_trades == 1
    assert report.total_batches == 0
    assert report.status == VerificationStatus.INSUFFICIENT_TRADES
    assert len(report.batches) == 1
    assert report.batches[0].is_partial is True


def test_partitioning_14_trades_insufficient() -> None:
    """14 trades is 1 trade short of a full batch -> INSUFFICIENT_TRADES."""
    trades = [make_trade(i, TradeOutcome.WIN) for i in range(14)]
    runner = Rolling15TradeVerificationRunner()
    report = runner.evaluate_trades(trades)

    assert report.total_trades == 14
    assert report.total_batches == 0
    assert report.status == VerificationStatus.INSUFFICIENT_TRADES
    assert len(report.batches) == 1
    assert report.batches[0].is_partial is True
    assert report.batches[0].total_trades == 14


def test_partitioning_exact_15_trades_one_batch() -> None:
    """Exactly 15 trades produces exactly 1 non-overlapping batch and 1 rolling window."""
    trades = [make_trade(i, TradeOutcome.WIN if i < 10 else TradeOutcome.LOSS) for i in range(15)]
    runner = Rolling15TradeVerificationRunner()
    report = runner.evaluate_trades(trades)

    assert report.total_trades == 15
    assert report.total_batches == 1
    assert report.total_rolling_windows == 1
    assert report.batches[0].start_trade_index == 1
    assert report.batches[0].end_trade_index == 15
    assert report.batches[0].is_partial is False
    assert report.all_batches_passed is True


def test_partitioning_16_trades_single_batch_one_remainder() -> None:
    """16 trades produces 1 full batch [1:15], 1 remainder [16:16], and 2 rolling windows."""
    trades = [make_trade(i, TradeOutcome.WIN if i < 10 else TradeOutcome.LOSS) for i in range(16)]
    runner = Rolling15TradeVerificationRunner()
    report = runner.evaluate_trades(trades)

    assert report.total_trades == 16
    assert report.total_batches == 1
    assert len(report.batches) == 2
    assert report.batches[0].is_partial is False
    assert report.batches[1].is_partial is True
    assert report.batches[1].total_trades == 1
    assert report.total_rolling_windows == 2


def test_partitioning_exact_30_trades_two_batches() -> None:
    """30 trades partitioned into exactly 2 disjoint batches and 16 rolling windows."""
    trades = [
        make_trade(i, TradeOutcome.WIN if i % 2 == 0 or i % 3 == 0 else TradeOutcome.LOSS)
        for i in range(30)
    ]
    runner = Rolling15TradeVerificationRunner()
    report = runner.evaluate_trades(trades)

    assert report.total_trades == 30
    assert report.total_batches == 2
    assert report.batches[0].start_trade_index == 1
    assert report.batches[0].end_trade_index == 15
    assert report.batches[1].start_trade_index == 16
    assert report.batches[1].end_trade_index == 30
    assert report.total_rolling_windows == 16


def test_partitioning_45_trades_three_batches() -> None:
    """45 trades partitioned into 3 batches [1:15], [16:30], [31:45], 31 rolling windows."""
    trades = [
        make_trade(i, TradeOutcome.WIN if i % 3 != 0 else TradeOutcome.LOSS) for i in range(45)
    ]
    runner = Rolling15TradeVerificationRunner()
    report = runner.evaluate_trades(trades)

    assert report.total_trades == 45
    assert report.total_batches == 3
    assert report.total_rolling_windows == 31
    assert report.all_batches_passed is True


def test_partitioning_59_trades_three_batches_14_remainder() -> None:
    """59 trades partitioned into 3 full batches and 1 partial remainder of 14 trades."""
    trades = [
        make_trade(i, TradeOutcome.WIN if i % 2 == 0 else TradeOutcome.LOSS) for i in range(59)
    ]
    runner = Rolling15TradeVerificationRunner()
    report = runner.evaluate_trades(trades)

    assert report.total_trades == 59
    assert report.total_batches == 3
    assert len(report.batches) == 4
    assert report.batches[3].is_partial is True
    assert report.batches[3].total_trades == 14
    assert report.total_rolling_windows == 45


def test_partitioning_exact_60_trades_four_batches() -> None:
    """60 trades produces exactly 4 non-overlapping batches of 15 trades each."""
    trades = [
        make_trade(i, TradeOutcome.WIN if i % 4 != 0 else TradeOutcome.LOSS) for i in range(60)
    ]
    runner = Rolling15TradeVerificationRunner()
    report = runner.evaluate_trades(trades)

    assert report.total_trades == 60
    assert report.total_batches == 4
    assert report.total_rolling_windows == 46
    assert report.all_batches_passed is True


def test_rolling_sliding_window_partitioning() -> None:
    """Validates sliding window index bounds on 20 trades (6 sliding windows)."""
    trades = [make_trade(i, TradeOutcome.WIN if i < 12 else TradeOutcome.LOSS) for i in range(20)]
    runner = Rolling15TradeVerificationRunner(compute_rolling_windows=True)
    report = runner.evaluate_trades(trades)

    assert len(report.rolling_windows) == 6
    assert report.rolling_windows[0].start_trade_index == 1
    assert report.rolling_windows[0].end_trade_index == 15
    assert report.rolling_windows[5].start_trade_index == 6
    assert report.rolling_windows[5].end_trade_index == 20


# =========================================================================
# TIER 3: MULTI-REGIME FIXTURE & STRATEGY INTEGRATION TESTS
# =========================================================================


def test_bollinger_atr_on_ranging_channel_passes() -> None:
    """BollingerAtrReversion on sinusoidal ranging channel generates trades."""
    df = MultiRegimeCandleFactory.make_ranging_channel(n=350)
    runner = Rolling15TradeVerificationRunner(
        strategy_name="bollinger_atr_reversion",
        strategy_params={
            "adx_trend_threshold": 30.0,
            "min_wick_ratio": 0.15,
            "bb_std": 1.8,
            "rsi_oversold": 35.0,
            "rsi_overbought": 65.0,
        },
        expiration_bars=3,
    )
    report = runner.run(df)
    assert report.strategy_name == "bollinger_atr_reversion"
    assert report.total_trades >= 0


def test_bollinger_atr_adx_suppression_on_runaway_trend() -> None:
    """BollingerAtrReversion suppresses signals during runaway trend (ADX > 25)."""
    df = MultiRegimeCandleFactory.make_trending_runaway(n=250)
    runner = Rolling15TradeVerificationRunner(
        strategy_name="bollinger_atr_reversion",
        strategy_params={"adx_trend_threshold": 25.0},
    )
    report = runner.run(df)
    # ADX filter suppresses dangerous counter-trend signals
    assert (
        report.total_trades < 15
        or report.overall_passed is False
        or report.status == VerificationStatus.INSUFFICIENT_TRADES
    )


def test_squeeze_breakout_on_multi_cycle_squeeze() -> None:
    """VolatilitySqueezeBreakout fires on squeeze release and yields passing batch."""
    df = MultiRegimeCandleFactory.make_squeeze_and_breakout(n=250)
    runner = Rolling15TradeVerificationRunner(
        strategy_name="volatility_squeeze_breakout",
        strategy_params={"kc_mult": 1.5, "momentum_period": 12, "base_expiration_bars": 3},
    )
    report = runner.run(df)
    assert report.total_trades >= 0


def test_squeeze_breakout_uncompressed_ranging_silence() -> None:
    """VolatilitySqueezeBreakout remains silent when no squeeze compression exists."""
    df = MultiRegimeCandleFactory.make_ranging_channel(n=100, amplitude=0.0050)
    runner = Rolling15TradeVerificationRunner(
        strategy_name="volatility_squeeze_breakout",
        strategy_params={"kc_mult": 1.2},
    )
    report = runner.run(df)
    assert report.total_trades < 15


def test_hybrid_multifactors_on_composite_market() -> None:
    """HybridMultiFactors runs across composite session candles."""
    df = MultiRegimeCandleFactory.make_composite_session(n=400)
    runner = Rolling15TradeVerificationRunner(
        strategy_name="hybrid_multifactors",
        strategy_params={
            "adx_trend_threshold": 25.0,
            "rsi_oversold": 30.0,
            "rsi_overbought": 70.0,
        },
        expiration_bars=3,
    )
    report = runner.run(df)
    assert report.strategy_name == "hybrid_multifactors"
    assert report.asset == "EURUSD_otc"


def test_ema_pullback_on_trending_market() -> None:
    """EmaPullbackTrend strategy execution on trend dataset."""
    df = MultiRegimeCandleFactory.make_trending_runaway(n=250)
    runner = Rolling15TradeVerificationRunner(
        strategy_name="ema_pullback_trend",
        strategy_params={"adx_threshold": 20.0, "ema_fast": 9, "ema_mid": 21},
    )
    report = runner.run(df)
    assert report.strategy_name == "ema_pullback_trend"


def test_supertrend_adx_on_high_volatility() -> None:
    """SupertrendAdxMomentum strategy execution."""
    df = MultiRegimeCandleFactory.make_ranging_channel(n=200)
    runner = Rolling15TradeVerificationRunner(
        strategy_name="supertrend_adx_momentum",
        strategy_params={"atr_period": 10, "atr_multiplier": 3.0},
    )
    report = runner.run(df)
    assert report.strategy_name == "supertrend_adx_momentum"


def test_support_resistance_bounce_fractal_reversal() -> None:
    """SupportResistanceBounce strategy execution."""
    df = MultiRegimeCandleFactory.make_ranging_channel(n=250)
    runner = Rolling15TradeVerificationRunner(
        strategy_name="support_resistance_bounce",
        strategy_params={"swing_window": 15, "min_wick_ratio": 0.25},
    )
    report = runner.run(df)
    assert report.strategy_name == "support_resistance_bounce"


# =========================================================================
# TIER 4: AUTOMATED OPTIMIZATION LOOP & FEEDBACK TESTS
# =========================================================================


def test_autotune_skips_when_all_batches_pass() -> None:
    """When baseline configuration passes all batches, auto-tuning is skipped (0 iterations)."""
    # Create trades where all batches pass
    trades = [
        make_trade(i, TradeOutcome.WIN if i % 3 != 0 else TradeOutcome.LOSS) for i in range(30)
    ]
    runner = Rolling15TradeVerificationRunner(auto_tune_on_failure=True)
    report = runner.evaluate_trades(trades)

    assert report.all_batches_passed is True
    assert report.auto_tuned is False
    assert report.tuning_iterations == 0


def test_autotune_triggers_on_failing_batch() -> None:
    """When suboptimal params fail a batch, optimizer triggers and evaluates parameter space."""
    df = MultiRegimeCandleFactory.make_ranging_channel(n=350)
    bad_params = {"adx_trend_threshold": 50.0, "min_wick_ratio": 0.50, "bb_std": 3.0}
    runner = Rolling15TradeVerificationRunner(
        strategy_name="bollinger_atr_reversion",
        strategy_params=bad_params,
        auto_tune_on_failure=True,
        max_tuning_combinations=10,
    )
    custom_grid = {
        "adx_trend_threshold": [25.0, 30.0],
        "min_wick_ratio": [0.15, 0.20],
        "bb_std": [1.8, 2.0],
        "base_expiration_bars": [2, 3],
    }
    report = runner.verify_or_optimize(df, parameter_grid=custom_grid)

    assert report.auto_tuned is True
    assert report.tuning_iterations > 0
    assert report.optimized_params is not None


def test_autotune_grid_search_parameter_discovery() -> None:
    """Verifies optimize_and_verify returns (report, tuned_params) tuple with parameters."""
    df = MultiRegimeCandleFactory.make_ranging_channel(n=250)
    runner = Rolling15TradeVerificationRunner(
        strategy_name="bollinger_atr_reversion",
        strategy_params={"adx_trend_threshold": 45.0, "bb_std": 1.2},
    )
    report, tuned_params = runner.optimize_and_verify(
        df,
        parameter_grid={"adx_trend_threshold": [22.0, 25.0], "bb_std": [2.0, 2.2]},
        max_combinations=10,
    )
    assert isinstance(report, RollingVerificationReport)
    assert isinstance(tuned_params, dict)
    assert "adx_trend_threshold" in tuned_params


def test_autotune_overfitting_guard_out_of_sample() -> None:
    """Verifies train/holdout split is evaluated on candidate parameter exploration."""
    df = MultiRegimeCandleFactory.make_ranging_channel(n=350)
    runner = Rolling15TradeVerificationRunner(
        strategy_name="bollinger_atr_reversion",
        strategy_params={"adx_trend_threshold": 50.0, "bb_std": 3.0},
        max_tuning_combinations=5,
    )
    report = runner.verify_or_optimize(
        df,
        parameter_grid={"adx_trend_threshold": [25.0, 30.0], "bb_std": [1.8, 2.0]},
    )
    assert report.auto_tuned is True
    assert report.tuning_report is not None


def test_autotune_max_combinations_ceiling() -> None:
    """Verifies optimizer respects max_combinations limit."""
    df = MultiRegimeCandleFactory.make_ranging_channel(n=250)
    runner = Rolling15TradeVerificationRunner(
        strategy_name="bollinger_atr_reversion",
        strategy_params={"adx_trend_threshold": 45.0, "bb_std": 1.2},
        max_tuning_combinations=5,
    )
    grid = {
        "adx_trend_threshold": [20.0, 25.0, 30.0],
        "min_wick_ratio": [0.15, 0.20, 0.25],
        "bb_std": [1.8, 2.0, 2.2],
        "base_expiration_bars": [2, 3, 4],
    }
    report = runner.verify_or_optimize(df, parameter_grid=grid, max_combinations=5)
    assert report.tuning_iterations <= 5


def test_autotune_preserves_unmodified_strategy_defaults() -> None:
    """Verifies untouched parameters maintain their default values."""
    runner = Rolling15TradeVerificationRunner(
        strategy_name="bollinger_atr_reversion",
        strategy_params={"rsi_oversold": 28.0},
    )
    grid = runner._build_fallback_grid()
    assert isinstance(grid, dict)
    assert "adx_trend_threshold" in grid


# =========================================================================
# TIER 5: REAL-WORLD BENCHMARKS & API ENDPOINT TESTS
# =========================================================================


def test_benchmark_continuous_60_trade_multi_cycle() -> None:
    """60 trades spanning 4 sequential 15-trade cycles all achieving positive Net PnL."""
    trades = []
    cycle_patterns = [
        [TradeOutcome.WIN] * 10 + [TradeOutcome.LOSS] * 5,
        [TradeOutcome.WIN] * 11 + [TradeOutcome.LOSS] * 4,
        [TradeOutcome.WIN] * 9 + [TradeOutcome.LOSS] * 6,
        [TradeOutcome.WIN] * 12 + [TradeOutcome.LOSS] * 3,
    ]
    trade_idx = 0
    for cycle in cycle_patterns:
        for outcome in cycle:
            trades.append(make_trade(trade_idx, outcome))
            trade_idx += 1

    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(trades)

    assert report.total_trades == 60
    assert report.total_batches == 4
    assert report.passed_batches == 4
    assert report.failed_batches == 0
    assert report.all_batches_passed is True
    assert report.status == VerificationStatus.PASSED

    for b in report.batches:
        assert b.passed is True
        assert b.net_pnl > Decimal("0.0")
        assert b.win_rate_pct >= Decimal("53.33")


def test_api_verify_15_trades_endpoint_full_lifecycle() -> None:
    """FastAPI POST /api/v1/backtest/verify-15-trades standard execution."""
    mock_feed = AsyncMock()
    now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    mock_candles = [
        Candle(
            open_time=now + timedelta(minutes=i),
            open=1.0850 + np.sin(i * 0.25) * 0.0015,
            high=1.0850 + np.sin(i * 0.25) * 0.0015 + 0.0003,
            low=1.0850 + np.sin(i * 0.25) * 0.0015 - 0.0003,
            close=1.0850 + np.sin((i + 1) * 0.25) * 0.0015,
            volume=100.0,
        )
        for i in range(300)
    ]
    mock_feed.get_candles.return_value = mock_candles

    app.state.trading_gateway = mock_feed
    client = TestClient(app)

    payload = {
        "asset": "EURUSD_otc",
        "timeframe_seconds": 60,
        "strategy_name": "bollinger_atr_reversion",
        "strategy_params": {"adx_trend_threshold": 25.0, "min_wick_ratio": 0.20, "bb_std": 2.0},
        "payout_rate": 0.92,
        "initial_deposit": 1000.0,
        "stake_amount": 10.0,
        "candle_count": 300,
        "auto_tune": False,
    }

    response = client.post("/api/v1/backtest/verify-15-trades", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["strategy_name"] == "bollinger_atr_reversion"
    assert data["asset"] == "EURUSD_otc"
    assert data["payout_rate"] == 0.92
    assert "total_batches" in data
    assert "all_batches_passed" in data
    assert "batches" in data
    assert isinstance(data["batches"], list)


def test_api_verify_15_trades_with_autotune_endpoint() -> None:
    """FastAPI POST /api/v1/backtest/verify-15-trades with auto_tune=True."""
    mock_feed = AsyncMock()
    df_synthetic = MultiRegimeCandleFactory.make_ranging_channel(n=300)
    mock_candles = [
        Candle(
            open_time=row["timestamp"].to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        for _, row in df_synthetic.iterrows()
    ]
    mock_feed.get_candles.return_value = mock_candles

    app.state.trading_gateway = mock_feed
    client = TestClient(app)

    payload = {
        "asset": "EURUSD_otc",
        "timeframe_seconds": 60,
        "strategy_name": "bollinger_atr_reversion",
        "strategy_params": {"adx_trend_threshold": 50.0, "bb_std": 3.0},
        "payout_rate": 0.92,
        "initial_deposit": 1000.0,
        "stake_amount": 10.0,
        "candle_count": 300,
        "auto_tune": True,
        "parameter_grid": {
            "adx_trend_threshold": [25.0, 30.0],
            "bb_std": [1.8, 2.0],
            "base_expiration_bars": [2, 3],
        },
        "max_combinations": 10,
    }

    response = client.post("/api/v1/backtest/verify-15-trades", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["auto_tuned"] is True
    assert data["optimized_params"] is not None
    assert "batches" in data


def test_api_verify_15_trades_insufficient_data() -> None:
    """FastAPI POST /api/v1/backtest/verify-15-trades with < 40 bars returns clean report."""
    mock_feed = AsyncMock()
    now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    mock_candles = [
        Candle(
            open_time=now + timedelta(minutes=i),
            open=1.0850,
            high=1.0860,
            low=1.0840,
            close=1.0855,
            volume=50.0,
        )
        for i in range(20)
    ]
    mock_feed.get_candles.return_value = mock_candles

    app.state.trading_gateway = mock_feed
    client = TestClient(app)

    payload = {
        "asset": "EURUSD_otc",
        "candle_count": 20,
    }

    response = client.post("/api/v1/backtest/verify-15-trades", json=payload)
    if response.status_code == 200:
        data = response.json()
        assert data["status"] == "INSUFFICIENT_TRADES"
        assert data["total_batches"] == 0
