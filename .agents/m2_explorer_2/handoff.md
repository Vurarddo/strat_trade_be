# Milestone 2: Cooldown Timers & Circuit Breakers in Bot Engine — Handoff Report

## 1. Observation
1. **Existing `BotStatus` Enum** (`src/strat_trade/domain/trading/entities.py:10-15`):
   - Only defines `IDLE`, `RUNNING`, `STOPPED`, `HALTED_BY_STOP_LOSS`.
   - Lacks `PAUSED` and `HALTED_BY_CIRCUIT_BREAKER` states.
2. **Existing `PreTradingPlan` Dataclass** (`src/strat_trade/domain/trading/entities.py:87-118`):
   - Configures `assignments`, `initial_deposit`, `stake_model`, `stake_amount`, `stake_percent`, `expiration_seconds`, `daily_stop_loss_pct`, `stop_loss_amount`, `max_concurrent_trades`, `min_payout_rate`.
   - Lacks fields for cooldown timing (`cooldown_bars`, `global_cooldown_seconds`), loss streak circuit breaker (`max_consecutive_losses`, `pause_duration_minutes`), max drawdown threshold (`max_drawdown_pct_limit`), and correlation exposure toggle (`correlation_filter_enabled`).
3. **Existing `BotSessionSummary` Dataclass** (`src/strat_trade/domain/trading/entities.py:152-171`):
   - Lacks real-time telemetry attributes for `consecutive_losses`, `peak_balance`, `current_drawdown_pct`, `paused_until`, and `is_paused`.
4. **Existing `LiveDemoBotEngine` State Machine & Execution Loop** (`src/strat_trade/domain/trading/bot_engine.py:27-407`):
   - `_run_loop()` runs only while `self.status == BotStatus.RUNNING` (line 139).
   - `_check_active_trades()` (lines 168-239) updates balance and PnL, but does not track peak balance ($HWM$), does not compute peak-to-trough drawdown, does not count consecutive losses, and does not activate post-settlement resting cooldown per asset.
   - `_evaluate_signals_and_trade()` (lines 240-256) fires concurrent evaluations without enforcing a global portfolio delay between executions or checking correlation conflicts.
   - `_evaluate_single_asset()` (lines 257-322) checks a 30s signal-to-signal timer, but does not enforce post-settlement $N$-bar cooldown or correlation filtering.
   - `LiveDemoBotEngine` lacks `pause()` and `resume()` methods.

---

## 2. Logic Chain
1. **Post-Trade Settlement Cooldown**:
   - Immediate re-entry into the same asset after trade settlement frequently results in whipsaws during adverse regimes.
   - By capturing trade close time in `_check_active_trades` and setting `_asset_cooldown_until[asset] = now + timedelta(seconds=cooldown_bars * 60)`, subsequent calls to `_evaluate_single_asset` will skip signal evaluation until the cooldown period expires.
2. **Global Portfolio Execution Delay**:
   - When multiple currency pairs generate signals concurrently (e.g. during a market shock), opening multiple trades at the exact same second spikes portfolio volatility.
   - Tracking `_last_global_execution_time` under an atomic async order lock (`_order_lock`) and rejecting trades if `elapsed < global_cooldown_seconds` ensures trades are spaced by at least 30 seconds across all assets.
3. **Consecutive Losses Circuit Breaker**:
   - Prolonged loss streaks typically signal strong regime shifts (e.g. mean-reversion in runaway trends).
   - In `_check_active_trades`, when `outcome == TradeOutcome.LOSS`, `consecutive_losses` increments. If it reaches `max_consecutive_losses` (default 3), the bot transitions to `BotStatus.PAUSED` with `paused_until = now + timedelta(minutes=15)`.
   - While `PAUSED`, `_run_loop` skips signal evaluation but continues settling open positions.
   - Once `now >= paused_until` or upon manual `resume()`, status transitions back to `BotStatus.RUNNING` and `consecutive_losses` resets to 0.
4. **High-Watermark Drawdown Circuit Breaker**:
   - `initial_deposit` stop-loss does not protect accrued session profits (e.g., account doubles, then gives back 50%).
   - Tracking `self.peak_balance = max(self.peak_balance, self.current_balance)` and computing `current_drawdown_pct = (peak_balance - current_balance) / peak_balance * 100` ensures that when drawdown exceeds `max_drawdown_pct_limit * 100` (e.g. 8.0%), the bot transitions to `BotStatus.HALTED_BY_CIRCUIT_BREAKER`, terminating execution immediately.
5. **Lifecycle State Machine (`pause()` / `resume()`)**:
   - `pause()` transitions `RUNNING -> PAUSED` and clears `paused_until` (requiring explicit manual resume).
   - `resume()` transitions `PAUSED -> RUNNING`, clears `paused_until`, and resets `consecutive_losses = 0`.

---

## 3. Caveats
- **Timezone Standardization**: All datetime operations in `bot_engine.py` must use `datetime.now(UTC)` to avoid timezone mismatch with SQLite UTC strings or system clock.
- **Drawdown Limit Format**: In `PreTradingPlan`, `max_drawdown_pct_limit` is defined as a float fraction (0.08 = 8%). Circuit breaker calculations multiply by 100.0 for comparison with `current_drawdown_pct`.
- **DRAW Outcome Handling**: In binary options, a DRAW returns the stake with 0 PnL. In our design, a DRAW does not increment `consecutive_losses` and does not reset the loss streak.
- **Correlation Filter Import**: `bot_engine.py` gracefully imports `is_correlated_conflict` from `strat_trade.domain.trading.correlation` with an `ImportError` fallback so bot engine tests can run even before `correlation.py` is fully populated.

---

## 4. Conclusion
The proposed architecture provides complete protection against whipsaws, rapid drawdown cascades, and simultaneous over-exposure in live/demo trading:
1. `entities.py` cleanly extends `BotStatus`, `PreTradingPlan`, and `BotSessionSummary` with fully backward-compatible default parameters.
2. `bot_engine.py` implements strict post-settlement per-asset cooldown ($N$ bars), global portfolio spacing (30s), consecutive loss cooling-off pause (15 mins), and peak equity high-watermark drawdown circuit breaking (8%).
3. Fully supports asynchronous, concurrency-safe `pause()` and `resume()` operations.

---

## 5. Verification Method
1. **Run Current Test Suite**:
   ```bash
   ./.venv/bin/pytest
   ```
2. **Run New Execution Guardrails Unit Test Suite**:
   ```bash
   ./.venv/bin/pytest tests/test_execution_guardrails.py -v
   ```
3. **Specific Test Invalidation Conditions**:
   - If an asset re-enters a trade within $N$ bars of prior trade settlement -> FAIL.
   - If two portfolio trades execute within `< 30s` of each other -> FAIL.
   - If 3 consecutive losses do not transition the bot to `BotStatus.PAUSED` -> FAIL.
   - If drawdown $\ge 8\%$ from peak balance does not halt the bot with `HALTED_BY_CIRCUIT_BREAKER` -> FAIL.
   - If `bot.pause()` and `bot.resume()` fail to pause/resume signal evaluation -> FAIL.
