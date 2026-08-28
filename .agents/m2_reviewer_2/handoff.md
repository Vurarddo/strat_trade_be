# Milestone 2 Review Report: Bot Engine Execution Guardrails & Anti-Whipsaw (R2)

## Review Summary
- **Reviewer**: Reviewer 2 (Critic & Quality Reviewer)
- **Scope**: Milestone 2: Bot Engine Execution Guardrails & Anti-Whipsaw Protection
- **Verdict**: **`APPROVE`**

---

## 1. Observation
I directly inspected all 11 modified and added files across domain, use cases, API routes/schemas, and test suites:
- `src/strat_trade/domain/trading/correlation.py`:
  - Implements `normalize_symbol` for stripping OTC tags and non-alphanumerics.
  - Implements `extract_currency_pair` decomposing 6-character ISO/crypto tickers.
  - Implements `get_directional_exposure` mapping binary actions (`CALL` -> Long Base/Short Quote, `PUT` -> Long Quote/Short Base).
  - Implements `is_correlated_conflict` detecting Double Long, Double Short, and opposing currency exposure conflicts across live and backtest records.
  - Implements `get_portfolio_currency_exposure` and benchmark correlation lookups.
- `src/strat_trade/domain/trading/entities.py`:
  - Added `BotStatus.PAUSED` and `BotStatus.HALTED_BY_CIRCUIT_BREAKER`.
  - Extended `PreTradingPlan` with guardrail parameters: `cooldown_bars`, `global_cooldown_seconds`, `max_consecutive_losses`, `max_drawdown_pct_limit`, `correlation_filter_enabled`, `pause_duration_minutes`.
  - Extended `BotSessionSummary` with telemetry metrics: `consecutive_losses`, `peak_balance`, `current_drawdown_pct`, `paused_until`, `is_paused`, `circuit_breaker_triggered`.
- `src/strat_trade/domain/trading/bot_engine.py`:
  - Thread safety enforced with `_lock` (lifecycle operations) and `_order_lock` (order placement).
  - Per-asset post-settlement cooldown (`_asset_cooldown_until`) and global portfolio delay (`_last_global_execution_time`).
  - Active trades settlement loop runs continuously in `_run_loop`, allowing positions to settle cleanly during `PAUSED` state.
  - Automatic resume from cooling-off pause upon expiration of `paused_until`.
  - Circuit breakers for hard stop-loss and high-watermark peak-to-trough drawdown (`HALTED_BY_CIRCUIT_BREAKER`).
- `src/strat_trade/domain/backtest/models.py` & `portfolio_engine.py`:
  - Added full parity for all M2 guardrails (`cooldown_bars`, `global_cooldown_seconds`, `correlation_filter_enabled`, `max_consecutive_losses`, `max_drawdown_pct_limit`) inside `PortfolioBacktestEngine`.
- `src/strat_trade/use_cases/auto_assign_strategies.py` & `manage_live_bot.py`:
  - `generate_pre_trading_plan` initializes guardrail parameters.
  - `pause_live_bot` and `resume_live_bot` expose pause/resume control.
- `src/strat_trade/api/schemas.py` & `src/strat_trade/api/routes/bot.py`:
  - Pydantic models validated with strict bounds and `extra="forbid"`.
  - `POST /api/v1/bot/pause` and `POST /api/v1/bot/resume` endpoints implemented with telemetry responses.
- `tests/test_currency_correlation.py` (12 unit tests) & `tests/test_execution_guardrails.py` (12 unit tests):
  - Comprehensive coverage of currency decomposition, conflicts, cooldown timers, consecutive losses pause, high-watermark drawdown halt, API lifecycle, and backtester parity.

---

## 2. Logic Chain
1. **Integrity & Authenticity Check**:
   - Inspected source code for hardcoded test outcomes, dummy facades, or skipped logic.
   - All correlation logic, cooldown timers, lock synchronizations, and drawdown formulas are genuinely calculated and verified.
   - Result: **Passed (Zero Integrity Violations)**.

2. **Concurrency & Thread Safety Analysis**:
   - `_order_lock` serializes multi-asset order execution. Inside `_order_lock`, `_last_global_execution_time` and duplicate asset presence are re-evaluated atomically before placing orders.
   - Tested rapid concurrent execution using `asyncio.gather`: portfolio delay properly rejected concurrent conflicting entries.
   - Result: **Passed**.

3. **High-Watermark Drawdown vs Daily Stop-Loss**:
   - Verified that if account balance peaks above initial deposit and subsequently drops by >= `max_drawdown_pct_limit` (e.g. 8%), the bot transitions to `BotStatus.HALTED_BY_CIRCUIT_BREAKER`.
   - Verified that net session loss against starting deposit triggers `BotStatus.HALTED_BY_STOP_LOSS`.
   - Division by zero is prevented when balance or peak balance is 0.
   - Result: **Passed**.

4. **Timing Semantics & State Machine Resiliency**:
   - When consecutive losses reach `max_consecutive_losses`, status transitions to `PAUSED` and `paused_until` is set.
   - During `PAUSED` status, active positions continue to be monitored and settled, preventing unmonitored orphan positions.
   - Auto-resume seamlessly restores status to `RUNNING` and resets loss counter upon expiry.
   - Manual `resume()` clears pause state, resets loss counter, and restarts background task if stopped.
   - Result: **Passed**.

5. **Edge Case & Symbol Normalization Robustness**:
   - Non-forex symbols (stocks, unparseable strings) and `None`/empty inputs evaluate gracefully to `None` and do not false-positive block trades or throw exceptions.
   - Tested OTC formats: `EURUSD_otc`, `USD/CHF OTC`, `EUR/USD (OTC)`, `audnzd_otc`, `BTCUSD_otc`.
   - Result: **Passed**.

---

## 3. Caveats
- No unresolved defects or regressions identified.
- Default `cooldown_bars` uses a 60-second bar multiplier (`cooldown_bars * 60`). If multi-timeframe candles are introduced, multiplying by the assignment's candle timeframe will maintain proportional cooldowns.

---

## 4. Conclusion
- The Milestone 2 implementation satisfies all functional and non-functional requirements specified in `ORIGINAL_REQUEST.md` (§R2) and `PROJECT.md`.
- Code quality is clean, typed, modular, and conforms to project conventions.
- 189 tests pass cleanly in the test suite (with 24 dedicated to M2).
- Ruff static analysis reports 0 errors.
- **Verdict**: **`APPROVE`**.

---

## 5. Verification Method
Independently reproducible commands and verification steps:

```bash
# 1. Run all unit and regression tests
.venv/bin/pytest tests/

# 2. Run dedicated Milestone 2 test suites
.venv/bin/pytest tests/test_currency_correlation.py tests/test_execution_guardrails.py -v

# 3. Run Ruff static analysis
.venv/bin/ruff check src/ tests/
```

**Verification Results**:
- `pytest tests/`: 189 passed, 0 failed in 4.81s.
- `pytest tests/test_currency_correlation.py tests/test_execution_guardrails.py -v`: 24 passed in 1.17s.
- `ruff check src/ tests/`: All checks passed! 0 errors.
