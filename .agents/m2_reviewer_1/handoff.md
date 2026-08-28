# Milestone 2 Review & Adversarial Challenge Report: Bot Engine Guardrails & Anti-Whipsaw (R2)

## Review Summary

**Verdict**: `REQUEST_CHANGES`

The overall implementation of Milestone 2 (currency correlation filter, post-settlement cooldown timers, global portfolio delays, consecutive loss pause state machine, high-watermark drawdown circuit breaker, and backtesting simulation parity) is well-architected, genuine, and verified by 189 passing tests. There are no integrity violations (no hardcoded test bypasses, facade implementations, or simulated results).

However, an adversarial state-machine investigation surfaced a **Major Lifecycle Defect**: when `LiveDemoBotEngine` is halted by `BotStatus.HALTED_BY_CIRCUIT_BREAKER` and an operator invokes `resume()` (via `POST /api/v1/bot/resume` or `engine.resume()`), `self.peak_balance` and `self.current_drawdown_pct` are not reset to the current account equity. As a result, the background `_run_loop()` immediately re-evaluates `_check_circuit_breakers()` on the first 4-second tick, detects the exact same peak-to-trough drawdown percentage ($\ge \text{limit}$), and instantly transitions back into `BotStatus.HALTED_BY_CIRCUIT_BREAKER`. This renders the resume lifecycle unusable after a drawdown circuit breaker trip.

---

## 1. Observation

### Codebase Inspection & Line References

1. **`src/strat_trade/domain/trading/bot_engine.py` (lines 127–142)**:
   ```python
   async def resume(self) -> None:
       async with self._lock:
           if self.status not in (BotStatus.PAUSED, BotStatus.HALTED_BY_CIRCUIT_BREAKER):
               logger.warning("Cannot resume bot in status %s", self.status.value)
               return

           self.status = BotStatus.RUNNING
           self.paused_until = None
           self.consecutive_losses = 0  # Reset loss streak upon manual resume

           # Ensure background trading loop is active if it was terminated
           if self._task is None or self._task.done():
               self._task = asyncio.create_task(self._run_loop())

           logger.info("LiveDemoBotEngine resumed by user to RUNNING")
   ```
   *Observation*: `self.peak_balance` is NOT reset to `self.current_balance`, and `self.current_drawdown_pct` is NOT reset to `0.0`.

2. **`src/strat_trade/domain/trading/bot_engine.py` (lines 237–256)**:
   ```python
   # 2. Peak-to-Trough High-Watermark Drawdown Circuit Breaker
   if self.peak_balance > Decimal("0.00"):
       drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
       self.current_drawdown_pct = max(0.0, float(drawdown * Decimal("100.0")))
       if self.current_drawdown_pct > self.max_drawdown_pct:
           self.max_drawdown_pct = self.current_drawdown_pct

       limit_pct = self.plan.max_drawdown_pct_limit * 100.0
       if self.current_drawdown_pct >= limit_pct:
           self.status = BotStatus.HALTED_BY_CIRCUIT_BREAKER
           logger.error(...)
           return
   ```
   *Observation*: In `_run_loop()`, `_check_circuit_breakers()` runs before `_evaluate_signals_and_trade()`. When `peak_balance` is $1200 and `current_balance` is $1100 ($8.33\%$ drawdown $\ge 8.0\%$), resuming without resetting `peak_balance` triggers this check on tick 1, resetting status to `HALTED_BY_CIRCUIT_BREAKER` and breaking out of `_run_loop()`.

3. **`src/strat_trade/domain/trading/correlation.py`**:
   - `normalize_symbol()` properly normalizes OTC suffixes (`_otc`, `-otc`, `(OTC)`, `OTC`), delimiters, and case.
   - `extract_currency_pair()` extracts `(base, quote)` for 6-letter currency codes and returns `None` for invalid or non-forex single-token tickers.
   - `get_directional_exposure()` maps `CALL` to Long base / Short quote, and `PUT` to Long quote / Short base.
   - `is_correlated_conflict()` prevents Double Long, Double Short, and (optionally) Opposing exposures across `LiveTradeRecord`, `BacktestTrade`, and `dict` trade representations.
   - `get_portfolio_currency_exposure()` sums net directional units per currency.

4. **`src/strat_trade/domain/backtest/portfolio_engine.py`**:
   - Implements identical guardrail mechanisms in chronological order: per-asset settlement cooldown (`cooldown_bars`), global portfolio entry spacing (`global_cooldown_seconds`), correlation filtering (`is_correlated_conflict`), consecutive loss pause (15-minute signal block), and high-watermark drawdown halt (`max_drawdown_pct_limit`).

5. **`tests/` Execution**:
   - `.venv/bin/pytest tests/`: 189 passed, 0 failed in 4.74s.
   - `.venv/bin/ruff check src/ tests/`: 0 errors.

---

## 2. Logic Chain

1. **Intended State Machine Behavior**:
   The requirements (ORIGINAL_REQUEST §R2, PROJECT.md §M2) and API design (`POST /api/v1/bot/resume`) state that the operator can resume the bot from `PAUSED` or `HALTED_BY_CIRCUIT_BREAKER`.
2. **Defect Mechanism**:
   When the bot halts due to high-watermark peak drawdown:
   - `peak_balance = $1200.00`
   - `current_balance = $1100.00`
   - `current_drawdown_pct = 8.33%` ($\ge 8.00\%$)
   - `status = BotStatus.HALTED_BY_CIRCUIT_BREAKER`
   When `resume()` is called:
   - `self.status = BotStatus.RUNNING`
   - `_run_loop()` task starts.
   - On tick 1 of `_run_loop()`: `await self._check_circuit_breakers()` executes.
   - `drawdown = ($1200.00 - $1100.00) / $1200.00 = 8.33%`.
   - `8.33% >= 8.00%` $\rightarrow$ `self.status = BotStatus.HALTED_BY_CIRCUIT_BREAKER`, `_run_loop()` breaks immediately.
3. **Financial Rationale for Fix**:
   A manual operator resume after an acknowledged circuit breaker event signifies resetting the reference high-watermark baseline (`self.peak_balance = self.current_balance`, `self.current_drawdown_pct = 0.0`) so that future drawdown is calculated relative to the new operational capital.

---

## 3. Findings & Required Fixes

### [Major] Finding 1: Instant Re-Halt on Resume from `HALTED_BY_CIRCUIT_BREAKER`

- **What**: Calling `LiveDemoBotEngine.resume()` does not update `peak_balance` to `current_balance` or reset `current_drawdown_pct`, causing immediate re-halting on the very first loop iteration.
- **Where**: `src/strat_trade/domain/trading/bot_engine.py:127-142`
- **Why**: Renders the manual resume feature completely inoperative after a peak drawdown circuit breaker halt.
- **Suggested Fix**:
  In `LiveDemoBotEngine.resume()`:
  ```python
  async def resume(self) -> None:
      async with self._lock:
          if self.status not in (BotStatus.PAUSED, BotStatus.HALTED_BY_CIRCUIT_BREAKER):
              logger.warning("Cannot resume bot in status %s", self.status.value)
              return

          self.status = BotStatus.RUNNING
          self.paused_until = None
          self.consecutive_losses = 0

          # Reset high-watermark baseline if resuming from a circuit breaker halt
          if self.current_balance > Decimal("0.00"):
              self.peak_balance = self.current_balance
              self.current_drawdown_pct = 0.0

          # Ensure background trading loop is active if it was terminated
          if self._task is None or self._task.done():
              self._task = asyncio.create_task(self._run_loop())

          logger.info("LiveDemoBotEngine resumed by user to RUNNING")
  ```
  Also add a dedicated unit test in `tests/test_execution_guardrails.py` verifying that after `HALTED_BY_CIRCUIT_BREAKER`, calling `resume()` allows the bot to continue running for subsequent loop ticks without immediately re-halting.

---

## 4. Adversarial Stress-Test Results

| # | Stress Scenario | Expected Behavior | Actual Behavior | Result |
|---|---|---|---|---|
| 1 | Normalization of tricky OTC symbols (`EUR/USD (OTC)`, `usd/chf-otc`, `AUDUSD_otc`) | Clean 6-letter canonical symbol | Returns `EURUSD`, `USDCHF`, `AUDUSD` | **PASS** |
| 2 | Candidate trade on `AUDNZD` (CALL) while `AUDUSD` (CALL) is active | Conflict detected: Double Long AUD | Returns `(True, "Conflict: Double Long AUD ...")` | **PASS** |
| 3 | Candidate trade on `USDCHF` (PUT) while `EURUSD` (CALL) is active | Conflict detected: Double Short USD | Returns `(True, "Conflict: Double Short USD ...")` | **PASS** |
| 4 | Candidate trade on `AUDNZD` while `EURUSD` is active (uncorrelated) | No conflict | Returns `(False, "")` | **PASS** |
| 5 | Concurrent order execution during global cooldown window | Order rejected / delayed | Only 1st order executes; 2nd order blocked under `_order_lock` | **PASS** |
| 6 | Trade settlement triggers per-asset cooldown | Asset locked for $N$ bars | Signal evaluation skipped during cooldown window | **PASS** |
| 7 | $K=3$ consecutive losses trigger cooling-off pause | Status $\rightarrow$ `PAUSED`, `paused_until` set for 15m | Status becomes `PAUSED`, active trades settle, new entries blocked | **PASS** |
| 8 | Winning trade settles after 2 losses | `consecutive_losses` resets to 0 | Streak resets to 0, status remains `RUNNING` | **PASS** |
| 9 | Peak-to-trough drawdown exceeds 8% | Status $\rightarrow$ `HALTED_BY_CIRCUIT_BREAKER` | Status transitions to `HALTED_BY_CIRCUIT_BREAKER`, loop halts | **PASS** |
| 10 | Manual resume from `HALTED_BY_CIRCUIT_BREAKER` | Bot resumes and continues running | **Fails**: Re-halts on tick 1 due to stale `peak_balance` | **FAIL** (Finding 1) |
| 11 | Portfolio backtester parity with correlation filter & cooldowns | Backtest trades filtered identically | Unfiltered (34 trades) $\rightarrow$ Filtered (17 trades) | **PASS** |
| 12 | Consecutive loss backtest suppression | Max consecutive loss capped at $K$ | Uncapped (4 losses) $\rightarrow$ Capped (2 losses) with 15m pauses | **PASS** |

---

## 5. Verified Claims & Parity Check

- **Currency Correlation Filter**: Verified via `tests/test_currency_correlation.py` and live bot / backtest simulation scripts. Correctly decomposes directional delta into base/quote exposures and blocks concentration.
- **Cooldown Timers**: Verified per-asset bar-based cooldown and global portfolio entry spacing.
- **Consecutive Loss Circuit Breaker**: Verified auto-pause state transition, 15m cooling-off timer, auto-resume, and streak reset on win.
- **REST Endpoints & Schemas**: Verified `/api/v1/bot/auto-assign`, `/start`, `/stop`, `/pause`, `/resume`, `/status`, and `/trades`.
- **Backtesting Parity**: `PortfolioBacktestEngine` mirrors `LiveDemoBotEngine` guardrail execution logic.

---

## 6. Caveats

- In `bot_engine._execute_order()`, when `global_cooldown_seconds == 0`, adding a redundant `is_correlated_conflict` check inside `_order_lock` is recommended for defense-in-depth against near-simultaneous asyncio tasks.
- No other regressions or edge-case failures were identified across the 189 tests.

---

## 7. Conclusion & Actionable Next Steps

**Verdict**: `REQUEST_CHANGES`

To complete Milestone 2:
1. Update `LiveDemoBotEngine.resume()` in `src/strat_trade/domain/trading/bot_engine.py` to reset `self.peak_balance = self.current_balance` and `self.current_drawdown_pct = 0.0` when resuming from a circuit breaker halt.
2. Add a regression test in `tests/test_execution_guardrails.py` asserting that resuming after `HALTED_BY_CIRCUIT_BREAKER` keeps the bot in `BotStatus.RUNNING` over multiple loop ticks.
3. Re-run `pytest` and `ruff`.

---

## 8. Verification Method

1. **Execute full test suite**:
   ```bash
   .venv/bin/pytest tests/
   ```
2. **Execute guardrails and correlation tests**:
   ```bash
   .venv/bin/pytest tests/test_currency_correlation.py tests/test_execution_guardrails.py -v
   ```
3. **Execute lint checks**:
   ```bash
   .venv/bin/ruff check src/ tests/
   ```
4. **Reproduce Finding 1**:
   ```bash
   .venv/bin/python -c "
   import asyncio
   from decimal import Decimal
   from unittest.mock import AsyncMock
   from strat_trade.domain.trading.bot_engine import LiveDemoBotEngine
   from strat_trade.domain.trading.entities import PreTradingPlan, BotStatus

   async def run():
       engine = LiveDemoBotEngine()
       plan = PreTradingPlan(
           assignments=[], total_assets=0, initial_deposit=Decimal('1000.00'),
           stake_model='flat', stake_amount=Decimal('10.00'), stake_percent=1.0,
           expiration_seconds=180, daily_stop_loss_pct=0.5,
           stop_loss_amount=Decimal('500.00'), max_concurrent_trades=3,
           min_payout_rate=0.8, max_drawdown_pct_limit=0.08,
       )
       await engine.start(plan, AsyncMock())
       engine.peak_balance = Decimal('1200.00')
       engine.current_balance = Decimal('1100.00')
       await engine._check_circuit_breakers()
       assert engine.status == BotStatus.HALTED_BY_CIRCUIT_BREAKER
       await engine.resume()
       assert engine.status == BotStatus.RUNNING
       await asyncio.sleep(0.1)
       # Before fix, this fails because status re-halts to HALTED_BY_CIRCUIT_BREAKER
       assert engine.status == BotStatus.RUNNING
       await engine.stop()

   asyncio.run(run())
   "
   ```
