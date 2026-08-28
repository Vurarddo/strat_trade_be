# Handoff Report: Automated Rolling 15-Trade Verification & Backtest Regression (R3)

**Explorer ID**: explorer_0_3  
**Working Directory**: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_0_3/`  
**Timestamp**: 2026-08-21T13:03:00Z  
**Parent Agent**: `14040b5c-ab25-44e2-afd8-52f95507aaa9` (orchestrator_1)

---

## 1. Observation

### 1.1 Architecture & Core Components for R3

#### A. `Rolling15TradeVerificationRunner` & Minimax Auto-Tuner
- **File**: `src/strat_trade/domain/backtest/verification_runner.py` (930 lines)
- **Lines 30–86**: `STRATEGY_TUNING_SPACES` dictionary containing parameter grid definitions for 8 strategies:
  * `volatility_squeeze_breakout` (`kc_mult`, `momentum_period`, `bb_length`, `base_expiration_bars`)
  * `bollinger_atr_reversion` (`adx_trend_threshold`, `min_wick_ratio`, `rsi_oversold`, `rsi_overbought`, `bb_std`, `max_atr_ratio`, `base_expiration_bars`)
  * `hybrid_multifactors` (`adx_trend_threshold`, `rsi_oversold`, `rsi_overbought`, `ema_fast`, `ema_mid`, `bb_std`, `base_expiration_bars`)
  * `ema_pullback_trend` (`adx_threshold`, `ema_fast`, `ema_mid`, `base_expiration_bars`)
  * `rsi_stochastic_extreme` (`rsi_period`, `rsi_oversold`, `rsi_overbought`, `stoch_oversold`, `stoch_overbought`, `base_expiration_bars`)
  * `macd_divergence_break` (`macd_fast`, `macd_slow`, `macd_sign`, `base_expiration_bars`)
  * `supertrend_adx_momentum` (`atr_period`, `atr_multiplier`, `adx_threshold`, `base_expiration_bars`)
  * `support_resistance_bounce` (`swing_window`, `min_wick_ratio`, `base_expiration_bars`)
- **Lines 90–138**: `TradeBatchResult` dataclass tracking 15-trade batch metrics (`batch_index`, `start_trade_index`, `end_trade_index`, `winning_trades`, `losing_trades`, `draw_trades`, `win_rate_pct`, `net_pnl`, `roi_pct`, `profit_factor`, `max_consecutive_losses`, `max_drawdown_amount`, `max_drawdown_pct`, `passed`, `failure_reasons`).
- **Lines 145–190**: `RollingVerificationReport` dataclass tracking overall results across all disjoint batches and sliding rolling windows (`total_batches`, `passed_batches`, `failed_batches`, `all_batches_passed`, `status: VerificationStatus`, `overall_win_rate_pct`, `overall_net_pnl`, `auto_tuned`, `tuned_params`, `tuning_report`).
- **Lines 196–254**: `Rolling15TradeVerificationRunner.__init__`:
  * Default params: `payout_rate=Decimal("0.92")`, `min_win_rate_pct=Decimal("53.4")`, `batch_size=15`, `min_batch_pnl=Decimal("0.0")`, `auto_tune_on_failure=True`, `compute_rolling_windows=True`, `enable_plateau_check=True`.
- **Lines 280–290**: `run(df_raw, params)` executes full backtest with `BinaryBacktestEngine` and evaluates batches.
- **Lines 291–336**: `evaluate_trades(trades, params)` evaluates a pre-existing list of `BacktestTrade` objects.
- **Lines 350–528**: `evaluate_backtest_summary(summary, params)`:
  * Non-overlapping partition: `trades[b * 15 : (b + 1) * 15]`
  * Sliding rolling windows (step = 1 trade): `trades[r : r + 15]` for $r \in [0, N - 15]$
  * Remainder handling: partial batches are flagged (`is_partial=True`) and excluded from hard pass/fail batch counts.
- **Lines 529–652**: `_evaluate_single_slice(slice_trades, ...)`:
  * Decisive win rate: $WR = \frac{W}{W + L} \times 100\%$ (draws excluded from denominator).
  * Net PnL: $\sum \text{pnl} = 0.92 \cdot W \cdot \text{stake} - 1.0 \cdot L \cdot \text{stake}$.
  * Batch Pass Rule (Lines 606–613):
    ```python
    is_8_of_15_win = wins >= 8 and cnt == 15 and net_pnl > Decimal("0.0")
    passed_wr = (win_rate_pct >= self.min_win_rate_pct) or is_8_of_15_win
    passed_pnl = net_pnl > self.min_batch_pnl
    passed = passed_wr and passed_pnl and not is_partial
    ```
- **Lines 654–844**: Minimax Multi-Batch Auto-Tuner (`verify_or_optimize`):
  * Holdout split on large datasets ($N \ge 180$ bars): 70% train / 30% holdout split.
  * Multi-batch fitness objective score (Lines 748–754):
    $$\text{Score} = 3.0 \cdot \min(WR) + 1.0 \cdot \text{mean}(WR) + 0.5 \cdot \text{NetPnL} - 1.5 \cdot \text{std}(WR) - 500.0 \cdot \text{failed\_batches}$$
  * Parameter plateau stability check (Lines 872–911, `_check_parameter_plateau`): perturbs candidate parameters by $\pm 1$ step in grid to ensure average neighbor WR $\ge 50.0\%$ (prevents overfitted parameter spikes).

#### B. Execution Use Cases & API Endpoints
- **`src/strat_trade/use_cases/verify_strategy.py:19-104`**: `execute_rolling_15_verification(feed, asset, timeframe_seconds, strategy_name, strategy_params, payout_rate=0.92, initial_deposit=1000.0, stake_amount=10.0, batch_size=15, min_win_rate_pct=53.4, auto_tune=False, ...)`
- **`src/strat_trade/use_cases/run_backtest.py:23-109`**: `execute_backtest` (single asset backtest engine)
- **`src/strat_trade/use_cases/run_portfolio_backtest.py:23-118`**: `execute_portfolio_backtest` (multi-asset chronological portfolio backtesting engine)
- **`src/strat_trade/use_cases/optimize_strategy.py:24-91`**: `execute_strategy_optimization`
- **`src/strat_trade/domain/optimizer/grid_search.py:42-170`**: `StrategyOptimizerEngine` (Cartesian product hyperparameter grid search)
- **`src/strat_trade/api/routes/backtest.py:460-495`**: `POST /api/v1/backtest/verify-15-trades` FastAPI endpoint.

---

### 1.2 Datasets, Trade Logs & Ingestion Mechanisms

#### A. Historical Candle Datasets & Ingestion
- **File**: `src/strat_trade/domain/backtest/data_loader.py:11-106` (`parse_candles_csv_or_json`):
  * Parses CSV or JSON strings/bytes into standardized DataFrame (`timestamp`, `open`, `high`, `low`, `close`, `volume`).
  * Normalizes column aliases (`time`, `datetime`, `date`, `t`, `ts` $\to$ `timestamp`; `open`, `o` $\to$ `open`; `high`, `h`, `max` $\to$ `high`; `low`, `l`, `min` $\to$ `low`; `close`, `c`, `price` $\to$ `close`; `volume`, `vol`, `v` $\to$ `volume`).
  * Handles integer/float epoch timestamps (auto-detects milliseconds vs seconds) and ISO 8601 strings.
  * Auto-sorts chronologically (`df.sort_values("timestamp", kind="mergesort")`).
- **File**: `src/strat_trade/ports/candles.py:12-25` (`CandleFeed` interface for live/broker candle streaming).

#### B. Persistent Broker Trade Logs
- **File**: `data/trades.db` (SQLite in WAL mode).
- **File**: `src/strat_trade/domain/trading/trade_store.py:17-237` (`TradeStore`):
  * Stores live/demo broker trades in `trades` table with columns: `trade_id`, `broker_order_id`, `asset`, `action`, `stake`, `open_time`, `expiration_seconds`, `open_price`, `close_time`, `close_price`, `strategy_id`, `strategy_name`, `strategy_params`, `indicator_snapshot`, `confidence`, `reason`, `payout_rate`, `outcome`, `pnl`, `balance_after`, `is_merged_with_broker`, `broker_profit`, `slippage`, `created_at`.
- **Observed Database Content**:
  * Total recorded trades: **511** trades across 70 currency/crypto/commodity pairs.
  * Trade counts by strategy:
    - `Bollinger + ATR Mean Reversion`: 39 trades, PnL = -$1,428.00
    - `EMA Ribbon Trend Pullback`: 49 trades, PnL = -$848.00 (confirming need for deactivation / R1 filtering)
    - `MACD Divergence & Cross`: 150 trades, PnL = -$961.00
    - `RSI + Stoch Extreme Scalp`: 99 trades, PnL = -$2,076.00
    - `SuperTrend + ADX Momentum`: 77 trades, PnL = +$217.00
    - `Support & Resistance Pin-Bar`: 58 trades, PnL = -$171.00
    - `TTM Volatility Squeeze Breakout`: 15 trades, PnL = -$476.00
    - `Гібридна Мульти-Факторна`: 21 trades, PnL = -$2.00
  * Trade counts on toxic assets:
    - `USD/VND OTC`: 22 trades, PnL = -$861.00
    - `USD/IDR OTC`: 18 trades, PnL = -$84.00
    - `USD/MYR OTC`: 9 trades, PnL = -$708.00
    - `USD/CLP OTC`: 9 trades, PnL = -$516.00
    - `GBP/JPY OTC`: 9 trades, PnL = -$516.00

#### C. Broker Report Reconciliation & Merger
- **File**: `src/strat_trade/domain/analytics/xls_merger.py:17-397` (`BrokerReportMerger`):
  * Ingests XLS (`xlrd`/HTML parser), XLSX (`openpyxl`), and CSV files exported from Pocket Option.
  * Merges broker execution records with internal database telemetry via exact `order_id` or timestamp ($\pm 10\text{s}$) + asset fuzzy matching.
  * Computes execution slippage ($\Delta = |\text{broker\_open} - \text{internal\_open}|$) and per-strategy/per-asset breakdowns.
  * Exports merged dataset back to Excel/CSV with indicator snapshots.

---

### 1.3 15-Trade Batch Evaluation Mathematics ($100 Stake, 92% Payout)

Under binary options broker payout structure (+92% / -100% / 0%):
- **Stake**: $\$100.00$
- **Win PnL**: $+\$92.00$
- **Loss PnL**: $-\$100.00$
- **Draw/Tie PnL**: $\$0.00$
- **Decisive Win Rate**: $WR = \frac{W}{W + L} \times 100\%$

| Wins ($W$) | Losses ($L$) | Win Rate ($WR$) | Gross Profit | Gross Loss | Net Batch PnL ($100 Stake) | Batch Pass Status |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 15 | 0 | 100.00% | $1,380.00 | $0.00 | **+$1,380.00** | PASS |
| 14 | 1 | 93.33% | $1,288.00 | $100.00 | **+$1,188.00** | PASS |
| 13 | 2 | 86.67% | $1,196.00 | $200.00 | **+$996.00** | PASS |
| 12 | 3 | 80.00% | $1,104.00 | $300.00 | **+$804.00** | PASS |
| 11 | 4 | 73.33% | $1,012.00 | $400.00 | **+$612.00** | PASS |
| 10 | 5 | 66.67% | $920.00 | $500.00 | **+$420.00** | PASS |
| 9 | 6 | 60.00% | $828.00 | $600.00 | **+$228.00** | PASS ($>56\%$ WR & $>0$ PnL) |
| 8 | 7 | 53.33% | $736.00 | $700.00 | **+$36.00** | PASS (8-of-15 exception: $>0$ PnL) |
| 7 | 8 | 46.67% | $644.00 | $800.00 | **-$156.00** | FAIL ($<53.4\%$ WR & $<0$ PnL) |
| 6 | 9 | 40.00% | $552.00 | $900.00 | **-$348.00** | FAIL |
| 0 | 15 | 0.00% | $0.00 | $1,500.00 | **-$1,500.00** | FAIL |

**Acceptance Criteria for R3**:
1. **Overall Win Rate**: $\ge 56.0\%$ (requires average $\ge 9$ wins per 15 trades).
2. **Overall Net PnL**: $> \$1,500.00$ at $\$100$ stake (e.g. across a 200–500 candle backtest dataset).
3. **Batch Consistency**: **0 negative batches** (every sequential 15-trade non-overlapping batch must have $\text{Net PnL} > 0$, i.e. $W \ge 8$).

---

### 1.4 Test Suite Survey & Execution Results

- **Test Framework**: Pytest (`.venv/bin/pytest`)
- **Total Test Files**: 34 test files in `tests/`
- **Total Test Cases**: **381 collected items**
- **Test Result**: **381 passed in 7.85s** (100% pass rate)

#### Summary of Test Inventory:
| Test File | Test Count | Scope |
|---|:---:|---|
| `test_rolling_15_trade_verification.py` | 44 | Discrete batch math, 92% payout break-even, 8-of-15 edge cases, Martingale/percent stake, ties/draws, sliding windows, synthetic candles |
| `test_adversarial_rolling_verification.py` | 30 | Variable sequence lengths ($N=0, 1, 14, 15, 16, 29, 30, 31, 100, 1000$), floating point precision, loss clusters, plateau stability |
| `test_m3_adversarial_stress_verification.py` | 13 | Multi-batch auto-tuner minimax optimization, 70/30 OOS train/holdout split, extreme noise robustness |
| `test_m4_empirical_challenger.py` | 17 | Trade store rate limits, cooldowns, burst limits, broker reconciliation, bot engine guardrails |
| `test_strategy_optimizer.py` & `test_optimizer_api.py` | 3 | Grid search ranking formula, Cartesian products, API optimization endpoints |
| `test_backtest_models_and_engine.py` & `test_backtest_api.py` | 8 | Binary backtest engine, execution simulation, stop loss, API routes |
| `test_portfolio_backtest_models_and_engine.py` & `test_portfolio_backtest_api.py` | 3 | Chronological multi-asset simulation, concurrent trade allocation |
| `test_backtest_data_loader.py` | 4 | CSV/JSON parsing, epoch/ISO timestamp conversions, alias column mapping |
| `test_live_trade_store.py` & `test_broker_xls_merger.py` | 2 | SQLite persistence, WAL mode, broker report fuzzy matching |
| `test_adversarial_guardrails.py` & `test_m2_adversarial_stress.py` | 82 | Strategy signal validation, toxic pair rejection, max concurrent limits |
| Strategy & Indicator Unit Tests (20 files) | 175 | Individual indicator mathematics (RSI, ADX, ATR, MACD, Stoch, BB, etc.) and strategy signals |

#### Quality & Lint Gate Findings:
- **`ruff check src tests`**: **0 errors** (all imports sorted, formatted).
- **`mypy src/strat_trade`**: 82 typing errors in 8 files (primarily due to optional/union typing `float | None` in `hybrid_multifactors.py`, `portfolio_engine.py`, and `auto_matcher.py`). Pytest executes without issue.

---

## 2. Logic Chain

1. **R3 Core Goal**: Verify systematic strategy performance and parameter optimization across sequential 15-trade batches to guarantee deposit growth without single-point failure batches.
2. **Batch Slicing Logic**:
   - `Rolling15TradeVerificationRunner` segments the chronological trade stream into $K = \lfloor N / 15 \rfloor$ non-overlapping windows of 15 trades.
   - It also generates $N - 15 + 1$ rolling sliding windows (step = 1 trade) for continuous streak auditing.
   - Any remainder trades ($N \pmod{15}$) are flagged as `is_partial=True` to prevent false failure alarms.
3. **Discrete Break-Even Mathematics**:
   - Under standard Pocket Option OTC payout (92%), a $\$100$ stake yields $+\$92$ on WIN and $-\$100$ on LOSS.
   - For a 15-trade batch, 8 wins / 7 losses produces $8 \times 92 - 7 \times 100 = +\$36.00$ ($WR = 53.33\%$).
   - 9 wins / 6 losses produces $9 \times 92 - 6 \times 100 = +\$228.00$ ($WR = 60.00\%$).
   - The condition `is_8_of_15_win` ensures mathematical consistency so that any batch generating positive net deposit growth is recognized as passed.
4. **Auto-Tuning Feedback Mechanism**:
   - When a strategy fails the 15-trade benchmark on historical data, `verify_or_optimize()` invokes minimax parameter optimization across `STRATEGY_TUNING_SPACES`.
   - The minimax objective function heavily penalizes failed batches ($-500 \cdot \text{failed\_batches}$) and win rate variance ($-1.5 \cdot \text{std}(WR)$), while maximizing the worst-case batch ($3.0 \cdot \min(WR)$).
   - OOS validation (70% train / 30% test) and parameter plateau perturbations prevent curve-fitting.

---

## 3. Caveats

1. **Live Trade Database PnL**: `data/trades.db` has 511 trades from previous live/demo bot sessions before strategy curation and asset filtering. Historical data shows significant drawdowns on `EMA Ribbon Trend Pullback` (-$848) and toxic OTC assets (`USD/VND OTC` -$861, `USD/MYR OTC` -$708). In M3, backtesting regression must run with M1 curated strategy rules and M2 asset blacklist applied.
2. **Mypy Type Errors**: Running `mypy src/strat_trade` flags 82 static typing discrepancies across 8 files (e.g. `hybrid_multifactors.py` lines 210-260, `portfolio_engine.py` lines 230-336). These do not prevent Python runtime execution or pytest passing, but should be addressed during M1–M3 implementation for clean gate compliance.

---

## 4. Conclusion

- The codebase possesses a fully developed, robust, and tested framework for Automated Rolling 15-Trade Verification (`Rolling15TradeVerificationRunner`), Minimax Auto-Tuning, and Backtest Regression in `src/strat_trade/domain/backtest/verification_runner.py`.
- The data ingestion pipeline supports CSV, JSON, and live broker feeds (`parse_candles_csv_or_json`), as well as persistent trade telemetry (`data/trades.db`) and broker report reconciliation (`BrokerReportMerger`).
- All 381 unit and integration tests are currently passing in `.venv/bin/pytest` in under 8 seconds.
- The system is completely prepared for M1 strategy curation, M2 toxic asset blacklisting, and subsequent M3 empirical regression verification.

---

## 5. Verification Method

To independently verify the observations and findings in this report:

### Step 1: Run Full Pytest Suite
```bash
cd /Users/vlados/work/projects/startup/strat_trade_be
.venv/bin/pytest
```
*Expected Result*: 381 passed in ~8 seconds.

### Step 2: Run Targeted Verification Runner Tests
```bash
.venv/bin/pytest tests/test_rolling_15_trade_verification.py tests/test_adversarial_rolling_verification.py tests/test_m3_adversarial_stress_verification.py -v
```
*Expected Result*: 87 passed.

### Step 3: Inspect Database & Historical Trades
```bash
python3 -c "import sqlite3; conn = sqlite3.connect('data/trades.db'); cur = conn.cursor(); print('Trades:', cur.execute('SELECT count(*) FROM trades').fetchone()[0])"
```
*Expected Result*: 511 trades.

### Step 4: Execute Programmatic Rolling 15-Trade Verification
```python
import pandas as pd
from decimal import Decimal
from strat_trade.domain.backtest.verification_runner import Rolling15TradeVerificationRunner

# Create synthetic 30-trade test sequence (60% win rate)
from strat_trade.domain.backtest.models import BacktestTrade, TradeAction, TradeOutcome
from datetime import datetime, UTC, timedelta

trades = [
    BacktestTrade(
        entry_index=i*3, exit_index=i*3+3,
        entry_time=datetime(2026, 8, 20, tzinfo=UTC) + timedelta(minutes=i*3),
        exit_time=datetime(2026, 8, 20, tzinfo=UTC) + timedelta(minutes=i*3+3),
        action=TradeAction.CALL, entry_price=Decimal("1.1000"), exit_price=Decimal("1.1005"),
        stake=Decimal("100.0"), payout_rate=Decimal("0.92"),
        pnl=Decimal("92.0") if i % 5 in (0, 1, 2) else Decimal("-100.0"),
        outcome=TradeOutcome.WIN if i % 5 in (0, 1, 2) else TradeOutcome.LOSS,
        balance_after=Decimal("1000.0"), confidence=0.85, expiration_seconds=180, asset="EURUSD_otc"
    )
    for i in range(30)
]

runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"), stake_amount=Decimal("100.0"))
report = runner.evaluate_trades(trades)
assert report.total_batches == 2
assert report.all_batches_passed is True
assert report.status.value == "PASSED"
print("Verification check passed successfully.")
```
