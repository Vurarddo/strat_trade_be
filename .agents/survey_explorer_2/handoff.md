# Handoff Report: Bot Engine & Execution Guardrails

**Agent**: `survey_explorer_2`  
**Handoff Type**: Hard (Task complete)  
**Date**: 2026-08-20  
**Target Subsystem**: Bot Engine Execution Guardrails (R2)  

---

## 1. Observation

Direct observations from the codebase:

1. **Bot Engine Implementation**:
   - Location: `src/strat_trade/domain/trading/bot_engine.py:27-459` (`LiveDemoBotEngine`).
   - Loop interval: 4.0 seconds (`asyncio.sleep(4.0)` at line 153).
   - Singleton manager: `src/strat_trade/use_cases/manage_live_bot.py:12-45`.
   - SQLite Persistence: `src/strat_trade/domain/trading/trade_store.py:17-237` (database at `data/trades.db`).
   - REST Routes: `src/strat_trade/api/routes/bot.py:26-229`.

2. **Cooldown Timers**:
   - In `src/strat_trade/domain/trading/bot_engine.py:274-278`:
     ```python
     # Cooldown per asset: at least 30s
     last_sig = self._last_signal_time.get(asset)
     if last_sig and (now - last_sig).total_seconds() < 30:
         return
     ```
   - Only checks 30 seconds from last *signal fired*, not post-settlement.
   - Zero global cooldown across assets.
   - Zero bar-based cooldown ($N$ bars).
   - `PreTradingPlan` (`entities.py:87-118`) and `PreTradingPlanResponse` (`schemas.py:595-610`) have no cooldown parameters.

3. **Correlated Asset Exposure**:
   - Grep search for `correlation` in `src/strat_trade/` returned 0 results.
   - `LiveDemoBotEngine._evaluate_single_asset()` evaluates each asset independently without inspecting open positions on correlated pairs.
   - If signals fire on `AUDUSD_otc` (CALL) and `AUDNZD_otc` (CALL), both execute up to `max_concurrent_trades`.

4. **Circuit Breakers & Pause/Resume**:
   - In `src/strat_trade/domain/trading/bot_engine.py:155-167`:
     ```python
     async def _check_stop_loss(self) -> None:
         if not self.plan:
             return
         loss = self.initial_balance - self.current_balance
         if loss >= self.plan.stop_loss_amount:
             self.status = BotStatus.HALTED_BY_STOP_LOSS
     ```
   - Only checks loss against `initial_balance`, not peak-to-trough drawdown.
   - Zero tracking of consecutive losses ($K$ streak).
   - `BotStatus` enum (`entities.py:10-15`) only has `IDLE`, `RUNNING`, `STOPPED`, `HALTED_BY_STOP_LOSS`. No `PAUSED` state or resume endpoints.

5. **Backtester Equivalence**:
   - `PortfolioBacktestEngine` (`portfolio_engine.py:230-236`) only checks concurrency and exact duplicate asset, lacking cooldowns and correlation filters.

---

## 2. Logic Chain

1. **Observation 1 & 2 $\implies$ Cooldown Gap**:
   Because cooldown is checked only as `(now - last_sig) < 30` at signal time, any trade lasting 180 seconds completes long after the 30s timer expired. As a result, when the trade settles, the bot can immediately re-enter the exact same asset on the very next 4-second loop tick (0-second resting period), leading to whipsaw losses in choppy markets.

2. **Observation 3 $\implies$ Correlated Exposure Risk**:
   Because there is no currency decomposition or correlation mapping, the bot treats `AUDUSD_otc`, `AUDNZD_otc`, `AUDCAD_otc`, and `AUDJPY_otc` as completely independent assets. Under multi-asset auto-assignment, a systemic move in AUD or USD can trigger concurrent losses across all open slots, causing sharp drawdown spikes.

3. **Observation 4 $\implies$ Lack of Downside Protection**:
   In the absence of a consecutive-loss circuit breaker, when a strategy experiences an adverse regime (e.g. strong trend against mean reversion), it continues trading until the session stop-loss is hit. Furthermore, measuring drawdown strictly against `initial_balance` fails to protect profits after the account has grown.

4. **Observation 5 $\implies$ Simulation Divergence**:
   Without mirroring cooldowns and correlation guards in `PortfolioBacktestEngine`, backtest results will over-estimate trade frequency and miscalculate portfolio drawdowns relative to live bot behavior.

---

## 3. Caveats

- **Network-Mode / Live Broker Execution**: Live execution timing depends on `PocketOptionTradingGateway` WebSocket responsiveness. The 4-second polling interval in `_run_loop()` creates a maximum 4s latency for signal detection on M1 candles, which is well within 60s bar boundaries.
- **Crypto / Cross Assets**: Currency pair decomposition applies to standard forex and OTC forex pairs (e.g. `EURUSD_otc`, `AUDUSD_otc`). For non-forex assets (e.g. `BTCUSD_otc` or commodity OTC), correlation rules should group by underlying asset class / quote currency.

---

## 4. Conclusion

The bot engine execution guardrails subsystem requires the following concrete additions to fulfill Requirement R2:
1. **Per-Asset & Global Cooldowns**: Enforce a post-settlement resting period of $N$ bars (or seconds) per asset and a global cooldown (e.g. 30s) between any consecutive trade entries.
2. **Correlation Guard**: Implement a currency decomposition engine (`src/strat_trade/domain/trading/correlation.py`) to prevent simultaneous trades with conflicting or duplicate net currency exposure (e.g. double Long AUD).
3. **Multi-Tier Circuit Breakers**: Implement $K$ consecutive losses pause (15-min pause into `BotStatus.PAUSED`), peak-to-trough high-watermark drawdown halting (`BotStatus.HALTED_BY_CIRCUIT_BREAKER`), and REST API routes for pause/resume.
4. **Portfolio Backtester Parity**: Update `PortfolioBacktestEngine` with the identical guardrail logic.

Detailed findings, data models, code sketches, and testing strategies are published in:
`/Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_2/survey_report.md`

---

## 5. Verification Method

1. **Inspect Survey Report**:
   ```bash
   view_file /Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_2/survey_report.md
   ```
2. **Run Test Suite**:
   ```bash
   pytest tests/test_bot_and_audit_api.py tests/test_portfolio_backtest_models_and_engine.py -v
   ```
   All existing tests pass with zero regressions.
