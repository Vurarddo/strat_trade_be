# Milestone 2 Gate Re-evaluation Report: Bot Engine Guardrails & Anti-Whipsaw (R2)

## Review Summary

**Verdict**: `APPROVE`

The defect identified in Finding 1 (`LiveDemoBotEngine.resume()` instant re-halt due to stale high-watermark drawdown baseline) has been thoroughly resolved and verified with dedicated regression and adversarial test suites. All Milestone 2 requirements — currency correlation filtering, per-asset settlement cooldown timers, global portfolio entry pacing, consecutive loss auto-pauses, peak drawdown circuit breakers, REST lifecycle endpoints, and backtesting simulation parity — are fully implemented, verified, and free of regressions. No integrity violations or shortcuts were found.

---

## 1. Observation

### Codebase Verification & Line References

1. **`src/strat_trade/domain/trading/bot_engine.py` (lines 127–146)**:
   ```python
   async def resume(self) -> None:
       async with self._lock:
           if self.status not in (BotStatus.PAUSED, BotStatus.HALTED_BY_CIRCUIT_BREAKER):
               logger.warning("Cannot resume bot in status %s", self.status.value)
               return

           self.status = BotStatus.RUNNING
           self.paused_until = None
           self.consecutive_losses = 0  # Reset loss streak upon manual resume

           # Reset high-watermark baseline if resuming from a circuit breaker halt
           if self.current_balance > Decimal("0.00"):
               self.peak_balance = self.current_balance
               self.current_drawdown_pct = 0.0

           # Ensure background trading loop is active if it was terminated
           if self._task is None or self._task.done():
               self._task = asyncio.create_task(self._run_loop())

           logger.info("LiveDemoBotEngine resumed by user to RUNNING")
   ```
   - **Direct observation**: `self.peak_balance` is reset to `self.current_balance` and `self.current_drawdown_pct` is reset to `0.0` whenever `self.current_balance > Decimal("0.00")`.

2. **`tests/test_execution_guardrails.py` (lines 528–560)**:
   ```python
   @pytest.mark.asyncio
   async def test_resume_from_drawdown_circuit_breaker_resets_baseline_and_continues_running():
       """Verifies that resuming from circuit breaker halt resets peak balance/drawdown
       and avoids immediate re-halt.
       """
       store = MagicMock(spec=TradeStore)
       engine = LiveDemoBotEngine(trade_store=store)
       plan = _make_pre_trading_plan(max_drawdown_pct_limit=0.08)
       gateway = AsyncMock()

       await engine.start(plan, gateway)
       engine.peak_balance = Decimal("1200.00")
       engine.current_balance = Decimal("1100.00")

       # Trigger circuit breaker halt (8.33% drawdown >= 8.0% limit)
       await engine._check_circuit_breakers()
       assert engine.status == BotStatus.HALTED_BY_CIRCUIT_BREAKER
       assert engine.current_drawdown_pct > 8.0

       # Resume bot
       await engine.resume()
       assert engine.status == BotStatus.RUNNING
       assert engine.peak_balance == Decimal("1100.00")
       assert engine.current_drawdown_pct == 0.0

       # Simulate subsequent loop ticks calling _check_circuit_breakers
       for _ in range(5):
           await engine._check_circuit_breakers()
           assert engine.status == BotStatus.RUNNING
           assert engine.current_drawdown_pct == 0.0

       await engine.stop()
   ```
   - **Direct observation**: The regression test validates both the state transition, the baseline reset values, and 5 consecutive loop ticks verifying that `BotStatus.RUNNING` is sustained.

3. **Tool Execution Results**:
   - Command: `.venv/bin/pytest tests/`
     - Result: `278 passed, 2 warnings in 5.12s` (Exit code: 0).
   - Command: `.venv/bin/pytest tests/test_execution_guardrails.py tests/test_currency_correlation.py tests/test_m2_adversarial_stress.py tests/test_adversarial_guardrails.py -v`
     - Result: `107 passed in 1.77s` (Exit code: 0).
   - Command: `.venv/bin/ruff check src/ tests/`
     - Result: `All checks passed!` (Exit code: 0).

4. **Integrity Audit**:
   - No mock overrides in production logic.
   - No hardcoded test responses or simulated bypasses.
   - Genuine domain logic across `LiveDemoBotEngine`, `PortfolioBacktestEngine`, `correlation.py`, and API routes.

---

## 2. Logic Chain

1. **Root Cause Analysis (Finding 1)**:
   - When high-watermark drawdown tripped the circuit breaker, `peak_balance` remained at the historical high (e.g., $1200.00) while `current_balance` was at the lower level (e.g., $1100.00).
   - Without resetting `peak_balance` on manual resume, subsequent ticks evaluated `drawdown = (1200 - 1100) / 1200 = 8.33% >= 8.0%`, immediately flipping the status back to `HALTED_BY_CIRCUIT_BREAKER`.
2. **Evaluation of Fix**:
   - When an operator resumes the bot, `resume()` resets `peak_balance = current_balance` and `current_drawdown_pct = 0.0`.
   - On the first and all subsequent loop ticks, `(peak_balance - current_balance) / peak_balance = (1100 - 1100) / 1100 = 0.0%`.
   - The bot remains in `BotStatus.RUNNING` and resumes active scanning, trading, and post-settlement management.
3. **M2 Scope Compliance**:
   - **Currency Correlation Filter**: Decomposes base/quote exposure and prevents double-long/short positions on correlated currency pairs (`correlation.py`).
   - **Cooldowns**: Enforces per-asset cooldown ($N$ bars post-settlement) and global portfolio entry spacing (`global_cooldown_seconds`).
   - **Circuit Breakers**: Enforces consecutive loss cooling-off pauses (15m default), session stop-loss limit, and peak-to-trough drawdown halt.
   - **Parity**: `PortfolioBacktestEngine` implements equivalent guardrail filters chronologically.
   - **API & Telemetry**: REST endpoints for `/pause`, `/resume`, `/status`, and `/trades` expose enriched metrics (`peak_balance`, `current_drawdown_pct`, `paused_until`, `circuit_breaker_triggered`).

---

## 3. Caveats

- No caveats. The implementation is clean, robust, and verified across unit, integration, API, and adversarial stress tests.

---

## 4. Conclusion

- **Verdict**: `APPROVE`
- Finding 1 has been completely fixed.
- All Milestone 2 requirements and acceptance criteria are satisfied.
- The project is ready to proceed to Milestone 3 (Automated Iterative Verification & Optimization Loop).

---

## 5. Verification Method

The reviewer and subsequent agents can independently verify using:

```bash
# 1. Full test suite execution
.venv/bin/pytest tests/

# 2. Targeted M2 guardrails and correlation test execution
.venv/bin/pytest tests/test_execution_guardrails.py tests/test_currency_correlation.py tests/test_m2_adversarial_stress.py tests/test_adversarial_guardrails.py -v

# 3. Code formatting & linting
.venv/bin/ruff check src/ tests/
```
