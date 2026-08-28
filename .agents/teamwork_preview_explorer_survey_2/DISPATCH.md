## 2026-08-22T13:06:23Z
<USER_REQUEST>
You are an Explorer investigating the Asset Filter and Toxic OTC Asset Blacklist for Phase 3 quantitative refinements.

Working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/teamwork_preview_explorer_survey_2
Original request: /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md

Your tasks:
1. Read /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md to understand the exact requirements (R2: add newly discovered high-drawdown OTC pairs to DEFAULT_TOXIC_BLACKLIST in asset_filter.py: USD/DZD OTC, UAH/USD OTC, USD/MYR OTC, USD/INR OTC, EUR/HUF OTC, GBP/JPY OTC; ensure all canonical variations with/without _otc, slashes, spaces are normalized and blocked in LiveDemoBotEngine and StrategyAutoMatcher).
2. Investigate codebase files relating to asset filtering, blacklisting, and symbol normalization:
   - Locate asset_filter.py (or similar modules) and inspect DEFAULT_TOXIC_BLACKLIST, normalization functions (e.g. normalize_asset, clean_symbol).
   - Locate LiveDemoBotEngine and StrategyAutoMatcher to inspect how asset filtering/blacklisting is applied before trade execution and strategy matching.
   - Check if canonical normalization handles formats like "USD/DZD OTC", "USD_DZD_OTC", "USDDZDOTC", "USD/DZD", "USD_DZD", "USDDZD_otc", etc.
   - Check existing tests for asset filtering in tests/.
3. Write a comprehensive report in /Users/vlados/work/projects/startup/strat_trade_be/.agents/teamwork_preview_explorer_survey_2/handoff.md detailing:
   - Current implementation of DEFAULT_TOXIC_BLACKLIST and normalization logic.
   - How LiveDemoBotEngine and StrategyAutoMatcher enforce asset filters.
   - Exact modifications required for R2.
   - Related tests that need updating or adding.
4. Send a completion message back with the path to your handoff.md.
</USER_REQUEST>
