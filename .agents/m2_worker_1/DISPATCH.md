## 2026-08-23T09:01:14Z
You are M2 Worker 1 (UI Expiration & Strategy Auto-Expiration Implementer).
Working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_worker_1
Parent Orchestrator directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/orchestrator
Original Request: /Users/vlados/work/projects/startup/strat_trade_be/ORIGINAL_REQUEST.md
Scope Document: /Users/vlados/work/projects/startup/strat_trade_be/PROJECT.md
Survey Report: /Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_survey_2/survey_r2_r3.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Mission (Requirement R2):
1. In `src/strat_trade/web/templates/index.html`:
   - Remove `#botCfgExpiration` select dropdown element cleanly from the HTML markup (and fix container layout if needed).
   - In JavaScript `prepareLiveBotLaunch()` / payload builders, remove `expiration_seconds: parseInt(document.getElementById('botCfgExpiration').value),` so backend strategy-calibrated expiration defaults are used.
2. In `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`:
   - Update default `base_expiration_bars` from `2` to `3` (180s) in `__init__` and in `get_parameter_definitions()`.
3. Verify `AutoAssignRequest` / pre-trading plan generation automatically assigns strategy-calibrated optimal expiration (180s / 3 bars) without requiring user input.
4. Run `.venv/bin/pytest` and `.venv/bin/ruff check src tests` to verify 100% tests pass and 0 errors.
5. Write your changes to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_worker_1/changes.md` and handoff to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_worker_1/handoff.md`. Notify orchestrator via send_message when done.
