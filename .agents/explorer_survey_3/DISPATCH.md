## 2026-08-24T13:42:10Z
<USER_REQUEST>
You are Explorer 3 for the project strat_trade_be.
Your working directory is `/Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_survey_3`.
Project root: `/Users/vlados/work/projects/startup/strat_trade_be`.
Original request file: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md`.

You MUST read `/Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md` first.

Your mission:
Survey and investigate UI expiration removal, test harness, verification runners, and datasets in the codebase:
1. Examine `src/strat_trade/web/templates/index.html` and related frontend JavaScript files / static assets:
   - Where "Час експірації" (`botCfgExpiration`) dropdown is located.
   - How JS payload builders construct the bot configuration payload sent to backend endpoints or WebSockets.
   - How expiration duration is handled in pre-trading plan generation and UI display.
2. Inspect testing and verification infrastructure:
   - Locate `Rolling15TradeVerificationRunner`, historical datasets, multi-session broker datasets (combining 600+ real broker trades, August 24 dataset).
   - Inspect the existing `tests/` directory, test runners, pytest configuration, linting configuration (`ruff`), and current test status.
   - Check what tests already exist and what new tests are needed for the requirements.
3. Report on existing code structure, exact file paths, line numbers, classes, methods, and interface contracts.
4. Write your complete analysis to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_survey_3/handoff.md`.
5. Send a message back to parent upon completion.
</USER_REQUEST>
