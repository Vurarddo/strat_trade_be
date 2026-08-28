# BRIEFING — 2026-08-23T08:52:30Z

## Mission
Investigate and design the restructuring of `src/strat_trade/domain/optimizer/auto_matcher.py` for Milestone 1 (Sniper Alpha Strategy selection).

## 🔒 My Identity
- Archetype: explorer
- Roles: investigator, quant-strategy-researcher, trading-systems-developer
- Working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/m1_explorer_1
- Original parent: 965d505d-f351-4731-b173-775c7711e297
- Milestone: Milestone 1 - Core Strategy Optimization & AutoMatcher Restructuring

## 🔒 Key Constraints
- Read-only investigation — do NOT implement code modifications directly in src/
- PRIORITY_STRATEGIES updated to frozenset({"support_resistance_bounce", "rsi_stochastic_extreme", "ema_pullback_trend"})
- Re-route commodities (Gold_otc) -> support_resistance_bounce, stocks -> ema_pullback_trend, default fallbacks -> support_resistance_bounce (primary), rsi_stochastic_extreme (secondary)
- Ensure find_optimal_strategy_for_asset only allocates sniper alpha strategies
- Prepare concrete diff patch / instructions and handoff report

## Current Parent
- Conversation ID: 965d505d-f351-4731-b173-775c7711e297
- Updated: not yet

## Investigation State
- **Explored paths**: `src/strat_trade/domain/optimizer/auto_matcher.py`, `src/strat_trade/domain/strategies/registry.py`, `src/strat_trade/domain/strategies/support_resistance_bounce.py`, `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`, `src/strat_trade/domain/strategies/ema_pullback_trend.py`, `src/strat_trade/domain/trading/bot_engine.py`, `src/strat_trade/use_cases/auto_assign_strategies.py`, `tests/`
- **Key findings**: Complete mapping of `PRIORITY_STRATEGIES`, `_heuristic_profile_for_asset`, `candidate_strategies` filtering in `find_optimal_strategy_for_asset`, `registry.py` fallback resolution, and 6 test suites requiring assertion synchronization.
- **Unexplored areas**: None. Milestone 1 investigation complete.

## Key Decisions Made
- `PRIORITY_STRATEGIES` updated strictly to `frozenset({"support_resistance_bounce", "rsi_stochastic_extreme", "ema_pullback_trend"})`.
- `_heuristic_profile_for_asset`: Commodities (`Gold_otc`) -> `support_resistance_bounce`, Stocks -> `ema_pullback_trend`, Crypto -> `rsi_stochastic_extreme`, Forex -> `support_resistance_bounce` (JPY/GBP) & `rsi_stochastic_extreme` (others), Default fallbacks -> `support_resistance_bounce` (primary) and `rsi_stochastic_extreme` (secondary).
- Candidate backtesting filtered to `candidate_strategies = [s for s in strategies if s["id"] in PRIORITY_STRATEGIES]`.
- Legacy strategies remain registered in `_STRATEGIES` (`registry.py`) for backward compatibility.
- Detailed diff patch and test synchronization guide documented in `m1_plan_automatcher.md` and `handoff.md`.

## Artifact Index
- /Users/vlados/work/projects/startup/strat_trade_be/.agents/m1_explorer_1/m1_plan_automatcher.md — Comprehensive M1 plan & diff for AutoMatcher restructuring
- /Users/vlados/work/projects/startup/strat_trade_be/.agents/m1_explorer_1/handoff.md — 5-component handoff report
