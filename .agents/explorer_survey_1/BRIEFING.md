# BRIEFING — 2026-08-24T13:45:35Z

## Mission
Survey and investigate the strategy engine and strategy portfolio in the codebase: strategy registration, auto-matching (`StrategyAutoMatcher`), execution (`LiveDemoBotEngine`), status of `MACD Divergence & Cross` and `hybrid_multifactors`, inspection of primary alpha strategies (`SupportResistanceBounceStrategy`, `RsiStochasticExtremeStrategy`, `EmaPullbackTrendStrategy`), and entry guard architecture for the runaway momentum / consecutive candle filter.

## 🔒 My Identity
- Archetype: explorer
- Roles: explorer, investigator, analyst
- Working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_survey_1
- Original parent: 96a7449c-e780-4951-bfe9-086304a9b5f3
- Milestone: Strategy Portfolio & Engine Investigation

## 🔒 Key Constraints
- Read-only investigation — do NOT implement code modifications in `src/` or tests.
- Deliver findings in `handoff.md` and message back to parent.

## Current Parent
- Conversation ID: 96a7449c-e780-4951-bfe9-086304a9b5f3
- Updated: 2026-08-24T13:45:35Z

## Investigation State
- **Explored paths**:
  - `src/strat_trade/domain/strategies/` (`base.py`, `registry.py`, `support_resistance_bounce.py`, `rsi_stochastic_extreme.py`, `ema_pullback_trend.py`, `bollinger_atr_reversion.py`, `volatility_squeeze_breakout.py`, `supertrend_adx_momentum.py`, `macd_divergence_break.py`, `hybrid_multifactors.py`)
  - `src/strat_trade/domain/optimizer/auto_matcher.py`
  - `src/strat_trade/domain/trading/bot_engine.py`, `asset_filter.py`, `correlation.py`, `entities.py`, `trade_store.py`
  - `src/strat_trade/use_cases/auto_assign_strategies.py`, `manage_live_bot.py`
  - `tests/` test suites (914 tests passing, 0 ruff errors)
- **Key findings**:
  - Strategy registration is centralized in `src/strat_trade/domain/strategies/registry.py` with 8 strategies.
  - `StrategyAutoMatcher` prioritizes 3 sniper strategies (`support_resistance_bounce`, `rsi_stochastic_extreme`, `ema_pullback_trend`) in `PRIORITY_STRATEGIES`.
  - `LiveDemoBotEngine` executes assigned strategies bar-by-bar, enforces per-asset cooldown (>= 180s), global execution cooldown (30s), correlation filtering, and consecutive-loss circuit breakers.
  - Current `SupportResistanceBounceStrategy` and `RsiStochasticExtremeStrategy` lack runaway momentum guards, making them vulnerable to catching falling knives during 3-4 consecutive candle momentum sweeps.
- **Unexplored areas**: None for this survey scope.

## Key Decisions Made
- Fully documented the exact architecture, line numbers, and proposed design for runaway momentum and consecutive candle filters in `handoff.md`.

## Artifact Index
- `handoff.md` — Complete 5-component handoff report.
