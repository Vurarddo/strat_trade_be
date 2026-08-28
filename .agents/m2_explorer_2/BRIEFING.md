# BRIEFING — 2026-08-20T17:33:05+04:00

## Mission
Formulate the exact implementation plan for Cooldown Timers and Circuit Breakers in `src/strat_trade/domain/trading/bot_engine.py` and `entities.py`.

## 🔒 My Identity
- Archetype: explorer
- Roles: Trading Systems Developer, Risk Manager, Quantitative Performance Auditor
- Working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_explorer_2
- Original parent: 2e5ef04d-99bc-4d93-9fc5-ae8ee49089dd
- Milestone: Milestone 2: Cooldown Timers & Circuit Breakers in Bot Engine

## 🔒 Key Constraints
- Read-only investigation — do NOT implement production code directly
- Precise design matching Clean Architecture & domain model in `entities.py` and `bot_engine.py`
- Complete evidence chains, diff/patch proposal, verified tests and edge cases

## Current Parent
- Conversation ID: 2e5ef04d-99bc-4d93-9fc5-ae8ee49089dd
- Updated: 2026-08-20T17:33:05+04:00

## Investigation State
- **Explored paths**:
  - `src/strat_trade/domain/trading/entities.py`
  - `src/strat_trade/domain/trading/bot_engine.py`
  - `src/strat_trade/domain/trading/trade_store.py`
  - `src/strat_trade/use_cases/manage_live_bot.py`
  - `src/strat_trade/use_cases/auto_assign_strategies.py`
  - `src/strat_trade/api/routes/bot.py`
  - `src/strat_trade/api/schemas.py`
  - `tests/test_bot_and_audit_api.py`
- **Key findings**:
  - `BotStatus` needs `PAUSED` and `HALTED_BY_CIRCUIT_BREAKER`.
  - `PreTradingPlan` needs `cooldown_bars=3`, `global_cooldown_seconds=30`, `max_consecutive_losses=3`, `max_drawdown_pct_limit=0.08`, `correlation_filter_enabled=True`, `pause_duration_minutes=15`.
  - `BotSessionSummary` needs `consecutive_losses`, `peak_balance`, `current_drawdown_pct`, `paused_until`, `is_paused`.
  - `LiveDemoBotEngine` requires: post-settlement per-asset cooldown ($N$ bars), global cooldown lock (30s), consecutive losses pause (15 mins), peak-to-trough high-watermark drawdown circuit breaker (8%), and `pause()` / `resume()` methods.
- **Unexplored areas**: None for this milestone domain scope.

## Key Decisions Made
- `_run_loop` remains active while in `BotStatus.PAUSED` to settle pending trades and service auto-resume expiry.
- Terminal halt states (`HALTED_BY_STOP_LOSS`, `HALTED_BY_CIRCUIT_BREAKER`) break the loop.
- Peak balance ($HWM$) is updated upon every trade settlement and tracked in `BotSessionSummary`.
- Cooldown timing and correlation filtering are enforced atomically inside `_execute_order` and in `_evaluate_single_asset`.

## Artifact Index
- `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_explorer_2/analysis.md` — Detailed analysis and proposed implementation specifications
- `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_explorer_2/handoff.md` — 5-component handoff report
