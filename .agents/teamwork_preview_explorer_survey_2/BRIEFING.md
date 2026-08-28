# BRIEFING — 2026-08-22T13:08:45Z

## Mission
Investigate Asset Filter and Toxic OTC Asset Blacklist for Phase 3 quantitative refinements (R2).

## 🔒 My Identity
- Archetype: explorer
- Roles: investigator, analyzer, synthesizer
- Working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/teamwork_preview_explorer_survey_2
- Original parent: 9c4a3d3c-8907-49b9-8a49-6d4505c5289a
- Milestone: Phase 3 Quantitative Refinements - R2 Toxic OTC Blacklist & Asset Filtering

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Produce 5-component handoff report (handoff.md)
- Communicate via send_message to parent agent

## Current Parent
- Conversation ID: 9c4a3d3c-8907-49b9-8a49-6d4505c5289a
- Updated: not yet

## Investigation State
- **Explored paths**:
  - `src/strat_trade/domain/trading/asset_filter.py` (canonical normalization, `DEFAULT_TOXIC_OTC_BLACKLIST`, `DEFAULT_HIGH_WINRATE_WHITELIST`, `is_toxic_asset`, `filter_allowed_assets`)
  - `src/strat_trade/domain/trading/correlation.py` (`normalize_symbol`, `extract_currency_pair`)
  - `src/strat_trade/domain/optimizer/auto_matcher.py` (toxic asset check in `find_optimal_strategy_for_asset`)
  - `src/strat_trade/domain/trading/bot_engine.py` (two-layer toxic asset enforcement: scan loop `_evaluate_single_asset` and atomic order lock `_execute_signal`)
  - `src/strat_trade/settings.py` (`toxic_asset_blacklist`, `high_winrate_asset_whitelist`)
  - `src/strat_trade/use_cases/auto_assign_strategies.py` (`generate_pre_trading_plan`)
  - `src/strat_trade/api/routes/candles.py` (`_CURATED_ASSETS`)
  - Test suites: `tests/test_strategy_curation_and_asset_filter.py`, `tests/test_empirical_stress_challenger.py`, `tests/test_m4_empirical_challenger_2.py`, `tests/test_rolling_15_regression.py`
- **Key findings**:
  - `normalize_symbol` in `correlation.py` and `canonical_asset_key` in `asset_filter.py` already cleanly normalize OTC variations (`USD/DZD OTC`, `USD_DZD_OTC`, `USDDZDOTC`, `USD/DZD`, `USD_DZD`, `USDDZD_otc`, `USD-DZD (OTC)`) to canonical 6-character uppercase keys (`USDDZD`, `UAHUSD`, `USDMYR`, `USDINR`, `EURHUF`, `GBPJPY`).
  - `DEFAULT_TOXIC_OTC_BLACKLIST` needs expansion with 6 pairs: `USDDZD`, `UAHUSD`, `USDMYR`, `USDINR`, `EURHUF`, `GBPJPY`, and `DEFAULT_TOXIC_BLACKLIST` alias should be defined.
  - Critical discovery: `GBPJPY` was previously in `DEFAULT_HIGH_WINRATE_WHITELIST` (in `asset_filter.py`), `settings.py`, and `auto_assign_strategies.py`. It MUST be removed from all whitelist configurations as it is now classified as toxic (0.0% WR).
  - Multi-layer defense in `LiveDemoBotEngine` and `StrategyAutoMatcher` relies directly on `is_toxic_asset`, ensuring zero execution leaks once blacklist is updated.
  - Existing test suites have 472 tests passing, but several tests specifically assert `GBPJPY` in whitelist and will need adjustment to reflect `GBPJPY` in toxic blacklist.
- **Unexplored areas**: None, full scope investigated.

## Key Decisions Made
- Fully documented all required changes, canonical mappings, multi-layer verification paths, and test suite updates in handoff.md.

## Artifact Index
- handoff.md — Final investigation handoff report
