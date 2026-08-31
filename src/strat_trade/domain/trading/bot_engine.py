from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd

from strat_trade.domain.entities import Candle
from strat_trade.domain.strategies.base import BaseStrategy
from strat_trade.domain.strategies.registry import get_strategy_instance, split_strategy_params
from strat_trade.domain.trading.asset_filter import (
    is_asset_in_active_session,
    is_otc_asset,
    is_toxic_asset,
    qualify_asset_microstructure,
)
from strat_trade.domain.trading.asset_governor import (
    AssetGovernor,
    AssetGovernorConfig,
    AssetTier,
    AssetVerdict,
)
from strat_trade.domain.trading.correlation import is_correlated_conflict
from strat_trade.domain.trading.entities import (
    BotSessionSummary,
    BotStatus,
    IndicatorSnapshot,
    LiveTradeRecord,
    PreTradingPlan,
    StrategyAssignment,
    TradeOutcome,
)
from strat_trade.domain.trading.execution_gates import (
    is_bar_edge_blocked,
    seconds_into_bar,
    select_closed_candles,
)
from strat_trade.domain.trading.regime_detector import (
    MarketRegime,
    detect_live_market_regime,
    select_candidate_strategies_for_regime,
)
from strat_trade.domain.trading.trade_store import TradeStore

logger = logging.getLogger(__name__)

# How long to wait past expiry for the broker to publish a result before settling
# from candles. Pocket Option normally answers within a few seconds.
BROKER_SETTLEMENT_GRACE_SECONDS = 25

_OUTCOME_BY_BROKER_RESULT = {
    "win": TradeOutcome.WIN,
    "loss": TradeOutcome.LOSS,
    "draw": TradeOutcome.DRAW,
}


def _as_positive_decimal(value: Any) -> Decimal | None:
    """Coerces a broker-supplied price, rejecting anything that is not a real number."""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        price = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None
    return price if price > 0 else None


def _pnl_for(outcome: TradeOutcome, trade: LiveTradeRecord) -> Decimal:
    """Models the payout for a settled trade when the broker reported no amount."""
    if outcome == TradeOutcome.WIN:
        return trade.stake * trade.payout_rate
    if outcome == TradeOutcome.LOSS:
        return -trade.stake
    return Decimal("0.00")


class LiveDemoBotEngine:
    """Orchestrates autonomous live/demo trading across multiple assets with assigned strategies."""

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
        self._dynamic_strategy_pool: dict[tuple[str, str], BaseStrategy] = {}
        self._executed_params: dict[tuple[str, str], dict[str, Any]] = {}
        self._last_signal_time: dict[str, datetime] = {}
        self._asset_cooldown_until: dict[str, datetime] = {}
        self._asset_consecutive_losses: dict[str, int] = {}
        self._asset_wins: dict[str, int] = {}
        self._asset_losses: dict[str, int] = {}
        self._asset_muted_until: dict[str, datetime] = {}
        self._last_global_execution_time: datetime | None = None
        self.asset_governor = AssetGovernor()
        self._task: asyncio.Task[None] | None = None
        self._gateway: Any = None
        self._lock = asyncio.Lock()
        self._order_lock = asyncio.Lock()

    @staticmethod
    def _build_governor_config(plan: PreTradingPlan) -> AssetGovernorConfig:
        return AssetGovernorConfig(
            otc_stake_multiplier=getattr(plan, "otc_stake_multiplier", 0.25),
            otc_min_payout_rate=getattr(plan, "otc_min_payout_rate", 0.90),
            spot_min_payout_rate=float(plan.min_payout_rate),
            min_trades_for_mute=getattr(plan, "governor_min_trades_for_mute", 20),
            mute_duration_minutes=getattr(plan, "governor_mute_duration_minutes", 240),
            promotion_min_trades=getattr(plan, "governor_promotion_min_trades", 400),
        )

    def _governor_verdict(self, asset: str, now: datetime) -> AssetVerdict:
        if not self.plan or not getattr(self.plan, "asset_governor_enabled", True):
            return AssetVerdict(
                tier=AssetTier.NORMAL,
                stake_multiplier=1.0,
                min_payout_rate=float(self.plan.min_payout_rate) if self.plan else 0.80,
                reason="Asset governor disabled",
            )
        return self.asset_governor.evaluate(asset, now)

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
            self._asset_consecutive_losses.clear()
            self._asset_wins.clear()
            self._asset_losses.clear()
            self._asset_muted_until.clear()
            self._last_global_execution_time = None
            self._strategy_instances.clear()
            self._dynamic_strategy_pool.clear()
            self._executed_params.clear()
            self.asset_governor = AssetGovernor(self._build_governor_config(plan))

            # Initialize strategies per asset
            for a in plan.assignments:
                try:
                    accepted, rejected = split_strategy_params(a.strategy_id, a.parameters)
                    if rejected:
                        logger.warning(
                            "Assignment for %s carries %d parameter(s) that %s does not "
                            "accept and that will fall back to defaults: %s",
                            a.asset,
                            len(rejected),
                            a.strategy_id,
                            ", ".join(rejected),
                        )
                    strat = get_strategy_instance(a.strategy_id, **accepted)
                    self._strategy_instances[a.asset] = strat
                    self._executed_params[a.asset, a.strategy_id] = accepted
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

    def clear_history(self) -> int:
        """Clears all stored trades from SQLite and in-memory list."""
        count = self.trade_store.clear_trades()
        self.recent_trades.clear()
        return count

    async def pause(self, duration_seconds: int | None = None, reason: str = "") -> None:
        async with self._lock:
            if self.status != BotStatus.RUNNING:
                logger.warning("Cannot pause bot in status %s", self.status.value)
                return

            self.status = BotStatus.PAUSED
            if duration_seconds and duration_seconds > 0:
                self.paused_until = datetime.now(UTC) + timedelta(seconds=duration_seconds)
            else:
                self.paused_until = None
            logger.info(
                "LiveDemoBotEngine paused (reason: %s, duration: %s, until: %s)",
                reason or "manual",
                f"{duration_seconds}s" if duration_seconds else "indefinite",
                self.paused_until.isoformat() if self.paused_until else "None",
            )

    async def resume(self) -> None:
        async with self._lock:
            if self.status not in (BotStatus.PAUSED, BotStatus.HALTED_BY_CIRCUIT_BREAKER):
                logger.warning("Cannot resume bot in status %s", self.status.value)
                return

            self.status = BotStatus.RUNNING
            self.paused_until = None
            self.consecutive_losses = 0  # Reset loss streak upon manual resume

            # Reset high-watermark baseline if resuming from a circuit breaker halt
            if self.current_balance > Decimal("0.00"):
                self.peak_balance = self.current_balance
                self.current_drawdown_pct = 0.0

            # Ensure background trading loop is active if it was terminated
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run_loop())

            logger.info("LiveDemoBotEngine resumed by user to RUNNING")

    def get_summary(self) -> BotSessionSummary:
        total = len(self.recent_trades) + len(self.active_trades)
        wins = sum(1 for t in self.recent_trades if t.outcome == TradeOutcome.WIN)
        losses = sum(1 for t in self.recent_trades if t.outcome == TradeOutcome.LOSS)
        draws = sum(1 for t in self.recent_trades if t.outcome == TradeOutcome.DRAW)
        pending = len(self.active_trades)

        decided = wins + losses + draws
        wr = (wins / decided * 100.0) if decided > 0 else 0.0
        net = self.current_balance - self.initial_balance
        roi = (
            float((net / self.initial_balance) * Decimal("100.0"))
            if self.initial_balance > 0
            else 0.0
        )

        stop_loss_hit = self.status == BotStatus.HALTED_BY_STOP_LOSS
        circuit_breaker_hit = self.status == BotStatus.HALTED_BY_CIRCUIT_BREAKER

        return BotSessionSummary(
            status=self.status,
            started_at=self.started_at,
            initial_balance=self.initial_balance,
            current_balance=self.current_balance,
            net_profit=net,
            roi_pct=roi,
            total_trades=total,
            winning_trades=wins,
            losing_trades=losses,
            draw_trades=draws,
            pending_trades=pending,
            win_rate_pct=wr,
            max_drawdown_pct=float(self.max_drawdown_pct),
            stop_loss_reached=stop_loss_hit,
            consecutive_losses=self.consecutive_losses,
            peak_balance=self.peak_balance,
            current_drawdown_pct=float(self.current_drawdown_pct),
            paused_until=self.paused_until,
            is_paused=(self.status == BotStatus.PAUSED),
            circuit_breaker_triggered=circuit_breaker_hit,
            active_assignments=self.plan.assignments if self.plan else [],
            recent_trades=list(self.active_trades.values()) + self.recent_trades[:50],
        )

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
                    "CIRCUIT BREAKER TRIGGERED! Max drawdown (%.2f%%) exceeded limit (%.2f%%). "
                    "Peak: $%.2f, Current: $%.2f. Halting bot.",
                    self.current_drawdown_pct,
                    limit_pct,
                    float(self.peak_balance),
                    float(self.current_balance),
                )
                return

        profit = self.current_balance - self.initial_balance

        # 3. Trailing Profit Lock Check
        if getattr(self.plan, "trailing_profit_lock_enabled", True):
            peak_profit = self.peak_balance - self.initial_balance
            lock_threshold = getattr(
                self.plan, "trailing_profit_lock_threshold_usd", Decimal("500.00")
            )
            if peak_profit >= lock_threshold:
                retention_pct = getattr(self.plan, "trailing_profit_retention_pct", 0.75)
                min_allowed_profit = peak_profit * Decimal(str(retention_pct))
                if profit < min_allowed_profit:
                    self.status = BotStatus.HALTED_BY_TRAILING_PROFIT_LOCK
                    logger.warning(
                        "🔒 TRAILING PROFIT LOCK TRIGGERED! Peak profit was $%.2f, current profit "
                        "fell to $%.2f (below %.0f%% retention = $%.2f). Halting bot.",
                        float(peak_profit),
                        float(profit),
                        retention_pct * 100.0,
                        float(min_allowed_profit),
                    )
                    return

        # 4. Hard Take-Profit Check (session total net profit vs take_profit_amount)
        take_profit_amount = getattr(self.plan, "take_profit_amount", Decimal("1000.00"))
        if profit >= take_profit_amount:
            self.status = BotStatus.HALTED_BY_TAKE_PROFIT
            logger.info(
                "🏆 TAKE-PROFIT ACHIEVED! Session net profit ($%.2f) reached target ($%.2f). "
                "Halting bot.",
                float(profit),
                float(take_profit_amount),
            )
            return

    async def _check_active_trades(self) -> None:
        now = datetime.now(UTC)
        finished_ids = []

        for tid, trade in list(self.active_trades.items()):
            expiry_time = trade.open_time + timedelta(seconds=trade.expiration_seconds)
            if now >= expiry_time:
                # The broker owns the truth: it settles against its own fill and
                # expiry tick. Deriving the verdict from closed candles instead made
                # the bot disagree with the account, which silently corrupted the
                # circuit breakers, the degradation guard and the asset governor.
                broker_can_settle = self._broker_can_settle(trade)
                settlement = await self._broker_settlement(trade) if broker_can_settle else None

                if settlement is None:
                    # Give the broker a short window to publish the result before
                    # falling back, rather than racing it with a stale candle. With
                    # no broker order to ask about there is nothing to wait for.
                    if broker_can_settle and now < expiry_time + timedelta(
                        seconds=BROKER_SETTLEMENT_GRACE_SECONDS
                    ):
                        continue
                    outcome, pnl, close_price = await self._settle_from_candles(trade)
                    settlement_source = "candle"
                    logger.warning(
                        "Broker did not settle %s on %s within %ds; falling back to candles.",
                        trade.broker_order_id,
                        trade.asset,
                        BROKER_SETTLEMENT_GRACE_SECONDS,
                    )
                else:
                    outcome = _OUTCOME_BY_BROKER_RESULT[settlement["result"]]
                    profit = settlement.get("profit")
                    pnl = (
                        Decimal(str(profit))
                        if isinstance(profit, (int, float, str, Decimal))
                        and not isinstance(profit, bool)
                        else _pnl_for(outcome, trade)
                    )
                    close_price = (
                        _as_positive_decimal(settlement.get("close_price")) or trade.open_price
                    )
                    settlement_source = "broker"

                trade.close_time = now
                trade.close_price = close_price
                trade.outcome = outcome
                trade.pnl = pnl
                trade.settlement_source = settlement_source

                self.current_balance += pnl
                if self.current_balance > self.peak_balance:
                    self.peak_balance = self.current_balance

                # Update drawdown tracking
                if self.peak_balance > Decimal("0.00"):
                    dd = float(
                        ((self.peak_balance - self.current_balance) / self.peak_balance)
                        * Decimal("100.0")
                    )
                    self.current_drawdown_pct = max(0.0, dd)
                    if self.current_drawdown_pct > self.max_drawdown_pct:
                        self.max_drawdown_pct = self.current_drawdown_pct

                trade.balance_after = self.current_balance

                # Update database
                self.trade_store.update_trade_outcome(
                    trade_id=trade.trade_id,
                    close_time=now,
                    close_price=close_price,
                    outcome=outcome,
                    pnl=pnl,
                    balance_after=self.current_balance,
                    settlement_source=settlement_source,
                )

                self.recent_trades.insert(0, trade)
                finished_ids.append(tid)

                # Feed the statistical governor. Draws carry no information about
                # directional skill, so they are not counted.
                if outcome in (TradeOutcome.WIN, TradeOutcome.LOSS) and getattr(
                    self.plan, "asset_governor_enabled", True
                ):
                    self.asset_governor.record_outcome(
                        asset=trade.asset,
                        is_win=outcome == TradeOutcome.WIN,
                        payout_rate=float(trade.payout_rate),
                        now=now,
                    )

                # Set Post-Trade-Settlement Per-Asset Cooldown
                cooldown_bars = self.plan.cooldown_bars if self.plan else 3
                cooldown_sec = max(180, cooldown_bars * 60)  # Hard minimum 3 minutes (180s)
                self._asset_cooldown_until[trade.asset] = now + timedelta(seconds=cooldown_sec)

                logger.info(
                    "Trade %s on %s closed: %s (PnL: $%.2f, Balance: $%.2f). "
                    "Cooldown active for %ds until %s.",
                    trade.action,
                    trade.asset,
                    outcome.value,
                    float(pnl),
                    float(self.current_balance),
                    cooldown_sec,
                    self._asset_cooldown_until[trade.asset].isoformat(),
                )

                # Handle Consecutive Loss Circuit Breaker & Per-Asset Degradation Guard
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
                        if self.status == BotStatus.RUNNING:
                            self.status = BotStatus.PAUSED
                        self.paused_until = now + timedelta(minutes=pause_mins)
                        logger.warning(
                            "CONSECUTIVE LOSS CIRCUIT BREAKER: %d losses reached limit (%d). "
                            "Bot PAUSED for %d minutes (until %s).",
                            self.consecutive_losses,
                            max_losses,
                            pause_mins,
                            self.paused_until.isoformat(),
                        )

                    # Dynamic Per-Asset Degradation Guard
                    if getattr(self.plan, "per_asset_degradation_guard_enabled", True):
                        self._asset_consecutive_losses[trade.asset] = (
                            self._asset_consecutive_losses.get(trade.asset, 0) + 1
                        )
                        self._asset_losses[trade.asset] = self._asset_losses.get(trade.asset, 0) + 1

                        max_asset_losses = getattr(self.plan, "per_asset_max_consecutive_losses", 2)
                        if self._asset_consecutive_losses[trade.asset] >= max_asset_losses:
                            mute_mins = 60
                            self._asset_muted_until[trade.asset] = now + timedelta(
                                minutes=mute_mins
                            )
                            logger.warning(
                                "ASSET DEGRADATION GUARD: %s suffered %d consecutive losses. "
                                "Muted for %d mins (until %s).",
                                trade.asset,
                                self._asset_consecutive_losses[trade.asset],
                                mute_mins,
                                self._asset_muted_until[trade.asset].isoformat(),
                            )

                        tot_trades = (
                            self._asset_wins.get(trade.asset, 0) + self._asset_losses[trade.asset]
                        )
                        if tot_trades >= 3:
                            asset_wr = (self._asset_wins.get(trade.asset, 0) / tot_trades) * 100.0
                            min_floor = getattr(self.plan, "per_asset_min_winrate_pct", 40.0)
                            if asset_wr < min_floor:
                                mute_mins = 120
                                self._asset_muted_until[trade.asset] = now + timedelta(
                                    minutes=mute_mins
                                )
                                logger.warning(
                                    "ASSET DEGRADATION GUARD: %s session win rate "
                                    "(%.1f%%, %dW/%dL) fell below floor (%.1f%%). Muted %d min.",
                                    trade.asset,
                                    asset_wr,
                                    self._asset_wins.get(trade.asset, 0),
                                    self._asset_losses[trade.asset],
                                    min_floor,
                                    mute_mins,
                                )

                elif outcome == TradeOutcome.WIN:
                    self.consecutive_losses = 0
                    if getattr(self.plan, "per_asset_degradation_guard_enabled", True):
                        self._asset_consecutive_losses[trade.asset] = 0
                        self._asset_wins[trade.asset] = self._asset_wins.get(trade.asset, 0) + 1

                    # The pause is deliberately NOT lifted here. Up to
                    # max_concurrent_trades - 1 trades are still in flight when the
                    # breaker fires, so letting one of them cancel the cooling-off
                    # made the breaker a no-op: an 11-loss run survived a cap of 3.
                    # _run_loop resumes on its own once paused_until elapses.

        for fid in finished_ids:
            self.active_trades.pop(fid, None)

    async def _evaluate_signals_and_trade(self) -> None:
        if not self.plan or not self._gateway or self.status != BotStatus.RUNNING:
            return

        # Check concurrency limit
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

    def _get_or_create_strategy(
        self, asset: str, strategy_id: str, assigned_params: dict[str, Any]
    ) -> BaseStrategy | None:
        key = (asset, strategy_id)
        if key in self._dynamic_strategy_pool:
            return self._dynamic_strategy_pool[key]
        if asset in self._strategy_instances and self.plan:
            assigned = next((a for a in self.plan.assignments if a.asset == asset), None)
            if assigned and assigned.strategy_id == strategy_id:
                self._dynamic_strategy_pool[key] = self._strategy_instances[asset]
                return self._strategy_instances[asset]
        try:
            params, rejected = split_strategy_params(strategy_id, assigned_params)
            if rejected:
                logger.info(
                    "Substituted strategy %s on %s ignores %d tuned parameter(s) "
                    "and uses its own defaults for them: %s",
                    strategy_id,
                    asset,
                    len(rejected),
                    ", ".join(rejected),
                )
            strat = get_strategy_instance(strategy_id, **params)
            self._dynamic_strategy_pool[key] = strat
            self._executed_params[key] = params
            return strat
        except Exception as e:
            logger.debug(
                "Failed to instantiate dynamic strategy %s for %s: %s", strategy_id, asset, e
            )
            return None

    def _params_actually_used(
        self, asset: str, strategy_id: str, assigned_params: dict[str, Any]
    ) -> dict[str, Any]:
        cached = self._executed_params.get((asset, strategy_id))
        if cached is not None:
            return cached
        params, _ = split_strategy_params(strategy_id, assigned_params)
        return params

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

        # 0. Bar-Edge Guard: the opening ticks of a bar are unstable, and entries
        # placed there carried 97% of the measured loss on the 24-28.08 sample.
        blocked, edge_reason = is_bar_edge_blocked(
            now, getattr(self.plan, "bar_edge_guard_seconds", 3.0)
        )
        if blocked:
            logger.debug("Skipping %s: %s", asset, edge_reason)
            return

        # 0b. Statistical Asset Governor verdict
        verdict = self._governor_verdict(asset, now)
        if not verdict.is_tradable:
            logger.debug("Skipping %s: %s", asset, verdict.reason)
            return

        # 1. Per-Asset Degradation Guard Mute Check
        if getattr(self.plan, "per_asset_degradation_guard_enabled", True):
            muted_until = self._asset_muted_until.get(asset)
            if muted_until and now < muted_until:
                logger.debug(
                    "Skipping %s: Muted by Asset Degradation Guard until %s (%.1fs remaining)",
                    asset,
                    muted_until.isoformat(),
                    (muted_until - now).total_seconds(),
                )
                return

        # 2. Asset Quality & Toxic Blacklist Filter Check
        if getattr(self.plan, "toxic_filter_enabled", True):
            is_toxic, toxic_reason = is_toxic_asset(
                asset, custom_blacklist=getattr(self.plan, "asset_blacklist", None)
            )
            if is_toxic:
                logger.warning("Skipping %s: %s", asset, toxic_reason)
                return

        # 3. Session Liquidity & Schedule Gate
        if getattr(self.plan, "session_filter_enabled", True):
            is_active_session, session_reason = is_asset_in_active_session(asset, now)
            if not is_active_session:
                logger.debug("Skipping %s: %s", asset, session_reason)
                return

        # 4. Don't open duplicate trades on the same asset if already active
        if any(t.asset == asset for t in self.active_trades.values()):
            return

        # 4. Check Post-Settlement Cooldown for this asset
        cooldown_until = self._asset_cooldown_until.get(asset)
        if cooldown_until and now < cooldown_until:
            logger.debug(
                "Skipping %s: in post-settlement cooldown until %s (%.1fs remaining)",
                asset,
                cooldown_until.isoformat(),
                (cooldown_until - now).total_seconds(),
            )
            return

        # 5. Check Signal-to-Signal Cooldown per asset: at least 30s
        last_sig = self._last_signal_time.get(asset)
        if last_sig and (now - last_sig).total_seconds() < 30:
            return

        async with sem:
            try:
                # 6. Live Broker Payout Check
                live_payout = 0.92
                if hasattr(self._gateway, "get_asset_payout"):
                    try:
                        live_payout = await self._gateway.get_asset_payout(asset)
                    except Exception as e:
                        logger.debug("Failed to get live payout for %s: %s", asset, e)

                # OTC needs a higher payout floor than spot: its break-even sits at
                # 52.08% while its measured win rate was 48.91%, so a thin payout
                # makes the trade negative-EV before any signal quality is considered.
                min_payout = max(float(self.plan.min_payout_rate), verdict.min_payout_rate)
                if live_payout < min_payout:
                    logger.debug(
                        "Skipping %s: payout (%.0f%%) below min requirement (%.0f%%)",
                        asset,
                        live_payout * 100,
                        min_payout * 100,
                    )
                    return

                raw_candles = await self._gateway.get_candles(asset, timeframe=60, count=100)
                if not raw_candles or len(raw_candles) < 25:
                    return

                # 6b. Closed-Bar Gate: indicators must not read a forming candle
                # whose high/low/close are still moving after the decision.
                if getattr(self.plan, "use_closed_bar_only", True):
                    candles = select_closed_candles(raw_candles, now)
                else:
                    candles = list(raw_candles)
                if len(candles) < 25:
                    return

                # 7. Microstructure Quality Gate (Step-tick / Discrete / Flat noise rejection)
                if len(candles) >= 50:
                    candle_df = pd.DataFrame(
                        [
                            {
                                "open": float(c.open),
                                "high": float(c.high),
                                "low": float(c.low),
                                "close": float(c.close),
                            }
                            for c in candles[-50:]
                        ]
                    )
                    is_qual, qual_reason = qualify_asset_microstructure(candle_df)
                    if not is_qual:
                        logger.info("Microstructure filter rejected %s: %s", asset, qual_reason)
                        return

                    # 8. Real-Time Dynamic Regime Detection
                    regime, _regime_metrics = detect_live_market_regime(candle_df)
                    if regime == MarketRegime.LOW_VOLATILITY_NOISE:
                        logger.debug(
                            "Regime detector: %s in LOW_VOLATILITY_NOISE regime. Standing aside.",
                            asset,
                        )
                        return
                else:
                    regime = MarketRegime.RANGING

                # 9. Strategy Selection. Substitution is opt-in: when the regime
                # detector swapped strategies it also discarded the parameters the
                # optimiser had tuned, so live trades no longer matched any backtest.
                if getattr(self.plan, "dynamic_strategy_switching_enabled", False):
                    allowed = getattr(self.plan, "allowed_strategies", None)
                    candidate_strat_ids = select_candidate_strategies_for_regime(
                        regime, allowed_strategies=allowed
                    )
                    if assignment.strategy_id not in candidate_strat_ids and (
                        not allowed or assignment.strategy_id in allowed
                    ):
                        candidate_strat_ids.append(assignment.strategy_id)
                else:
                    candidate_strat_ids = [assignment.strategy_id]

                best_signal = None
                best_strat_id = assignment.strategy_id

                for strat_id in candidate_strat_ids:
                    strat_inst = self._get_or_create_strategy(
                        asset, strat_id, assignment.parameters
                    )
                    if not strat_inst:
                        continue
                    try:
                        sig = strat_inst.evaluate_candles(candles)
                        act = (
                            sig.action.value
                            if hasattr(sig.action, "value")
                            else str(sig.action or "")
                        )
                        if act in ("CALL", "PUT") and sig.confidence >= 0.50:
                            if best_signal is None or sig.confidence > best_signal.confidence:
                                best_signal = sig
                                best_strat_id = strat_id
                    except Exception as e:
                        logger.debug("Eval error for %s on %s: %s", strat_id, asset, e)

                if not best_signal:
                    return

                act_str = (
                    best_signal.action.value
                    if hasattr(best_signal.action, "value")
                    else str(best_signal.action or "")
                )
                if act_str in ("CALL", "PUT") and best_signal.confidence >= 0.50:
                    # 10. Currency Correlation & Exposure Filter Check
                    if self.plan.correlation_filter_enabled and self.active_trades:
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

                    # 11. Execute order
                    if len(self.active_trades) < self.plan.max_concurrent_trades:
                        self._last_signal_time[asset] = now
                        reason = best_signal.metadata.get("reason", best_signal.regime)
                        await self._execute_order(
                            assignment,
                            act_str,
                            best_signal.confidence,
                            reason,
                            candles,
                            live_payout,
                            now=now,
                            executed_strategy_id=best_strat_id,
                            verdict=verdict,
                            live_price=Decimal(str(raw_candles[-1].close)),
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
        now: datetime | None = None,
        executed_strategy_id: str | None = None,
        verdict: AssetVerdict | None = None,
        live_price: Decimal | None = None,
    ) -> None:
        async with self._order_lock:
            if not self.plan or not self._gateway or self.status != BotStatus.RUNNING:
                return

            if len(self.active_trades) >= self.plan.max_concurrent_trades:
                return

            now = now or datetime.now(UTC)

            # Atomic Bar-Edge Guard: signal evaluation is concurrent, so the bar may
            # have rolled over between the scan and reaching this lock.
            blocked, edge_reason = is_bar_edge_blocked(
                now, getattr(self.plan, "bar_edge_guard_seconds", 3.0)
            )
            if blocked:
                logger.debug("Blocked execution on %s: %s", assignment.asset, edge_reason)
                return

            # Atomic Governor Check inside order lock
            verdict = verdict or self._governor_verdict(assignment.asset, now)
            if not verdict.is_tradable:
                logger.info("Blocked execution on %s: %s", assignment.asset, verdict.reason)
                return

            # Atomic Toxic Blacklist Check inside order lock
            if getattr(self.plan, "toxic_filter_enabled", True):
                is_toxic, toxic_reason = is_toxic_asset(
                    assignment.asset, custom_blacklist=getattr(self.plan, "asset_blacklist", None)
                )
                if is_toxic:
                    logger.error(
                        "Blocked execution on blacklisted toxic asset: %s (%s)",
                        assignment.asset,
                        toxic_reason,
                    )
                    return

            # Atomic Post-Settlement Cooldown Check inside order lock
            cooldown_until = self._asset_cooldown_until.get(assignment.asset)
            if cooldown_until and now < cooldown_until:
                logger.debug(
                    "Asset %s is in post-settlement cooldown inside order lock (until %s)",
                    assignment.asset,
                    cooldown_until.isoformat(),
                )
                return

            # Atomic Global Cooldown Check inside order lock
            if self._last_global_execution_time:
                elapsed = (now - self._last_global_execution_time).total_seconds()
                if elapsed < self.plan.global_cooldown_seconds:
                    logger.debug(
                        "Global cooldown active inside order lock: skipping %s", assignment.asset
                    )
                    return

            if any(t.asset == assignment.asset for t in self.active_trades.values()):
                return

            # Sizing
            if self.plan.stake_model == "percent":
                stake = (
                    self.current_balance * Decimal(str(self.plan.stake_percent / 100.0))
                ).quantize(Decimal("1.00"))
                stake = max(Decimal("1.00"), stake)
            else:
                stake = self.plan.stake_amount

            # Governed sizing: assets on probation risk a fraction of the stake
            # until their own record justifies more.
            multiplier = Decimal(str(verdict.stake_multiplier))
            if multiplier != Decimal("1"):
                stake = max(Decimal("1.00"), (stake * multiplier).quantize(Decimal("1.00")))

            executed_strat_id = executed_strategy_id or assignment.strategy_id
            executed_params = self._params_actually_used(
                assignment.asset, executed_strat_id, assignment.parameters
            )
            snapshot = self._extract_snapshot(
                candles, rsi_period=int(executed_params.get("rsi_period", 14))
            )

            trade_id = str(uuid.uuid4())
            open_time = now
            open_price = live_price or Decimal(str(candles[-1].close))
            payout_rate = Decimal(str(live_payout))

            # Open order via Pocket Option Gateway
            broker_order_id: str | None = None
            open_price_source = "candle"
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

                # The candle feed serves closed bars only, so `open_price` above can
                # be a whole bar behind the fill. Every downstream verdict compares
                # against it, so anchor it to the broker's price when available.
                fill = await self._broker_fill_price(order_id, deal_info)
                if fill is not None:
                    open_price = fill
                    open_price_source = "broker"
            except Exception as exc:
                logger.warning(
                    "Gateway order execution failed (continuing paper demo tracking): %s", exc
                )
                broker_order_id = f"demo-{uuid.uuid4().hex[:12]}"

            final_strat_id = executed_strat_id
            final_strat_name = (
                assignment.strategy_name
                if final_strat_id == assignment.strategy_id
                else final_strat_id.replace("_", " ").title()
            )

            record = LiveTradeRecord(
                trade_id=trade_id,
                broker_order_id=broker_order_id,
                asset=assignment.asset,
                action=action,
                stake=stake,
                open_time=open_time,
                expiration_seconds=self.plan.expiration_seconds,
                open_price=open_price,
                strategy_id=final_strat_id,
                strategy_name=final_strat_name,
                strategy_params=assignment.parameters,
                indicator_snapshot=snapshot,
                confidence=confidence,
                reason=reason,
                payout_rate=payout_rate,
                outcome=TradeOutcome.PENDING,
                pnl=Decimal("0.00"),
                executed_params=executed_params,
                asset_tier=str(verdict.tier),
                stake_multiplier=verdict.stake_multiplier,
                entry_second=int(seconds_into_bar(now)),
                is_otc=is_otc_asset(assignment.asset),
                open_price_source=open_price_source,
            )

            self.trade_store.save_trade(record)
            self.active_trades[trade_id] = record
            self._last_global_execution_time = now

            logger.info(
                "Opened %s trade on %s ($%.2f, exp: %ds, Strategy: %s, Tier: %s @%.0f%% stake, "
                "%ds into bar, Broker Order: %s)",
                action,
                assignment.asset,
                float(stake),
                self.plan.expiration_seconds,
                final_strat_name,
                verdict.tier,
                verdict.stake_multiplier * 100.0,
                record.entry_second,
                broker_order_id,
            )

    async def _broker_fill_price(self, order_id: str, deal_info: Any) -> Decimal | None:
        """Reads the price the broker actually opened the order at, if it says so."""
        if isinstance(deal_info, dict):
            for key in ("entry_price", "openPrice", "open_price"):
                price = _as_positive_decimal(deal_info.get(key))
                if price is not None:
                    return price

        getter = getattr(self._gateway, "get_deal_entry_price", None)
        if not callable(getter):
            return None
        try:
            return _as_positive_decimal(await getter(order_id))
        except Exception as exc:
            logger.debug("Broker entry price lookup failed for %s: %s", order_id, exc)
            return None

    async def _settle_from_candles(
        self, trade: LiveTradeRecord
    ) -> tuple[TradeOutcome, Decimal, Decimal]:
        """Last-resort settlement when the broker never published a result."""
        try:
            candles = await self._gateway.get_candles(trade.asset, timeframe=60, count=5)
            close_price = Decimal(str(candles[-1].close)) if candles else trade.open_price
        except Exception:
            close_price = trade.open_price

        if close_price == trade.open_price:
            outcome = TradeOutcome.DRAW
        elif (close_price > trade.open_price) == (trade.action == "CALL"):
            outcome = TradeOutcome.WIN
        else:
            outcome = TradeOutcome.LOSS

        return outcome, _pnl_for(outcome, trade), close_price

    def _broker_can_settle(self, trade: LiveTradeRecord) -> bool:
        """True when there is a real broker order this engine is able to ask about."""
        order_id = trade.broker_order_id
        if not order_id or order_id.startswith("demo-"):
            return False
        return callable(getattr(self._gateway, "get_trade_result", None))

    async def _broker_settlement(self, trade: LiveTradeRecord) -> dict[str, Any] | None:
        """Asks the broker how a trade resolved. None means 'not settled yet'."""
        order_id = trade.broker_order_id
        try:
            result = await self._gateway.get_trade_result(order_id)
        except Exception as exc:
            logger.debug("Broker settlement lookup failed for %s: %s", order_id, exc)
            return None

        # A gateway may answer with anything; only a recognised verdict is allowed
        # to override the local fallback.
        if not isinstance(result, dict):
            return None
        if result.get("result") not in _OUTCOME_BY_BROKER_RESULT:
            return None
        return result

    def _extract_snapshot(self, candles: list[Candle], rsi_period: int = 14) -> IndicatorSnapshot:
        """Extracts technical indicator values at the current candle bar.

        `rsi_period` must match the period the strategy gated on, otherwise the
        logged RSI describes a different indicator than the one that fired and the
        entry cannot be audited afterwards.
        """
        if not candles:
            return IndicatorSnapshot()

        closes = [float(c.close) for c in candles]
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]

        # ADX gates several strategies but was never persisted, so post-trade
        # analysis could not tell whether the trend filter was actually active.
        adx = None
        if len(candles) >= 35:
            try:
                import ta

                frame = pd.DataFrame({"high": highs, "low": lows, "close": closes})
                adx_ind = ta.trend.ADXIndicator(
                    high=frame["high"], low=frame["low"], close=frame["close"], window=14
                )
                adx_value = float(adx_ind.adx().iloc[-1])
                adx = None if pd.isna(adx_value) else adx_value
            except Exception as e:
                logger.debug("ADX snapshot failed: %s", e)

        # Strategies read RSI through `ta` (Wilder smoothing) at their own period.
        # A hand-rolled simple average at a fixed 14 produced a different number,
        # which made 12 of 32 logged entries look like they contradicted their own
        # threshold when in fact only the log was wrong.
        rsi = None
        period = max(2, int(rsi_period))
        if len(closes) >= period + 1:
            try:
                import ta

                rsi_value = float(
                    ta.momentum.RSIIndicator(close=pd.Series(closes), window=period).rsi().iloc[-1]
                )
                rsi = None if pd.isna(rsi_value) else rsi_value
            except Exception as e:
                logger.debug("RSI snapshot failed: %s", e)

        # ATR snapshot
        atr = None
        if len(candles) >= 15:
            trs = [
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
                for i in range(1, len(candles))
            ]
            atr = sum(trs[-14:]) / 14.0

        # Fast and Slow EMA
        ema_fast = closes[-1] if closes else None
        ema_slow = (sum(closes[-21:]) / 21.0) if len(closes) >= 21 else None

        # Stochastic
        stoch_k = None
        if len(candles) >= 14:
            h14 = max(highs[-14:])
            l14 = min(lows[-14:])
            stoch_k = ((closes[-1] - l14) / (h14 - l14) * 100.0) if h14 > l14 else 50.0

        return IndicatorSnapshot(
            rsi=rsi,
            adx=adx,
            atr=atr,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            stoch_k=stoch_k,
            raw_indicators={"close": closes[-1]},
        )
