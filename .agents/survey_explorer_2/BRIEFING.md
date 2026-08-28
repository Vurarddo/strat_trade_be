# BRIEFING — 2026-08-20T13:22:50Z

## Mission
Survey the codebase with a focus on Bot Engine & Execution Guardrails (trade processing, cooldown timers, correlated asset filtering, circuit breakers, data models, state tracking).

## 🔒 My Identity
- Archetype: explorer
- Roles: read-only investigator, codebase surveyor, synthesis
- Working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_2
- Original parent: 2e5ef04d-99bc-4d93-9fc5-ae8ee49089dd
- Milestone: Bot Engine & Execution Guardrails Survey Complete

## 🔒 Key Constraints
- Read-only investigation — do NOT implement changes to source code
- Write only inside /Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_2/
- Follow 5-component handoff report protocol

## Current Parent
- Conversation ID: 2e5ef04d-99bc-4d93-9fc5-ae8ee49089dd
- Updated: 2026-08-20T13:22:50Z

## Investigation State
- **Explored paths**:
  - `src/strat_trade/domain/trading/bot_engine.py` (LiveDemoBotEngine)
  - `src/strat_trade/domain/trading/entities.py` (BotStatus, PreTradingPlan, LiveTradeRecord)
  - `src/strat_trade/domain/trading/trade_store.py` (TradeStore, SQLite)
  - `src/strat_trade/use_cases/manage_live_bot.py` (Use cases & singleton management)
  - `src/strat_trade/use_cases/auto_assign_strategies.py` (Pre-trading plan generation)
  - `src/strat_trade/api/routes/bot.py` & `src/strat_trade/api/schemas.py` (REST endpoints & schemas)
  - `src/strat_trade/adapters/pocket_option_gateway.py` (Pocket Option Gateway)
  - `src/strat_trade/domain/backtest/portfolio_engine.py` & `engine.py` (Backtesting parity)
  - `tests/test_bot_and_audit_api.py`, `tests/test_portfolio_backtest_models_and_engine.py`
- **Key findings**:
  - Cooldown timers: only a hardcoded 30s check from signal firing; missing post-settlement $N$-bar resting period and global portfolio cooldown.
  - Correlation filtering: completely absent across the entire repository; multi-asset trading risks over-concentration in base/quote currencies.
  - Circuit breakers: only basic session stop-loss from initial deposit; missing $K$ consecutive losses pause and peak-to-trough high-watermark drawdown breaker.
- **Unexplored areas**: None within the assigned survey scope.

## Key Decisions Made
- Fully documented architecture, data models, state tracking, and execution flow.
- Formulated concrete blueprints for correlation engine, cooldown timers, circuit breakers, and backtester alignment.

## Artifact Index
- `DISPATCH.md` — incoming dispatch instructions
- `BRIEFING.md` — persistent situational awareness
- `progress.md` — liveness heartbeat and step tracking
- `survey_report.md` — comprehensive technical survey findings and architecture blueprint
- `handoff.md` — 5-component self-contained handoff report
