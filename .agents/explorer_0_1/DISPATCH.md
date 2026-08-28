## 2026-08-21T12:58:47Z
You are Explorer 1 for Phase 0 Survey.
Your working directory is /Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_0_1/

Read /Users/vlados/work/projects/startup/strat_trade_be/ORIGINAL_REQUEST.md and /Users/vlados/work/projects/startup/strat_trade_be/.agents/orchestrator_1/PROJECT.md.

Investigate the codebase for Strategy Portfolio Curation & Loss Remediation (R1):
1. Locate all strategy definitions in the codebase, specifically:
   - `EMA Ribbon Trend Pullback` (or similar name)
   - `Support & Resistance Pin-Bar` (or similar name)
   - `SuperTrend + ADX Momentum`
   - `Гібридна Мульти-Факторна` (Hybrid Multi-Factor)
   - `RSI + Stoch Extreme Scalp`
   - `MACD Divergence & Cross`
2. How are strategies registered, enabled/disabled, prioritized, and scored?
3. How is signal generation implemented for EMA Ribbon and Pin-Bar? Where are RSI, Stochastic, wick rejection ratios, bounce confirmations calculated or filtered?
4. Document exact file paths, class/function names, line numbers, and proposed implementation details for deactivating/filtering EMA Ribbon, adding Pin-Bar wick rejection ratio (>=0.35) and bounce confirmation, and prioritizing top strategies.

Write your findings to /Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_0_1/handoff.md and report back via send_message.
