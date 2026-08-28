## 2026-08-28T11:50:13Z

You are the Forensic Integrity Auditor for the Pocket Option AutoTrader Pro stress-test.
Your working directory is: /Users/vlados/work/projects/startup/strat_trade_be/.agents/auditor_stress_test/
Create your directory and maintain your BRIEFING.md, progress.md, and handoff.md inside it.

MANDATORY INPUTS:
- Read /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md
- Read /Users/vlados/work/projects/startup/strat_trade_be/STRESS_TEST_REPORT.md

TASKS:
1. Perform an uncompromising forensic integrity audit of the entire stress-test work product:
   - Check for cheating, hardcoded facades, fake data, or superficial summaries.
   - Verify that all analysis is genuinely grounded in the actual codebase (`src/strat_trade/`) and database (`data/trades.db`).
   - Verify compliance with the constraint: "pure research and analysis task — produce a detailed Markdown report. No code changes" (confirm no source code files in `src/` or tests have been improperly altered).
   - Verify that all 16 vulnerabilities, mathematical formulas, and simulation distributions are authentic and derived from real code and calculations.
2. Record your BINARY VETO VERDICT: **CLEAN** or **INTEGRITY VIOLATION** with full evidence in handoff.md and send_message to orchestrator.
