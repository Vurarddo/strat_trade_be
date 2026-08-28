## 2026-08-20T13:19:50Z
<USER_REQUEST>
You are survey_explorer_3.
Your working directory is: /Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_3
Read the authoritative requirements in: /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md

Mission: Survey the codebase with a focus on Backtesting, Verification, Optimization, and Test Infrastructure:
1. Locate and examine the existing backtesting framework, simulation loop, payout calculation (92% payout / -100% loss), metrics calculation, and historical data loaders.
2. Examine existing unit and integration tests in `tests/` and identify how tests are currently executed (e.g., pytest, poetry, venv).
3. Investigate how to construct an automated rolling 15-trade window verification benchmark:
   - Partitioning historical trades into sequential non-overlapping 15-trade batches.
   - Profitability condition checks: Win Rate >= 53.4%, Net Growth > 0 per 15-trade batch.
   - Parameter optimization/tuning loop when batches fail.
4. Document all relevant files, existing test coverage, benchmarks, datasets available, and execution commands.
5. Write your complete findings to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_3/survey_report.md` and deliver your handoff.
</USER_REQUEST>
