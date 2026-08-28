# BRIEFING — 2026-08-21T17:01:00+04:00

## Mission
Investigate Asset Quality Filter & Toxic Pair Blacklist (R2) in the trading engine codebase.

## 🔒 My Identity
- Archetype: Explorer
- Roles: Teamwork explorer (Read-only investigation)
- Working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_0_2
- Original parent: 14040b5c-ab25-44e2-afd8-52f95507aaa9
- Milestone: Phase 0 Survey - R2 Asset Quality Filter & Toxic Pair Blacklist

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Investigate LiveDemoBotEngine and StrategyAutoMatcher asset selection, quote processing, evaluation, and order triggering
- Identify existing filtering/blacklisting/whitelisting mechanisms
- Recommend design and exact file/line changes for toxic pair blacklisting & high-winrate whitelisting

## Current Parent
- Conversation ID: 14040b5c-ab25-44e2-afd8-52f95507aaa9
- Updated: not yet

## Investigation State
- **Explored paths**:
  - `src/strat_trade/domain/trading/bot_engine.py` (LiveDemoBotEngine)
  - `src/strat_trade/domain/optimizer/auto_matcher.py` (StrategyAutoMatcher)
  - `src/strat_trade/use_cases/auto_assign_strategies.py` (generate_pre_trading_plan)
  - `src/strat_trade/use_cases/manage_live_bot.py` (singleton management)
  - `src/strat_trade/api/routes/bot.py` (bot endpoints)
  - `src/strat_trade/api/routes/candles.py` (market assets & candle queries)
  - `src/strat_trade/domain/trading/correlation.py` (symbol normalization, exposure check)
  - `src/strat_trade/domain/backtest/portfolio_engine.py` (portfolio backtest engine)
  - `src/strat_trade/settings.py` (application settings)
  - `src/strat_trade/web/templates/index.html` (frontend asset selection)
- **Key findings**:
  - Zero asset quality / blacklist filtering exists in `LiveDemoBotEngine` or `StrategyAutoMatcher`.
  - Toxic pairs (`USD/IDR OTC`, `USD/VND OTC`, `BNB OTC`, `EUR/CHF OTC`) are currently accepted and traded if requested.
  - High-winrate pairs (`EUR/USD OTC`, `USD/CLP OTC`, `USD/BDT OTC`, `USD/EGP OTC`, `GBP/JPY OTC`, `Gold OTC`) have no preferential scoring or curated presets in the auto-assigner.
  - Need a dedicated `asset_filter.py` domain module with canonical symbol normalization, blacklist and whitelist definitions, and integration into `bot_engine.py`, `auto_matcher.py`, `auto_assign_strategies.py`, `settings.py`, and API schemas.
- **Unexplored areas**: None for R2 scope.

## Key Decisions Made
- Architecture designed around clean domain module `src/strat_trade/domain/trading/asset_filter.py` with multi-layer defense (API level, pre-trading plan level, auto-matcher level, bot scan loop level, and atomic order placement lock level).

## Artifact Index
- DISPATCH.md — incoming dispatch instructions
- progress.md — liveness heartbeat and subtask progress
- handoff.md — final survey findings report
