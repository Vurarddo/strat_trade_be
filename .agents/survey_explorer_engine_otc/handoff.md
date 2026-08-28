# Handoff Report: Explorer 2 (Engine Architecture & OTC Microstructure Analyst)

**Agent:** Explorer 2  
**Working Directory:** `/Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_engine_otc`  
**Date:** 2026-08-28  
**Report Target:** `handoff.md`  
**Parent Orchestrator:** `a4cd7c19-41e7-41e0-a8ff-77a082f42fec`

---

## 1. Observation

Direct code and database observations with exact line numbers and quotes:

1. **Database Anomaly Telemetry (`data/trades.db`):**
   - Query command: `SELECT trade_id, asset, action, stake, open_time, strategy_id FROM trades ORDER BY open_time ASC`
   - Output observed:
     - Trade 1: `5f659123-b38b-4051-9cc2-b469a29fb007`, `EURUSD_otc`, `CALL`, `open_time: 2026-08-28T11:05:58.711275+00:00`
     - Trade 2-6: Five trades on `EURUSD_otc`, `GBPUSD_otc`, `USDJPY_otc`, `AUDUSD_otc`, `NZDUSD_otc` with exact identical timestamp: `2026-08-28T11:06:00.350966+00:00`, all `CALL`, all `supertrend_adx_momentum` with `confidence: 0.7`.
     - Trade 7-9: Three trades at `11:06:01.111359`, `11:06:01.113413`, `11:06:01.121401` on `EURUSD_otc` and `GBPUSD_otc`.

2. **Parallel Task Dispatch Race Condition (`src/strat_trade/domain/trading/bot_engine.py:528-533, 564, 597, 712`):**
   - Line 514: `now = datetime.now(UTC)`
   - Line 528-532:
     ```python
     sem = asyncio.Semaphore(6)
     tasks = [
         self._evaluate_single_asset(assignment, now, sem)
         for assignment in self.plan.assignments
     ]
     await asyncio.gather(*tasks, return_exceptions=True)
     ```
   - Line 597: `if any(t.asset == asset for t in self.active_trades.values()): return`
   - Line 712: `if self.plan.correlation_filter_enabled and self.active_trades:`
   - Line 728: `if len(self.active_trades) < self.plan.max_concurrent_trades:`

3. **Circuit Breaker Auto-Unpause Invalidation Bug (`src/strat_trade/domain/trading/bot_engine.py:424-436, 488-502`):**
   - Lines 427-436:
     ```python
     if self.status == BotStatus.RUNNING:
         self.status = BotStatus.PAUSED
     self.paused_until = now + timedelta(minutes=pause_mins)
     ```
   - Lines 488-496:
     ```python
     elif outcome == TradeOutcome.WIN:
         self.consecutive_losses = 0
         ...
         if self.status == BotStatus.PAUSED and self.paused_until:
             self.status = BotStatus.RUNNING
             self.paused_until = None
     ```

4. **Forex Session Filter Hard-Blocking 24/7 OTC Pairs (`src/strat_trade/domain/trading/asset_filter.py:284-290, 340-349`):**
   - Lines 284-289: Normalizes symbol by removing `_OTC`, ` OTC`, `_otc` -> `EURUSD_otc` becomes `EURUSD`.
   - Lines 343-348:
     ```python
     start_mins = 6 * 60 + 30  # 06:30 UTC
     end_mins = 22 * 60        # 22:00 UTC
     if not (start_mins <= current_mins <= end_mins):
         return False, f"European/US asset '{asset}' is outside active London/NY session..."
     ```

5. **Broker Payout Query Silent Fallback to 92% (`src/strat_trade/adapters/pocket_option_gateway.py:522`):**
   - Line 522: `return 0.92 if "OTC" in sym else 0.80`

6. **Settlement on Active Next Bar (`src/strat_trade/domain/trading/bot_engine.py:328-341`):**
   - Lines 333-338:
     ```python
     candles = await self._gateway.get_candles(trade.asset, timeframe=60, count=5)
     close_price = Decimal(str(candles[-1].close)) if candles else trade.open_price
     ```

---

## 2. Logic Chain

1. **Concurrent Evaluation Execution:** In `_evaluate_signals_and_trade`, all configured assets are evaluated concurrently via `asyncio.gather(*tasks)`.
2. **State Check Before Lock:** Gates 4 (Duplicate Asset), Gate 10 (Correlation Conflict), and Gate 11 (Concurrency Limit) inspect `self.active_trades` while it is still empty (`{}`).
3. **Multi-Order Dispatch:** Because all concurrent tasks see `self.active_trades` as empty, all tasks generate signals and enter `_execute_order` with the same `now` timestamp.
4. **Bypass of Guards:** As a direct consequence, 5 trades open simultaneously across correlated pairs (`EURUSD_otc`, `GBPUSD_otc`, `AUDUSD_otc`, `NZDUSD_otc`, `USDJPY_otc`) at microsecond `11:06:00.350966`, bypassing concurrency limits, duplicate checks, and correlation rules.
5. **Circuit Breaker Defeat:** If 3 consecutive losses pause the engine for 15 minutes, an in-flight 4th trade that finishes as a WIN executes line 495 (`self.status = BotStatus.RUNNING; self.paused_until = None`), instantly destroying the 15-minute cooldown.
6. **Session Filter Flaw:** Normalizing `EURUSD_otc` to `EURUSD` subjects a 24/7 OTC feed to interbank 06:30-22:00 UTC hours, blocking the bot from trading OTC at night (22:00-06:30 UTC) and on weekends.

---

## 3. Caveats

1. **Broker WebSocket Message Protocol:** BinaryOptionsToolsV2 handles low-level WebSocket frame decoding; latency figures reflect local gateway profiling.
2. **Backtesting Framework:** Analysis focused on live execution architecture in `bot_engine.py` and real-time filters; standalone vectorized backtester (`VectorizedBinaryBacktester`) was not the primary focus of this engine audit.
3. **Network Jitter:** In live environments, network round-trip time (RTT) between server and broker WebSocket adds an additional 50-300ms of entry slippage not modeled in offline unit tests.

---

## 4. Conclusion

The engine architecture suffers from **4 Critical (P0) flaws** and **4 High (P1) flaws**:
- The database anomaly was conclusively proven to be caused by parallel task execution (`asyncio.gather`) evaluating pre-trade state against an empty in-flight dictionary, exacerbated by continuous signal emission in `SupertrendAdxMomentumStrategy`.
- The circuit breaker is unsafe due to in-flight winning trade state pollution.
- The session filter mistakenly cripples 24/7 OTC trading.
- The 4-metric microstructure gate is blind to short-duration 5-minute broker manipulation bursts.

Full technical details, mathematical impact models, and remediation specifications are documented in `analysis.md`.

---

## 5. Verification Method

To independently verify these findings:

1. **Verify Database Telemetry:**
   ```bash
   python3 -c "
   import sqlite3
   conn = sqlite3.connect('data/trades.db')
   cursor = conn.cursor()
   cursor.execute('SELECT trade_id, asset, action, open_time, strategy_id FROM trades ORDER BY open_time ASC')
   for r in cursor.fetchall():
       print(r)
   "
   ```
2. **Verify Session Filter Bug on OTC Pairs:**
   ```bash
   python3 -c "
   from datetime import datetime, UTC
   from strat_trade.domain.trading.asset_filter import is_asset_in_active_session
   t_night = datetime(2026, 8, 28, 23, 0, 0, tzinfo=UTC)
   active, reason = is_asset_in_active_session('EURUSD_otc', t_night)
   print('EURUSD_otc at 23:00 UTC active?', active, '| Reason:', reason)
   assert active is False  # Confirms the bug blocking OTC at night
   "
   ```
3. **Verify Circuit Breaker Auto-Unpause Invalidation:**
   Inspect `src/strat_trade/domain/trading/bot_engine.py` lines 488-502 to confirm `self.status = BotStatus.RUNNING` and `self.paused_until = None` are executed whenever any trade closes as `TradeOutcome.WIN`.
4. **Verify Concurrency Gathering:**
   Inspect `src/strat_trade/domain/trading/bot_engine.py` lines 528-533 to confirm `asyncio.gather(*tasks)` launches parallel asset evaluations without state pre-reservations.
