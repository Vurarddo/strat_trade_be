# BRIEFING — 2026-08-24T13:46:00Z

## Mission
Survey and investigate risk management, circuit breakers, cooldowns, asset qualification, and WebSocket telemetry in `strat_trade_be`.

## 🔒 My Identity
- Archetype: explorer
- Roles: Teamwork explorer (investigation, synthesis)
- Working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_survey_2
- Original parent: 96a7449c-e780-4951-bfe9-086304a9b5f3
- Milestone: Explorer survey phase 2

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Follow Handoff Protocol (5 components)
- Output report in `handoff.md` and message parent upon completion

## Current Parent
- Conversation ID: 96a7449c-e780-4951-bfe9-086304a9b5f3
- Updated: 2026-08-24T13:42:10Z

## Investigation State
- **Explored paths**:
  - `src/strat_trade/domain/trading/bot_engine.py` (LiveDemoBotEngine)
  - `src/strat_trade/domain/trading/entities.py` (BotStatus, PreTradingPlan, LiveTradeRecord, BotSessionSummary)
  - `src/strat_trade/domain/trading/asset_filter.py` (Microstructure metrics, blacklist/whitelist)
  - `src/strat_trade/domain/trading/trade_store.py` (SQLite persistent store)
  - `src/strat_trade/domain/trading/correlation.py` (Currency correlation filter)
  - `src/strat_trade/domain/backtest/portfolio_engine.py` (Backtest risk engine parity)
  - `src/strat_trade/domain/optimizer/auto_matcher.py` (Strategy auto matcher & microstructure qualification)
  - `src/strat_trade/domain/strategies/` (SupportResistanceBounce, RsiStochasticExtreme, EmaPullbackTrend)
  - `src/strat_trade/api/routes/bot.py` (REST endpoints: auto-assign, start, stop, pause, resume, status, trades)
  - `src/strat_trade/api/schemas.py` (BotStatusResponse, PreTradingPlanResponse, LiveTradeResponse)
  - `src/strat_trade/web/templates/index.html` (UI rendering and polling logic)
  - `tests/test_execution_guardrails.py` & other test suites (914 tests passing, 0 ruff errors)
- **Key findings**:
  1. Risk governance is unified within `LiveDemoBotEngine` and `PortfolioBacktestEngine`.
  2. Loss streak tracking (`self.consecutive_losses`) and 15-minute circuit breaker pause (`self.paused_until`) are implemented in `bot_engine.py:360-383` and `portfolio_engine.py:195-200`.
  3. Anti-whipsaw post-settlement cooldown (minimum 180s per asset) is enforced via `self._asset_cooldown_until` in `bot_engine.py:343-346` and checked under `self._order_lock`.
  4. Microstructure qualification is implemented in `qualify_asset_microstructure` with 4 mathematical dimensions (flat_bar_ratio, unique_price_ratio, whipsaw_sign_flip_ratio, relative_atr).
  5. UI communicates via REST polling (3000ms `fetchLiveBotStatus` on `/api/v1/bot/status`), and `index.html` lacks explicit UI badge rendering for `PAUSED` / countdown display.
- **Unexplored areas**: None for survey scope.

## Key Decisions Made
- Fully documented all 4 investigation areas with exact file paths, line numbers, formulas, and interface contracts.

## Artifact Index
- `.agents/explorer_survey_2/DISPATCH.md` — Inbound message log
- `.agents/explorer_survey_2/progress.md` — Progress and liveness log
- `.agents/explorer_survey_2/BRIEFING.md` — Persistent memory
- `.agents/explorer_survey_2/handoff.md` — Final comprehensive analysis report
