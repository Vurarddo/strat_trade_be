# Milestone 2 Handoff Report: API, Portfolio Backtester Alignment & Test Strategy

**Agent**: `m2_explorer_3`  
**Milestone**: Milestone 2 — Bot Engine Guardrails & Anti-Whipsaw (R2)  
**Date**: 2026-08-20  
**Handoff Type**: Hard Handoff (Investigation & Architecture Specification Complete)

---

## 1. Observation

### 1.1 Existing Codebase State
- **API Schemas (`src/strat_trade/api/schemas.py`)**:
  - `BotStatusResponse` (lines 646-665) currently exposes basic session counters (`status`, `initial_balance`, `current_balance`, `net_profit`, `roi_pct`, `total_trades`, `winning_trades`, `losing_trades`, `draw_trades`, `pending_trades`, `win_rate_pct`, `max_drawdown_pct`, `stop_loss_reached`, `active_assignments`, `recent_trades`), but lacks real-time circuit breaker and pause metrics (`consecutive_losses`, `peak_balance`, `current_drawdown_pct`, `paused_until`, `is_paused`, `circuit_breaker_triggered`).
  - `PreTradingPlanResponse` (lines 595-610) and `AutoAssignRequest` (lines 579-593) lack Milestone 2 guardrail configuration fields (`cooldown_bars`, `global_cooldown_seconds`, `max_consecutive_losses`, `max_drawdown_pct_limit`, `correlation_filter_enabled`).
  - `PortfolioBacktestRequest` (lines 410-455) lacks guardrail toggle and threshold parameters.
  - No `PauseBotRequest` schema exists.
- **API Routes (`src/strat_trade/api/routes/bot.py`)**:
  - Exposes `POST /auto-assign`, `POST /start`, `POST /stop`, `GET /status`, `GET /trades`.
  - Missing `POST /pause` and `POST /resume` endpoints.
- **Use Cases (`src/strat_trade/use_cases/manage_live_bot.py`)**:
  - Exposes `start_live_bot`, `stop_live_bot`, `get_live_bot_status`, `get_live_bot_trades`.
  - Missing `pause_live_bot` and `resume_live_bot`.
- **Portfolio Backtest Engine (`src/strat_trade/domain/backtest/portfolio_engine.py`)**:
  - Chronological multi-asset simulation exists (lines 40-428), but currently enforces only a per-asset concurrent open position check (`any(t.asset == sig.asset for t in active_trades)`).
  - Lacks post-trade settlement cooldown ($N$ bars), global portfolio spacing cooldown, currency correlation exposure filter, and peak-to-trough drawdown circuit breaker.
- **Test Infrastructure (`tests/`)**:
  - 165 tests currently passing across unit and API suites.
  - No dedicated execution guardrails test suite (`tests/test_execution_guardrails.py`).

---

## 2. Logic Chain

1. **API Lifecycle Symmetry**:
   - Live trading bots require the ability to temporarily suspend execution (e.g. during major macro announcements or after rapid streak losses) without tearing down open positions or dropping session state.
   - Adding `POST /bot/pause` and `POST /bot/resume` in `src/strat_trade/api/routes/bot.py` wired directly through `src/strat_trade/use_cases/manage_live_bot.py` into `LiveDemoBotEngine.pause()` / `resume()` provides a clean, idempotent control interface.
2. **Telemetry Observability**:
   - Operators and front-end dashboards need to know *why* a bot is not firing trades. Extending `BotStatusResponse` with `is_paused`, `paused_until`, `consecutive_losses`, `peak_balance`, `current_drawdown_pct`, and `circuit_breaker_triggered` gives full visibility into the state machine.
3. **Simulation-Production Parity in Backtesting**:
   - If the portfolio backtester does not simulate currency correlation filtering and post-trade settlement cooldowns, backtested Sharpe/Win-rates will be artificially optimistic compared to live bot performance.
   - Integrating `is_correlated_conflict` and cooldown timestamps directly into `PortfolioBacktestEngine.run()` guarantees that backtested trade logs faithfully mirror live bot execution constraints.
4. **Comprehensive Test Coverage**:
   - Designing a standalone test suite in `tests/test_execution_guardrails.py` covering all 6 functional tiers (correlation math, cooldown timings, consecutive loss state machine, peak drawdown halt, API routes, and backtester alignment) prevents regressions and validates all R2 requirements.

---

## 3. Caveats

1. **Concurrency and Time Synchronization**:
   - In `PortfolioBacktestEngine`, trades are resolved chronologically based on candle timestamps. For identical timestamps across multiple assets, stable sorting on `(entry_time, asset)` ensures deterministic ordering.
2. **Correlation Code Sharing**:
   - `is_correlated_conflict(candidate_asset, candidate_action, active_trades)` is designed to work agnostically with both `LiveTradeRecord` and `BacktestTrade` by accessing `.asset` and `.action` via duck-typing.
3. **Auto-Resume vs Manual Resume**:
   - When a bot is paused due to consecutive losses circuit breaker, it can auto-resume after a configurable cooling-off duration (e.g. 15 minutes / 900 seconds) OR be manually resumed via `POST /bot/resume`.

---

## 4. Conclusion

The architectural design for Milestone 2 API endpoints, use cases, backtester alignment, and test suite is fully specified:
- **Schemas**: Updated `src/strat_trade/api/schemas.py` with `PauseBotRequest`, updated `AutoAssignRequest`, `PreTradingPlanResponse`, `BotStatusResponse`, and `PortfolioBacktestRequest`.
- **Routes**: Added `POST /bot/pause` and `POST /bot/resume` in `src/strat_trade/api/routes/bot.py`.
- **Use Cases**: Added `pause_live_bot` and `resume_live_bot` in `src/strat_trade/use_cases/manage_live_bot.py`.
- **Portfolio Engine**: Full guardrail integration in `src/strat_trade/domain/backtest/portfolio_engine.py` and `models.py`.
- **Test Suite**: Ready-to-implement 6-suite specification in `tests/test_execution_guardrails.py` (with prototype in `.agents/m2_explorer_3/proposed_test_execution_guardrails.py`).

---

## 5. Verification Method

1. **Verify Unit & Integration Tests**:
   ```bash
   .venv/bin/pytest tests/test_execution_guardrails.py -v
   .venv/bin/pytest tests/test_bot_and_audit_api.py -v
   .venv/bin/pytest tests/test_portfolio_backtest_models_and_engine.py -v
   .venv/bin/pytest tests/test_portfolio_backtest_api.py -v
   ```
2. **Verify Full Regression Suite**:
   ```bash
   .venv/bin/pytest
   ```
   *Expected*: All existing tests (165+) plus all new execution guardrail tests pass with 0 failures.
3. **Inspect Implementation Files**:
   - `src/strat_trade/api/schemas.py`
   - `src/strat_trade/api/routes/bot.py`
   - `src/strat_trade/use_cases/manage_live_bot.py`
   - `src/strat_trade/domain/backtest/portfolio_engine.py`
   - `src/strat_trade/domain/backtest/models.py`
   - `tests/test_execution_guardrails.py`
