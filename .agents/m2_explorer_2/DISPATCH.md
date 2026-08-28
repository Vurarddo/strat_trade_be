## 2026-08-20T13:31:06Z
You are m2_explorer_2 for Milestone 2: Cooldown Timers & Circuit Breakers in Bot Engine.
Your working directory is: /Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_explorer_2
Read the authoritative requirements in: /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md
Read the project architecture in: /Users/vlados/work/projects/startup/strat_trade_be/PROJECT.md

Mission: Formulate the exact implementation plan for Cooldown Timers and Circuit Breakers in `src/strat_trade/domain/trading/bot_engine.py` and `entities.py`:
1. `entities.py`:
   - Extend `BotStatus` enum with `PAUSED = "PAUSED"` and `HALTED_BY_CIRCUIT_BREAKER = "HALTED_BY_CIRCUIT_BREAKER"`.
   - Extend `PreTradingPlan` with `cooldown_bars: int = 3`, `global_cooldown_seconds: int = 30`, `max_consecutive_losses: int = 3`, `max_drawdown_pct_limit: float = 0.08`, `correlation_filter_enabled: bool = True`.
   - Extend `BotSessionSummary` with `consecutive_losses: int`, `peak_balance: Decimal`, `current_drawdown_pct: float`, `paused_until: datetime | None`, `is_paused: bool`.
2. `bot_engine.py`:
   - Implement post-trade-settlement per-asset cooldown ($N$ bars / seconds).
   - Implement global cooldown delay between portfolio executions.
   - Implement consecutive losses counter and automatic transition to `BotStatus.PAUSED` for cooling-off duration (e.g. 15 minutes) or auto-resume.
   - Implement high-watermark peak balance tracking and max drawdown circuit breaker (`HALTED_BY_CIRCUIT_BREAKER`).
   - Implement `pause()` and `resume()` lifecycle methods.
3. Write your findings to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_explorer_2/analysis.md` and handoff to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_explorer_2/handoff.md`.
