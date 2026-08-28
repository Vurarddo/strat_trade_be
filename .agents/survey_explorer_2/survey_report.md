# Survey Report: Bot Engine & Execution Guardrails

**Explorer**: `survey_explorer_2`  
**Date**: 2026-08-20  
**Target Subsystem**: Bot Execution Engine, Signal Processing & Filtering, Execution Guardrails, Risk Governance  
**Workspace**: `/Users/vlados/work/projects/startup/strat_trade_be`

---

## 1. Executive Summary

This investigation analyzed the execution subsystem of `strat_trade_be`, specifically focusing on **Requirement R2 (Bot Engine Execution Guardrails & Anti-Whipsaw Protection)** from `ORIGINAL_REQUEST.md`.

The primary findings are:
1. **Bot Engine Architecture**: The bot engine is implemented as `LiveDemoBotEngine` in `src/strat_trade/domain/trading/bot_engine.py`, managed via singleton use-case wrappers in `src/strat_trade/use_cases/manage_live_bot.py`, and exposed through FastAPI REST endpoints in `src/strat_trade/api/routes/bot.py`.
2. **Current Filtering State**: Signal evaluation in `_evaluate_single_asset()` currently performs basic validation (concurrency limit, single-asset lock, a hardcoded 30-second timestamp check, live payout threshold, minimum candle count $\ge 25$, and signal confidence $\ge 0.50$).
3. **Guardrail Gaps**:
   - **Cooldown Timers**: There is only a rudimentary hardcoded 30s check (`self._last_signal_time`). There is **no bar-based cooldown** (minimum $N$ bars), **no global cooldown** across the portfolio, and **no cooldown after trade settlement**.
   - **Correlated Asset Exposure**: There is **zero correlation filtering**. Simultaneous signals on correlated currency pairs (e.g. `AUDUSD_otc` and `AUDNZD_otc`, or `EURUSD_otc` and `GBPUSD_otc`) execute concurrently, tripling directional risk on individual currencies (e.g., USD or AUD).
   - **Circuit Breakers**: Only a session stop-loss based on initial deposit (`loss >= stop_loss_amount`) exists. There is **no consecutive loss circuit breaker** ($K$ losses in a row), **no peak-to-trough (high-watermark) drawdown breaker**, and **no temporary pause / resume mechanism** (`PAUSED` state).
4. **Backtesting Alignment**: `PortfolioBacktestEngine` (`src/strat_trade/domain/backtest/portfolio_engine.py`) and `BinaryBacktestEngine` (`src/strat_trade/domain/backtest/engine.py`) lack post-trade cooldowns and correlation filters, creating a mismatch between backtest simulation and real-world execution.

---

## 2. Bot Engine Architecture & Trade Execution Flow

### 2.1 Component Structure

```
strat_trade_be/
├── src/strat_trade/
│   ├── domain/
│   │   ├── trading/
│   │   │   ├── bot_engine.py      # LiveDemoBotEngine (Async polling, signal dispatch, trade monitoring)
│   │   │   ├── entities.py        # Domain entities (BotStatus, TradeOutcome, PreTradingPlan, LiveTradeRecord)
│   │   │   └── trade_store.py     # SQLite persistence layer (data/trades.db)
│   │   ├── backtest/
│   │   │   ├── engine.py          # BinaryBacktestEngine (single-asset backtest)
│   │   │   ├── portfolio_engine.py# PortfolioBacktestEngine (multi-asset chronological backtest)
│   │   │   └── models.py          # Backtest configuration & result dataclasses
│   │   └── strategies/
│   │       ├── base.py            # BaseStrategy ABC & SignalResult dataclass
│   │       └── registry.py        # Strategy registry & metadata catalog
│   ├── use_cases/
│   │   ├── manage_live_bot.py     # Singleton instance & lifecycle methods (start, stop, status)
│   │   └── auto_assign_strategies.py # Pre-trading plan generation
│   ├── adapters/
│   │   └── pocket_option_gateway.py # PocketOptionTradingGateway (BinaryOptionsToolsV2 wrapper)
│   └── api/
│       ├── routes/bot.py          # REST endpoints (/bot/auto-assign, /bot/start, /bot/stop, /bot/status)
│       └── schemas.py             # Pydantic request/response schemas
```

### 2.2 Execution Flow in `LiveDemoBotEngine`

The runtime execution loop is driven by `_run_loop()` in `src/strat_trade/domain/trading/bot_engine.py:138-154`:

```
                    ┌──────────────────────────────┐
                    │     LiveDemoBotEngine        │
                    │   _run_loop() (every 4.0s)   │
                    └──────────────┬───────────────┘
                                   │
      ┌────────────────────────────┴────────────────────────────┐
      ▼                                                         ▼
[1. _check_active_trades()]                               [2. _check_stop_loss()]
 • Check expiry (now >= open_time + exp)                   • loss = initial - current
 • Fetch latest close from gateway                         • If loss >= stop_loss_amount:
 • Evaluate WIN / LOSS / DRAW                                status = HALTED_BY_STOP_LOSS
 • Settle PnL & update SQLite
 • Remove from active_trades
      │
      ▼
[3. _evaluate_signals_and_trade()]
 • Concurrency check: len(active_trades) < max_concurrent_trades
 • Spawn asyncio.gather with Semaphore(6) over plan.assignments
      │
      ▼
[4. _evaluate_single_asset(assignment)]
 • Reject if asset is in active_trades
 • Reject if (now - last_signal_time[asset]) < 30s
 • Check live broker payout >= min_payout_rate
 • Fetch 100 historical candles (require >= 25)
 • Signal = strategy.evaluate_candles(candles)
 • If action in ("CALL", "PUT") and confidence >= 0.50:
      │
      ▼
[5. _execute_order(assignment, action, confidence...)]
 • Sizing: stake = stake_amount or (balance * stake_percent)
 • Extract IndicatorSnapshot
 • broker_order_id = gateway.open_trade(asset, action, stake, expiration)
 • Persist LiveTradeRecord to SQLite & active_trades
```

---

## 3. Detailed Audit of Execution Guardrails

### 3.1 Cooldown Timers (Per-Asset & Global)

#### Current Implementation (`src/strat_trade/domain/trading/bot_engine.py:274-278`):
```python
# Cooldown per asset: at least 30s
last_sig = self._last_signal_time.get(asset)
if last_sig and (now - last_sig).total_seconds() < 30:
    return
```

#### Deficiencies Identified:
1. **Signal-Fired Timing vs Settlement Timing**: Cooldown is evaluated against the timestamp when a signal was *fired*, rather than when the previous trade *closed/settled*. If a 180s trade is placed, the 30s timer expires while the trade is still running. Once the trade finishes at 180s, a new trade can be immediately opened with **0 seconds** of post-settlement rest.
2. **Missing Bar-Based Cooldown**: There is no support for specifying cooldown in terms of candle bars (e.g. minimum $N = 3$ or $N = 5$ bars on M1). In volatile OTC markets, price requires multiple bars to establish a new structure after an exit.
3. **Missing Global Portfolio Cooldown**: If 3 asset strategies fire simultaneously, all 3 are executed within the same second, creating a clustered execution spike.
4. **Configuration Absence**: `PreTradingPlan`, `PreTradingPlanResponse`, and `StartBotRequest` have no parameters for `cooldown_bars` or `global_cooldown_seconds`.
5. **Backtester Omission**: In `BinaryBacktestEngine` (`src/strat_trade/domain/backtest/engine.py:120, 268`), `next_available_idx = exit_idx`. A new trade can be entered on `exit_idx` immediately on the next bar. In `PortfolioBacktestEngine` (`portfolio_engine.py`), no cooldown is enforced between trades of the same asset once resolved.

---

### 3.2 Correlated Asset Exposure Filtering

#### Current Implementation:
**Completely absent** across `LiveDemoBotEngine`, `PortfolioBacktestEngine`, `BinaryBacktestEngine`, and `PreTradingPlan`.

#### Deficiencies & Failure Modes:
1. **Shared Currency Over-Concentration**:
   - Currency pairs share underlying base and quote currencies:
     - `AUDUSD_otc` (Base: AUD, Quote: USD)
     - `AUDNZD_otc` (Base: AUD, Quote: NZD)
     - `EURUSD_otc` (Base: EUR, Quote: USD)
     - `GBPUSD_otc` (Base: GBP, Quote: USD)
   - If `LiveDemoBotEngine` holds active positions on both `AUDUSD_otc` (CALL) and `AUDNZD_otc` (CALL), the portfolio is **double long AUD**. Any systemic Australian economic news or OTC drift against AUD triggers a simultaneous double loss.
   - If CALL trades are opened on `EURUSD_otc`, `GBPUSD_otc`, and `AUDUSD_otc`, the portfolio has **triple short USD** exposure.
2. **Inverse Currency Conflicts**:
   - `EURUSD_otc` and `USDCHF_otc` have an inverse correlation ($\approx -0.90$). Opening CALL on `EURUSD_otc` and CALL on `USDCHF_otc` is a self-hedging contradiction that pays broker spreads on both sides without alpha.
3. **Simultaneous Signal Contention**:
   - When multiple correlated assets generate signals in the same polling cycle, the engine does not compare their `confidence` or quantum scores. It executes all of them until `max_concurrent_trades` is filled.

---

### 3.3 Circuit Breakers & Pause/Resume Mechanisms

#### Current Implementation (`src/strat_trade/domain/trading/bot_engine.py:155-167`):
```python
async def _check_stop_loss(self) -> None:
    if not self.plan:
        return

    loss = self.initial_balance - self.current_balance
    if loss >= self.plan.stop_loss_amount:
        self.status = BotStatus.HALTED_BY_STOP_LOSS
        logger.warning(
            "HARD STOP-LOSS TRIGGERED! Session loss ($%.2f) reached limit ($%.2f). Halting.",
            float(loss),
            float(self.plan.stop_loss_amount),
        )
```

#### Deficiencies Identified:
1. **No Consecutive Loss Circuit Breaker**:
   - If market conditions switch to a hostile regime (e.g. sharp trend against mean-reversion), the bot can lose 4, 5, or 6 trades consecutively. There is no streak breaker to pause trading after $K$ consecutive losses (e.g., $K=3$).
2. **Initial Balance vs High-Watermark Drawdown**:
   - `loss = self.initial_balance - self.current_balance` only checks losses against day-start capital.
   - *Example*: Account starts at $1,000. It compounds up to $1,800 (+80% profit). It then suffers a -$300 drawdown down to $1,500 (-16.7% from peak). The current check computes `loss = 1000 - 1500 = -500`, so no stop-loss is triggered, allowing gains to bleed away.
3. **No Pause/Resume State Machine**:
   - `BotStatus` enum (`src/strat_trade/domain/trading/entities.py:10-15`) only defines:
     ```python
     class BotStatus(StrEnum):
         IDLE = "IDLE"
         RUNNING = "RUNNING"
         STOPPED = "STOPPED"
         HALTED_BY_STOP_LOSS = "HALTED_BY_STOP_LOSS"
     ```
   - Missing: `BotStatus.PAUSED` or `BotStatus.HALTED_BY_CIRCUIT_BREAKER`.
   - Missing: Temporary cooling-off duration (e.g. pause for 15 minutes, then automatically resume), and API endpoints `POST /api/v1/bot/pause` and `POST /api/v1/bot/resume`.

---

## 4. Data Models, State Tracking & Schema Mapping

### 4.1 Domain Entities (`src/strat_trade/domain/trading/entities.py`)

| Entity | Role | Required Fields for Guardrails |
| :--- | :--- | :--- |
| `BotStatus` | Lifecycle states | Add `PAUSED`, `HALTED_BY_CIRCUIT_BREAKER` |
| `PreTradingPlan` | Plan configuration | Add `cooldown_bars: int`, `global_cooldown_seconds: int`, `max_consecutive_losses: int`, `max_drawdown_pct_limit: float`, `correlation_filter_enabled: bool` |
| `BotSessionSummary` | Real-time telemetry | Add `consecutive_losses: int`, `peak_balance: Decimal`, `current_drawdown_pct: float`, `paused_until: datetime | None`, `is_paused: bool` |
| `LiveTradeRecord` | Trade persistence | Existing structure is comprehensive with `indicator_snapshot`, `confidence`, `reason`, `payout_rate`. |

### 4.2 SQLite Store (`src/strat_trade/domain/trading/trade_store.py`)
- Persistent database `data/trades.db` with WAL mode.
- Table `trades` schema stores full telemetry and is indexed on `broker_order_id`, `asset`, `strategy_id`, and `open_time`.
- Fully capable of supporting the enhanced trade lifecycle.

### 4.3 REST API Schemas (`src/strat_trade/api/schemas.py`)
- `AutoAssignRequest` & `StartBotRequest` need parameters for guardrails:
  - `cooldown_bars` (default: 3 bars)
  - `global_cooldown_seconds` (default: 30s)
  - `max_consecutive_losses` (default: 3)
  - `max_drawdown_pct` (default: 0.08 / 8%)
  - `correlation_filter_enabled` (default: True)
- `BotStatusResponse` should expose:
  - `consecutive_losses: int`
  - `peak_balance: float`
  - `current_drawdown_pct: float`
  - `paused_until: str | None`
  - `is_paused: bool`

---

## 5. Architectural Blueprint for Implementation

### 5.1 Currency Exposure & Correlation Engine

To implement **Correlated Asset Exposure Filtering**:

```python
# Correlation & Currency Parser Model
def extract_currency_pair(asset: str) -> tuple[str, str] | None:
    """Extracts (base, quote) currencies from asset symbol (e.g. 'AUDUSD_otc' -> ('AUD', 'USD'))."""
    clean = asset.upper().replace("_OTC", "").replace("/", "").replace("-", "").replace(" ", "")
    # Check known 6-char currency pairs
    if len(clean) == 6:
        return clean[:3], clean[3:]
    return None

def is_correlated_conflict(
    candidate_asset: str,
    candidate_action: str,
    active_trades: list[LiveTradeRecord],
) -> tuple[bool, str]:
    """
    Checks if candidate trade conflicts with any active trade via currency exposure.
    Directional rules:
    - CALL on BASE/QUOTE -> Long BASE, Short QUOTE
    - PUT on BASE/QUOTE  -> Short BASE, Long QUOTE
    """
    cand_pair = extract_currency_pair(candidate_asset)
    if not cand_pair:
        return False, ""

    cand_base, cand_quote = cand_pair
    # Determine candidate directional bias
    cand_long = cand_base if candidate_action == "CALL" else cand_quote
    cand_short = cand_quote if candidate_action == "CALL" else cand_base

    for active in active_trades:
        act_pair = extract_currency_pair(active.asset)
        if not act_pair:
            continue
        act_base, act_quote = act_pair
        act_long = act_base if active.action == "CALL" else act_quote
        act_short = act_quote if active.action == "CALL" else act_base

        # Check for duplicate directional exposure on same currency
        if cand_long == act_long:
            return True, f"Conflict: Double Long {cand_long} (active: {active.asset} {active.action})"
        if cand_short == act_short:
            return True, f"Conflict: Double Short {cand_short} (active: {active.asset} {active.action})"

    return False, ""
```

### 5.2 Cooldown State Tracking in `LiveDemoBotEngine`

```python
# Inside LiveDemoBotEngine state
self._last_trade_closed_time: dict[str, datetime] = {}
self._last_trade_closed_bar_ts: dict[str, int] = {}
self._global_last_trade_open_time: datetime | None = None

# When a trade closes in _check_active_trades():
self._last_trade_closed_time[trade.asset] = now
self._last_trade_closed_bar_ts[trade.asset] = int(now.timestamp() // 60)

# In _evaluate_single_asset():
# 1. Global Cooldown Check
if self._global_last_trade_open_time:
    elapsed_global = (now - self._global_last_trade_open_time).total_seconds()
    if elapsed_global < self.plan.global_cooldown_seconds:
        return

# 2. Per-Asset Bar / Time Cooldown Check
last_closed = self._last_trade_closed_time.get(asset)
if last_closed:
    elapsed_sec = (now - last_closed).total_seconds()
    min_cooldown_sec = self.plan.cooldown_bars * 60  # for M1 timeframe
    if elapsed_sec < min_cooldown_sec:
        return
```

### 5.3 Consecutive Loss & High-Watermark Circuit Breakers

```python
# In LiveDemoBotEngine
self.consecutive_losses: int = 0
self.peak_balance: Decimal = Decimal("1000.00")
self.paused_until: datetime | None = None

# In _check_active_trades() upon trade settlement:
if outcome == TradeOutcome.LOSS:
    self.consecutive_losses += 1
    if self.consecutive_losses >= self.plan.max_consecutive_losses:
        self.status = BotStatus.PAUSED
        self.paused_until = now + timedelta(minutes=15)
        logger.warning("CIRCUIT BREAKER: %d consecutive losses. Pausing bot for 15m.", self.consecutive_losses)
elif outcome == TradeOutcome.WIN:
    self.consecutive_losses = 0

# Track Peak Balance & Max Drawdown Circuit Breaker
if self.current_balance > self.peak_balance:
    self.peak_balance = self.current_balance

drawdown_from_peak = (self.peak_balance - self.current_balance) / self.peak_balance
if drawdown_from_peak >= Decimal(str(self.plan.max_drawdown_pct_limit)):
    self.status = BotStatus.HALTED_BY_CIRCUIT_BREAKER
    logger.critical("CIRCUIT BREAKER: Peak-to-trough drawdown reached %.2f%%. Halting.", float(drawdown_from_peak * 100))
```

### 5.4 Async Mutex & Prioritization

To prevent race conditions during concurrent signal evaluation across assets:
```python
# Sort candidate signals in evaluation cycle by confidence descending
qualified_signals.sort(key=lambda s: s["confidence"], reverse=True)

# Sequentially filter through correlation guard before dispatching order
for sig in qualified_signals:
    if len(self.active_trades) >= self.plan.max_concurrent_trades:
        break
    conflict, reason = is_correlated_conflict(sig["asset"], sig["action"], list(self.active_trades.values()))
    if conflict:
        logger.info("Correlated signal rejected for %s %s: %s", sig["asset"], sig["action"], reason)
        continue
    await self._execute_order(...)
```

---

## 6. Verification and Test Strategy

To verify the enhanced execution guardrails without regressions:
1. **Unit Tests for Cooldowns**:
   - Test per-asset cooldown rejects signals within $N$ bars of trade exit.
   - Test global cooldown prevents opening two trades in $< \text{global\_cooldown\_seconds}$.
2. **Unit Tests for Correlation Guard**:
   - Test that `AUDUSD_otc` (CALL) blocks `AUDNZD_otc` (CALL) due to double-long AUD exposure.
   - Test that `EURUSD_otc` (CALL) and `USDCHF_otc` (CALL) are recognized as contradictory inverse positions.
   - Test that independent pairs (e.g. `EURUSD_otc` and `USDJPY_otc`) are allowed when exposure limits are satisfied.
3. **Unit Tests for Circuit Breakers**:
   - Test that $K$ consecutive losses transition the bot into `PAUSED` state for the specified duration.
   - Test peak-to-trough drawdown triggers `HALTED_BY_CIRCUIT_BREAKER` even when current balance is higher than initial balance.
   - Test manual pause/resume endpoints.
4. **Portfolio Backtest Engine Integration**:
   - Run multi-asset backtest with correlation filtering and verify trade frequency and drawdown reduction.
5. **Full Regression Suite**:
   - Run `pytest -v` across all existing tests in `tests/`.

---

## 7. Next Steps for Implementation Agents

1. **Step 1 (Entities & Schemas)**: Update `src/strat_trade/domain/trading/entities.py` and `src/strat_trade/api/schemas.py` to add new fields and status enums (`PAUSED`, `HALTED_BY_CIRCUIT_BREAKER`).
2. **Step 2 (Currency & Correlation Engine)**: Create helper module `src/strat_trade/domain/trading/correlation.py` implementing pair decomposition and directional conflict checking.
3. **Step 3 (Bot Engine Core)**: Update `src/strat_trade/domain/trading/bot_engine.py` with cooldown timers, correlation filtering, consecutive losses tracking, peak-to-trough drawdown check, and pause/resume logic.
4. **Step 4 (API Routes & Use Cases)**: Expose `/bot/pause` and `/bot/resume` in `src/strat_trade/api/routes/bot.py` and update `manage_live_bot.py`.
5. **Step 5 (Portfolio Backtester Alignment)**: Update `src/strat_trade/domain/backtest/portfolio_engine.py` with the same correlation and cooldown filters for consistent simulation.
6. **Step 6 (Test Suite & Verification)**: Write unit and integration tests covering all guardrail scenarios.
