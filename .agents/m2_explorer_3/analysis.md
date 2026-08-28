# Milestone 2: API, Portfolio Backtester Alignment & Test Strategy Analysis

**Author**: `m2_explorer_3`  
**Milestone**: Milestone 2 — Bot Engine Guardrails & Anti-Whipsaw (R2)  
**Date**: 2026-08-20  
**Scope**: REST API schemas, routes, use cases, portfolio backtester guardrails alignment, and end-to-end test suite design for execution guardrails.

---

## 1. Executive Summary & Problem Boundary

Milestone 2 addresses systemic risk and execution safeguards in `strat_trade_be`:
1. **False entries / redundant correlation exposure**: Eliminating simultaneous trades on correlated pairs (e.g. `AUDUSD` and `AUDNZD` in the same direction, or `EURUSD` and `USDCHF` in opposite directions).
2. **Post-trade whipsaws**: Preventing immediate re-entry on the same asset after a trade settles ($N$ bars settlement cooldown) and enforcing minimum spacing between consecutive portfolio executions (global cooldown).
3. **Cascading drawdowns**: Circuit breakers that automatically pause the bot after $K$ consecutive losses and halt the bot if peak-to-trough drawdown exceeds the maximum risk budget (e.g. 8%).
4. **Lifecycle management & observability**: Enriching REST API telemetry with live risk state and exposing `/bot/pause` and `/bot/resume` endpoints.
5. **Backtesting parity**: Ensuring the multi-asset chronological backtesting engine (`PortfolioBacktestEngine`) accurately simulates all guardrails so backtest results match live execution dynamics.

---

## 2. API & Schema Specification

### 2.1 Pydantic Schema Enhancements (`src/strat_trade/api/schemas.py`)

#### A. New Schemas
```python
class PauseBotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_seconds: int | None = Field(
        None,
        ge=1,
        le=86400,
        description="Optional pause duration in seconds. If omitted, pauses indefinitely until manual resume.",
    )
    reason: str | None = Field(
        None,
        max_length=256,
        description="Optional operator reason for pausing (e.g. 'manual', 'high-impact news event').",
    )
```

#### B. Updated `AutoAssignRequest`
```python
class AutoAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[str] = Field(..., min_length=1, description="List of target assets to profile")
    initial_deposit: float = Field(1000.0, ge=10.0, description="Session starting capital")
    stake_model: str = Field("flat", description="flat or percent")
    stake_amount: float = Field(10.0, ge=1.0, description="Flat stake amount")
    stake_percent: float = Field(1.0, ge=0.1, le=100.0, description="Dynamic percent stake")
    expiration_seconds: int = Field(180, ge=5, le=86400, description="Trade duration in seconds")
    daily_stop_loss_pct: float = Field(0.05, ge=0.01, le=0.5, description="Stop-loss % of deposit")
    max_concurrent_trades: int = Field(3, ge=1, le=20, description="Max open trades allowed")
    min_payout_rate: float = Field(
        0.80, ge=0.5, le=1.0, description="Minimum allowed broker payout"
    )
    # Milestone 2 Guardrail Fields
    cooldown_bars: int = Field(
        3, ge=0, le=50, description="Post-trade settlement cooldown in bars per asset"
    )
    global_cooldown_seconds: int = Field(
        30, ge=0, le=3600, description="Minimum delay in seconds between consecutive portfolio trades"
    )
    max_consecutive_losses: int = Field(
        3, ge=1, le=20, description="Consecutive losses before circuit breaker cooling-off pause"
    )
    max_drawdown_pct_limit: float = Field(
        0.08, ge=0.01, le=0.50, description="Peak-to-trough drawdown threshold for circuit breaker halt"
    )
    correlation_filter_enabled: bool = Field(
        True, description="Enable currency pair correlation and exposure filter"
    )
```

#### C. Updated `PreTradingPlanResponse`
```python
class PreTradingPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignments: list[StrategyAssignmentResponse]
    total_assets: int
    initial_deposit: float
    stake_model: str
    stake_amount: float
    stake_percent: float
    expiration_seconds: int
    daily_stop_loss_pct: float
    stop_loss_amount: float
    max_concurrent_trades: int
    min_payout_rate: float
    # Milestone 2 Guardrail Fields
    cooldown_bars: int = 3
    global_cooldown_seconds: int = 30
    max_consecutive_losses: int = 3
    max_drawdown_pct_limit: float = 0.08
    correlation_filter_enabled: bool = True
    created_at: str
```

#### D. Updated `BotStatusResponse`
```python
class BotStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    started_at: str | None
    initial_balance: float
    current_balance: float
    net_profit: float
    roi_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    pending_trades: int
    win_rate_pct: float
    max_drawdown_pct: float
    stop_loss_reached: bool
    # Milestone 2 Enriched Guardrail Telemetry
    consecutive_losses: int = 0
    peak_balance: float = 1000.0
    current_drawdown_pct: float = 0.0
    paused_until: str | None = None
    is_paused: bool = False
    circuit_breaker_triggered: bool = False
    active_assignments: list[StrategyAssignmentResponse]
    recent_trades: list[LiveTradeResponse]
```

#### E. Updated `PortfolioBacktestRequest`
```python
class PortfolioBacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[str] = Field(
        default_factory=lambda: ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc"],
        description="List of broker asset symbols to trade concurrently.",
    )
    max_concurrent_trades: int = Field(
        3, ge=1, le=20, description="Max open trades across the portfolio simultaneously"
    )
    timeframe_seconds: int = Field(
        60, description="Candle timeframe in seconds (5, 15, 30, 60, 300)"
    )
    initial_deposit: float = Field(
        1000.0, gt=0, description="Starting shared portfolio balance ($)"
    )
    stake_model: Literal["flat", "percent", "martingale"] = Field(
        "flat", description="Position sizing model"
    )
    stake_amount: float = Field(10.0, gt=0, description="Fixed bet amount for flat/martingale ($)")
    stake_percent: float = Field(
        1.0, ge=0.1, le=100.0, description="Bet size percentage for dynamic model"
    )
    martingale_multiplier: float = Field(2.0, ge=1.0, le=5.0, description="Multiplier after loss")
    martingale_max_steps: int = Field(
        2, ge=1, le=10, description="Max consecutive martingale steps"
    )
    payout_rates: dict[str, float] = Field(
        default_factory=dict, description="Custom payout rate override per asset (e.g. 0.92)"
    )
    min_payout_rate: float = Field(
        0.80, ge=0.1, le=1.0, description="Minimum payout filter threshold"
    )
    expiration_bars: int = Field(
        3, ge=1, le=100, description="Duration in bars (e.g. 3 bars on M1 = 180s)"
    )
    adaptive_expiration: bool = Field(False, description="Enable ATR-adaptive expiration duration")
    daily_stop_loss_pct: float = Field(
        0.05, ge=0.01, le=1.0, description="Daily stop-loss limit (e.g. 0.05 = 5%)"
    )
    # Milestone 2 Guardrails in Backtesting
    cooldown_bars: int = Field(
        0, ge=0, le=50, description="Post-trade settlement cooldown in bars per asset (0 = disabled)"
    )
    global_cooldown_seconds: int = Field(
        0, ge=0, le=3600, description="Delay in seconds between consecutive portfolio trades"
    )
    correlation_filter_enabled: bool = Field(
        False, description="Enable currency pair correlation and exposure filter"
    )
    max_consecutive_losses: int = Field(
        0, ge=0, le=20, description="Consecutive losses circuit breaker pause threshold (0 = disabled)"
    )
    max_drawdown_pct_limit: float = Field(
        0.08, ge=0.01, le=0.50, description="Peak-to-trough max drawdown halt threshold"
    )
    strategy_name: str = Field("hybrid_multifactors", description="Selected strategy module")
    candle_count: int = Field(
        500, ge=60, le=2000, description="Historical candles count to test per asset"
    )
    end_at: datetime | None = Field(None, description="Anchor timestamp for history (UTC)")
```

---

### 2.2 FastAPI Routes (`src/strat_trade/api/routes/bot.py`)

#### A. Pause Endpoint
```python
@router.post("/pause", response_model=BotStatusResponse, summary="Pause active trading session")
async def pause_bot_endpoint(req: PauseBotRequest | None = None) -> BotStatusResponse:
    """Pauses the active trading bot, preventing new trade entries while active positions settle."""
    duration = req.duration_seconds if req else None
    reason = req.reason if req and req.reason else ""
    summary = await pause_live_bot(duration_seconds=duration, reason=reason)
    return _build_status_response(summary)
```

#### B. Resume Endpoint
```python
@router.post("/resume", response_model=BotStatusResponse, summary="Resume paused trading session")
async def resume_bot_endpoint() -> BotStatusResponse:
    """Resumes trading bot from PAUSED or HALTED_BY_CIRCUIT_BREAKER state."""
    summary = await resume_live_bot()
    return _build_status_response(summary)
```

#### C. Updated `_build_status_response`
```python
def _build_status_response(s: Any) -> BotStatusResponse:
    return BotStatusResponse(
        status=s.status.value if hasattr(s.status, "value") else str(s.status),
        started_at=s.started_at.isoformat() if s.started_at else None,
        initial_balance=float(s.initial_balance),
        current_balance=float(s.current_balance),
        net_profit=float(s.net_profit),
        roi_pct=s.roi_pct,
        total_trades=s.total_trades,
        winning_trades=s.winning_trades,
        losing_trades=s.losing_trades,
        draw_trades=s.draw_trades,
        pending_trades=s.pending_trades,
        win_rate_pct=s.win_rate_pct,
        max_drawdown_pct=s.max_drawdown_pct,
        stop_loss_reached=s.stop_loss_reached,
        # Guardrail metrics
        consecutive_losses=getattr(s, "consecutive_losses", 0),
        peak_balance=float(getattr(s, "peak_balance", s.initial_balance)),
        current_drawdown_pct=float(getattr(s, "current_drawdown_pct", 0.0)),
        paused_until=s.paused_until.isoformat() if getattr(s, "paused_until", None) else None,
        is_paused=bool(getattr(s, "is_paused", False)),
        circuit_breaker_triggered=bool(
            getattr(s, "circuit_breaker_triggered", False)
            or (hasattr(s, "status") and s.status == BotStatus.HALTED_BY_CIRCUIT_BREAKER)
        ),
        active_assignments=[
            StrategyAssignmentResponse(
                asset=a.asset,
                strategy_id=a.strategy_id,
                strategy_name=a.strategy_name,
                category=a.category,
                parameters=a.parameters,
                estimated_win_rate_pct=a.estimated_win_rate_pct,
                estimated_profit_factor=a.estimated_profit_factor,
                estimated_trades_count=a.estimated_trades_count,
                quantum_score=a.quantum_score,
                rationale=a.rationale,
            )
            for a in s.active_assignments
        ],
        recent_trades=[
            LiveTradeResponse(
                trade_id=t.trade_id,
                broker_order_id=t.broker_order_id,
                asset=t.asset,
                action=t.action,
                stake=float(t.stake),
                open_time=t.open_time.isoformat(),
                expiration_seconds=t.expiration_seconds,
                open_price=float(t.open_price),
                close_time=t.close_time.isoformat() if t.close_time else None,
                close_price=float(t.close_price) if t.close_price is not None else None,
                strategy_id=t.strategy_id,
                strategy_name=t.strategy_name,
                strategy_params=t.strategy_params,
                indicator_snapshot=t.indicator_snapshot.to_dict()
                if hasattr(t.indicator_snapshot, "to_dict")
                else t.indicator_snapshot,
                confidence=t.confidence,
                reason=t.reason,
                payout_rate=float(t.payout_rate),
                outcome=t.outcome.value if hasattr(t.outcome, "value") else str(t.outcome),
                pnl=float(t.pnl),
                balance_after=float(t.balance_after) if t.balance_after is not None else None,
                is_merged_with_broker=t.is_merged_with_broker,
                broker_profit=float(t.broker_profit) if t.broker_profit is not None else None,
                slippage=float(t.slippage) if t.slippage is not None else None,
            )
            for t in s.recent_trades
        ],
    )
```

#### D. Updated `start_bot_endpoint`
```python
@router.post("/start", response_model=BotStatusResponse)
async def start_bot_endpoint(
    req: StartBotRequest,
    feed: CandleFeedDep,
) -> BotStatusResponse:
    """Starts autonomous live demo trading using the confirmed pre-trading plan."""
    assignments = [
        StrategyAssignment(
            asset=a.asset,
            strategy_id=a.strategy_id,
            strategy_name=a.strategy_name,
            category=a.category,
            parameters=a.parameters,
            estimated_win_rate_pct=a.estimated_win_rate_pct,
            estimated_profit_factor=a.estimated_profit_factor,
            estimated_trades_count=a.estimated_trades_count,
            quantum_score=a.quantum_score,
            rationale=a.rationale,
        )
        for a in req.plan.assignments
    ]

    dep_dec = Decimal(str(req.plan.initial_deposit))
    plan = PreTradingPlan(
        assignments=assignments,
        total_assets=req.plan.total_assets,
        initial_deposit=dep_dec,
        stake_model=req.plan.stake_model,
        stake_amount=Decimal(str(req.plan.stake_amount)),
        stake_percent=req.plan.stake_percent,
        expiration_seconds=req.plan.expiration_seconds,
        daily_stop_loss_pct=req.plan.daily_stop_loss_pct,
        stop_loss_amount=Decimal(str(req.plan.stop_loss_amount)),
        max_concurrent_trades=req.plan.max_concurrent_trades,
        min_payout_rate=req.plan.min_payout_rate,
        # Guardrail plan params
        cooldown_bars=getattr(req.plan, "cooldown_bars", 3),
        global_cooldown_seconds=getattr(req.plan, "global_cooldown_seconds", 30),
        max_consecutive_losses=getattr(req.plan, "max_consecutive_losses", 3),
        max_drawdown_pct_limit=getattr(req.plan, "max_drawdown_pct_limit", 0.08),
        correlation_filter_enabled=getattr(req.plan, "correlation_filter_enabled", True),
    )

    summary = await start_live_bot(plan=plan, gateway=feed)
    return _build_status_response(summary)
```

---

### 2.3 Use Cases Layer (`src/strat_trade/use_cases/manage_live_bot.py`)

```python
async def pause_live_bot(
    duration_seconds: int | None = None, reason: str = ""
) -> BotSessionSummary:
    """Pauses the active trading bot session."""
    engine = get_bot_engine()
    await engine.pause(duration_seconds=duration_seconds, reason=reason)
    return engine.get_summary()


async def resume_live_bot() -> BotSessionSummary:
    """Resumes the trading bot from paused or circuit breaker state."""
    engine = get_bot_engine()
    await engine.resume()
    return engine.get_summary()
```

---

## 3. Portfolio Backtester Guardrails Alignment

### 3.1 Backtest Domain Models (`src/strat_trade/domain/backtest/models.py`)

`PortfolioBacktestConfig` extended fields:
```python
@dataclass(frozen=True)
class PortfolioBacktestConfig:
    assets: list[str]
    timeframe_seconds: int
    initial_deposit: Decimal = Decimal("1000.0")
    max_concurrent_trades: int = 3
    stake_model: StakeModel = StakeModel.FLAT
    stake_amount: Decimal = Decimal("10.0")
    stake_percent: Decimal = Decimal("1.0")
    martingale_multiplier: Decimal = Decimal("2.0")
    martingale_max_steps: int = 2
    payout_rates: dict[str, Decimal] = field(default_factory=dict)
    min_payout_rate: Decimal = Decimal("0.80")
    expiration_bars: int = 3
    adaptive_expiration: bool = False
    daily_stop_loss_pct: Decimal = Decimal("0.05")
    # Guardrails
    cooldown_bars: int = 0  # Per-asset post-settlement cooldown bars (0 = disabled)
    global_cooldown_seconds: int = 0  # Delay between portfolio entries
    correlation_filter_enabled: bool = False  # Directional currency correlation filter
    max_consecutive_losses: int = 0  # Pause after K consecutive losses (0 = disabled)
    max_drawdown_pct_limit: Decimal = Decimal("0.08")  # Peak-to-trough circuit breaker halt
    strategy_name: str = "hybrid_multifactors"
    strategy_params: dict[str, Any] = field(default_factory=dict)
```

### 3.2 Chronological Simulation Algorithm in `PortfolioBacktestEngine.run()`

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Generate candidate signals across all assets             │
│    Sort all signals chronologically by entry_time           │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Chronological Iteration over sorted signals (sig)        │
├─────────────────────────────────────────────────────────────┤
│ A. Resolve active trades where exit_time <= sig.entry_time  │
│    - Record last_settled_time[trade.asset] = trade.exit_time│
│    - Update consecutive_losses (reset on WIN, ++ on LOSS)   │
│    - If consecutive_losses >= max_consecutive_losses:       │
│        paused_until_time = trade.exit_time + 15 min cooldown│
│    - Update peak_balance = max(peak_balance, current_balance│
│    - If (peak_balance - current_balance)/peak >= max_dd_pct:│
│        HALT backtest simulation immediately                │
├─────────────────────────────────────────────────────────────┤
│ B. Circuit Breaker / Pause Check                            │
│    - If paused_until_time and sig.entry_time < paused_until:│
│        SKIP sig (circuit breaker cooling-off)               │
│    - If session loss >= daily_stop_loss_pct:                │
│        HALT simulation                                      │
├─────────────────────────────────────────────────────────────┤
│ C. Concurrency Limit Check                                  │
│    - If len(active_trades) >= max_concurrent_trades:        │
│        SKIP sig                                             │
│    - If any active trade on same asset:                     │
│        SKIP sig                                             │
├─────────────────────────────────────────────────────────────┤
│ D. Per-Asset Post-Settlement Cooldown Check                 │
│    - If cooldown_bars > 0 and asset in last_settled_time:   │
│        If (sig.entry_time - last_settled) < cooldown_time:  │
│            SKIP sig                                         │
├─────────────────────────────────────────────────────────────┤
│ E. Global Portfolio Delay Check                             │
│    - If global_cooldown_seconds > 0 and last_entry_time:   │
│        If (sig.entry_time - last_entry) < global_cooldown:  │
│            SKIP sig                                         │
├─────────────────────────────────────────────────────────────┤
│ F. Currency Correlation & Directional Exposure Filter       │
│    - If correlation_filter_enabled:                         │
│        conflict, _ = is_correlated_conflict(                │
│            sig.asset, sig.action.value, active_trades       │
│        )                                                    │
│        If conflict: SKIP sig                                │
├─────────────────────────────────────────────────────────────┤
│ G. Position Sizing & Execution                              │
│    - Sizing model (Flat / Percent / Martingale)             │
│    - Add BacktestTrade to active_trades                     │
│    - Set last_portfolio_entry_time = sig.entry_time         │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Comprehensive Test Suite Architecture (`tests/test_execution_guardrails.py`)

The test suite is structured into 6 focused test suites with 100% assertion coverage:

```
tests/test_execution_guardrails.py
├── Suite 1: Per-Asset Settlement Cooldown & Global Cooldown Timing
│   ├── test_per_asset_settlement_cooldown_enforcement()
│   ├── test_per_asset_cooldown_allows_different_assets()
│   ├── test_global_cooldown_portfolio_delay()
│   └── test_cooldown_disabled_when_set_to_zero()
│
├── Suite 2: Currency Pair Correlation & Directional Exposure Filter
│   ├── test_correlation_filter_rejects_same_base_duplicate_long()
│   ├── test_correlation_filter_rejects_same_quote_duplicate_short()
│   ├── test_correlation_filter_rejects_inverse_hedges()
│   ├── test_correlation_filter_accepts_uncorrelated_pairs()
│   └── test_correlation_symbol_parser_otc_and_standard_formats()
│
├── Suite 3: Consecutive Loss Circuit Breaker State Machine
│   ├── test_consecutive_losses_triggers_pause_state()
│   ├── test_consecutive_losses_counter_resets_on_win()
│   ├── test_auto_resume_after_cooling_off_period()
│   └── test_circuit_breaker_blocks_signals_during_pause()
│
├── Suite 4: High-Watermark Peak Balance & Drawdown Circuit Breaker
│   ├── test_peak_balance_tracking_across_wins_and_losses()
│   ├── test_peak_to_trough_drawdown_triggers_circuit_breaker_halt()
│   └── test_halted_bot_terminates_signal_loop()
│
├── Suite 5: REST API Lifecycle & Enriched Telemetry
│   ├── test_api_bot_pause_and_resume_endpoints()
│   ├── test_api_bot_pause_with_duration()
│   ├── test_api_bot_status_returns_enriched_guardrail_fields()
│   └── test_api_pause_resume_idempotency_and_edge_cases()
│
└── Suite 6: Portfolio Backtester Guardrails Parity
    ├── test_portfolio_backtest_with_correlation_filter()
    ├── test_portfolio_backtest_with_settlement_cooldown()
    └── test_portfolio_backtest_consecutive_loss_and_drawdown_halts()
```

---

## 5. Implementation Blueprint

### 5.1 Step-by-Step Code Changes
1. **`src/strat_trade/domain/trading/entities.py`**:
   - Add `PAUSED` and `HALTED_BY_CIRCUIT_BREAKER` to `BotStatus`.
   - Add guardrail parameters to `PreTradingPlan`.
   - Add telemetry fields to `BotSessionSummary`.
2. **`src/strat_trade/domain/trading/correlation.py`**:
   - Implement `extract_currency_pair` and `is_correlated_conflict`.
3. **`src/strat_trade/domain/trading/bot_engine.py`**:
   - Implement cooldown timers, correlation check, consecutive loss circuit breaker, peak balance tracking, `pause()`, and `resume()`.
4. **`src/strat_trade/api/schemas.py`**:
   - Add `PauseBotRequest`, update `AutoAssignRequest`, `PreTradingPlanResponse`, `BotStatusResponse`, `PortfolioBacktestRequest`.
5. **`src/strat_trade/api/routes/bot.py`**:
   - Add `POST /bot/pause` and `POST /bot/resume` endpoints, update `_build_status_response` and `start_bot_endpoint`.
6. **`src/strat_trade/use_cases/manage_live_bot.py`**:
   - Expose `pause_live_bot` and `resume_live_bot`.
7. **`src/strat_trade/domain/backtest/models.py` & `portfolio_engine.py`**:
   - Integrate cooldowns, correlation filtering, and circuit breakers into `PortfolioBacktestEngine.run()`.
8. **`tests/test_execution_guardrails.py`**:
   - Implement the complete 6-suite test file.
