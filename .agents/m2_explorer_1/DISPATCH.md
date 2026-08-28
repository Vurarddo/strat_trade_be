## 2026-08-20T13:31:06Z
You are m2_explorer_1 for Milestone 2: Currency Correlation & Exposure Filtering.
Your working directory is: /Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_explorer_1
Read the authoritative requirements in: /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md
Read the project architecture in: /Users/vlados/work/projects/startup/strat_trade_be/PROJECT.md

Mission: Formulate the exact implementation plan for the Currency Pair Correlation & Exposure Filter:
1. Design `src/strat_trade/domain/trading/correlation.py`:
   - `extract_currency_pair(asset: str) -> tuple[str, str] | None` (handling symbols like `AUDUSD_otc`, `EURUSD_otc`, `USDCHF`, etc.).
   - Directional exposure analysis:
     - `CALL` on `BASE/QUOTE` -> Long `BASE`, Short `QUOTE`.
     - `PUT` on `BASE/QUOTE` -> Short `BASE`, Long `QUOTE`.
   - `is_correlated_conflict(candidate_asset: str, candidate_action: str, active_trades: list[LiveTradeRecord]) -> tuple[bool, str]`.
   - Correlation detection between pairs (e.g. `AUDUSD` and `AUDNZD` in same direction, `EURUSD` and `USDCHF` in inverse direction).
2. Specify exact unit tests for `correlation.py`.
3. Write your findings to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_explorer_1/analysis.md` and handoff to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_explorer_1/handoff.md`.
