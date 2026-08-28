## 2026-08-20T13:19:50Z

You are survey_explorer_2.
Your working directory is: /Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_2
Read the authoritative requirements in: /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md

Mission: Survey the codebase with a focus on Bot Engine & Execution Guardrails:
1. Locate and examine the bot execution engine (e.g. `src/engine/bot_engine.py` or equivalent, order managers, trade execution flow, risk managers).
2. Investigate how trade entry signals are processed, filtered, and dispatched.
3. Investigate the current state (or absence) of:
   - Per-asset and global Cooldown timers (minimum N bars / time before re-entering).
   - Correlated asset exposure filtering (handling currency pairs like AUD/USD and AUD/NZD).
   - Circuit Breakers (consecutive losses K, max drawdown threshold, pause mechanisms).
4. Document all relevant files, data models, state tracking mechanisms, interfaces, dependencies, and edge cases.
5. Write your complete findings to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_2/survey_report.md` and deliver your handoff.
