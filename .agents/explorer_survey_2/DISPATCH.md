## 2026-08-24T13:42:10Z

Mission: Survey and investigate risk management, circuit breakers, cooldowns, and asset qualification in the codebase.
1. Examine `src/` to find `RiskManager`, `LiveDemoBotEngine`, and related risk/engine modules.
2. Inspect current loss handling, streak tracking, and cooldown implementations:
   - How trade outcomes are recorded and tracked.
   - How asset-specific cooldowns (anti-whipsaw 3-5 min per asset) are or should be implemented.
   - How global consecutive-loss circuit breaker (atomic counter across all assets, 3 consecutive losses -> 15 min / 900s global lockout `global_cooldown_until`, reset on WIN or expiry) should be integrated with `LiveDemoBotEngine` and `RiskManager`.
   - How WebSocket telemetry broadcasts work and where cooldown status events are emitted to the UI.
3. Investigate asset qualification and micro-tick noise filtering:
   - How asset pairs are currently filtered/whitelisted or evaluated for continuous vs discrete/erratic price action.
4. Report on existing code structure, exact file paths, line numbers, classes, methods, and interface contracts.
5. Write complete analysis to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_survey_2/handoff.md`.
6. Send a message back to parent upon completion.
