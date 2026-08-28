# 🔬 Milestone 3 Explorer 1 Handoff Report: Verification Runner Architecture & Data Infrastructure

**Milestone**: Milestone 3: Automated Iterative Verification & Optimization Loop (R3)  
**Agent**: `m3_explorer_1`  
**Working Directory**: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m3_explorer_1/`  
**Date**: 2026-08-20  
**Scope**: Historical candle data storage/formats/loaders, and architecture/specifications for `Rolling15TradeVerificationRunner` in `src/strat_trade/domain/backtest/verification_runner.py`.

---

## 1. Observation

### 1.1 Historical Candle Data Storage, Formats & Loaders
1. **Existing Persistent Storage**:
   - `data/trades.db` (`src/strat_trade/domain/trading/trade_store.py:20-69`): SQLite persistent database storing live/demo trade telemetry (`trades` table) with order IDs, timestamps, entry/exit prices, indicator snapshots, PnL, and outcome statuses.
2. **Broker Live & Historical Feeds**:
   - `PocketOptionTradingGateway` (`src/strat_trade/adapters/pocket_option_gateway.py:351-412`): Asynchronous WebSocket gateway querying native broker periods (`1s`, `5s`, `15s`, `30s`, `60s`, `300s`) via `get_candles(asset, timeframe, count, end_time)`.
   - `TradingViewGateway` (`src/strat_trade/adapters/trading_view_gateway.py:142-185`): Historical spot market OHLCV feed via `tvdatafeed` with interval mapping and DataFrame normalization.
3. **Canonical In-Memory Candle DataFrame Schema**:
   - Normalized 6-column structure utilized throughout `src/strat_trade/domain/backtest/`:
     ```python
     df.columns == ["timestamp", "open", "high", "low", "close", "volume"]
     ```
     - `timestamp`: UTC `pd.DatetimeIndex` or `datetime` (`pd.to_datetime(..., utc=True)`).
     - `open`, `high`, `low`, `close`: `float64` numeric prices.
     - `volume`: `float64` (defaults to `0.0` if absent).
     - Sorting: Strictly ascending by `timestamp` via `.sort_values("timestamp", kind="mergesort").reset_index(drop=True)`.
4. **Data Loader (`src/strat_trade/domain/backtest/data_loader.py:11-105`)**:
   - `parse_candles_csv_or_json(content: str | bytes, filename: str = "") -> pd.DataFrame`:
     - Parses CSV and JSON formats.
     - Supports nested JSON payloads (`candles`, `data`, `history`, `items`, `result`).
     - Normalizes column aliases (`time`/`t`/`ts`/`datetime` $\rightarrow$ `timestamp`, `o` $\rightarrow$ `open`, `h` $\rightarrow$ `high`, `l` $\rightarrow$ `low`, `c`/`price` $\rightarrow$ `close`, `v`/`vol` $\rightarrow$ `volume`).
     - Automatically handles epoch timestamps in seconds vs milliseconds (threshold $> 10^{11}$).
     - Filters invalid/null records (`dropna`, `fillna(0.0)`).
5. **Synthetic Candle Fixture Generators (`tests/test_backtest_models_and_engine.py:13-40`)**:
   - Generates realistic sinusoidal price trajectories + Gaussian noise for deterministic testing:
     ```python
     t = np.linspace(0, 16 * np.pi, n)
     sine = np.sin(t) * 0.0080
     noise = np.random.normal(0, 0.0003, n)
     closes = 1.1000 + sine + noise
     ```

---

### 1.2 Binary Options Backtesting & Payoff Mathematics
1. **Engine Mechanics (`src/strat_trade/domain/backtest/engine.py:21-321`)**:
   - `BinaryBacktestEngine`: Event-driven bar-by-bar execution.
   - Warm-up: First 50 bars reserved for indicator initialization (`for i in range(50, n - 1):`).
   - Execution lock: Non-overlapping trades on the same asset (`next_available_idx = exit_idx`).
   - Expiration settlement: Future bar close comparison at $t + \text{expiration\_bars}$.
2. **Fixed Payoff Formulation**:
   - Under payout rate $R$ (default $R = 0.92$ for Pocket Option OTC) and stake $S$:
     $$\text{Win PnL} = +S \times R \quad (+0.92 S)$$
     $$\text{Loss PnL} = -S \times 1.00 \quad (-1.00 S)$$
     $$\text{Draw PnL} = 0.00$$
3. **Break-Even Win Rate ($WR_{BE}$)**:
   $$WR_{BE} = \frac{1}{1 + R} = \frac{1}{1 + 0.92} = 52.083\%$$
4. **15-Trade Window Exact Combinatorics ($N = 15, S = \$10, R = 0.92$)**:
   $$\text{Net PnL}(k) = k \times (\$9.20) - (15 - k) \times (\$10.00) = \$19.20 k - \$150.00$$

| Wins ($k$) | Losses ($15-k$) | Win Rate % | Net PnL ($S=\$10$) | Profit Factor | Status ($WR \ge 53.4\% \land \text{PnL} > 0$) |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 15 | 0 | 100.00% | +$138.00 | $\infty$ | **PASSED** |
| 12 | 3 | 80.00% | +$80.40 | 3.68 | **PASSED** |
| 10 | 5 | 66.67% | +$42.00 | 1.84 | **PASSED** |
| 9 | 6 | 60.00% | +$22.80 | 1.38 | **PASSED** |
| **8** | **7** | **53.33% (~53.4%)** | **+$3.60** | **1.05** | **PASSED** ($WR \ge 53.33\% \land \text{PnL} > 0$) |
| 7 | 8 | 46.67% | -$15.60 | 0.81 | **FAILED** |
| 5 | 10 | 33.33% | -$54.00 | 0.46 | **FAILED** |
| 0 | 15 | 0.00% | -$150.00 | 0.00 | **FAILED** |

---

## 2. Logic Chain

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                          Verification & Optimization Pipeline                               │
├───────────────────────────────┬─────────────────────────────┬───────────────────────────────┤
│    1. Backtest Execution      │    2. Window Partitioning   │   3. Quantitative Validation  │
│  - Load Historical Dataset    │  - Sequential 15-Trade      │  - Win Rate >= 53.4%          │
│  - Run BinaryBacktestEngine   │    Batches (1-15, 16-30...) │  - Net PnL > 0.0              │
│  - Extract Executed Trades    │  - Rolling 15-Trade Sliding │  - Streak & Drawdown Checks   │
│                               │    Windows (Step = 1 trade) │  - Diagnostic Failure Logs    │
└───────────────────────────────┴─────────────────────────────┴───────────────────────────────┘
                                               │ (If any batch fails)
                                               ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                       4. Automated Parameter Optimization Feedback Loop                     │
│  - Query Strategy Parameter Space (Grid / Cartesian Search)                                 │
│  - Re-evaluate Candidates Through Rolling15TradeVerificationRunner                          │
│  - Select Parameter Plateau Maximizing Min-Batch Win Rate & Profitability                   │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Step 1 — Backtest on Candidate Configuration**:
   Given candle data (from CSV, JSON, broker feed, or synthetic generator), `BinaryBacktestEngine` runs the target strategy with `payout_rate = Decimal("0.92")`, `stake_model = StakeModel.FLAT`, `stake_amount = Decimal("10.0")`, generating a full chronological list of `BacktestTrade` records.
2. **Step 2 — Partitioning into Non-Overlapping Batches & Rolling Windows**:
   - For $N$ total trades and batch size $B = 15$:
     - **Non-Overlapping Batches**: $M = \lfloor N / 15 \rfloor$ disjoint slices: $[0..14], [15..29], \dots, [15(M-1)..15M-1]$.
     - **Rolling Windows**: $K = \max(0, N - 15 + 1)$ sliding slices: $[0..14], [1..15], [2..16], \dots, [N-15..N-1]$.
3. **Step 3 — Batch Metric Synthesis**:
   For each batch/window:
   - Compute `winning_trades`, `losing_trades`, `draw_trades`.
   - Calculate `win_rate_pct = (winning_trades / decisive_trades) * 100`.
   - Sum `net_pnl = sum(trade.pnl)`.
   - Compute `roi_pct = (net_pnl / total_staked) * 100`.
   - Compute `profit_factor = gross_profit / gross_loss`.
   - Calculate `max_consecutive_losses` and `max_consecutive_wins`.
   - Calculate intra-batch `max_drawdown_amount` and `max_drawdown_pct`.
4. **Step 4 — Validation Evaluation**:
   - A batch passes iff `(win_rate_pct >= min_win_rate_pct) and (net_pnl > min_batch_pnl)`.
   - The overall run passes iff $M \ge 1$ and all non-overlapping batches pass (`all_non_overlapping_passed == True`).
5. **Step 5 — Feedback Loop & Auto-Tuning**:
   - When verification fails (`all_non_overlapping_passed == False`), candidate parameters are iterated via `StrategyOptimizerEngine` and filtered through the runner until an optimal parameter set passes all batches.

---

## 3. Caveats

1. **8 Wins vs 9 Wins Rounding Nuance ($53.33\%$ vs $53.40\%$)**:
   - In a 15-trade binary sample, 8 wins yields $8 / 15 = 53.333\%$.
   - Mathematically, 8 wins at 92% payout produces $+0.36 S$ (profitable).
   - If `min_win_rate_pct` is strictly evaluated as `Decimal("53.4")`, $53.33\% < 53.40\%$, which would require 9 wins ($60.0\%$).
   - **Resolution**: `min_win_rate_pct` must be configurable (default `Decimal("53.4")` or `Decimal("53.33")`), with explicit support for `min_win_rate_pct = Decimal("53.33")` so 8-win profitable batches are accepted when intended.
2. **Session Stop Loss During Verification**:
   - In standard backtesting, `daily_stop_loss_pct` (e.g. 5%) may abort execution early after a short drawdown streak before 15 trades are completed.
   - **Resolution**: For verification runs, `daily_stop_loss_pct` should default to `Decimal("1.0")` (or disabled) to guarantee full dataset traversal.
3. **Minimum Trade Threshold**:
   - Datasets generating fewer than 15 trades cannot form a full batch.
   - The runner must return a clean `status = "INSUFFICIENT_TRADES"` and `passed = False` rather than raising uncaught indexing exceptions.
4. **Handling Draws (Ties)**:
   - In rare broker instances where `exit_price == entry_price`, `pnl = 0.0`.
   - Decisive win rate formula must be: $\frac{\text{Wins}}{\text{Wins} + \text{Losses}} \times 100$ (with fallback to $0.0$ if $\text{Wins} + \text{Losses} == 0$).

---

## 4. Conclusion & Architecture Specifications

### 4.1 Architecture Diagram

```
strat_trade/
├── domain/
│   └── backtest/
│       ├── models.py                  # Dataclasses: BacktestConfig, BacktestTrade, BacktestSummary
│       ├── data_loader.py             # parse_candles_csv_or_json()
│       ├── engine.py                  # BinaryBacktestEngine
│       ├── portfolio_engine.py        # PortfolioBacktestEngine
│       └── verification_runner.py     # [NEW] Rolling15TradeVerificationRunner, BatchEvaluationResult, VerificationReport
├── domain/
│   └── optimizer/
│       ├── grid_search.py             # StrategyOptimizerEngine
│       └── auto_matcher.py            # StrategyAutoMatcher
├── use_cases/
│   ├── run_backtest.py                # execute_backtest()
│   ├── optimize_strategy.py           # execute_strategy_optimization()
│   └── verify_strategy.py             # [NEW] execute_rolling_15_verification()
└── api/
    ├── routes/backtest.py             # POST /api/v1/backtest/verify-15-trade
    └── schemas.py                     # VerificationRequest, VerificationResponse schemas
```

---

### 4.2 Proposed Code Implementation Specification

#### Domain File: `src/strat_trade/domain/backtest/verification_runner.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

import pandas as pd

from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import (
    BacktestConfig,
    BacktestSummary,
    BacktestTrade,
    StakeModel,
    TradeOutcome,
)
from strat_trade.domain.optimizer.grid_search import StrategyOptimizerEngine
from strat_trade.domain.strategies.registry import list_available_strategies


class VerificationStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    INSUFFICIENT_TRADES = "INSUFFICIENT_TRADES"


@dataclass
class BatchEvaluationResult:
    batch_index: int
    trade_start_idx: int
    trade_end_idx: int
    start_time: datetime | None
    end_time: datetime | None
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    win_rate_pct: Decimal
    total_staked: Decimal
    gross_profit: Decimal
    gross_loss: Decimal
    net_pnl: Decimal
    roi_pct: Decimal
    profit_factor: Decimal
    max_consecutive_losses: int
    max_consecutive_wins: int
    max_drawdown_amount: Decimal
    max_drawdown_pct: Decimal
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)


@dataclass
class VerificationReport:
    strategy_name: str
    asset: str
    timeframe_seconds: int
    payout_rate: Decimal
    batch_size: int
    min_win_rate_pct: Decimal
    total_trades: int
    total_non_overlapping_batches: int
    passed_non_overlapping_batches: int
    failed_non_overlapping_batches: int
    all_non_overlapping_passed: bool
    total_rolling_windows: int
    passed_rolling_windows: int
    failed_rolling_windows: int
    all_rolling_passed: bool
    overall_passed: bool
    min_batch_win_rate_pct: Decimal
    max_batch_win_rate_pct: Decimal
    avg_batch_win_rate_pct: Decimal
    min_batch_net_pnl: Decimal
    max_batch_net_pnl: Decimal
    total_net_pnl: Decimal
    max_consecutive_losses_overall: int
    status: VerificationStatus
    batches: list[BatchEvaluationResult] = field(default_factory=list)
    rolling_windows: list[BatchEvaluationResult] = field(default_factory=list)
    backtest_summary: BacktestSummary | None = None
    tuned_params: dict[str, Any] | None = None


class Rolling15TradeVerificationRunner:
    """Automated benchmark validating non-overlapping and rolling 15-trade batch profitability."""

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
        batch_size: int = 15,
        min_win_rate_pct: Decimal | float = Decimal("53.4"),
        min_batch_pnl: Decimal | float = Decimal("0.0"),
        compute_rolling_windows: bool = True,
    ) -> None:
        self.strategy_name = strategy_name
        self.strategy_params = strategy_params or {}
        self.asset = asset
        self.timeframe_seconds = timeframe_seconds
        self.expiration_bars = max(1, expiration_bars)
        self.adaptive_expiration = adaptive_expiration
        self.payout_rate = Decimal(str(payout_rate))
        self.min_payout_rate = Decimal(str(min_payout_rate))
        self.initial_deposit = Decimal(str(initial_deposit))
        self.stake_model = stake_model
        self.stake_amount = Decimal(str(stake_amount))
        self.batch_size = max(1, batch_size)
        self.min_win_rate_pct = Decimal(str(min_win_rate_pct))
        self.min_batch_pnl = Decimal(str(min_batch_pnl))
        self.compute_rolling_windows = compute_rolling_windows

    def run(self, df_raw: pd.DataFrame | list[Any]) -> VerificationReport:
        """Runs backtesting on dataset and performs 15-trade batch verification."""
        config = BacktestConfig(
            asset=self.asset,
            timeframe_seconds=self.timeframe_seconds,
            initial_deposit=self.initial_deposit,
            stake_model=self.stake_model,
            stake_amount=self.stake_amount,
            payout_rate=self.payout_rate,
            min_payout_rate=self.min_payout_rate,
            expiration_bars=self.expiration_bars,
            adaptive_expiration=self.adaptive_expiration,
            daily_stop_loss_pct=Decimal("1.0"),  # Relaxed stop loss for full verification
            strategy_name=self.strategy_name,
            strategy_params=self.strategy_params,
        )
        engine = BinaryBacktestEngine(config)
        summary = engine.run(df_raw)
        return self.evaluate_backtest_summary(summary)

    def evaluate_backtest_summary(self, summary: BacktestSummary) -> VerificationReport:
        """Evaluates an existing BacktestSummary across 15-trade batches."""
        trades = summary.trades
        total_trades = len(trades)
        num_non_overlapping = total_trades // self.batch_size

        if num_non_overlapping == 0:
            return VerificationReport(
                strategy_name=self.strategy_name,
                asset=self.asset,
                timeframe_seconds=self.timeframe_seconds,
                payout_rate=self.payout_rate,
                batch_size=self.batch_size,
                min_win_rate_pct=self.min_win_rate_pct,
                total_trades=total_trades,
                total_non_overlapping_batches=0,
                passed_non_overlapping_batches=0,
                failed_non_overlapping_batches=0,
                all_non_overlapping_passed=False,
                total_rolling_windows=0,
                passed_rolling_windows=0,
                failed_rolling_windows=0,
                all_rolling_passed=False,
                overall_passed=False,
                min_batch_win_rate_pct=Decimal("0.0"),
                max_batch_win_rate_pct=Decimal("0.0"),
                avg_batch_win_rate_pct=Decimal("0.0"),
                min_batch_net_pnl=Decimal("0.0"),
                max_batch_net_pnl=Decimal("0.0"),
                total_net_pnl=summary.net_profit,
                max_consecutive_losses_overall=summary.max_consecutive_losses,
                status=VerificationStatus.INSUFFICIENT_TRADES,
                batches=[],
                rolling_windows=[],
                backtest_summary=summary,
            )

        # 1. Evaluate Non-Overlapping Batches
        batches: list[BatchEvaluationResult] = []
        for b in range(num_non_overlapping):
            b_trades = trades[b * self.batch_size : (b + 1) * self.batch_size]
            b_res = self._evaluate_single_slice(
                b_trades,
                batch_index=b + 1,
                start_idx=b * self.batch_size + 1,
                end_idx=(b + 1) * self.batch_size,
            )
            batches.append(b_res)

        # 2. Evaluate Rolling Windows (if enabled)
        rolling_windows: list[BatchEvaluationResult] = []
        if self.compute_rolling_windows:
            num_rolling = total_trades - self.batch_size + 1
            for r in range(num_rolling):
                r_trades = trades[r : r + self.batch_size]
                r_res = self._evaluate_single_slice(
                    r_trades,
                    batch_index=r + 1,
                    start_idx=r + 1,
                    end_idx=r + self.batch_size,
                )
                rolling_windows.append(r_res)

        passed_non_overlap = sum(1 for b in batches if b.passed)
        failed_non_overlap = len(batches) - passed_non_overlap
        all_non_overlap_passed = (failed_non_overlap == 0) and len(batches) > 0

        passed_rolling = sum(1 for r in rolling_windows if r.passed)
        failed_rolling = len(rolling_windows) - passed_rolling
        all_rolling_passed = (failed_rolling == 0) and len(rolling_windows) > 0 if rolling_windows else True

        overall_passed = all_non_overlap_passed

        wrs = [b.win_rate_pct for b in batches]
        pnls = [b.net_pnl for b in batches]

        min_wr = min(wrs) if wrs else Decimal("0.0")
        max_wr = max(wrs) if wrs else Decimal("0.0")
        avg_wr = round(sum(wrs) / Decimal(str(len(wrs))), 2) if wrs else Decimal("0.0")

        min_pnl = min(pnls) if pnls else Decimal("0.0")
        max_pnl = max(pnls) if pnls else Decimal("0.0")
        total_pnl = round(sum((b.net_pnl for b in batches), Decimal("0.0")), 2)

        status = VerificationStatus.PASSED if overall_passed else VerificationStatus.FAILED

        return VerificationReport(
            strategy_name=self.strategy_name,
            asset=self.asset,
            timeframe_seconds=self.timeframe_seconds,
            payout_rate=self.payout_rate,
            batch_size=self.batch_size,
            min_win_rate_pct=self.min_win_rate_pct,
            total_trades=total_trades,
            total_non_overlapping_batches=len(batches),
            passed_non_overlapping_batches=passed_non_overlap,
            failed_non_overlapping_batches=failed_non_overlap,
            all_non_overlapping_passed=all_non_overlap_passed,
            total_rolling_windows=len(rolling_windows),
            passed_rolling_windows=passed_rolling,
            failed_rolling_windows=failed_rolling,
            all_rolling_passed=all_rolling_passed,
            overall_passed=overall_passed,
            min_batch_win_rate_pct=min_wr,
            max_batch_win_rate_pct=max_wr,
            avg_batch_win_rate_pct=avg_wr,
            min_batch_net_pnl=min_pnl,
            max_batch_net_pnl=max_pnl,
            total_net_pnl=total_pnl,
            max_consecutive_losses_overall=summary.max_consecutive_losses,
            status=status,
            batches=batches,
            rolling_windows=rolling_windows,
            backtest_summary=summary,
        )

    def _evaluate_single_slice(
        self,
        slice_trades: list[BacktestTrade],
        batch_index: int,
        start_idx: int,
        end_idx: int,
    ) -> BatchEvaluationResult:
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
        gross_loss = abs(sum((t.pnl for t in slice_trades if t.pnl < Decimal("0.0")), Decimal("0.0")))
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

        # Streaks & Drawdown
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

        # Validation Rule Check
        passed = (win_rate_pct >= self.min_win_rate_pct) and (net_pnl > self.min_batch_pnl)
        reasons: list[str] = []
        if win_rate_pct < self.min_win_rate_pct:
            reasons.append(f"Win rate {win_rate_pct}% < {self.min_win_rate_pct}%")
        if net_pnl <= self.min_batch_pnl:
            reasons.append(f"Net PnL ${net_pnl} <= ${self.min_batch_pnl}")

        start_time = slice_trades[0].entry_time if slice_trades else None
        end_time = slice_trades[-1].exit_time if slice_trades else None

        return BatchEvaluationResult(
            batch_index=batch_index,
            trade_start_idx=start_idx,
            trade_end_idx=end_idx,
            start_time=start_time,
            end_time=end_time,
            total_trades=cnt,
            winning_trades=wins,
            losing_trades=losses,
            draw_trades=draws,
            win_rate_pct=win_rate_pct,
            total_staked=total_staked,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            net_pnl=net_pnl,
            roi_pct=roi_pct,
            profit_factor=profit_factor,
            max_consecutive_losses=max_cons_losses,
            max_consecutive_wins=max_cons_wins,
            max_drawdown_amount=max_dd_amount,
            max_drawdown_pct=max_dd_pct,
            passed=passed,
            failure_reasons=reasons,
        )

    def optimize_and_verify(
        self,
        df_raw: pd.DataFrame,
        parameter_grid: dict[str, list[Any]] | None = None,
        max_combinations: int = 50,
    ) -> tuple[VerificationReport, dict[str, Any]]:
        """Iteratively tunes parameters until a configuration satisfies all 15-trade validation batches."""
        # 1. Run baseline
        baseline_report = self.run(df_raw)
        if baseline_report.overall_passed:
            return baseline_report, dict(self.strategy_params)

        # 2. Run Optimizer
        optimizer = StrategyOptimizerEngine(
            strategy_name=self.strategy_name,
            asset=self.asset,
            timeframe_seconds=self.timeframe_seconds,
            initial_deposit=float(self.initial_deposit),
            payout_rate=float(self.payout_rate),
            stake_model=self.stake_model,
            stake_amount=float(self.stake_amount),
            max_combinations=max_combinations,
        )

        grid = parameter_grid or {}
        opt_report = optimizer.run(df_raw, grid)

        # 3. Test top ranked candidates through Verification Runner
        best_candidate_report = baseline_report
        best_candidate_params = dict(self.strategy_params)
        best_score = -999999.0

        for item in opt_report.results:
            candidate_runner = Rolling15TradeVerificationRunner(
                strategy_name=self.strategy_name,
                strategy_params=item.params,
                asset=self.asset,
                timeframe_seconds=self.timeframe_seconds,
                expiration_bars=int(item.params.get("base_expiration_bars", self.expiration_bars)),
                payout_rate=self.payout_rate,
                batch_size=self.batch_size,
                min_win_rate_pct=self.min_win_rate_pct,
                min_batch_pnl=self.min_batch_pnl,
            )
            v_report = candidate_runner.run(df_raw)

            # Score candidates: heavily bonus overall_passed, then min_batch_win_rate & min_batch_net_pnl
            score = (
                (1000.0 if v_report.overall_passed else 0.0)
                + float(v_report.min_batch_win_rate_pct) * 5.0
                + float(v_report.min_batch_net_pnl) * 2.0
                + float(v_report.avg_batch_win_rate_pct) * 2.0
                - float(v_report.max_consecutive_losses_overall) * 4.0
            )

            if score > best_score:
                best_score = score
                best_candidate_report = v_report
                best_candidate_params = item.params
                if v_report.overall_passed:
                    break

        best_candidate_report.tuned_params = best_candidate_params
        return best_candidate_report, best_candidate_params
```

---

## 5. Verification Method

### 5.1 Test Suites & Pytest Commands
To independently verify the implementation:

```bash
# 1. Run full unit and regression test suite
.venv/bin/pytest -v

# 2. Run specific verification benchmark suite
.venv/bin/pytest -v tests/test_rolling_15_trade_verification.py

# 3. Check linting and static analysis
.venv/bin/ruff check .
.venv/bin/mypy src/strat_trade
```

### 5.2 4-Tier Test Coverage Matrix for Milestone 3 (R3)

| Tier | Category | Proposed Test Function | Verification Target |
|:---|:---|:---|:---|
| **Tier 1** | Coverage | `test_verification_runner_15_trade_exact_pass` | 15 trades (8W/7L, WR 53.33%, PnL +$3.60 at 92% payout) passes. |
| **Tier 1** | Coverage | `test_verification_runner_15_trade_fail_winrate` | 15 trades (7W/8L, WR 46.67%, PnL -$15.60) fails with descriptive reason. |
| **Tier 1** | Coverage | `test_verification_runner_multi_batch_partition` | 45 trades correctly partitioned into exactly 3 disjoint batches (1-15, 16-30, 31-45). |
| **Tier 1** | Coverage | `test_verification_runner_rolling_windows` | 20 trades partitioned into 1 non-overlapping batch and 6 rolling sliding windows. |
| **Tier 1** | Coverage | `test_verification_runner_insufficient_trades` | $<15$ trades returns `INSUFFICIENT_TRADES` status without raising errors. |
| **Tier 2** | Boundary | `test_verification_runner_zero_trades` | 0 trades / empty DataFrame returns empty report with clean status. |
| **Tier 2** | Boundary | `test_verification_runner_exact_15_trades` | Exactly 15 trades produces exactly 1 batch and 1 rolling window. |
| **Tier 2** | Boundary | `test_verification_runner_draws_handling` | Batches containing DRAWs calculate decisive win rate without zero division. |
| **Tier 2** | Boundary | `test_verification_runner_payout_sensitivity` | Compares outcomes under 80%, 85%, and 92% payouts. |
| **Tier 2** | Boundary | `test_verification_runner_custom_winrate_threshold` | Tests custom `min_win_rate_pct` thresholds (e.g. 50.0%, 53.33%, 60.0%). |
| **Tier 3** | Pairwise | `test_verification_runner_with_optimizer_feedback_loop` | Verifies automated parameter tuning kicks in and resolves failing batches. |
| **Tier 3** | Pairwise | `test_verification_runner_percent_and_flat_stakes` | Verifies metrics across `StakeModel.FLAT` and `StakeModel.PERCENT`. |
| **Tier 4** | Workload | `test_verification_runner_60_trade_extended_synthetic_workload` | 60-trade multi-cycle validation across trending, ranging, and squeeze regimes. |

---

*Report prepared by `m3_explorer_1`. All findings and specifications directly supported by codebase investigation.*
