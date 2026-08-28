## 2026-08-20T13:43:40Z
You are Worker for Milestone 2 Remediation: Bot Engine Execution Guardrails & Anti-Whipsaw (R2).
Your working directory is: /Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_worker_2/

Read:
- /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md
- /Users/vlados/work/projects/startup/strat_trade_be/PROJECT.md
- /Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_reviewer_1/handoff.md

Tasks:
1. In `src/strat_trade/domain/trading/bot_engine.py`:
   Update `LiveDemoBotEngine.resume()` so that when resuming:
   ```python
   # Reset high-watermark baseline if resuming from a circuit breaker halt
   if self.current_balance > Decimal("0.00"):
       self.peak_balance = self.current_balance
       self.current_drawdown_pct = 0.0
   ```
2. In `tests/test_execution_guardrails.py`:
   Add a test verifying that after `HALTED_BY_CIRCUIT_BREAKER`, calling `resume()` resets `peak_balance` and `current_drawdown_pct`, and the bot remains in `BotStatus.RUNNING` over subsequent `_check_circuit_breakers()` ticks without immediately re-halting.
3. Run `.venv/bin/pytest tests/` and `.venv/bin/ruff check src/ tests/`.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Write your report to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_worker_2/handoff.md` and send a completion message.
