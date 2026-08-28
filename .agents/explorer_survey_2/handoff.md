# Explorer 2 Survey & Architecture Analysis Report

**Date**: 2026-08-24  
**Project**: `strat_trade_be`  
**Mission**: Survey and investigate risk management, circuit breakers, cooldowns, asset qualification, and telemetry in the codebase.

---

## 1. Observation

### 1.1 Codebase Structure & Component Locations

| Component | Exact File Path | Key Classes / Methods | Interface Role |
|---|---|---|---|
| **Bot Engine & Risk Governance** | `src/strat_trade/domain/trading/bot_engine.py` | `LiveDemoBotEngine` (`start`, `stop`, `pause`, `resume`, `_run_loop`, `_check_circuit_breakers`, `_check_active_trades`, `_evaluate_signals_and_trade`, `_evaluate_single_asset`, `_execute_order`) | Central autonomous live/demo trading engine orchestrating risk limits, circuit breakers, streaks, and cooldowns. |
| **Trading Domain Entities** | `src/strat_trade/domain/trading/entities.py` | `BotStatus`, `TradeOutcome`, `IndicatorSnapshot`, `StrategyAssignment`, `PreTradingPlan`, `LiveTradeRecord`, `BotSessionSummary` | Domain data models and state enums. |
| **Asset Quality & Noise Filter** | `src/strat_trade/domain/trading/asset_filter.py` | `qualify_asset_microstructure()`, `is_toxic_asset()`, `is_whitelisted_asset()`, `filter_allowed_assets()`, `canonical_asset_key()` | Statistical price-action micro-tick filter, canonical normalization, blacklist/whitelist filtering. |
| **Portfolio Backtest Risk Parity** | `src/strat_trade/domain/backtest/portfolio_engine.py` | `PortfolioBacktestEngine` (`run`, `resolve_trade`) | Multi-asset backtesting engine with identical risk governance (stop loss, peak drawdown halt, consecutive loss pause, cooldowns). |
| **Currency Correlation Filter** | `src/strat_trade/domain/trading/correlation.py` | `is_correlated_conflict()`, `extract_base_quote_currencies()`, `normalize_symbol()` | Rejects correlated directional exposure on base/quote currencies. |
| **Persistent SQLite Store** | `src/strat_trade/domain/trading/trade_store.py` | `TradeStore` (`save_trade`, `update_trade_outcome`, `get_trade_by_id`, `list_trades`, `mark_merged`, `clear_trades`) | Persistent WAL SQLite storage for trade records and indicator snapshots (`data/trades.db`). |
| **Use Cases & Bot Singleton** | `src/strat_trade/use_cases/manage_live_bot.py` | `get_bot_engine()`, `start_live_bot()`, `stop_live_bot()`, `pause_live_bot()`, `resume_live_bot()`, `get_live_bot_status()`, `get_live_bot_trades()`, `clear_live_bot_trades()` | Singleton accessor and lifecycle management use cases. |
| **Pre-Trading Plan Generation** | `src/strat_trade/use_cases/auto_assign_strategies.py` | `generate_pre_trading_plan()` | Concurrent asset evaluation and optimal strategy assignment. |
| **Strategy Auto Matcher** | `src/strat_trade/domain/optimizer/auto_matcher.py` | `StrategyAutoMatcher` (`find_optimal_strategy_for_asset`, `_heuristic_profile_for_asset`) | Asset profiling with microstructure qualification and quantitative scoring. |
| **API Endpoints** | `src/strat_trade/api/routes/bot.py` | `POST /api/v1/bot/auto-assign`, `POST /api/v1/bot/start`, `POST /api/v1/bot/stop`, `POST /api/v1/bot/pause`, `POST /api/v1/bot/resume`, `GET /api/v1/bot/status`, `GET /api/v1/bot/trades`, `POST /api/v1/bot/clear-trades` | REST API routes for bot management and telemetry. |
| **API Schemas** | `src/strat_trade/api/schemas.py` | `BotStatusResponse`, `PreTradingPlanResponse`, `LiveTradeResponse`, `AutoAssignRequest`, `StartBotRequest`, `PauseBotRequest` | Pydantic v2 schemas for request validation and response serialization. |
| **Web UI & Telemetry Polling** | `src/strat_trade/web/templates/index.html` | `fetchLiveBotStatus()`, `renderLiveBotStatus()`, `handleStartLiveBot()`, `handleStopLiveBot()` | Frontend web dashboard interacting via 3000ms REST polling. |

---

### 1.2 Trade Outcome Recording and Streak Tracking

In `src/strat_trade/domain/trading/bot_engine.py:269-386`:
```python
async def _check_active_trades(self) -> None:
    now = datetime.now(UTC)
    finished_ids = []

    for tid, trade in list(self.active_trades.items()):
        expiry_time = trade.open_time + timedelta(seconds=trade.expiration_seconds)
        if now >= expiry_time:
            # Resolve trade result with latest market price
            try:
                candles = await self._gateway.get_candles(
                    trade.asset, timeframe=60, count=5
                )
                close_price = Decimal(str(candles[-1].close)) if candles else trade.open_price
            except Exception:
                close_price = trade.open_price

            # Determine WIN / LOSS / DRAW
            if trade.action == "CALL":
                if close_price > trade.open_price:
                    outcome = TradeOutcome.WIN
                    pnl = trade.stake * trade.payout_rate
                elif close_price < trade.open_price:
                    outcome = TradeOutcome.LOSS
                    pnl = -trade.stake
                else:
                    outcome = TradeOutcome.DRAW
                    pnl = Decimal("0.00")
            else:  # PUT
                if close_price < trade.open_price:
                    outcome = TradeOutcome.WIN
                    pnl = trade.stake * trade.payout_rate
                elif close_price > trade.open_price:
                    outcome = TradeOutcome.LOSS
                    pnl = -trade.stake
                else:
                    outcome = TradeOutcome.DRAW
                    pnl = Decimal("0.00")

            trade.close_time = now
            trade.close_price = close_price
            trade.outcome = outcome
            trade.pnl = pnl

            self.current_balance += pnl
            if self.current_balance > self.peak_balance:
                self.peak_balance = self.current_balance

            # Update drawdown tracking
            if self.peak_balance > Decimal("0.00"):
                dd = float(((self.peak_balance - self.current_balance) / self.peak_balance) * Decimal("100.0"))
                self.current_drawdown_pct = max(0.0, dd)
                if self.current_drawdown_pct > self.max_drawdown_pct:
                    self.max_drawdown_pct = self.current_drawdown_pct

            trade.balance_after = self.current_balance

            # Update SQLite database
            self.trade_store.update_trade_outcome(
                trade_id=trade.trade_id,
                close_time=now,
                close_price=close_price,
                outcome=outcome,
                pnl=pnl,
                balance_after=self.current_balance,
            )

            self.recent_trades.insert(0, trade)
            finished_ids.append(tid)

            # Set Post-Trade-Settlement Per-Asset Cooldown (Hard min 3 mins / 180s)
            cooldown_bars = self.plan.cooldown_bars if self.plan else 3
            cooldown_sec = max(180, cooldown_bars * 60)
            self._asset_cooldown_until[trade.asset] = now + timedelta(seconds=cooldown_sec)

            # Handle Consecutive Loss Circuit Breaker
            if outcome == TradeOutcome.LOSS:
                self.consecutive_losses += 1
                max_losses = self.plan.max_consecutive_losses if self.plan else 3
                if self.consecutive_losses >= max_losses:
                    pause_mins = self.plan.pause_duration_minutes if self.plan else 15
                    self.status = BotStatus.PAUSED
                    self.paused_until = now + timedelta(minutes=pause_mins)
            elif outcome == TradeOutcome.WIN:
                self.consecutive_losses = 0

    for fid in finished_ids:
        self.active_trades.pop(fid, None)
```

---

### 1.3 Cooldown Mechanisms & Concurrency Safety

1. **Asset-Specific Post-Settlement Anti-Whipsaw Cooldown**:
   - Set in `bot_engine.py:343-346`: `self._asset_cooldown_until[trade.asset] = now + timedelta(seconds=cooldown_sec)` with `cooldown_sec = max(180, cooldown_bars * 60)`.
   - Checked first in `_evaluate_single_asset` (`bot_engine.py:442-450`):
     ```python
     cooldown_until = self._asset_cooldown_until.get(asset)
     if cooldown_until and now < cooldown_until:
         return
     ```
   - Checked atomically inside `self._order_lock` in `_execute_order` (`bot_engine.py:557-564`):
     ```python
     cooldown_until = self._asset_cooldown_until.get(assignment.asset)
     if cooldown_until and now < cooldown_until:
         return
     ```

2. **Global Portfolio Inter-Trade Delay**:
   - Configured via `self.plan.global_cooldown_seconds` (default 30s).
   - In `_evaluate_signals_and_trade` (`bot_engine.py:398-407`) and `_execute_order` (`bot_engine.py:567-574`): blocks firing multiple orders across different assets in the same 30s window to prevent simultaneous multi-asset margin commitment.

3. **Global Consecutive-Loss Circuit Breaker (15-Minute / 900s Lockout)**:
   - Counter: `self.consecutive_losses: int = 0`.
   - On trade close in `_check_active_trades` (`bot_engine.py:361-383`):
     - If `LOSS`: `self.consecutive_losses += 1`. When `consecutive_losses >= max_losses` (3), sets `self.status = BotStatus.PAUSED` and `self.paused_until = now + timedelta(minutes=15)`.
     - If `WIN`: `self.consecutive_losses = 0`.
   - Auto-resume in `_run_loop` (`bot_engine.py:213-222`):
     ```python
     if self.status == BotStatus.PAUSED and self.paused_until:
         if datetime.now(UTC) >= self.paused_until:
             self.status = BotStatus.RUNNING
             self.paused_until = None
             self.consecutive_losses = 0
     ```
   - Manual resume in `resume()` (`bot_engine.py:134-154`): resets `self.status = BotStatus.RUNNING`, `self.paused_until = None`, `self.consecutive_losses = 0`, and resets high-watermark peak balance baseline to prevent immediate re-halt.

---

### 1.4 Dynamic Asset Qualification & Micro-Tick Noise Filtering

In `src/strat_trade/domain/trading/asset_filter.py:96-195`:
`qualify_asset_microstructure(candles: pd.DataFrame) -> tuple[bool, str]` evaluates 4 statistical dimensions on candle history ($\ge 50$ bars):

1. **Flat-Bar Ratio**:
   $$\text{flat\_bar\_ratio} = \frac{1}{N} \sum_{i=1}^N \mathbf{1}_{(\text{high}_i \le \text{low}_i + 10^{-9}) \lor (|\text{close}_i - \text{open}_i| \le 10^{-9})}$$
   - Rejection threshold: $> 0.15$ (15.00%). Screens out dead zero-spread illiquid or frozen broker feeds.

2. **Unique Price Ratio**:
   $$\text{unique\_price\_ratio} = \frac{|\text{unique}(\text{close})|}{N}$$
   - Rejection threshold: $< 0.30$ (30.00%). Screens out discrete quantized step-tick exotics (e.g. synthetic 5-tick ladders).

3. **Micro-Whipsaw Sign-Flip Ratio**:
   $$\text{whipsaw\_sign\_flip\_ratio} = \frac{1}{N-2} \sum_{t=2}^{N-1} \mathbf{1}_{(r_t \cdot r_{t-1} < 0)}$$
   where $r_t = \text{close}_t - \text{close}_{t-1}$.
   - Rejection threshold: $> 0.80$ (80.00%). Screens out high-frequency alternating noise feeds where price bounces 1 tick up, 1 tick down every second.

4. **Relative ATR**:
   $$\text{relative\_atr} = \frac{\text{ATR}_{14}}{\text{close}_N}$$
   - Rejection threshold: $< 0.000030$ (3.00e-5). Screens out zero-volatility flatline feeds.

5. **Defensive Validation**:
   - Requires $N \ge 50$ bars.
   - Requires columns `open`, `high`, `low`, `close`.
   - Rejects NaNs, infinite values, and non-positive prices ($\le 0$).

---

### 1.5 Telemetry Dispatch & UI Communication

1. **Backend Telemetry Endpoint**:
   - `GET /api/v1/bot/status` in `src/strat_trade/api/routes/bot.py:173-178` returns `BotStatusResponse` containing:
     - `status`: `"IDLE" | "RUNNING" | "PAUSED" | "STOPPED" | "HALTED_BY_STOP_LOSS" | "HALTED_BY_CIRCUIT_BREAKER"`
     - `consecutive_losses`: `int`
     - `paused_until`: `ISO-8601 string | None`
     - `is_paused`: `bool`
     - `circuit_breaker_triggered`: `bool`
     - `current_drawdown_pct`, `max_drawdown_pct`, `peak_balance`, `current_balance`, `net_profit`, `win_rate_pct`, etc.
2. **Frontend UI Polling**:
   - In `src/strat_trade/web/templates/index.html:1874, 1901-2016`:
     - Polling timer: `botPollingInterval = setInterval(fetchLiveBotStatus, 3000)`.
     - `renderLiveBotStatus(data)` handles:
       - `RUNNING`: green badge & pulse.
       - `HALTED_BY_STOP_LOSS`: red stop-loss badge.
       - Generic `else`: displays gray `IDLE` badge.
     - **UI Gap**: `renderLiveBotStatus()` currently lacks a distinct UI rendering branch for `data.status === 'PAUSED'` or `data.is_paused === true` with a live countdown of remaining pause seconds from `data.paused_until`.

---

## 2. Logic Chain

```
[Observation: bot_engine.py:361-383 tracks consecutive_losses & sets status=PAUSED, paused_until = now + 15m]
                                 │
                                 ▼
[Observation: bot_engine.py:213-222 auto-resumes to RUNNING & consecutive_losses=0 when now >= paused_until]
                                 │
                                 ▼
[Observation: portfolio_engine.py:195-200 & 254-260 mirror identical consecutive-loss 15-min lockout]
                                 │
                                 ▼
[Observation: bot_engine.py:343-346 sets 180s per-asset cooldown & checks under order lock]
                                 │
                                 ▼
[Observation: asset_filter.py:96-195 calculates 4 mathematical metrics in qualify_asset_microstructure]
                                 │
                                 ▼
[Observation: schemas.py:802-827 includes consecutive_losses, paused_until, is_paused in BotStatusResponse]
                                 │
                                 ▼
[Observation: index.html:1912-1943 polls /api/v1/bot/status but lacks dedicated PAUSED badge / countdown]
                                 │
                                 ▼
[Conclusion: Full backend risk architecture and parity are in place; UI frontend requires dedicated pause status banner & countdown display, and WebSocket telemetry stream can complement REST polling.]
```

---

## 3. Caveats

1. **No Dedicated `RiskManager` Class File**: The risk management logic currently lives directly inside `LiveDemoBotEngine` (`bot_engine.py`) and `PortfolioBacktestEngine` (`portfolio_engine.py`). If architectural modularity is desired, these risk methods (`_check_circuit_breakers`, `_check_active_trades` outcome handling, cooldown checks) can be extracted into an explicit `RiskManager` class in `src/strat_trade/domain/trading/risk_manager.py`.
2. **WebSocket vs REST Polling**: The frontend web console currently uses 3-second REST polling against `/api/v1/bot/status`. The Pocket Option broker connection uses WebSocket via `pocket_option_gateway.py`. To emit real-time WebSocket telemetry to the browser, a FastAPI WebSocket endpoint (`/api/v1/bot/ws`) can broadcast state updates on every state change or tick.
3. **Runaway Momentum Filter in Strategies**: `SupportResistanceBounceStrategy` and `RsiStochasticExtremeStrategy` currently check wick ratios and oscillator boundaries, but do not yet include a multi-candle consecutive runaway momentum filter (e.g. 3-4 consecutive strong trend candles with minimal wicks).

---

## 4. Conclusion

1. **Loss Handling & Streak Tracking**:
   - `LiveDemoBotEngine` tracks `consecutive_losses` and triggers a 15-minute (`900s`) trading lockout (`paused_until`) upon 3 consecutive losses across all assets.
   - The counter is reset to `0` on any `WIN`, on cooldown expiration (auto-resume), or on manual `resume()`.
   - `PortfolioBacktestEngine` implements exact mathematical parity with `paused_until_time = t.exit_time + timedelta(minutes=15)`.

2. **Asset Cooldowns**:
   - `_asset_cooldown_until[asset] = now + max(180, cooldown_bars * 60)` enforces a hard minimum 3-minute post-settlement anti-whipsaw cooldown.
   - Enforced both at asset candidate evaluation and atomically within `_order_lock`.

3. **Asset Microstructure Qualification**:
   - `qualify_asset_microstructure()` implements 4 quantitative metrics: flat bar ratio ($\le 15\%$), unique price ratio ($\ge 30\%$), whipsaw sign flip ratio ($\le 80\%$), and relative ATR ($\ge 0.000030$).
   - Integrated into `StrategyAutoMatcher` and `filter_allowed_assets`.

4. **UI & Telemetry Integration**:
   - `BotStatusResponse` already provides `consecutive_losses`, `paused_until`, `is_paused`, and `circuit_breaker_triggered`.
   - The UI in `index.html` requires an update to `renderLiveBotStatus()` to render an amber/yellow `PAUSED (COOLDOWN)` badge with live countdown timer when `is_paused` is true.

---

## 5. Verification Method

To independently verify the findings and test execution:

1. **Run full automated test suite**:
   ```bash
   .venv/bin/pytest tests/test_execution_guardrails.py -v
   .venv/bin/pytest
   ```
   *Expected Result*: All 914 tests pass with 0 failures.

2. **Run linter**:
   ```bash
   .venv/bin/ruff check .
   ```
   *Expected Result*: `All checks passed!`

3. **Inspect key source files**:
   - `src/strat_trade/domain/trading/bot_engine.py` (lines 41-49, 212-222, 249-268, 343-383, 441-450, 556-574)
   - `src/strat_trade/domain/trading/asset_filter.py` (lines 96-195)
   - `src/strat_trade/domain/backtest/portfolio_engine.py` (lines 187-200, 254-283)
   - `src/strat_trade/api/schemas.py` (lines 802-827)
   - `src/strat_trade/web/templates/index.html` (lines 1912-1945)
