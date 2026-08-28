## 2026-08-20T13:31:06Z
You are m2_explorer_3 for Milestone 2: API, Portfolio Backtester Alignment & Test Strategy.
Your working directory is: /Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_explorer_3
Read the authoritative requirements in: /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md
Read the project architecture in: /Users/vlados/work/projects/startup/strat_trade_be/PROJECT.md

Mission: Formulate the integration, API, and test strategy for Milestone 2:
1. REST API and Use Cases:
   - Update `src/strat_trade/api/schemas.py` and `src/strat_trade/api/routes/bot.py` to expose `/bot/pause` and `/bot/resume` endpoints and return enriched status telemetry.
   - Update `src/strat_trade/use_cases/manage_live_bot.py`.
2. Portfolio Backtester Alignment:
   - Check `src/strat_trade/domain/backtest/portfolio_engine.py` and specify how correlation filtering and post-trade cooldowns are integrated into multi-asset backtesting.
3. Test Suite Design:
   - Design comprehensive tests in `tests/test_execution_guardrails.py` covering cooldown timing, correlated pair rejection, circuit breaker pause on $K$ consecutive losses, peak-to-trough drawdown halt, and API pause/resume.
4. Write your findings to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_explorer_3/analysis.md` and handoff to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_explorer_3/handoff.md`.
