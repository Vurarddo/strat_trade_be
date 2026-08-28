# Backtesting Infrastructure & Rolling 15-Trade Verification Survey Report

## 1. Observation

### A. Codebase Architecture & Key Files
- **`src/strat_trade/domain/backtest/verification_runner.py`** (922 lines):
  - Defines `VerificationStatus` enum (`PASSED`, `FAILED`, `INSUFFICIENT_TRADES`).
  - Defines `STRATEGY_TUNING_SPACES` (lines 30–86) for 8 strategies (`volatility_squeeze_breakout`, `bollinger_atr_reversion`, `hybrid_multifactors`, `ema_pullback_trend`, `rsi_stochastic_extreme`, `macd_divergence_break`, `supertrend_adx_momentum`, `support_resistance_bounce`).
  - Defines `TradeBatchResult` (lines 90–138) with metrics: `batch_index`, `total_trades`, `winning_trades`, `losing_trades`, `draw_trades`, `win_rate_pct`, `net_pnl`, `roi_pct`, `profit_factor`, `max_consecutive_losses`, `max_consecutive_wins`, `max_drawdown_amount`, `max_drawdown_pct`, `passed`, `failure_reasons`.
  - Defines `RollingVerificationReport` (lines 145–190) aggregating non-overlapping batches and rolling sliding windows.
  - Implements `Rolling15TradeVerificationRunner` (lines 196–922):
    - `run(df_raw, params)` (lines 280–290): executes backtest over raw DataFrame and evaluates 15-trade batches.
    - `evaluate_trades(trades, params)` (lines 291–336): evaluates pre-existing list of `BacktestTrade` objects.
    - `evaluate_backtest_summary(summary, params)` (lines 350–524): partitions trade stream into non-overlapping batches ($[0:15], [15:30], \dots$) and rolling sliding windows ($[0:15], [1:16], \dots$, step=1).
    - `_evaluate_single_slice(slice_trades, ...)` (lines 525–649): calculates decisive win rate and validates batch passing rule.
    - `verify_or_optimize(df_raw, ...)` (lines 650–836): automated verification & minimax iterative auto-tuning feedback loop with train/holdout (70/30) split and parameter plateau stability check (`_check_parameter_plateau`).

- **`src/strat_trade/domain/backtest/data_loader.py`** (106 lines):
  - `parse_candles_csv_or_json(content, filename)` (lines 11–106): parses raw CSV/JSON text/bytes, normalizes timestamp/epoch formats (seconds/milliseconds to UTC datetime), validates OHLCV columns, drops NaNs, sorts chronologically.

- **`src/strat_trade/domain/backtest/engine.py`** & **`portfolio_engine.py`**:
  - `BinaryBacktestEngine`: single-asset sequential candle execution with binary options fixed expiration.
  - `PortfolioBacktestEngine`: multi-asset chronological backtesting with concurrent position limits, correlation conflict checks, and per-asset payout rates.

- **`src/strat_trade/domain/trading/asset_filter.py`** (100 lines):
  - `canonical_asset_key(asset)` (lines 38–46): normalizes symbol strings (e.g., `USD/IDR OTC`, `USDIDR_otc` -> `USDIDR`).
  - `DEFAULT_TOXIC_OTC_BLACKLIST` (lines 14–22): currently contains `USDIDR`, `USDVND`, `BNB`, `BNBUSD`, `EURCHF`.
  - `DEFAULT_HIGH_WINRATE_WHITELIST` (lines 25–35): currently contains `EURUSD`, `USDCLP`, `USDBDT`, `USDEGP`, `GBPJPY`, `GOLD`, `XAUUSD`.
  - `is_toxic_asset(asset)` (lines 48–65): evaluates asset against toxic blacklist.

- **`src/strat_trade/domain/optimizer/auto_matcher.py`** (482 lines):
  - `StrategyAutoMatcher`: multi-strategy evaluation across candle data to assign optimal strategy per asset.
  - Lines 322–339: currently uses `hybrid_multifactors` as the default heuristic fallback when historical candle data is sparse.
  - Lines 444–450: applies +15.0 quantum priority bonus to `PRIORITY_STRATEGIES` and +15.0 bonus to whitelisted assets.

- **`src/strat_trade/domain/trading/trade_store.py`** & **`data/trades.db`**:
  - `TradeStore`: SQLite database (`data/trades.db`) operating with WAL mode, storing persistent live/demo trade telemetry (`trades` table) including open/close prices, timestamps, strategy metadata, indicator snapshots, PnL, and balance history.

### B. Mathematical Formulations & Discrete 15-Trade Batch Rules
Under binary options broker payout structure ($P = 0.92$, Stake = $S = \$100.00$):
1. **Trade Level PnL**:
   - Win: $+S \times P = +\$92.00$
   - Loss: $-S = -\$100.00$
   - Draw: $\$0.00$
2. **Decisive Win Rate Calculation**:
   $$\text{Decisive Trades} = W + L$$
   $$\text{Win Rate \%} = \frac{W}{W + L} \times 100$$
   (Draws are excluded from the decisive denominator and produce zero PnL).
3. **15-Trade Discrete Batch Outcomes ($N = 15$)**:
   - **8 Wins, 7 Losses (53.33% WR)**:
     $$\text{Net PnL} = 8 \times 92 - 7 \times 100 = 736 - 700 = +\$36.00 \quad (\text{PASS})$$
   - **9 Wins, 6 Losses (60.00% WR)**:
     $$\text{Net PnL} = 9 \times 92 - 6 \times 100 = 828 - 600 = +\$228.00 \quad (\text{PASS})$$
   - **10 Wins, 5 Losses (66.67% WR)**:
     $$\text{Net PnL} = 10 \times 92 - 5 \times 100 = 920 - 500 = +\$420.00 \quad (\text{PASS})$$
   - **11 Wins, 4 Losses (73.33% WR)**:
     $$\text{Net PnL} = 11 \times 92 - 4 \times 100 = 1012 - 400 = +\$612.00 \quad (\text{PASS})$$
   - **7 Wins, 8 Losses (46.67% WR)**:
     $$\text{Net PnL} = 7 \times 92 - 8 \times 100 = 644 - 800 = -\$156.00 \quad (\text{FAIL})$$
4. **Batch Acceptance Logic** (`verification_runner.py:604–608`):
   ```python
   is_8_of_15_win = wins >= 8 and cnt == 15 and net_pnl > Decimal("0.0")
   passed_wr = (win_rate_pct >= self.min_win_rate_pct) or is_8_of_15_win
   passed_pnl = net_pnl > self.min_batch_pnl
   passed = passed_wr and passed_pnl and not is_partial
   ```
5. **Phase 3 Portfolio Targets (R3)**:
   - Overall Win Rate $\ge 58.0\%$.
   - Overall Net PnL $> \$1,500.00$ (and $> \$1,700.00$ for combined dataset acceptance).
   - Positive net growth on all sequential non-overlapping 15-trade batches ($0$ failed full batches).

### C. Test Suite & Linting Baseline Execution
- **Pytest Suite**:
  - Command: `.venv/bin/pytest`
  - Output: `472 passed, 2 warnings in 11.58s` (100% pass rate across 38 test files).
- **Ruff Linter**:
  - Command: `.venv/bin/ruff check src tests`
  - Output: `All checks passed!` (0 lint errors).

---

## 2. Logic Chain

1. **Verification Runner Operation & Architecture**:
   - `Rolling15TradeVerificationRunner` accepts either raw OHLCV candle DataFrames/lists or pre-computed `BacktestTrade`/`BacktestSummary` collections.
   - It computes both non-overlapping batches ($B_k = \text{trades}[15(k-1) : 15k]$) and sliding rolling windows ($W_r = \text{trades}[r : r + 15]$).
   - In single-batch evaluation (`_evaluate_single_slice`), decisive trades are isolated from ties/draws. The discrete boundary condition where 8 wins out of 15 trades yields $53.33\%$ WR (below standard $53.4\%$ threshold due to float rounding) is explicitly handled: $W \ge 8 \implies \text{Net PnL} = +\$36.00 > 0 \implies \text{PASS}$.

2. **Minimax Optimization & Overfitting Prevention**:
   - When any batch fails, `verify_or_optimize` performs a grid search over `STRATEGY_TUNING_SPACES`.
   - Datasets with $\ge 180$ bars undergo a 70/30 train/holdout split.
   - The multi-batch minimax fitness function evaluates:
     $$\text{Fitness} = 3.0 \cdot \min(\text{WR}_{\text{batch}}) + 1.0 \cdot \text{mean}(\text{WR}_{\text{batch}}) + 0.5 \cdot \text{PnL} - 1.5 \cdot \sigma(\text{WR}_{\text{batch}}) - 500 \cdot N_{\text{failed\_batches}}$$
   - Candidate parameter sets passing the training check are further evaluated on full data with a parameter plateau stability check (`_check_parameter_plateau`) by perturbing neighbor values.

3. **Phase 3 Requirements Mapping for Implementation**:
   - **R1 (Auto-Matcher Strategy Hierarchy & Hybrid Deprecation)**:
     - In `src/strat_trade/domain/optimizer/auto_matcher.py` (lines 322–339), change the fallback strategy from `hybrid_multifactors` to `supertrend_adx_momentum` (primary) and `macd_divergence_break` (secondary).
     - In `src/strat_trade/domain/strategies/hybrid_multifactors.py`, enforce strict trend confirmation (ADX $\ge 22.0$ with RSI + EMA + ADX agreement) to suppress false breakout entries.
   - **R2 (Expand Toxic OTC Asset Blacklist)**:
     - In `src/strat_trade/domain/trading/asset_filter.py`, add the newly identified toxic OTC pairs to `DEFAULT_TOXIC_OTC_BLACKLIST`:
       - `USDDZD` (`USD/DZD OTC`, 33.3% WR)
       - `UAHUSD` (`UAH/USD OTC`, 28.6% WR)
       - `USDMYR` (`USD/MYR OTC`, 33.3% WR)
       - `USDINR` (`USD/INR OTC`, 25.0% WR)
       - `EURHUF` (`EUR/HUF OTC`, 0.0% WR)
       - `GBPJPY` (`GBP/JPY OTC`, 0.0% WR)
     - Note: `GBPJPY` must be removed from `DEFAULT_HIGH_WINRATE_WHITELIST` and added to `DEFAULT_TOXIC_OTC_BLACKLIST`.
   - **R3 (Verification & Rolling 15-Trade Batch Validation)**:
     - Execute `Rolling15TradeVerificationRunner` across multi-batch sequences (e.g. 60–75 trades) to verify $\ge 58\%$ overall win rate, $> \$1,500$ ($> \$1,700$) net PnL, and positive deposit growth on sequential 15-trade batches.
     - Maintain 100% test pass rate across pytest and 0 ruff errors.

---

## 3. Caveats

- **Historical Database Size**: `data/trades.db` currently contains 1 recorded live trade in the repository's SQLite database file; backtesting verification and benchmark suites rely on synthetic multi-regime candle generators (`MultiRegimeCandleFactory`, `MultiRegimeStressCandleFactory`) and CSV/JSON ingestion (`parse_candles_csv_or_json`) for large sample generation ($\ge 250\text{--}500$ bars).
- **Mypy Static Typing**: While `ruff check` passes with 0 errors and `pytest` has 472 passing tests, `mypy src/strat_trade` currently shows type annotations warnings in domain strategies/portfolio engine that are not covered by the current ruff lint gate.
- No other caveats.

---

## 4. Conclusion

- The Backtesting Infrastructure and `Rolling15TradeVerificationRunner` are fully functional, mathematically accurate under binary options payout ($P = 0.92$, Stake = $\$100$), and equipped with multi-batch partitioning, sliding rolling windows, and minimax auto-tuning.
- The existing test suite encompasses 472 unit, integration, and adversarial tests passing with 100% success rate, and the codebase passes `ruff check` with 0 errors.
- The Phase 3 requirements (R1 auto-matcher hierarchy, R2 toxic blacklist expansion, R3 rolling 15-trade validation) are clearly delineated with exact file locations and mathematical acceptance thresholds ready for implementation.

---

## 5. Verification Method

To independently verify the backtesting infrastructure, test suite, and linting baseline, run the following commands in `/Users/vlados/work/projects/startup/strat_trade_be`:

1. **Run Full Pytest Test Suite**:
   ```bash
   .venv/bin/pytest -v
   ```
   *Expected outcome*: 472 tests pass in `tests/`.

2. **Run Rolling 15-Trade Verification & Regression Tests Specifically**:
   ```bash
   .venv/bin/pytest -v tests/test_rolling_15_regression.py tests/test_rolling_15_trade_verification.py tests/test_adversarial_rolling_verification.py
   ```
   *Expected outcome*: All discrete PnL, sliding window, and multi-batch tests pass.

3. **Run Ruff Linter**:
   ```bash
   .venv/bin/ruff check src tests
   ```
   *Expected outcome*: `All checks passed!` with 0 errors.

4. **Verify Direct 15-Trade Discrete Batch Mathematics via Python CLI**:
   ```bash
   .venv/bin/python -c "
   from decimal import Decimal
   from strat_trade.domain.backtest.models import BacktestTrade, TradeOutcome, TradeAction
   from strat_trade.domain.backtest.verification_runner import Rolling15TradeVerificationRunner, VerificationStatus
   from datetime import datetime, UTC, timedelta

   runner = Rolling15TradeVerificationRunner(payout_rate=Decimal('0.92'), stake_amount=Decimal('100.00'), min_win_rate_pct=Decimal('53.4'))
   trades = [
       BacktestTrade(
           entry_index=i, exit_index=i+1, entry_time=datetime.now(UTC)+timedelta(minutes=i),
           exit_time=datetime.now(UTC)+timedelta(minutes=i+1), action=TradeAction.CALL,
           entry_price=Decimal('1.10'), exit_price=Decimal('1.11') if i < 8 else Decimal('1.09'),
           stake=Decimal('100.00'), payout_rate=Decimal('0.92'),
           pnl=Decimal('92.00') if i < 8 else Decimal('-100.00'),
           outcome=TradeOutcome.WIN if i < 8 else TradeOutcome.LOSS,
           balance_after=Decimal('1000.00'), confidence=0.85, expiration_seconds=60, asset='EURUSD_otc'
       ) for i in range(15)
   ]
   rep = runner.evaluate_trades(trades)
   print('8 Wins / 7 Losses Net PnL:', rep.overall_net_pnl, 'Status:', rep.status.value)
   assert rep.overall_net_pnl == Decimal('36.00')
   assert rep.status == VerificationStatus.PASSED
   print('Mathematical verification PASSED.')
   "
   ```
