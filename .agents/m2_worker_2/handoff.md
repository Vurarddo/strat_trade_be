# Milestone 2 Remediation Handoff Report: Bot Engine Execution Guardrails & Anti-Whipsaw (R2)

## 1. Observation
- **Original Defect (Finding 1 from `m2_reviewer_1/handoff.md`)**:
  In `src/strat_trade/domain/trading/bot_engine.py`, calling `LiveDemoBotEngine.resume()` did not reset `self.peak_balance` to `self.current_balance` nor `self.current_drawdown_pct` to `0.0`. When resuming from `BotStatus.HALTED_BY_CIRCUIT_BREAKER`, the background trading loop immediately re-evaluated `_check_circuit_breakers()` on the subsequent tick, detected `current_drawdown_pct >= limit_pct`, and instantly re-halted back into `BotStatus.HALTED_BY_CIRCUIT_BREAKER`.
- **Applied Modifications**:
  1. In `src/strat_trade/domain/trading/bot_engine.py` (lines 137–140):
     ```python
     # Reset high-watermark baseline if resuming from a circuit breaker halt
     if self.current_balance > Decimal("0.00"):
         self.peak_balance = self.current_balance
         self.current_drawdown_pct = 0.0
     ```
  2. In `tests/test_execution_guardrails.py` (lines 528–560):
     Added `test_resume_from_drawdown_circuit_breaker_resets_baseline_and_continues_running()` to SUITE 4. It verifies that tripping the peak drawdown circuit breaker halts the engine, calling `resume()` resets `peak_balance` and `current_drawdown_pct`, and 5 consecutive calls to `_check_circuit_breakers()` maintain `BotStatus.RUNNING` without re-halting.
- **Verification Results**:
  - Full test suite: `.venv/bin/pytest tests/` $\rightarrow$ **278 passed** in 5.06s.
  - Linting: `.venv/bin/ruff check src/ tests/` $\rightarrow$ **All checks passed!**

---

## 2. Logic Chain
1. When a drawdown circuit breaker trips, `self.status` is set to `BotStatus.HALTED_BY_CIRCUIT_BREAKER`, where `peak_balance` is the previous high-watermark (e.g. $1200.00) and `current_balance` is below the allowed limit (e.g. $1100.00 with drawdown $8.33\% \ge 8.0\%$).
2. A human operator resuming the bot manually (`POST /api/v1/bot/resume` or `engine.resume()`) acknowledges the drawdown event and intends to resume trading against the new baseline balance.
3. By setting `self.peak_balance = self.current_balance` and `self.current_drawdown_pct = 0.0` when `self.current_balance > Decimal("0.00")`, future drawdown checks evaluate drawdown relative to the current starting capital.
4. On subsequent ticks of `_run_loop()`, `_check_circuit_breakers()` calculates `drawdown = (1100 - 1100) / 1100 = 0.0%`, keeping the bot in `BotStatus.RUNNING` and allowing normal signal scanning and execution.

---

## 3. Caveats
- No caveats. The fix is strictly scoped to `resume()` and maintains full compatibility with stop-loss protection and existing test suites.

---

## 4. Conclusion
- The instant re-halt defect on `LiveDemoBotEngine.resume()` has been resolved.
- Full unit test coverage in `tests/test_execution_guardrails.py` confirms that the engine remains in `RUNNING` status across repeated circuit breaker checks after resuming.
- All 278 unit/integration/adversarial tests pass and no lint violations exist.

---

## 5. Verification Method
Execute the following verification commands:
```bash
# 1. Run all tests
.venv/bin/pytest tests/

# 2. Run execution guardrails tests specifically
.venv/bin/pytest tests/test_execution_guardrails.py -v

# 3. Run ruff linter
.venv/bin/ruff check src/ tests/
```
