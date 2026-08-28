from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from strat_trade.domain.backtest.models import (
    BacktestTrade,
    TradeAction,
    TradeOutcome,
)
from strat_trade.domain.backtest.verification_runner import (
    Rolling15TradeVerificationRunner,
    VerificationStatus,
)


def make_test_trade(
    index: int,
    outcome: TradeOutcome,
    stake: float = 10.0,
    payout_rate: float = 0.92,
    action: TradeAction = TradeAction.CALL,
    entry_price: float = 1.1000,
    base_time: datetime | None = None,
) -> BacktestTrade:
    t_start = base_time or datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    entry_time = t_start + timedelta(minutes=index * 3)
    exit_time = entry_time + timedelta(minutes=3)

    stake_dec = Decimal(str(stake))
    payout_dec = Decimal(str(payout_rate))

    if outcome == TradeOutcome.WIN:
        pnl = round(stake_dec * payout_dec, 4)
        exit_p = entry_price + 0.0005 if action == TradeAction.CALL else entry_price - 0.0005
    elif outcome == TradeOutcome.LOSS:
        pnl = -stake_dec
        exit_p = entry_price - 0.0005 if action == TradeAction.CALL else entry_price + 0.0005
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


# =========================================================================
# SECTION 1: VARIABLE TRADE SEQUENCE LENGTH STRESS TESTS
# N in {0, 1, 14, 15, 16, 29, 30, 31, 100, 1000}
# =========================================================================


@pytest.mark.parametrize(
    "n_trades, expected_full_batches, expected_partial_batches, "
    "expected_rolling_windows, expected_status",
    [
        (0, 0, 0, 0, VerificationStatus.INSUFFICIENT_TRADES),
        (1, 0, 1, 0, VerificationStatus.INSUFFICIENT_TRADES),
        (14, 0, 1, 0, VerificationStatus.INSUFFICIENT_TRADES),
        (15, 1, 0, 1, VerificationStatus.PASSED),
        (16, 1, 1, 2, VerificationStatus.PASSED),
        (29, 1, 1, 15, VerificationStatus.PASSED),
        (30, 2, 0, 16, VerificationStatus.PASSED),
        (31, 2, 1, 17, VerificationStatus.PASSED),
        (100, 6, 1, 86, VerificationStatus.PASSED),
        (1000, 66, 1, 986, VerificationStatus.PASSED),
    ],
)
def test_adversarial_sequence_lengths_partitioning(
    n_trades: int,
    expected_full_batches: int,
    expected_partial_batches: int,
    expected_rolling_windows: int,
    expected_status: VerificationStatus,
) -> None:
    """Stress tests partitioning and slicing across exact variable sequence lengths."""
    # Pattern with 60% win rate (WIN, WIN, WIN, LOSS, LOSS repeat) so all full batches pass
    trades = [
        make_test_trade(
            i,
            TradeOutcome.WIN if i % 5 in (0, 1, 2) else TradeOutcome.LOSS,
            stake=10.0,
            payout_rate=0.92,
        )
        for i in range(n_trades)
    ]

    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    t0 = time.perf_counter()
    report = runner.evaluate_trades(trades)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert report.total_trades == n_trades
    assert report.total_batches == expected_full_batches
    assert report.total_non_overlapping_batches == expected_full_batches
    assert report.total_rolling_windows == expected_rolling_windows
    assert report.status == expected_status

    # Check batch structure
    full_batches = [b for b in report.batches if not b.is_partial]
    partial_batches = [b for b in report.batches if b.is_partial]

    assert len(full_batches) == expected_full_batches
    assert len(partial_batches) == expected_partial_batches

    # Verify contiguous disjoint indexing for full batches
    for b_idx, batch in enumerate(full_batches):
        expected_start = b_idx * 15 + 1
        expected_end = (b_idx + 1) * 15
        assert batch.start_trade_index == expected_start
        assert batch.end_trade_index == expected_end
        assert batch.total_trades == 15
        assert batch.is_partial is False

    # Verify remainder index bounds
    if expected_partial_batches > 0:
        p_batch = partial_batches[0]
        assert p_batch.is_partial is True
        assert p_batch.start_trade_index == expected_full_batches * 15 + 1
        assert p_batch.end_trade_index == n_trades
        assert p_batch.total_trades == n_trades - (expected_full_batches * 15)

    # Verify rolling windows bounds
    if expected_rolling_windows > 0:
        assert len(report.rolling_windows) == expected_rolling_windows
        for r_idx, r_win in enumerate(report.rolling_windows):
            assert r_win.start_trade_index == r_idx + 1
            assert r_win.end_trade_index == r_idx + 15
            assert r_win.total_trades == 15
            assert r_win.is_partial is False

    # Performance constraint: even 1000 trades evaluation must complete in < 250ms
    assert elapsed_ms < 250.0


# =========================================================================
# SECTION 2: ADVERSARIAL PAYOUT RATIOS & BREAK-EVEN THRESHOLDS
# Payout in {0.50, 0.80, 0.92, 0.95, 1.00}
# =========================================================================


@pytest.mark.parametrize(
    "payout_rate, wins, losses, draws, expected_pass, expected_net_pnl, desc",
    [
        # 50% Payout: Break-even is 66.67% (10W=$0.00 -> FAIL; 11W=+$15.00 -> PASS)
        (0.50, 10, 5, 0, False, Decimal("0.00"), "50% payout 10W/5L net zero fails > 0 check"),
        (0.50, 11, 4, 0, True, Decimal("15.00"), "50% payout 11W/4L yields +$15.00 passes"),
        (0.50, 8, 7, 0, False, Decimal("-30.00"), "50% payout 8W/7L yields negative net PnL"),
        # 80% Payout: Break-even is 55.56% (8W=-$6.00 -> FAIL; 9W=+$12.00 -> PASS)
        (0.80, 8, 7, 0, False, Decimal("-6.00"), "80% payout 8W/7L yields -$6.00 and fails"),
        (0.80, 9, 6, 0, True, Decimal("12.00"), "80% payout 9W/6L yields +$12.00 and passes"),
        (0.80, 7, 8, 0, False, Decimal("-24.00"), "80% payout 7W/8L fails"),
        # 92% Payout: Break-even is 52.08% (7W=-$15.60 -> FAIL; 8W=+$3.60 -> PASS)
        (0.92, 7, 8, 0, False, Decimal("-15.60"), "92% payout 7W/8L yields -$15.60 and fails"),
        (0.92, 8, 7, 0, True, Decimal("3.60"), "92% payout 8W/7L yields +$3.60 and passes"),
        # 95% Payout: Break-even is 51.28% (7W=-$13.50 -> FAIL; 8W=+$6.00 -> PASS)
        (0.95, 7, 8, 0, False, Decimal("-13.50"), "95% payout 7W/8L yields -$13.50 and fails"),
        (0.95, 8, 7, 0, True, Decimal("6.00"), "95% payout 8W/7L yields +$6.00 and passes"),
        # 100% Payout (1.00): Break-even is 50.0% (7W=-$10.00 -> FAIL; 8W=+$10.00 -> PASS)
        (1.00, 7, 8, 0, False, Decimal("-10.00"), "100% payout 7W/8L yields -$10.00 and fails"),
        (1.00, 8, 7, 0, True, Decimal("10.00"), "100% payout 8W/7L yields +$10.00 and passes"),
    ],
)
def test_adversarial_payout_ratios_and_breakeven_thresholds(
    payout_rate: float,
    wins: int,
    losses: int,
    draws: int,
    expected_pass: bool,
    expected_net_pnl: Decimal,
    desc: str,
) -> None:
    """Verifies analytical break-even win rate thresholds across broker payout structures."""
    total = wins + losses + draws
    assert total == 15

    outcomes = (
        [TradeOutcome.WIN] * wins + [TradeOutcome.LOSS] * losses + [TradeOutcome.DRAW] * draws
    )
    trades = [
        make_test_trade(i, outcomes[i], stake=10.0, payout_rate=payout_rate) for i in range(15)
    ]

    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal(str(payout_rate)))
    report = runner.evaluate_trades(trades)

    assert report.total_batches == 1
    batch = report.batches[0]
    assert batch.winning_trades == wins
    assert batch.losing_trades == losses
    assert batch.draw_trades == draws
    assert batch.net_pnl == expected_net_pnl
    assert batch.passed is expected_pass, f"Failed case: {desc}"
    assert report.overall_passed is expected_pass


# =========================================================================
# SECTION 3: COMBINATIONS OF WIN/LOSS/TIE OUTCOMES & EXACT DECIMAL MATH
# =========================================================================


def test_adversarial_all_fifteen_draws() -> None:
    """15 DRAW trades in a batch: 0 decisive trades, WR=0.0%, PnL=$0.00 -> FAILS."""
    trades = [
        make_test_trade(i, TradeOutcome.DRAW, stake=10.0, payout_rate=0.92) for i in range(15)
    ]
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(trades)

    assert report.total_batches == 1
    batch = report.batches[0]
    assert batch.winning_trades == 0
    assert batch.losing_trades == 0
    assert batch.draw_trades == 15
    assert batch.win_rate_pct == Decimal("0.00")
    assert batch.net_pnl == Decimal("0.00")
    assert batch.profit_factor == Decimal("0.00")
    assert batch.passed is False
    assert "Net PnL $0.00 <= $0.0" in batch.failure_reason


def test_adversarial_draws_with_wins_only() -> None:
    """8 WINs + 7 DRAWs: decisive=8, WR=100.0%, PnL=+$73.60, PF=99.99 -> PASSES."""
    outcomes = [TradeOutcome.WIN] * 8 + [TradeOutcome.DRAW] * 7
    trades = [make_test_trade(i, outcomes[i], stake=10.0, payout_rate=0.92) for i in range(15)]
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(trades)

    batch = report.batches[0]
    assert batch.winning_trades == 8
    assert batch.draw_trades == 7
    assert batch.win_rate_pct == Decimal("100.00")
    assert batch.net_pnl == Decimal("73.60")
    assert batch.gross_profit == Decimal("73.60")
    assert batch.gross_loss == Decimal("0.00")
    assert batch.profit_factor == Decimal("99.99")
    assert batch.passed is True


def test_adversarial_mixed_draws_decisive_win_rate() -> None:
    """4 WINs, 3 LOSSes, 8 DRAWs: decisive=7, WR=57.14%, PnL=+$6.80 -> PASSES."""
    outcomes = [TradeOutcome.WIN] * 4 + [TradeOutcome.LOSS] * 3 + [TradeOutcome.DRAW] * 8
    trades = [make_test_trade(i, outcomes[i], stake=10.0, payout_rate=0.92) for i in range(15)]
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(trades)

    batch = report.batches[0]
    assert batch.winning_trades == 4
    assert batch.losing_trades == 3
    assert batch.draw_trades == 8
    assert batch.win_rate_pct == Decimal("57.14")
    assert batch.net_pnl == Decimal("6.80")
    assert batch.passed is True


def test_adversarial_draw_streak_reset() -> None:
    """DRAW breaks consecutive win and loss streaks."""
    outcomes = (
        [TradeOutcome.WIN] * 4
        + [TradeOutcome.DRAW]
        + [TradeOutcome.WIN] * 5
        + [TradeOutcome.LOSS] * 5
    )
    trades = [make_test_trade(i, outcomes[i], stake=10.0, payout_rate=0.92) for i in range(15)]
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(trades)

    batch = report.batches[0]
    # Max consecutive wins should be 5 (4 wins -> draw reset -> 5 wins)
    assert batch.max_consecutive_wins == 5
    assert batch.max_consecutive_losses == 5


def test_adversarial_micro_and_macro_stakes_precision() -> None:
    """Tests Decimal precision with fractional stakes ($0.01) and large stakes ($1,000,000.00)."""
    # Micro stake: $0.01
    micro_trades = [
        make_test_trade(
            i, TradeOutcome.WIN if i < 8 else TradeOutcome.LOSS, stake=0.01, payout_rate=0.92
        )
        for i in range(15)
    ]
    runner = Rolling15TradeVerificationRunner(
        stake_amount=Decimal("0.01"), payout_rate=Decimal("0.92")
    )
    micro_report = runner.evaluate_trades(micro_trades)
    micro_batch = micro_report.batches[0]
    assert micro_batch.total_staked == Decimal("0.15")
    assert micro_batch.winning_trades == 8
    assert micro_batch.losing_trades == 7

    # Macro stake: $1,000,000.00
    macro_trades = [
        make_test_trade(
            i, TradeOutcome.WIN if i < 8 else TradeOutcome.LOSS, stake=1000000.0, payout_rate=0.92
        )
        for i in range(15)
    ]
    runner_macro = Rolling15TradeVerificationRunner(
        stake_amount=Decimal("1000000.0"), payout_rate=Decimal("0.92")
    )
    macro_report = runner_macro.evaluate_trades(macro_trades)
    macro_batch = macro_report.batches[0]
    # 8 * 920,000 - 7 * 1,000,000 = 7,360,000 - 7,000,000 = +360,000.00
    assert macro_batch.total_staked == Decimal("15000000.0")
    assert macro_batch.net_pnl == Decimal("360000.00")
    assert macro_batch.gross_profit == Decimal("7360000.00")
    assert macro_batch.gross_loss == Decimal("7000000.00")
    assert macro_batch.passed is True


def test_adversarial_custom_batch_sizes() -> None:
    """Verifies runner functions seamlessly when batch_size is customized (e.g. 10 or 20)."""
    # Batch size 10 across 30 trades = 3 full batches
    trades = [
        make_test_trade(
            i, TradeOutcome.WIN if i % 2 == 0 else TradeOutcome.LOSS, stake=10.0, payout_rate=0.92
        )
        for i in range(30)
    ]
    runner_10 = Rolling15TradeVerificationRunner(batch_size=10, payout_rate=Decimal("0.92"))
    report_10 = runner_10.evaluate_trades(trades)

    assert report_10.batch_size == 10
    assert report_10.total_batches == 3
    assert len(report_10.batches) == 3
    assert report_10.total_rolling_windows == 21  # 30 - 10 + 1 = 21


# =========================================================================
# SECTION 4: PEAK DRAWDOWN AND RECOVERY TRAJECTORIES
# =========================================================================


def test_adversarial_drawdown_trajectory_calculation() -> None:
    """Verifies peak drawdown math across steep loss trajectories followed by recovery."""
    # Outcomes: 7 LOSS, then 8 WIN
    # PnL steps: -10, -20, -30, -40, -50, -60, -70, then +9.2 * 8 = +73.6 -> ending at +3.6
    # Peak PnL is 0.0 initially, max drawdown is 70.0 (from 0.0 to -70.0)
    outcomes = [TradeOutcome.LOSS] * 7 + [TradeOutcome.WIN] * 8
    trades = [make_test_trade(i, outcomes[i], stake=10.0, payout_rate=0.92) for i in range(15)]
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(trades)

    batch = report.batches[0]
    assert batch.max_drawdown_amount == Decimal("70.0")
    assert batch.max_drawdown_pct == Decimal("46.67")  # 70.0 / 150.0 * 100 = 46.67%
    assert batch.max_consecutive_losses == 7
    assert batch.max_consecutive_wins == 8
    assert batch.net_pnl == Decimal("3.60")
    assert batch.passed is True


# =========================================================================
# SECTION 5: MINIMAX AUTO-TUNING STRESS & MULTI-REGIME SYNTHESIS
# =========================================================================


def test_adversarial_autotune_convergence_on_noisy_market() -> None:
    """Adversarially feeds unoptimized strategy into noisy composite market and tests tuning."""
    # Synthetic noisy sine wave
    n = 300
    times = pd.date_range("2026-08-20 08:00:00", periods=n, freq="1min", tz="UTC")
    t = np.linspace(0, 20 * np.pi, n)
    closes = 1.1000 + np.sin(t) * 0.0030 + np.sin(t * 5) * 0.0005
    opens = np.roll(closes, 1)
    opens[0] = 1.1000
    highs = np.maximum(opens, closes) + 0.0004
    lows = np.minimum(opens, closes) - 0.0004
    volumes = np.random.uniform(50.0, 150.0, n)

    df = pd.DataFrame(
        {
            "timestamp": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )

    bad_params = {"adx_trend_threshold": 48.0, "min_wick_ratio": 0.45, "bb_std": 2.8}
    runner = Rolling15TradeVerificationRunner(
        strategy_name="bollinger_atr_reversion",
        strategy_params=bad_params,
        auto_tune_on_failure=True,
        max_tuning_combinations=8,
        enable_plateau_check=True,
    )

    custom_grid = {
        "adx_trend_threshold": [22.0, 28.0],
        "min_wick_ratio": [0.15, 0.25],
        "bb_std": [1.8, 2.0],
    }

    report = runner.verify_or_optimize(df, parameter_grid=custom_grid)

    assert report.auto_tuned is True
    assert report.tuning_iterations > 0
    assert report.initial_params == bad_params
    assert report.optimized_params is not None
    assert report.tuning_report is not None
    assert "total_combinations_evaluated" in report.tuning_report
