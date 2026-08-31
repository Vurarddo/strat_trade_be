# Pocket Option AutoTrader Pro — Live Bot Runtime Briefing

**Repository:** `strat_trade_be`  
**Stack:** FastAPI + async Python, SQLite (`data/trades.db`), Pocket Option via `BinaryOptionsToolsV2`  
**Domain:** Binary options (CALL/PUT), fixed expiration, payout ~75–92%, spot and OTC assets  
**Document date:** 2026-08-31 (post broker-truth fixes)

This document is a self-contained technical briefing for another AI agent or reviewer. It describes how the live bot works end-to-end: business intent, execution order, risk controls, known limitations, and recent empirical context.

---

## 1. Business Intent (Why the System Is Built This Way)

**Goal:** Autonomously trade Pocket Option binary options with positive mathematical expectancy while protecting capital.

Core product assumptions:

1. **Alpha is sought on short M1 candles** (typical expiration: 180s = 3 bars).
2. **OTC ≠ spot.** OTC is broker-generated synthetic price action: noise, flat bars, step-tick microstructure. OTC therefore starts in **probation** (stake ×0.25, higher payout floor 90%).
3. **Pre-launch optimizer** assigns each asset a strategy + parameters on a short backtest (~150 candles). This is **not** a guarantee of edge — only a starting plan.
4. **Capital protection beats trade frequency.** Many gates reject signals before any order is sent.
5. **Ground truth for WIN/LOSS is the broker**, not the bot’s local candles. Previously, candle-based settlement corrupted circuit breaker and asset governor behavior.

Philosophy: *profit first*, but today the system is better described as a **risk-gated executor with a noisy optimizer** than as a proven alpha engine.

---

## 2. Architecture (Layers)

```
UI / HTTP client
    ↓
FastAPI routes: src/strat_trade/api/routes/bot.py, audit.py
    ↓
Use-cases: manage_live_bot.py, auto_assign_strategies.py, merge_broker_report.py
    ↓
Domain:
  trading/bot_engine.py          ← main loop (singleton LiveDemoBotEngine)
  optimizer/auto_matcher.py      ← strategy assignment
  strategies/* + registry.py     ← signal generation
  trading/execution_gates.py     ← bar-edge, closed candles
  trading/asset_governor.py      ← OTC probation / mute / promote
  trading/asset_filter.py        ← toxic list + microstructure
  trading/correlation.py
  trading/regime_detector.py
  trading/trade_store.py         ← SQLite persistence
  analytics/xls_merger.py        ← broker CSV ↔ bot DB merge
    ↓
Adapter: adapters/pocket_option_gateway.py
    ↓
SDK: BinaryOptionsToolsV2 (buy/sell/candles/closed deals)
```

One process = one global bot instance (`_global_bot_engine`).

---

## 3. Session Lifecycle (What Fires After What)

### Step A — Auto-assign

`POST /api/v1/bot/auto-assign` → `StrategyAutoMatcher` / `generate_pre_trading_plan`.

For each asset:

1. Fetch ~**150** M1 candles.
2. Filter toxic asset names (blacklist).
3. If insufficient data (<35 bars) → **heuristic** profile (fake WR≈62%, PF≈1.45).
4. If ≥50 bars and **microstructure fails** → heuristic + `quantum_score=15` + rationale `[MICROSTRUCTURE REJECTED] …`  
   **Important:** the asset **remains in the plan**, but live trading re-runs the same filter and often does not trade.
5. Otherwise → parameter grid × `BinaryBacktestEngine`.
6. Compute `quantum_score` (simplified):

   ```
   (WR - 50) * 3 + min(PF, 4) * 15 + min(trades, 10) * 3 - DD * 0.5 + ROI * 0.5
   + bonus if strategy ∈ PRIORITY_STRATEGIES
   ```

7. By default, priority strategies only:
   - `support_resistance_bounce`
   - `rsi_stochastic_extreme`  
   (others rarely win the matcher unless listed in `allowed_strategies`).

**Reproducibility issue:** repeated auto-assign on the same assets yields **different** plans (small backtest samples of 1–9 trades → unstable ranking).  
**Ground truth for the running plan** = `GET /api/v1/bot/status` **after** `start`, not the raw auto-assign JSON.

### Step B — Start

`POST /api/v1/bot/start` with `plan` → `LiveDemoBotEngine.start`:

- resets balance/counters from `initial_deposit`;
- builds `AssetGovernor`;
- instantiates strategies with assignment parameters;
- starts `_run_loop` every **4 seconds**.

### Step C — Main loop (each tick)

```
1. _check_active_trades()     # settle expired trades
2. _check_circuit_breakers()  # hard SL / DD / trailing / TP
3. if PAUSED and paused_until elapsed → RUNNING, reset consecutive_losses
4. if RUNNING → _evaluate_signals_and_trade()
5. sleep 4s
```

### Step D — Before scanning assets

- `active_trades >= max_concurrent_trades` (default **3**) → stop
- global cooldown (**30s** between portfolio opens) → stop
- then evaluate assets in parallel (semaphore **6**)

### Step E — Per-asset gates (order matters)

| # | Gate | Intent | Default / rule |
|---|------|--------|----------------|
| 0 | Bar-edge | Avoid first seconds of new M1 bar (noise/spike) | block **3s** |
| 0b | Asset governor | OTC haircut / mute / promote | OTC stake ×**0.25**, OTC payout ≥**0.90** |
| 1 | Per-asset degradation | Fast mute after loss streak / low WR | 2 losses → 60m; WR<40% after ≥3 → 120m |
| 2 | Toxic blacklist | Hard block by name | `asset_filter.DEFAULT_TOXIC…` |
| 3 | Session filter | Spot blocked on weekends; OTC 24/7 (with exceptions) | enabled |
| 4 | Already open | No duplicate position on same asset | |
| 4b | Post-settle cooldown | Pause after close on asset | ≥ max(180, cooldown_bars×60) s |
| 5 | Signal-to-signal | Anti-spam | ≥**30s** |
| 6 | Live payout | Skip low payout assets | spot ≥**0.80**, OTC ≥**0.90** (governor) |
| 6b | Closed bar only | Indicators on closed candles only | **True** |
| 7 | Microstructure | Reject dead/step-tick synthetic feeds | flat>15%, uniq<30%, ATR/close<3e-5, price<0.001 |
| 8 | Regime | Stand aside in LOW_VOLATILITY_NOISE | |
| 9 | Strategy signal | CALL/PUT + confidence ≥ **0.50** | |
| 10 | Correlation | Block same-currency exposure conflict | enabled |
| 11 | Execute | Re-check under `_order_lock` → place order | |

### Step F — Order execution

1. Stake size: flat `stake_amount` or % of balance, × `stake_multiplier` from governor.
2. `gateway.open_trade` → CALL=`buy`, PUT=`sell`, duration = **`plan.expiration_seconds`** (not strategy `base_expiration_bars`!).
3. `open_price`: broker fill preferred (`get_deal_entry_price` / deal fields), else candle. Telemetry: `open_price_source` = `broker|candle`.
4. Persist to SQLite + indicator snapshot (RSI with **strategy period** via `ta`, ADX, ATR, Stoch, etc.).

### Step G — Settlement

After `open_time + expiration_seconds`:

1. Query broker `get_trade_result` → WIN/LOSS/DRAW + profit + close → `settlement_source=broker`.
2. If broker silent, wait up to **25s** grace (`BROKER_SETTLEMENT_GRACE_SECONDS`).
3. Fallback: compare candle close vs `open_price` → `settlement_source=candle`.

After settlement: update local balance, consecutive losses, governor stats, cooldowns, per-asset mute.

**Important:** a WIN **no longer clears** circuit breaker pause. Pause ends only when `paused_until` elapses.

### Step H — Post-session audit (user workflow)

1. Download CSV from Pocket Option trade history.
2. Upload to Merger (`POST /api/v1/audit/upload-xls`).
3. Merge by `broker_order_id` (fuzzy fallback: same asset + |Δt|≤10s).
4. Broker profit/outcome overwrite bot record → export merged CSV for analysis.

The merger is **correct** (validated field-by-field against broker API). Previously it only **fixed the report after the fact**; live guards had already learned from wrong candle outcomes. After broker-truth, DB and merged CSV should align.

---

## 4. Strategy Catalog

File: `src/strat_trade/domain/strategies/registry.py`

| ID | Name | Signal type |
|----|------|-------------|
| `rsi_stochastic_extreme` | RSI + Stoch Extreme Scalp | reversal at extremes |
| `support_resistance_bounce` | S&R Pin-Bar | S/R bounce + pin-bar wick |
| `ema_pullback_trend` | EMA Ribbon Trend Pullback | trend + pullback |
| `bollinger_atr_reversion` | BB+ATR | mean reversion |
| `hybrid_multifactors` | Hybrid | combined factors |
| `macd_divergence_break` | MACD divergence | divergence break |
| `volatility_squeeze_breakout` | Squeeze | breakout |
| `supertrend_adx_momentum` | SuperTrend+ADX | momentum |

Signal path: `BaseStrategy.evaluate_candles` → indicators on DataFrame → `evaluate_bar` on last **closed** bar.

On live, the first three dominate (matcher priority + user `allowed_strategies`).

---

## 5. Risk Management (Plan Defaults)

From `PreTradingPlan` / `entities.py`:

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `stake_model` | flat | fixed stake |
| `stake_amount` | 10 (user often 100 → OTC 25) | base stake |
| `otc_stake_multiplier` | 0.25 | OTC probation |
| `expiration_seconds` | 180 | live order duration |
| `max_concurrent_trades` | 3 | open position cap |
| `max_consecutive_losses` | 3 | → PAUSED |
| `pause_duration_minutes` | 15 | cooling-off |
| `max_drawdown_pct_limit` | 0.08 | halt at 8% from peak |
| `daily_stop_loss_pct` | 0.05 | hard SL vs deposit |
| `daily_take_profit_pct` | 0.025 | take-profit halt |
| `trailing_profit_lock` | on @ $500 keep 75% | profit protection |
| `min_payout_rate` | 0.80 | spot floor |
| `otc_min_payout_rate` | 0.90 | OTC floor |
| `governor_min_trades_for_mute` | 20 | statistical mute |
| `governor_promotion_min_trades` | 400 | full OTC stake |
| `bar_edge_guard_seconds` | 3.0 | |
| `use_closed_bar_only` | True | |
| `dynamic_strategy_switching_enabled` | **False** | no mid-session strategy swap |
| `correlation_filter_enabled` | True | |

**Local balance** = `initial_deposit ± sum(local PnL)`. This is **not** live wallet sync with the broker inside the loop.

---

## 6. OTC-Specific Logic

Why OTC is treated separately:

- synthetic broker feed → spikes, flat bars, ultra-micro prices (IRR/NGN-type assets);
- historically OTC underperformed on demo;
- static name blacklist had ~zero predictive power OOS → replaced by **dynamic governor + microstructure**.

Current OTC behavior:

1. Stake ×0.25 until promotion (requires many trades, ≥400 with confident WR).
2. Payout must be ≥90%, else skip.
3. Microstructure re-checked at runtime — auto-assign rejected assets often **silently do not trade**.
4. Weekends: OTC only (spot session filter blocks).

### Microstructure rejection thresholds (`qualify_asset_microstructure`)

- flat_bar_ratio **> 0.15**
- unique_price_ratio **< 0.30**
- whipsaw_sign_flip_ratio **> 0.80**
- relative_atr **< 0.00003**
- price **< 0.001**

---

## 7. Telemetry Fields (Critical for Analysis)

In `LiveTradeRecord` / merged CSV:

| Field | Meaning |
|-------|---------|
| `Open Price Source` | should be `broker` after fix |
| `Settlement Source` | should be `broker` after fix |
| `Slippage` | \|broker_open − internal_open\| → should be ~0 |
| `Entry Second` | second within M1 bar at entry |
| `asset_tier`, `stake_multiplier` | governor verdict |
| `Strategy Parameters` | assigned params |
| `executed_params` | params actually used (if logged) |
| `RSI`, `ADX`, `ATR`, `Stoch %K` | snapshot at entry |
| `Signal Reason`, `Confidence %` | strategy output |

Export path: Merger → merged CSV for post-session analysis.

---

## 8. Recent Empirical Context

### 28–29 Aug (pre broker-truth)

- Large demo drawdown.
- Median bot↔broker entry price gap ~tens of bps / several ATR.
- Circuit breaker ineffective (WIN cleared pause with concurrent trades → streaks up to 11 losses).
- RSI in CSV did not match strategy thresholds (wrong period/smoothing in snapshot).

### Fixes before 30 Aug restart

1. Broker fill price + broker settlement (+25s grace, candle fallback).
2. Circuit breaker pause not cleared by a later WIN.
3. RSI snapshot uses `ta.RSIIndicator` with strategy period.
4. Telemetry: `open_price_source` / `settlement_source`.

### 31 Aug session (post fix, OTC only)

- 25 trades, WR 52%, PnL **−$1**, stake $25, implied payout ~92% (break-even WR ≈ 52.1%).
- **25/25** broker open + broker settle, slippage 0.
- Microstructure-rejected exotics did not trade.
- Clusters: AUD/NZD+EMA +$82; AMD OTC+RSI +$44; **AUD/CAD+S&R −$127**.
- Conclusion: infrastructure OK, trading edge not proven; sample too small.

---

## 9. Known Gaps / Limitations (For Critical Review)

1. **Auto-assign is not reproducible**; WR 100% on 1–3 trades is optimizer noise.
2. Microstructure-rejected assets **stay in the plan** with heuristic metrics.
3. Live `expiration_seconds` ≠ matcher `base_expiration_bars` → backtest vs live comparison is fragile.
4. Matcher assumes fixed payout (0.92 OTC / 0.80 spot), not live payout.
5. On gateway failure, a `demo-{uuid}` order may still drive local balance/CB without a real broker order.
6. Balance is synthetic — no wallet sync in the loop.
7. Correlation filter only blocks same-currency long/short exposure, not full pair correlation matrix.
8. Candle settlement fallback after 25s grace is still possible.
9. One late entry (`entry_second=26`) on 31 Aug — possible bar-edge exception.
10. Mid-week re-assign can change asset set (31 Aug traded AMD OTC not present in 30 Aug status).

---

## 10. Key Source Files

```
src/strat_trade/domain/trading/bot_engine.py
src/strat_trade/domain/trading/entities.py
src/strat_trade/domain/trading/execution_gates.py
src/strat_trade/domain/trading/asset_governor.py
src/strat_trade/domain/trading/asset_filter.py
src/strat_trade/domain/trading/correlation.py
src/strat_trade/domain/trading/regime_detector.py
src/strat_trade/domain/trading/trade_store.py
src/strat_trade/domain/optimizer/auto_matcher.py
src/strat_trade/domain/strategies/registry.py
src/strat_trade/adapters/pocket_option_gateway.py
src/strat_trade/api/routes/bot.py
src/strat_trade/api/schemas.py
src/strat_trade/domain/analytics/xls_merger.py
```

---

## 11. Analysis Checklist (For Another Agent)

When reviewing code or CSV dumps, verify:

1. Are `settlement_source` / `open_price_source` = `broker`?
2. Is OTC stake actually ×0.25?
3. Do microstructure-rejected assets appear in trades?
4. Does CB pause hold full 15 minutes without early unpause from a WIN?
5. Is `entry_second` mostly below bar-edge threshold?
6. Does aggregate PnL mask a single toxic asset×strategy cluster?
7. Do not trust `estimated_win_rate` from auto-assign when `trades_count < 20`.
8. Compare live behavior to `/api/v1/bot/status`, not saved auto-assign JSON.

---

## 12. API Endpoints (Live Bot)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/bot/auto-assign` | Generate pre-trading plan |
| POST | `/api/v1/bot/start` | Start bot with confirmed plan |
| POST | `/api/v1/bot/stop` | Stop bot |
| POST | `/api/v1/bot/pause` | Pause trading |
| POST | `/api/v1/bot/resume` | Resume trading |
| GET | `/api/v1/bot/status` | **Running plan ground truth** |
| GET | `/api/v1/bot/trades` | Trade history from DB |
| POST | `/api/v1/audit/upload-xls` | Upload broker CSV → merge with DB |

---

## 13. Sequential Narrative (One-Paragraph Summary)

The app starts with a Pocket Option gateway. The client calls auto-assign to backtest/heuristic-match strategies per asset, then starts the bot with the confirmed plan. Every 4 seconds the engine settles expired trades (broker-first), checks portfolio circuit breakers, and if running scans each asset through a long gate chain before opening a trade with governed stake and broker fill price. After expiration, broker result settles the trade and feeds cooldowns, consecutive-loss pause, and asset governor. Optionally, the user uploads a broker CSV; the merger overwrites bot records with broker ground truth for audit analytics.

---

*Generated for handoff to external AI agents. Update this file when major runtime behavior changes.*
