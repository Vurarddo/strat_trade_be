## 2026-08-21T12:58:47Z
You are Explorer 2 for Phase 0 Survey.
Your working directory is /Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_0_2/

Read /Users/vlados/work/projects/startup/strat_trade_be/ORIGINAL_REQUEST.md and /Users/vlados/work/projects/startup/strat_trade_be/.agents/orchestrator_1/PROJECT.md.

Investigate the codebase for Asset Quality Filter & Toxic Pair Blacklist (R2):
1. Locate `LiveDemoBotEngine` and `StrategyAutoMatcher` (and related bot/engine files).
2. How do `LiveDemoBotEngine` and `StrategyAutoMatcher` select assets, receive quotes, evaluate strategies on assets, and trigger orders?
3. Is there existing asset filtering, blacklisting, or whitelisting? Where should explicit blacklisting for toxic OTC pairs (`USD/IDR OTC`, `USD/VND OTC`, `BNB OTC`, `EUR/CHF OTC`) and configurable whitelisting for high-winrate pairs (`EUR/USD OTC`, `USD/CLP OTC`, `USD/BDT OTC`, `USD/EGP OTC`, `GBP/JPY OTC`, `Gold OTC`) be implemented?
4. Document exact file paths, class/function names, line numbers, and proposed implementation changes.

Write your findings to /Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_0_2/handoff.md and report back via send_message.
