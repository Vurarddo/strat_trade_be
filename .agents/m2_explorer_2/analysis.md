# Milestone 2: Cooldown Timers & Circuit Breakers in Bot Engine — Technical Analysis & Implementation Plan

## Executive Summary
This document specifies the domain enhancements for **Milestone 2 (R2)**:
1. **Cooldown Timers**:
   - **Post-Trade-Settlement Per-Asset Cooldown**: Enforces a minimum resting window ($N$ bars / seconds) after any trade closes on an asset before allowing re-entry on that same asset.
   - **Global Portfolio Cooldown**: Introduces an atomic delay (default 30s) between any executions across the entire multi-asset portfolio, eliminating simultaneous order bursts.
2. **Multi-Tier Circuit Breakers**:
   - **Consecutive Loss Pause**: Tracks consecutive trade losses ($K$ losses, default 3). Upon hitting the threshold, the bot transitions to `BotStatus.PAUSED` with an automated cooling-off timer (default 15 minutes) or manual resume.
   - **High-Watermark Peak Drawdown Halt**: Tracks peak account equity ($HWM$) dynamically and computes current peak-to-trough drawdown percentage. If drawdown exceeds `max_drawdown_pct_limit` (default 8.0%), the bot transitions to terminal `BotStatus.HALTED_BY_CIRCUIT_BREAKER`.
3. **Bot Lifecycle State Machine**:
   - Extends `BotStatus` with `PAUSED` and `HALTED_BY_CIRCUIT_BREAKER`.
   - Exposes asynchronous `pause()` and `resume()` methods with concurrency protection.
   - Maintains the background loop in `PAUSED` to settle pending trades and service auto-resume expiry, while halting execution permanently on `HALTED_BY_STOP_LOSS` and `HALTED_BY_CIRCUIT_BREAKER`.

---

## 1. Domain Entities Specification (`src/strat_trade/domain/trading/entities.py`)

### 1.1 `BotStatus` Enum Extension
```python
class BotStatus(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    HALTED_BY_STOP_LOSS = "HALTED_BY_STOP_LOSS"
    HALTED_BY_CIRCUIT_BREAKER = "HALTED_BY_CIRCUIT_BREAKER"
```

### 1.2 `PreTradingPlan` Dataclass Updates
Add new risk and timing configuration fields with backward-compatible defaults:
```python
@dataclass
class PreTradingPlan:
    """Pre-trading configuration plan shown to the user in the confirmation modal."""

    assignments: list[StrategyAssignment]
    total_assets: int
    initial_deposit: Decimal
    stake_model: str
    stake_amount: Decimal
    stake_percent: float
    expiration_seconds: int
    daily_stop_loss_pct: float
    stop_loss_amount: Decimal
    max_concurrent_trades: int
    min_payout_rate: float
    cooldown_bars: int = 3
    global_cooldown_seconds: int = 30
    max_consecutive_losses: int = 3
    max_drawdown_pct_limit: float = 0.08
    correlation_filter_enabled: bool = True
    pause_duration_minutes: int = 15
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignments": [a.to_dict() for a in self.assignments],
            "total_assets": self.total_assets,
            "initial_deposit": float(self.initial_deposit),
            "stake_model": self.stake_model,
            "stake_amount": float(self.stake_amount),
            "stake_percent": self.stake_percent,
            "expiration_seconds": self.expiration_seconds,
            "daily_stop_loss_pct": round(self.daily_stop_loss_pct * 100.0, 2),
            "stop_loss_amount": float(self.stop_loss_amount),
            "max_concurrent_trades": self.max_concurrent_trades,
            "min_payout_rate": self.min_payout_rate,
            "cooldown_bars": self.cooldown_bars,
            "global_cooldown_seconds": self.global_cooldown_seconds,
            "max_consecutive_losses": self.max_consecutive_losses,
            "max_drawdown_pct_limit": self.max_drawdown_pct_limit,
            "correlation_filter_enabled": self.correlation_filter_enabled,
            "pause_duration_minutes": self.pause_duration_minutes,
            "created_at": self.created_at.isoformat(),
        }
```

### 1.3 `BotSessionSummary` Dataclass Updates
Add real-time telemetry metrics for cooldowns, peak equity, and pause state:
```python
@dataclass
class BotSessionSummary:
    """Real-time metrics summary for active trading session."""

    status: BotStatus
    started_at: datetime | None
    initial_balance: Decimal
    current_balance: Decimal
    net_profit: Decimal
    roi_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    pending_trades: int
    win_rate_pct: float
    max_drawdown_pct: float
    stop_loss_reached: bool
    consecutive_losses: int = 0
    peak_balance: Decimal = Decimal("0.00")
    current_drawdown_pct: float = 0.0
    paused_until: datetime | None = None
    is_paused: bool = False
    active_assignments: list[StrategyAssignment] = field(default_factory=list)
    recent_trades: list[LiveTradeRecord] = field(default_factory=list)
```

---

## 2. Bot Engine State Machine & Guardrails (`src/strat_trade/domain/trading/bot_engine.py`)

### 2.1 State & Attributes in `LiveDemoBotEngine.__init__`
```python
class LiveDemoBotEngine:
    def __init__(self, trade_store: TradeStore | None = None) -> None:
        self.trade_store = trade_store or TradeStore()
        self.status = BotStatus.IDLE
        self.plan: PreTradingPlan | None = None
        self.initial_balance = Decimal("1000.00")
        self.current_balance = Decimal("1000.00")
        self.peak_balance = Decimal("1000.00")
        self.current_drawdown_pct: float = 0.0
        self.max_drawdown_pct: float = 0.0
        self.consecutive_losses: int = 0
        self.paused_until: datetime | None = None
        self.started_at: datetime | None = None
        self.active_trades: dict[str, LiveTradeRecord] = {}
        self.recent_trades: list[LiveTradeRecord] = []
        self._strategy_instances: dict[str, BaseStrategy] = {}
        self._last_signal_time: dict[str, datetime] = {}
        self._asset_cooldown_until: dict[str, datetime] = {}
        self._last_global_execution_time: datetime | None = None
        self._task: asyncio.Task[None] | None = None
        self._gateway: Any = None
        self._lock = asyncio.Lock()
        self._order_lock = asyncio.Lock()
```

### 2.2 Lifecycle Methods: `start`, `stop`, `pause`, `resume`
```python
    def is_running(self) -> bool:
        return self.status == BotStatus.RUNNING

    def is_paused(self) -> bool:
        return self.status == BotStatus.PAUSED

    async def start(self, plan: PreTradingPlan, gateway: Any) -> None:
        async with self._lock:
            if self.status in (BotStatus.RUNNING, BotStatus.PAUSED):
                return

            self.plan = plan
            self._gateway = gateway
            self.initial_balance = Decimal(str(plan.initial_deposit))
            self.current_balance = Decimal(str(plan.initial_deposit))
            self.peak_balance = Decimal(str(plan.initial_deposit))
            self.current_drawdown_pct = 0.0
            self.max_drawdown_pct = 0.0
            self.consecutive_losses = 0
            self.paused_until = None
            self.started_at = datetime.now(UTC)
            self.status = BotStatus.RUNNING
            self.active_trades.clear()
            self._last_signal_time.clear()
            self._asset_cooldown_until.clear()
            self._last_global_execution_time = None
            self._strategy_instances.clear()

            # Initialize strategies per asset
            for a in plan.assignments:
                try:
                    strat = get_strategy_instance(a.strategy_id, **a.parameters)
                    self._strategy_instances[a.asset] = strat
                except Exception as e:
                    logger.warning("Failed to initialize strategy for %s: %s", a.asset, e)

            self._task = asyncio.create_task(self._run_loop())
            logger.info("LiveDemoBotEngine started with %d assets", len(plan.assignments))

    async def stop(self) -> None:
        async with self._lock:
            if self.status in (BotStatus.IDLE, BotStatus.STOPPED):
                return

            self.status = BotStatus.STOPPED
            self.paused_until = None
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None
            logger.info("LiveDemoBotEngine stopped by user")

    async def pause(self) -> None:
        async with self._lock:
            if self.status != BotStatus.RUNNING:
                logger.warning("Cannot pause bot in status %s", self.status.value)
                return

            self.status = BotStatus.PAUSED
            self.paused_until = None  # Manual pause has no auto-resume timer
            logger.info("LiveDemoBotEngine paused by user")

    async def resume(self) -> None:
        async with self._lock:
            if self.status != BotStatus.PAUSED:
                logger.warning("Cannot resume bot in status %s", self.status.value)
                return

            self.status = BotStatus.RUNNING
            self.paused_until = None
            self.consecutive_losses = 0  # Reset loss streak upon manual resume
            logger.info("LiveDemoBotEngine resumed by user to RUNNING")
```

### 2.3 Circuit Breaker Evaluation (`_check_circuit_breakers`)
```python
    async def _check_circuit_breakers(self) -> None:
        if not self.plan:
            return

        # 1. Hard Stop-Loss Check (session total net loss vs stop_loss_amount)
        loss = self.initial_balance - self.current_balance
        if loss >= self.plan.stop_loss_amount:
            self.status = BotStatus.HALTED_BY_STOP_LOSS
            logger.warning(
                "HARD STOP-LOSS TRIGGERED! Session loss ($%.2f) reached limit ($%.2f). Halting.",
                float(loss),
                float(self.plan.stop_loss_amount),
            )
            return

        # 2. Peak-to-Trough High-Watermark Drawdown Circuit Breaker
        if self.peak_balance > Decimal("0.00"):
            drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
            self.current_drawdown_pct = max(0.0, float(drawdown * Decimal("100.0")))
            if self.current_drawdown_pct > self.max_drawdown_pct:
                self.max_drawdown_pct = self.current_drawdown_pct

            limit_pct = self.plan.max_drawdown_pct_limit * 100.0
            if self.current_drawdown_pct >= limit_pct:
                self.status = BotStatus.HALTED_BY_CIRCUIT_BREAKER
                logger.error(
                    "CIRCUIT BREAKER TRIGGERED! Max drawdown (%.2f%%) exceeded limit (%.2f%%). Peak: $%.2f, Current: $%.2f. Halting bot.",
                    self.current_drawdown_pct,
                    limit_pct,
                    float(self.peak_balance),
                    float(self.current_balance),
                )
                return
```

### 2.4 Main Loop Orchestration (`_run_loop`)
```python
    async def _run_loop(self) -> None:
        while self.status in (BotStatus.RUNNING, BotStatus.PAUSED):
            try:
                # 1. Settle expiring active trades
                await self._check_active_trades()

                # 2. Evaluate circuit breakers (Stop-Loss and Max Drawdown)
                await self._check_circuit_breakers()

                # If status transitioned to a terminal halt, break out of loop
                if self.status not in (BotStatus.RUNNING, BotStatus.PAUSED):
                    break

                # 3. Auto-Resume handling for cooling-off pause
                if self.status == BotStatus.PAUSED and self.paused_until:
                    if datetime.now(UTC) >= self.paused_until:
                        logger.info(
                            "Cooling-off pause period expired (%s). Auto-resuming bot.",
                            self.paused_until.isoformat(),
                        )
                        self.status = BotStatus.RUNNING
                        self.paused_until = None
                        self.consecutive_losses = 0

                # 4. Only scan and execute when active RUNNING
                if self.status == BotStatus.RUNNING:
                    await self._evaluate_signals_and_trade()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in bot trading loop: %s", e, exc_info=True)

            await asyncio.sleep(4.0)
```

### 2.5 Active Trade Settlement & Post-Trade Cooldown
```python
    async def _check_active_trades(self) -> None:
        now = datetime.now(UTC)
        finished_ids = []

        for tid, trade in list(self.active_trades.items()):
            expiry_time = trade.open_time + timedelta(seconds=trade.expiration_seconds)
            if now >= expiry_time:
                try:
                    candles = await self._gateway.get_candles(
                        trade.asset,
                        timeframe=60,
                        count=5,
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
                if self.peak_balance > 0:
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

                # Set Post-Trade-Settlement Per-Asset Cooldown
                cooldown_bars = self.plan.cooldown_bars if self.plan else 3
                cooldown_sec = cooldown_bars * 60  # default 60s bar timeframe
                self._asset_cooldown_until[trade.asset] = now + timedelta(seconds=cooldown_sec)

                logger.info(
                    "Trade %s on %s closed: %s (PnL: $%.2f, Balance: $%.2f). Cooldown active for %ds until %s.",
                    trade.action,
                    trade.asset,
                    outcome.value,
                    float(pnl),
                    float(self.current_balance),
                    cooldown_sec,
                    self._asset_cooldown_until[trade.asset].isoformat(),
                )

                # Handle Consecutive Loss Circuit Breaker
                if outcome == TradeOutcome.LOSS:
                    self.consecutive_losses += 1
                    max_losses = self.plan.max_consecutive_losses if self.plan else 3
                    logger.warning(
                        "Consecutive losses count: %d (limit: %d)",
                        self.consecutive_losses,
                        max_losses,
                    )
                    if self.consecutive_losses >= max_losses:
                        pause_mins = self.plan.pause_duration_minutes if self.plan else 15
                        self.status = BotStatus.PAUSED
                        self.paused_until = now + timedelta(minutes=pause_mins)
                        logger.warning(
                            "CONSECUTIVE LOSS CIRCUIT BREAKER: %d losses reached limit (%d). Bot PAUSED for %d minutes (until %s).",
                            self.consecutive_losses,
                            max_losses,
                            pause_mins,
                            self.paused_until.isoformat(),
                        )
                elif outcome == TradeOutcome.WIN:
                    self.consecutive_losses = 0

        for fid in finished_ids:
            self.active_trades.pop(fid, None)
```

### 2.6 Signal Evaluation & Exposure Filtering (`_evaluate_signals_and_trade`, `_evaluate_single_asset`, `_execute_order`)
```python
    async def _evaluate_signals_and_trade(self) -> None:
        if not self.plan or not self._gateway or self.status != BotStatus.RUNNING:
            return

        if len(self.active_trades) >= self.plan.max_concurrent_trades:
            return

        now = datetime.now(UTC)

        # Global Portfolio Cooldown Delay
        if self._last_global_execution_time:
            elapsed = (now - self._last_global_execution_time).total_seconds()
            if elapsed < self.plan.global_cooldown_seconds:
                logger.debug(
                    "Global cooldown active: %.1fs remaining of %ds",
                    self.plan.global_cooldown_seconds - elapsed,
                    self.plan.global_cooldown_seconds,
                )
                return

        sem = asyncio.Semaphore(6)
        tasks = [
            self._evaluate_single_asset(assignment, now, sem)
            for assignment in self.plan.assignments
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _evaluate_single_asset(
        self,
        assignment: StrategyAssignment,
        now: datetime,
        sem: asyncio.Semaphore,
    ) -> None:
        if not self.plan or self.status != BotStatus.RUNNING:
            return

        if len(self.active_trades) >= self.plan.max_concurrent_trades:
            return

        asset = assignment.asset
        # 1. Prevent duplicate simultaneous trades on same asset
        if any(t.asset == asset for t in self.active_trades.values()):
            return

        # 2. Check Post-Settlement Cooldown for this asset
        cooldown_until = self._asset_cooldown_until.get(asset)
        if cooldown_until and now < cooldown_until:
            logger.debug(
                "Skipping %s: in post-settlement cooldown until %s (%.1fs remaining)",
                asset,
                cooldown_until.isoformat(),
                (cooldown_until - now).total_seconds(),
            )
            return

        # 3. Check Signal-to-Signal Cooldown per asset (minimum 30s)
        last_sig = self._last_signal_time.get(asset)
        if last_sig and (now - last_sig).total_seconds() < 30:
            return

        strat = self._strategy_instances.get(asset)
        if not strat:
            return

        async with sem:
            try:
                # Live Broker Payout Check
                live_payout = 0.92
                if hasattr(self._gateway, "get_asset_payout"):
                    try:
                        live_payout = await self._gateway.get_asset_payout(asset)
                    except Exception as e:
                        logger.debug("Failed to get live payout for %s: %s", asset, e)

                min_payout = float(self.plan.min_payout_rate)
                if live_payout < min_payout:
                    return

                candles = await self._gateway.get_candles(asset, timeframe=60, count=100)
                if not candles or len(candles) < 25:
                    return

                signal = strat.evaluate_candles(candles)
                act_str = (
                    signal.action.value
                    if hasattr(signal.action, "value")
                    else str(signal.action or "")
                )
                if act_str in ("CALL", "PUT") and signal.confidence >= 0.50:
                    # 4. Currency Correlation & Exposure Filter Check
                    if self.plan.correlation_filter_enabled and self.active_trades:
                        try:
                            from strat_trade.domain.trading.correlation import is_correlated_conflict
                            is_conflict, conflict_reason = is_correlated_conflict(
                                candidate_asset=asset,
                                candidate_action=act_str,
                                active_trades=list(self.active_trades.values()),
                            )
                            if is_conflict:
                                logger.info(
                                    "Correlation filter rejected %s %s: %s",
                                    act_str,
                                    asset,
                                    conflict_reason,
                                )
                                return
                        except ImportError:
                            pass

                    # 5. Execute order
                    if len(self.active_trades) < self.plan.max_concurrent_trades:
                        self._last_signal_time[asset] = now
                        reason = signal.metadata.get("reason", signal.regime)
                        await self._execute_order(
                            assignment, act_str, signal.confidence, reason, candles, live_payout
                        )
            except Exception as e:
                logger.debug("Signal evaluation failed on %s: %s", asset, e)

    async def _execute_order(
        self,
        assignment: StrategyAssignment,
        action: str,
        confidence: float,
        reason: str,
        candles: list[Candle],
        live_payout: float = 0.92,
    ) -> None:
        async with self._order_lock:
            if not self.plan or not self._gateway or self.status != BotStatus.RUNNING:
                return

            if len(self.active_trades) >= self.plan.max_concurrent_trades:
                return

            now = datetime.now(UTC)

            # Atomic Global Cooldown Check inside order lock
            if self._last_global_execution_time:
                elapsed = (now - self._last_global_execution_time).total_seconds()
                if elapsed < self.plan.global_cooldown_seconds:
                    logger.debug("Global cooldown active inside order lock: skipping %s", assignment.asset)
                    return

            if any(t.asset == assignment.asset for t in self.active_trades.values()):
                return

            # Sizing
            if self.plan.stake_model == "percent":
                stake = (self.current_balance * Decimal(str(self.plan.stake_percent / 100.0))).quantize(
                    Decimal("1.00")
                )
                stake = max(Decimal("1.00"), stake)
            else:
                stake = self.plan.stake_amount

            snapshot = self._extract_snapshot(candles)

            trade_id = str(uuid.uuid4())
            open_time = now
            open_price = Decimal(str(candles[-1].close))
            payout_rate = Decimal(str(live_payout))

            # Open order via Pocket Option Gateway
            broker_order_id: str | None = None
            try:
                order_id, deal_info = await self._gateway.open_trade(
                    asset=assignment.asset,
                    action=action,
                    amount=float(stake),
                    expiration_seconds=self.plan.expiration_seconds,
                )
                broker_order_id = order_id
                if isinstance(deal_info, dict) and "percentProfit" in deal_info:
                    try:
                        payout_rate = (
                            Decimal(str(deal_info["percentProfit"])) / Decimal("100.0")
                        ).quantize(Decimal("0.01"))
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning(
                    "Gateway order execution failed (continuing paper demo tracking): %s", exc
                )
                broker_order_id = f"demo-{uuid.uuid4().hex[:12]}"

            record = LiveTradeRecord(
                trade_id=trade_id,
                broker_order_id=broker_order_id,
                asset=assignment.asset,
                action=action,
                stake=stake,
                open_time=open_time,
                expiration_seconds=self.plan.expiration_seconds,
                open_price=open_price,
                strategy_id=assignment.strategy_id,
                strategy_name=assignment.strategy_name,
                strategy_params=assignment.parameters,
                indicator_snapshot=snapshot,
                confidence=confidence,
                reason=reason,
                payout_rate=payout_rate,
                outcome=TradeOutcome.PENDING,
                pnl=Decimal("0.00"),
            )

            self.trade_store.save_trade(record)
            self.active_trades[trade_id] = record
            self._last_global_execution_time = now

            logger.info(
                "Opened %s trade on %s ($%.2f, exp: %ds, Strategy: %s, Broker Order: %s)",
                action,
                assignment.asset,
                float(stake),
                self.plan.expiration_seconds,
                assignment.strategy_name,
                broker_order_id,
            )
```

---

## 3. Telemetry Integration & Schema Alignment

### 3.1 `BotStatusResponse` (in `schemas.py`)
Ensure `BotStatusResponse` includes the new telemetry fields:
- `consecutive_losses: int`
- `peak_balance: float`
- `current_drawdown_pct: float`
- `paused_until: str | None`
- `is_paused: bool`

### 3.2 Use Cases Layer (`manage_live_bot.py`)
Expose:
- `async def pause_live_bot() -> BotSessionSummary`
- `async def resume_live_bot() -> BotSessionSummary`

---

## 4. Comprehensive Unit Test Plan for Guardrails

The test file `tests/test_execution_guardrails.py` should implement:
1. `test_post_settlement_per_asset_cooldown`:
   - Open and close a trade on `EURUSD_otc` with `cooldown_bars=3`.
   - Confirm `_asset_cooldown_until['EURUSD_otc']` is set to 180s in the future.
   - Verify `_evaluate_single_asset` skips evaluation during cooldown and accepts signals once cooldown expires.
2. `test_global_portfolio_cooldown`:
   - Set `global_cooldown_seconds=30`.
   - Simulate an order execution on `EURUSD_otc`.
   - Verify subsequent candidate execution on `GBPUSD_otc` within 10s is rejected by global cooldown lock.
   - Advance clock past 30s and verify `GBPUSD_otc` executes.
3. `test_consecutive_losses_circuit_breaker_and_pause`:
   - Set `max_consecutive_losses=3`, `pause_duration_minutes=15`.
   - Settle 3 consecutive LOSS trades.
   - Verify status becomes `BotStatus.PAUSED`, `paused_until` is set to +15m, and `is_paused` is True.
   - Advance clock past `paused_until` and verify loop auto-resumes to `BotStatus.RUNNING` and resets `consecutive_losses = 0`.
4. `test_max_drawdown_high_watermark_halt`:
   - Set `initial_deposit=1000.0`, `max_drawdown_pct_limit=0.08` (8%).
   - Balance grows to $1200 (`peak_balance=1200`).
   - Settle loss trades bringing balance to $1100 ($100 / $1200 = 8.33% drawdown).
   - Verify status transitions to `BotStatus.HALTED_BY_CIRCUIT_BREAKER`.
5. `test_manual_pause_and_resume_lifecycle`:
   - Start bot (`RUNNING`).
   - Call `bot.pause()` -> verify `BotStatus.PAUSED`, `paused_until is None`.
   - Call `bot.resume()` -> verify `BotStatus.RUNNING`.
