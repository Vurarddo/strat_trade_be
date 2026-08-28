## 2026-08-23T09:01:14Z
You are M3 Worker 1 (Dynamic Microstructure Noise Filter & Cooldown Implementer).
Working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/m3_worker_1
Parent Orchestrator directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/orchestrator
Original Request: /Users/vlados/work/projects/startup/strat_trade_be/ORIGINAL_REQUEST.md
Scope Document: /Users/vlados/work/projects/startup/strat_trade_be/PROJECT.md
Survey Report: /Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_survey_2/survey_r2_r3.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Mission (Requirement R3):
1. In `src/strat_trade/domain/trading/asset_filter.py`:
   - Implement `qualify_asset_microstructure(candles: pd.DataFrame) -> tuple[bool, str]` using statistical price action metrics:
     - Require minimum 50 candles.
     - `flat_bar_ratio`: proportion of candles where `high == low` or zero body range; reject if $> 0.15$ (15%).
     - `unique_price_ratio`: unique close prices / total bars; reject if $< 0.30$ (30%) to block discrete step-tick exotics.
     - `whipsaw_sign_flip_ratio`: sign flips in consecutive 1-bar returns; reject if $> 0.80$ (80%).
     - `relative_atr`: $ATR(14) / Close$; reject if $< 0.00003$.
     - Allow all continuous liquid OTC and Forex assets (`EURUSD`, `GBPUSD`, `USDJPY`, `AUDUSD`, `USDCLP`, `USDBDT`, `USDEGP`, `Gold`, etc.).
     - Integrate dynamic microstructure qualification into `filter_allowed_assets` or strategy auto-matching as appropriate.
2. In `src/strat_trade/domain/trading/bot_engine.py`:
   - Enforce hard minimum 3-minute cooldown (`cooldown_sec = max(180, cooldown_bars * 60)`) on post-trade settlement.
   - Add atomic check in `_execute_order()` to prevent repeat entries during volatile breakouts.
3. Add unit/integration tests in `tests/test_strategy_curation_and_asset_filter.py` or new test file covering microstructure qualification metrics and anti-whipsaw cooldown.
4. Run `.venv/bin/pytest` and `.venv/bin/ruff check src tests` to verify 100% tests pass and 0 errors.
5. Write your changes to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m3_worker_1/changes.md` and handoff to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m3_worker_1/handoff.md`. Notify orchestrator via send_message when done.
