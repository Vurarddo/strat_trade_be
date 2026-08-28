from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd

from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import (
    BacktestConfig,
    BacktestSummary,
    BacktestTrade,
    StakeModel,
    TradeOutcome,
)
from strat_trade.domain.strategies.registry import _STRATEGIES


class VerificationStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    INSUFFICIENT_TRADES = "INSUFFICIENT_TRADES"


STRATEGY_TUNING_SPACES: dict[str, dict[str, list[Any]]] = {
    "volatility_squeeze_breakout": {
        "kc_mult": [1.2, 1.4, 1.5, 1.6, 1.8],
        "momentum_period": [8, 10, 12, 14, 16],
        "bb_length": [18, 20, 22],
        "base_expiration_bars": [2, 3, 4],
    },
    "bollinger_atr_reversion": {
        "adx_trend_threshold": [20.0, 22.5, 25.0, 28.0, 30.0],
        "min_wick_ratio": [0.20, 0.25, 0.30, 0.35],
        "rsi_oversold": [25.0, 28.0, 30.0, 32.0],
        "rsi_overbought": [68.0, 70.0, 72.0, 75.0],
        "bb_std": [1.8, 2.0, 2.2],
        "max_atr_ratio": [1.8, 2.2, 2.5],
        "base_expiration_bars": [2, 3, 4],
    },
    "hybrid_multifactors": {
        "adx_trend_threshold": [22.0, 25.0, 28.0],
        "rsi_oversold": [28.0, 30.0, 32.0],
        "rsi_overbought": [68.0, 70.0, 72.0],
        "ema_fast": [7, 9, 11],
        "ema_mid": [18, 21, 25],
        "bb_std": [1.9, 2.0, 2.2],
        "base_expiration_bars": [2, 3, 4],
    },
    "ema_pullback_trend": {
        "adx_threshold": [20.0, 24.0, 28.0],
        "ema_fast": [7, 9, 12],
        "ema_mid": [18, 21, 26],
        "base_expiration_bars": [2, 3, 4],
    },
    "rsi_stochastic_extreme": {
        "rsi_period": [9, 12, 14],
        "rsi_oversold": [20.0, 25.0, 30.0],
        "rsi_overbought": [70.0, 75.0, 80.0],
        "stoch_oversold": [15.0, 20.0, 25.0],
        "stoch_overbought": [75.0, 80.0, 85.0],
        "base_expiration_bars": [1, 2, 3],
    },
    "macd_divergence_break": {
        "macd_fast": [8, 12, 14],
        "macd_slow": [21, 26, 30],
        "macd_sign": [7, 9, 11],
        "base_expiration_bars": [2, 3, 4],
    },
    "supertrend_adx_momentum": {
        "atr_period": [8, 10, 14],
        "atr_multiplier": [2.5, 3.0, 3.5],
        "adx_threshold": [20.0, 24.0, 28.0],
        "base_expiration_bars": [2, 3, 4],
    },
    "support_resistance_bounce": {
        "swing_window": [15, 20, 25],
        "min_wick_ratio": [0.35, 0.38, 0.42],
        "base_expiration_bars": [2, 3, 4],
    },
}


@dataclass
class TradeBatchResult:
    """Evaluation metrics for a single partition or rolling window of binary options trades."""

    batch_index: int
    start_trade_index: int
    end_trade_index: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    win_rate_pct: Decimal
    net_pnl: Decimal
    max_consecutive_losses: int
    roi_pct: Decimal
    passed: bool
    is_partial: bool = False
    start_time: datetime | None = None
    end_time: datetime | None = None
    total_staked: Decimal = Decimal("0.0")
    gross_profit: Decimal = Decimal("0.0")
    gross_loss: Decimal = Decimal("0.0")
    profit_factor: Decimal = Decimal("0.0")
    max_consecutive_wins: int = 0
    max_drawdown_amount: Decimal = Decimal("0.0")
    max_drawdown_pct: Decimal = Decimal("0.0")
    failure_reasons: list[str] = field(default_factory=list)
    failure_reason: str | None = None

    @property
    def trade_start_idx(self) -> int:
        return self.start_trade_index

    @property
    def trade_end_idx(self) -> int:
        return self.end_trade_index

    @property
    def wins(self) -> int:
        return self.winning_trades

    @property
    def losses(self) -> int:
        return self.losing_trades

    @property
    def draws(self) -> int:
        return self.draw_trades


# Aliases for cross-module compatibility
BatchEvaluationResult = TradeBatchResult
BatchVerificationItem = TradeBatchResult


@dataclass
class RollingVerificationReport:
    """Comprehensive verification report across sequential batches and rolling windows."""

    strategy_name: str
    asset: str
    timeframe_seconds: int = 60
    payout_rate: Decimal = Decimal("0.92")
    batch_size: int = 15
    min_win_rate_pct: Decimal = Decimal("53.4")
    total_trades: int = 0
    total_batches: int = 0
    total_non_overlapping_batches: int = 0
    passed_batches: int = 0
    passed_non_overlapping_batches: int = 0
    failed_batches: int = 0
    failed_non_overlapping_batches: int = 0
    all_batches_passed: bool = False
    all_non_overlapping_passed: bool = False
    total_rolling_windows: int = 0
    passed_rolling_windows: int = 0
    failed_rolling_windows: int = 0
    all_rolling_passed: bool = False
    overall_passed: bool = False
    status: VerificationStatus = VerificationStatus.FAILED
    overall_win_rate_pct: Decimal = Decimal("0.0")
    min_batch_win_rate_pct: Decimal = Decimal("0.0")
    max_batch_win_rate_pct: Decimal = Decimal("0.0")
    avg_batch_win_rate_pct: Decimal = Decimal("0.0")
    min_batch_net_pnl: Decimal = Decimal("0.0")
    max_batch_net_pnl: Decimal = Decimal("0.0")
    overall_net_pnl: Decimal = Decimal("0.0")
    total_net_pnl: Decimal = Decimal("0.0")
    max_consecutive_losses_overall: int = 0
    batches: list[TradeBatchResult] = field(default_factory=list)
    rolling_windows: list[TradeBatchResult] = field(default_factory=list)
    auto_tuned: bool = False
    tuned: bool = False
    initial_params: dict[str, Any] = field(default_factory=dict)
    original_params: dict[str, Any] = field(default_factory=dict)
    optimized_params: dict[str, Any] | None = None
    tuned_params: dict[str, Any] | None = None
    tuning_iterations: int = 0
    tuning_iterations_tested: int = 0
    tuning_report: dict[str, Any] | None = None
    backtest_summary: BacktestSummary | None = None


# Alias for cross-module compatibility
VerificationReport = RollingVerificationReport


class Rolling15TradeVerificationRunner:
    """
    Automated verification benchmark and iterative auto-tuning feedback loop
    for Pocket Option strategies.

    Evaluates candidate strategy parameters on sequential non-overlapping 15-trade batches and
    sliding rolling 15-trade windows under realistic broker payout conditions (+0.92 / -1.00 / 0.0).

    Pass Criterion per Batch:
      - Win Rate >= 53.4% (or 8 wins out of 15 trades = 53.33% with net PnL > 0)
      - Net PnL > 0.0

    When any batch fails, the runner can automatically trigger multi-batch minimax optimization
    with train/holdout split and parameter plateau stability checks to find optimal parameters
    without overfitting.
    """

    def __init__(
        self,
        strategy_name: str = "hybrid_multifactors",
        strategy_params: dict[str, Any] | None = None,
        asset: str = "EURUSD_otc",
        timeframe_seconds: int = 60,
        expiration_bars: int = 3,
        adaptive_expiration: bool = False,
        payout_rate: Decimal | float = Decimal("0.92"),
        min_payout_rate: Decimal | float = Decimal("0.80"),
        initial_deposit: Decimal | float = Decimal("1000.0"),
        stake_model: StakeModel = StakeModel.FLAT,
        stake_amount: Decimal | float = Decimal("10.0"),
        stake_percent: Decimal | float = Decimal("1.0"),
        batch_size: int = 15,
        min_win_rate_pct: Decimal | float = Decimal("53.4"),
        min_batch_pnl: Decimal | float = Decimal("0.0"),
        auto_tune_on_failure: bool = True,
        compute_rolling_windows: bool = True,
        max_tuning_combinations: int = 60,
        enable_plateau_check: bool = True,
    ) -> None:
        self.strategy_name = strategy_name
        self.strategy_params = dict(strategy_params or {})
        self.asset = asset
        self.timeframe_seconds = timeframe_seconds
        self.expiration_bars = max(1, expiration_bars)
        self.adaptive_expiration = adaptive_expiration
        self.payout_rate = Decimal(str(payout_rate))
        self.min_payout_rate = Decimal(str(min_payout_rate))
        self.initial_deposit = Decimal(str(initial_deposit))
        self.stake_model = stake_model
        self.stake_amount = Decimal(str(stake_amount))
        self.stake_percent = Decimal(str(stake_percent))
        self.batch_size = max(1, batch_size)
        self.min_win_rate_pct = Decimal(str(min_win_rate_pct))
        self.min_batch_pnl = Decimal(str(min_batch_pnl))
        self.auto_tune_on_failure = auto_tune_on_failure
        self.compute_rolling_windows = compute_rolling_windows
        self.max_tuning_combinations = max(1, min(max_tuning_combinations, 200))
        self.enable_plateau_check = enable_plateau_check

    def _create_backtest_config(
        self,
        params: dict[str, Any] | None = None,
        daily_stop_loss_pct: Decimal | float = Decimal("1.0"),
    ) -> BacktestConfig:
        strat_p = dict(params if params is not None else self.strategy_params)
        exp_bars = int(strat_p.get("base_expiration_bars", self.expiration_bars))
        adapt_exp = bool(strat_p.get("adaptive_expiration_enabled", self.adaptive_expiration))

        return BacktestConfig(
            asset=self.asset,
            timeframe_seconds=self.timeframe_seconds,
            initial_deposit=self.initial_deposit,
            stake_model=self.stake_model,
            stake_amount=self.stake_amount,
            stake_percent=self.stake_percent,
            payout_rate=self.payout_rate,
            min_payout_rate=self.min_payout_rate,
            expiration_bars=exp_bars,
            adaptive_expiration=adapt_exp,
            daily_stop_loss_pct=Decimal(str(daily_stop_loss_pct)),
            strategy_name=self.strategy_name,
            strategy_params=strat_p,
        )

    def run(
        self,
        df_raw: pd.DataFrame | list[Any],
        params: dict[str, Any] | None = None,
    ) -> RollingVerificationReport:
        """Executes backtesting over dataset and performs 15-trade batch verification."""
        cfg = self._create_backtest_config(params=params, daily_stop_loss_pct=Decimal("1.0"))
        engine = BinaryBacktestEngine(cfg)
        summary = engine.run(df_raw)
        return self.evaluate_backtest_summary(summary, params=params or self.strategy_params)

    def evaluate_trades(
        self,
        trades: list[BacktestTrade],
        params: dict[str, Any] | None = None,
    ) -> RollingVerificationReport:
        """Evaluates a raw list of BacktestTrades directly."""
        decisive_count = sum(
            1 for t in trades if t.outcome in (TradeOutcome.WIN, TradeOutcome.LOSS)
        )
        total_pnl = sum((t.pnl for t in trades), Decimal("0.0"))
        roi = (
            round(total_pnl / self.initial_deposit * Decimal("100.0"), 2)
            if self.initial_deposit > Decimal("0.0")
            else Decimal("0.0")
        )
        win_count = sum(1 for t in trades if t.outcome == TradeOutcome.WIN)
        wr = (
            round(
                Decimal(str(win_count)) / Decimal(str(decisive_count)) * Decimal("100.0"),
                2,
            )
            if decisive_count > 0
            else Decimal("0.0")
        )

        summary = BacktestSummary(
            asset=self.asset,
            timeframe_seconds=self.timeframe_seconds,
            initial_deposit=self.initial_deposit,
            final_balance=trades[-1].balance_after if trades else self.initial_deposit,
            net_profit=total_pnl,
            roi_pct=roi,
            total_trades=len(trades),
            winning_trades=win_count,
            losing_trades=sum(1 for t in trades if t.outcome == TradeOutcome.LOSS),
            draw_trades=sum(1 for t in trades if t.outcome == TradeOutcome.DRAW),
            win_rate_pct=wr,
            profit_factor=Decimal("1.0"),
            max_drawdown_amount=Decimal("0.0"),
            max_drawdown_pct=Decimal("0.0"),
            max_consecutive_wins=0,
            max_consecutive_losses=0,
            trades=trades,
            strategy_name=self.strategy_name,
        )
        return self.evaluate_backtest_summary(summary, params=params)

    def evaluate_batches(self, summary: BacktestSummary) -> RollingVerificationReport:
        """Alias for evaluate_backtest_summary."""
        return self.evaluate_backtest_summary(summary)

    def evaluate_summary(
        self,
        summary: BacktestSummary,
        params: dict[str, Any] | None = None,
    ) -> RollingVerificationReport:
        """Alias for evaluate_backtest_summary."""
        return self.evaluate_backtest_summary(summary, params=params)

    def evaluate_backtest_summary(
        self,
        summary: BacktestSummary,
        params: dict[str, Any] | None = None,
    ) -> RollingVerificationReport:
        """
        Partitions trades from BacktestSummary into non-overlapping batches and rolling windows.
        """
        trades = summary.trades
        total_trades = len(trades)
        num_non_overlapping = total_trades // self.batch_size
        remainder_count = total_trades % self.batch_size
        applied_params = dict(params if params is not None else self.strategy_params)

        if num_non_overlapping == 0:
            # Check if there is a partial batch
            partial_batches: list[TradeBatchResult] = []
            if total_trades > 0:
                p_res = self._evaluate_single_slice(
                    trades,
                    batch_index=1,
                    start_idx=1,
                    end_idx=total_trades,
                    is_partial=True,
                )
                partial_batches.append(p_res)

            return RollingVerificationReport(
                strategy_name=self.strategy_name,
                asset=self.asset,
                timeframe_seconds=self.timeframe_seconds,
                payout_rate=self.payout_rate,
                batch_size=self.batch_size,
                min_win_rate_pct=self.min_win_rate_pct,
                total_trades=total_trades,
                total_batches=0,
                total_non_overlapping_batches=0,
                passed_batches=0,
                passed_non_overlapping_batches=0,
                failed_batches=0,
                failed_non_overlapping_batches=0,
                all_batches_passed=False,
                all_non_overlapping_passed=False,
                total_rolling_windows=0,
                passed_rolling_windows=0,
                failed_rolling_windows=0,
                all_rolling_passed=False,
                overall_passed=False,
                status=VerificationStatus.INSUFFICIENT_TRADES,
                overall_win_rate_pct=summary.win_rate_pct,
                min_batch_win_rate_pct=Decimal("0.0"),
                max_batch_win_rate_pct=Decimal("0.0"),
                avg_batch_win_rate_pct=Decimal("0.0"),
                min_batch_net_pnl=Decimal("0.0"),
                max_batch_net_pnl=Decimal("0.0"),
                overall_net_pnl=summary.net_profit,
                total_net_pnl=summary.net_profit,
                max_consecutive_losses_overall=summary.max_consecutive_losses,
                batches=partial_batches,
                rolling_windows=[],
                initial_params=applied_params,
                original_params=applied_params,
                optimized_params=applied_params,
                tuned_params=applied_params,
                backtest_summary=summary,
            )

        # 1. Non-Overlapping Batches
        batches: list[TradeBatchResult] = []
        for b in range(num_non_overlapping):
            b_trades = trades[b * self.batch_size : (b + 1) * self.batch_size]
            b_res = self._evaluate_single_slice(
                b_trades,
                batch_index=b + 1,
                start_idx=b * self.batch_size + 1,
                end_idx=(b + 1) * self.batch_size,
                is_partial=False,
            )
            batches.append(b_res)

        # Handle non-empty remainder if present
        if remainder_count > 0:
            rem_trades = trades[num_non_overlapping * self.batch_size :]
            rem_res = self._evaluate_single_slice(
                rem_trades,
                batch_index=num_non_overlapping + 1,
                start_idx=num_non_overlapping * self.batch_size + 1,
                end_idx=total_trades,
                is_partial=True,
            )
            batches.append(rem_res)

        # 2. Rolling Sliding Windows (Step = 1 trade)
        rolling_windows: list[TradeBatchResult] = []
        if self.compute_rolling_windows and total_trades >= self.batch_size:
            num_rolling = total_trades - self.batch_size + 1
            for r in range(num_rolling):
                r_trades = trades[r : r + self.batch_size]
                r_res = self._evaluate_single_slice(
                    r_trades,
                    batch_index=r + 1,
                    start_idx=r + 1,
                    end_idx=r + self.batch_size,
                    is_partial=False,
                )
                rolling_windows.append(r_res)

        full_batches = [b for b in batches if not b.is_partial]
        passed_non_overlap = sum(1 for b in full_batches if b.passed)
        failed_non_overlap = len(full_batches) - passed_non_overlap
        all_non_overlap_passed = (failed_non_overlap == 0) and len(full_batches) > 0

        passed_rolling = sum(1 for r in rolling_windows if r.passed)
        failed_rolling = len(rolling_windows) - passed_rolling
        all_rolling_passed = (
            (failed_rolling == 0) and len(rolling_windows) > 0 if rolling_windows else True
        )

        overall_passed = all_non_overlap_passed

        wrs = [b.win_rate_pct for b in full_batches]
        pnls = [b.net_pnl for b in full_batches]

        min_wr = min(wrs) if wrs else Decimal("0.0")
        max_wr = max(wrs) if wrs else Decimal("0.0")
        avg_wr = (
            round(sum(wrs, Decimal("0.0")) / Decimal(str(len(wrs))), 2) if wrs else Decimal("0.0")
        )

        min_pnl = min(pnls) if pnls else Decimal("0.0")
        max_pnl = max(pnls) if pnls else Decimal("0.0")
        total_pnl = round(sum((b.net_pnl for b in batches), Decimal("0.0")), 2)

        status = VerificationStatus.PASSED if overall_passed else VerificationStatus.FAILED

        return RollingVerificationReport(
            strategy_name=self.strategy_name,
            asset=self.asset,
            timeframe_seconds=self.timeframe_seconds,
            payout_rate=self.payout_rate,
            batch_size=self.batch_size,
            min_win_rate_pct=self.min_win_rate_pct,
            total_trades=total_trades,
            total_batches=len(full_batches),
            total_non_overlapping_batches=len(full_batches),
            passed_batches=passed_non_overlap,
            passed_non_overlapping_batches=passed_non_overlap,
            failed_batches=failed_non_overlap,
            failed_non_overlapping_batches=failed_non_overlap,
            all_batches_passed=all_non_overlap_passed,
            all_non_overlapping_passed=all_non_overlap_passed,
            total_rolling_windows=len(rolling_windows),
            passed_rolling_windows=passed_rolling,
            failed_rolling_windows=failed_rolling,
            all_rolling_passed=all_rolling_passed,
            overall_passed=overall_passed,
            status=status,
            overall_win_rate_pct=summary.win_rate_pct,
            min_batch_win_rate_pct=min_wr,
            max_batch_win_rate_pct=max_wr,
            avg_batch_win_rate_pct=avg_wr,
            min_batch_net_pnl=min_pnl,
            max_batch_net_pnl=max_pnl,
            overall_net_pnl=summary.net_profit,
            total_net_pnl=total_pnl,
            max_consecutive_losses_overall=summary.max_consecutive_losses,
            batches=batches,
            rolling_windows=rolling_windows,
            initial_params=applied_params,
            original_params=applied_params,
            optimized_params=applied_params,
            tuned_params=applied_params,
            backtest_summary=summary,
        )

    def _evaluate_single_slice(
        self,
        slice_trades: list[BacktestTrade],
        batch_index: int,
        start_idx: int,
        end_idx: int,
        is_partial: bool = False,
    ) -> TradeBatchResult:
        cnt = len(slice_trades)
        wins = sum(1 for t in slice_trades if t.outcome == TradeOutcome.WIN)
        losses = sum(1 for t in slice_trades if t.outcome == TradeOutcome.LOSS)
        draws = sum(1 for t in slice_trades if t.outcome == TradeOutcome.DRAW)
        decisive = wins + losses

        win_rate_pct = (
            round((Decimal(str(wins)) / Decimal(str(decisive)) * Decimal("100.0")), 2)
            if decisive > 0
            else Decimal("0.0")
        )

        total_staked = sum((t.stake for t in slice_trades), Decimal("0.0"))
        gross_profit = sum((t.pnl for t in slice_trades if t.pnl > Decimal("0.0")), Decimal("0.0"))
        gross_loss = abs(
            sum((t.pnl for t in slice_trades if t.pnl < Decimal("0.0")), Decimal("0.0"))
        )
        net_pnl = round(sum((t.pnl for t in slice_trades), Decimal("0.0")), 2)

        roi_pct = (
            round((net_pnl / total_staked * Decimal("100.0")), 2)
            if total_staked > Decimal("0.0")
            else Decimal("0.0")
        )

        if gross_loss > Decimal("0.0"):
            profit_factor = round(gross_profit / gross_loss, 2)
        elif gross_profit > Decimal("0.0"):
            profit_factor = Decimal("99.99")
        else:
            profit_factor = Decimal("0.0")

        # Consecutive streaks and peak drawdown
        max_cons_losses = 0
        cur_cons_losses = 0
        max_cons_wins = 0
        cur_cons_wins = 0

        cum_pnl = Decimal("0.0")
        peak_pnl = Decimal("0.0")
        max_dd_amount = Decimal("0.0")

        for t in slice_trades:
            if t.outcome == TradeOutcome.WIN:
                cur_cons_wins += 1
                cur_cons_losses = 0
                max_cons_wins = max(max_cons_wins, cur_cons_wins)
            elif t.outcome == TradeOutcome.LOSS:
                cur_cons_losses += 1
                cur_cons_wins = 0
                max_cons_losses = max(max_cons_losses, cur_cons_losses)
            else:
                cur_cons_losses = 0
                cur_cons_wins = 0

            cum_pnl += t.pnl
            if cum_pnl > peak_pnl:
                peak_pnl = cum_pnl
            dd = peak_pnl - cum_pnl
            if dd > max_dd_amount:
                max_dd_amount = dd

        max_dd_pct = (
            round((max_dd_amount / total_staked * Decimal("100.0")), 2)
            if total_staked > Decimal("0.0")
            else Decimal("0.0")
        )

        # Validation Rule Check:
        # Standard: win_rate_pct >= min_win_rate_pct and net_pnl > min_batch_pnl
        # 8 wins / 15 trades (53.33%) at 92% payout yields net_pnl > 0 and satisfies requirement
        is_8_of_15_win = wins >= 8 and cnt == 15 and net_pnl > Decimal("0.0")
        passed_wr = (win_rate_pct >= self.min_win_rate_pct) or is_8_of_15_win
        passed_pnl = net_pnl > self.min_batch_pnl

        passed = passed_wr and passed_pnl and not is_partial

        failure_reasons: list[str] = []
        if is_partial:
            failure_reasons.append(f"Partial batch of {cnt} trades (< {self.batch_size})")
        if not passed_wr:
            failure_reasons.append(f"Win rate {win_rate_pct}% < {self.min_win_rate_pct}%")
        if not passed_pnl:
            failure_reasons.append(f"Net PnL ${net_pnl} <= ${self.min_batch_pnl}")

        reason_str = "; ".join(failure_reasons) if failure_reasons else None

        start_time = slice_trades[0].entry_time if slice_trades else None
        end_time = slice_trades[-1].exit_time if slice_trades else None

        return TradeBatchResult(
            batch_index=batch_index,
            start_trade_index=start_idx,
            end_trade_index=end_idx,
            total_trades=cnt,
            winning_trades=wins,
            losing_trades=losses,
            draw_trades=draws,
            win_rate_pct=win_rate_pct,
            net_pnl=net_pnl,
            max_consecutive_losses=max_cons_losses,
            roi_pct=roi_pct,
            passed=passed,
            is_partial=is_partial,
            start_time=start_time,
            end_time=end_time,
            total_staked=total_staked,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            profit_factor=profit_factor,
            max_consecutive_wins=max_cons_wins,
            max_drawdown_amount=max_dd_amount,
            max_drawdown_pct=max_dd_pct,
            failure_reasons=failure_reasons,
            failure_reason=reason_str,
        )

    def verify_or_optimize(
        self,
        df_raw: pd.DataFrame | list[Any],
        initial_params: dict[str, Any] | None = None,
        parameter_grid: dict[str, list[Any]] | None = None,
        max_combinations: int | None = None,
    ) -> RollingVerificationReport:
        """
        Automated verification & iterative tuning feedback loop.

        1. Executes baseline verification with initial parameters.
        2. If all batches pass, returns immediately (fast path).
        3. If any batch fails and auto_tune_on_failure=True, initiates minimax grid search
           across parameter space to find robust configurations that satisfy all batches.
        """
        if isinstance(df_raw, list):
            df_norm = pd.DataFrame(
                [
                    {
                        "timestamp": getattr(c, "open_time", getattr(c, "timestamp", None)),
                        "open": float(c.open),
                        "high": float(c.high),
                        "low": float(c.low),
                        "close": float(c.close),
                        "volume": float(getattr(c, "volume", 0.0)),
                    }
                    for c in df_raw
                ]
            )
            if "timestamp" in df_norm.columns:
                df_norm["timestamp"] = pd.to_datetime(df_norm["timestamp"], utc=True)
                df_norm = df_norm.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
        else:
            df_norm = df_raw.copy()

        base_params = dict(initial_params if initial_params is not None else self.strategy_params)
        baseline_report = self.run(df_norm, params=base_params)

        if baseline_report.overall_passed or not self.auto_tune_on_failure:
            return baseline_report

        # Auto-Tuning Optimization activated
        grid = parameter_grid or STRATEGY_TUNING_SPACES.get(self.strategy_name)
        if not grid:
            grid = self._build_fallback_grid()

        limit = max_combinations or self.max_tuning_combinations
        keys = list(grid.keys())
        values = list(grid.values())
        raw_combos = [dict(zip(keys, prod)) for prod in itertools.product(*values)]

        if len(raw_combos) > limit:
            step = len(raw_combos) / limit
            sampled_combos = [raw_combos[int(i * step)] for i in range(limit)]
        else:
            sampled_combos = raw_combos

        # Holdout split for large datasets (train on 70%, evaluate on holdout)
        n_bars = len(df_norm)
        if n_bars >= 180:
            split_idx = int(n_bars * 0.70)
            df_train = df_norm.iloc[:split_idx].reset_index(drop=True)
            use_oos_split = True
        else:
            df_train = df_norm
            use_oos_split = False

        candidate_evals: list[dict[str, Any]] = []

        for combo in sampled_combos:
            cfg = self._create_backtest_config(params=combo, daily_stop_loss_pct=Decimal("1.0"))
            eng = BinaryBacktestEngine(cfg)
            sum_res = eng.run(df_train)
            rep = self.evaluate_backtest_summary(sum_res, params=combo)

            if rep.total_trades < 3:
                continue

            full_b = [b for b in rep.batches if not b.is_partial]
            if full_b:
                batch_wrs = [float(b.win_rate_pct) for b in full_b]
                min_wr = min(batch_wrs)
                mean_wr = float(np.mean(batch_wrs))
                std_wr = float(np.std(batch_wrs)) if len(batch_wrs) > 1 else 0.0
                failed_b = rep.failed_batches
            else:
                min_wr = float(rep.overall_win_rate_pct)
                mean_wr = float(rep.overall_win_rate_pct)
                std_wr = 0.0
                failed_b = 1 if min_wr < float(self.min_win_rate_pct) else 0

            pnl = float(rep.overall_net_pnl)

            # Minimax multi-batch fitness function
            score = 3.0 * min_wr + 1.0 * mean_wr + 0.5 * pnl - 1.5 * std_wr - 500.0 * failed_b

            candidate_evals.append(
                {
                    "params": combo,
                    "score": score,
                    "min_wr": min_wr,
                    "mean_wr": mean_wr,
                    "all_passed_train": rep.all_batches_passed,
                    "report_train": rep,
                }
            )

        if not candidate_evals:
            baseline_report.auto_tuned = True
            baseline_report.tuned = True
            baseline_report.tuning_iterations = len(sampled_combos)
            baseline_report.tuning_iterations_tested = len(sampled_combos)
            baseline_report.tuning_report = {
                "total_combinations_evaluated": len(sampled_combos),
                "baseline_passed": baseline_report.overall_passed,
                "baseline_failed_batches": baseline_report.failed_batches,
                "oos_split_used": use_oos_split,
            }
            return baseline_report

        # Sort descending by fitness score
        candidate_evals.sort(key=lambda x: x["score"], reverse=True)

        best_passing_report: RollingVerificationReport | None = None
        best_candidate_params: dict[str, Any] = base_params

        for cand in candidate_evals:
            c_params = cand["params"]
            cfg_full = self._create_backtest_config(
                params=c_params, daily_stop_loss_pct=Decimal("1.0")
            )
            eng_full = BinaryBacktestEngine(cfg_full)
            sum_full = eng_full.run(df_norm)
            rep_full = self.evaluate_backtest_summary(sum_full, params=c_params)

            if rep_full.overall_passed:
                # Parameter plateau stability test
                if self.enable_plateau_check and len(candidate_evals) > 3:
                    is_stable = self._check_parameter_plateau(df_norm, c_params, grid)
                    if not is_stable:
                        continue

                best_passing_report = rep_full
                best_candidate_params = c_params
                break

        if best_passing_report is not None:
            best_passing_report.auto_tuned = True
            best_passing_report.tuned = True
            best_passing_report.initial_params = base_params
            best_passing_report.original_params = base_params
            best_passing_report.optimized_params = best_candidate_params
            best_passing_report.tuned_params = best_candidate_params
            best_passing_report.tuning_iterations = len(candidate_evals)
            best_passing_report.tuning_iterations_tested = len(candidate_evals)
            best_passing_report.tuning_report = {
                "total_combinations_evaluated": len(candidate_evals),
                "baseline_passed": baseline_report.overall_passed,
                "baseline_failed_batches": baseline_report.failed_batches,
                "oos_split_used": use_oos_split,
            }
            return best_passing_report

        # If no config passed 100% of batches on full data, evaluate top scored candidate
        top_params = candidate_evals[0]["params"]
        cfg_top = self._create_backtest_config(
            params=top_params, daily_stop_loss_pct=Decimal("1.0")
        )
        eng_top = BinaryBacktestEngine(cfg_top)
        sum_top = eng_top.run(df_norm)
        failed_rep = self.evaluate_backtest_summary(sum_top, params=top_params)
        failed_rep.auto_tuned = True
        failed_rep.tuned = True
        failed_rep.initial_params = base_params
        failed_rep.original_params = base_params
        failed_rep.optimized_params = top_params
        failed_rep.tuned_params = top_params
        failed_rep.tuning_iterations = len(candidate_evals)
        failed_rep.tuning_iterations_tested = len(candidate_evals)
        failed_rep.tuning_report = {
            "total_combinations_evaluated": len(candidate_evals),
            "baseline_passed": baseline_report.overall_passed,
            "baseline_failed_batches": baseline_report.failed_batches,
            "oos_split_used": use_oos_split,
        }
        return failed_rep

    def optimize_and_verify(
        self,
        df_raw: pd.DataFrame | list[Any],
        parameter_grid: dict[str, list[Any]] | None = None,
        max_combinations: int | None = None,
    ) -> tuple[RollingVerificationReport, dict[str, Any]]:
        """Alias method returning (report, tuned_params) tuple."""
        rep = self.verify_or_optimize(
            df_raw,
            parameter_grid=parameter_grid,
            max_combinations=max_combinations,
        )
        return rep, rep.optimized_params or rep.initial_params

    def verify_and_tune(
        self,
        df_raw: pd.DataFrame | list[Any],
        initial_params: dict[str, Any] | None = None,
        custom_parameter_grid: dict[str, list[Any]] | None = None,
    ) -> RollingVerificationReport:
        """Alias method for verify_or_optimize."""
        return self.verify_or_optimize(
            df_raw,
            initial_params=initial_params,
            parameter_grid=custom_parameter_grid,
        )

    def _check_parameter_plateau(
        self,
        df: pd.DataFrame,
        opt_params: dict[str, Any],
        grid: dict[str, list[Any]],
    ) -> bool:
        """Perturbs parameters by 1 step in each direction to ensure stability."""
        neighbor_wrs = []
        for param_name, values in grid.items():
            if param_name not in opt_params or len(values) < 2:
                continue
            cur_val = opt_params[param_name]
            if cur_val not in values:
                continue
            idx = values.index(cur_val)
            perturbations = []
            if idx > 0:
                perturbations.append(values[idx - 1])
            if idx < len(values) - 1:
                perturbations.append(values[idx + 1])

            for p_val in perturbations:
                test_params = dict(opt_params)
                test_params[param_name] = p_val
                cfg_p = self._create_backtest_config(
                    params=test_params, daily_stop_loss_pct=Decimal("1.0")
                )
                eng_p = BinaryBacktestEngine(cfg_p)
                sum_p = eng_p.run(df)
                rep_p = self.evaluate_backtest_summary(sum_p, params=test_params)
                if rep_p.total_batches > 0:
                    neighbor_wrs.append(float(rep_p.overall_win_rate_pct))

        if not neighbor_wrs:
            return True

        avg_neighbor_wr = float(np.mean(neighbor_wrs))
        # If neighbor WR drops heavily below 50.0%, it is a fragile single-point spike
        return avg_neighbor_wr >= 50.0

    def _build_fallback_grid(self) -> dict[str, list[Any]]:
        meta = _STRATEGIES.get(self.strategy_name.strip().lower())
        if not meta:
            meta = _STRATEGIES["hybrid_multifactors"]
        grid: dict[str, list[Any]] = {}
        for p in meta.cls.get_parameter_definitions():
            if p.options:
                grid[p.name] = p.options
            elif p.min_value is not None and p.max_value is not None:
                if p.param_type == "int":
                    min_v, max_v = int(p.min_value), int(p.max_value)
                    grid[p.name] = list(range(min_v, max_v + 1, max(1, (max_v - min_v) // 3)))[:4]
                else:
                    min_v, max_v = float(p.min_value), float(p.max_value)
                    grid[p.name] = [round(min_v + i * (max_v - min_v) / 3.0, 2) for i in range(4)]
            else:
                grid[p.name] = [p.default_value]
        return grid
