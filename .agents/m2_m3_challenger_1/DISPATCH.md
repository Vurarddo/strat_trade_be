# Task Assignment: M2/M3 Challenger 1 (Microstructure & Expiration Verifier)

## 2026-08-23T09:07:30Z
You are M2/M3 Challenger 1.
Working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_m3_challenger_1
Parent Orchestrator directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/orchestrator
Original Request: /Users/vlados/work/projects/startup/strat_trade_be/ORIGINAL_REQUEST.md
Scope Document: /Users/vlados/work/projects/startup/strat_trade_be/PROJECT.md
Worker Reports:
- /Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_worker_1/handoff.md
- /Users/vlados/work/projects/startup/strat_trade_be/.agents/m3_worker_1/handoff.md

Empirically challenge M2 & M3:
1. Test microstructure noise filter against synthetic flatline candles, discrete step-tick quantization, high-frequency whipsaw noise, and verify genuine continuous Forex/OTC pairs pass.
2. Verify post-settlement cooldown (minimum 180s) and order lock drop behavior during cooldown.
3. Verify expiration duration defaults to 180s (3 bars) without manual user input.
4. Write report to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_m3_challenger_1/challenge.md` and handoff with explicit APPROVE or REJECT verdict to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_m3_challenger_1/handoff.md`. Notify orchestrator via send_message when done.
