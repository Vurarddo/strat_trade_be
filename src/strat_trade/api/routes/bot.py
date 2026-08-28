from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter

from strat_trade.api.deps import CandleFeedDep
from strat_trade.api.schemas import (
    AutoAssignRequest,
    BotStatusResponse,
    LiveTradeResponse,
    PauseBotRequest,
    PreTradingPlanResponse,
    StartBotRequest,
    StrategyAssignmentResponse,
)
from strat_trade.domain.trading.entities import PreTradingPlan, StrategyAssignment
from strat_trade.use_cases.auto_assign_strategies import generate_pre_trading_plan
from strat_trade.use_cases.manage_live_bot import (
    clear_live_bot_trades,
    get_live_bot_status,
    get_live_bot_trades,
    pause_live_bot,
    resume_live_bot,
    start_live_bot,
    stop_live_bot,
)

router = APIRouter(prefix="/bot", tags=["Live Demo Bot"])


@router.post("/auto-assign", response_model=PreTradingPlanResponse)
async def auto_assign_strategies_endpoint(
    req: AutoAssignRequest,
    feed: CandleFeedDep,
) -> PreTradingPlanResponse:
    """Evaluates selected assets and generates an optimized pre-trading plan."""
    plan = await generate_pre_trading_plan(
        feed=feed,
        assets=req.assets,
        initial_deposit=req.initial_deposit,
        stake_model=req.stake_model,
        stake_amount=req.stake_amount,
        stake_percent=req.stake_percent,
        expiration_seconds=req.expiration_seconds,
        daily_stop_loss_pct=req.daily_stop_loss_pct,
        daily_take_profit_pct=req.daily_take_profit_pct,
        trailing_profit_lock_enabled=req.trailing_profit_lock_enabled,
        trailing_profit_lock_threshold_usd=req.trailing_profit_lock_threshold_usd,
        trailing_profit_retention_pct=req.trailing_profit_retention_pct,
        per_asset_degradation_guard_enabled=req.per_asset_degradation_guard_enabled,
        per_asset_max_consecutive_losses=req.per_asset_max_consecutive_losses,
        per_asset_min_winrate_pct=req.per_asset_min_winrate_pct,
        max_concurrent_trades=req.max_concurrent_trades,
        min_payout_rate=req.min_payout_rate,
        cooldown_bars=req.cooldown_bars,
        global_cooldown_seconds=req.global_cooldown_seconds,
        max_consecutive_losses=req.max_consecutive_losses,
        max_drawdown_pct_limit=req.max_drawdown_pct_limit,
        correlation_filter_enabled=req.correlation_filter_enabled,
        pause_duration_minutes=req.pause_duration_minutes,
        asset_blacklist=req.asset_blacklist or None,
        toxic_filter_enabled=req.toxic_filter_enabled,
        session_filter_enabled=req.session_filter_enabled,
        allowed_strategies=req.allowed_strategies,
        bar_edge_guard_seconds=req.bar_edge_guard_seconds,
        use_closed_bar_only=req.use_closed_bar_only,
        dynamic_strategy_switching_enabled=req.dynamic_strategy_switching_enabled,
        asset_governor_enabled=req.asset_governor_enabled,
        otc_stake_multiplier=req.otc_stake_multiplier,
        otc_min_payout_rate=req.otc_min_payout_rate,
        governor_min_trades_for_mute=req.governor_min_trades_for_mute,
        governor_mute_duration_minutes=req.governor_mute_duration_minutes,
        governor_promotion_min_trades=req.governor_promotion_min_trades,
    )

    return PreTradingPlanResponse(
        assignments=[
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
            for a in plan.assignments
        ],
        total_assets=plan.total_assets,
        initial_deposit=float(plan.initial_deposit),
        stake_model=plan.stake_model,
        stake_amount=float(plan.stake_amount),
        stake_percent=plan.stake_percent,
        expiration_seconds=plan.expiration_seconds,
        daily_stop_loss_pct=plan.daily_stop_loss_pct,
        stop_loss_amount=float(plan.stop_loss_amount),
        daily_take_profit_pct=plan.daily_take_profit_pct,
        take_profit_amount=float(plan.take_profit_amount),
        trailing_profit_lock_enabled=plan.trailing_profit_lock_enabled,
        trailing_profit_lock_threshold_usd=float(plan.trailing_profit_lock_threshold_usd),
        trailing_profit_retention_pct=plan.trailing_profit_retention_pct,
        per_asset_degradation_guard_enabled=plan.per_asset_degradation_guard_enabled,
        per_asset_max_consecutive_losses=plan.per_asset_max_consecutive_losses,
        per_asset_min_winrate_pct=plan.per_asset_min_winrate_pct,
        max_concurrent_trades=plan.max_concurrent_trades,
        min_payout_rate=plan.min_payout_rate,
        cooldown_bars=plan.cooldown_bars,
        global_cooldown_seconds=plan.global_cooldown_seconds,
        max_consecutive_losses=plan.max_consecutive_losses,
        max_drawdown_pct_limit=plan.max_drawdown_pct_limit,
        correlation_filter_enabled=plan.correlation_filter_enabled,
        pause_duration_minutes=plan.pause_duration_minutes,
        asset_blacklist=plan.asset_blacklist,
        asset_whitelist=plan.asset_whitelist,
        toxic_filter_enabled=plan.toxic_filter_enabled,
        session_filter_enabled=getattr(plan, "session_filter_enabled", True),
        allowed_strategies=req.allowed_strategies,
        bar_edge_guard_seconds=plan.bar_edge_guard_seconds,
        use_closed_bar_only=plan.use_closed_bar_only,
        dynamic_strategy_switching_enabled=plan.dynamic_strategy_switching_enabled,
        asset_governor_enabled=plan.asset_governor_enabled,
        otc_stake_multiplier=plan.otc_stake_multiplier,
        otc_min_payout_rate=plan.otc_min_payout_rate,
        governor_min_trades_for_mute=plan.governor_min_trades_for_mute,
        governor_mute_duration_minutes=plan.governor_mute_duration_minutes,
        governor_promotion_min_trades=plan.governor_promotion_min_trades,
        created_at=plan.created_at.isoformat(),
    )


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
        daily_take_profit_pct=getattr(req.plan, "daily_take_profit_pct", 0.025),
        take_profit_amount=Decimal(str(getattr(req.plan, "take_profit_amount", 1000.0))),
        trailing_profit_lock_enabled=getattr(req.plan, "trailing_profit_lock_enabled", True),
        trailing_profit_lock_threshold_usd=Decimal(
            str(getattr(req.plan, "trailing_profit_lock_threshold_usd", 500.0))
        ),
        trailing_profit_retention_pct=getattr(req.plan, "trailing_profit_retention_pct", 0.75),
        per_asset_degradation_guard_enabled=getattr(
            req.plan, "per_asset_degradation_guard_enabled", True
        ),
        per_asset_max_consecutive_losses=getattr(req.plan, "per_asset_max_consecutive_losses", 2),
        per_asset_min_winrate_pct=getattr(req.plan, "per_asset_min_winrate_pct", 40.0),
        max_concurrent_trades=req.plan.max_concurrent_trades,
        min_payout_rate=req.plan.min_payout_rate,
        cooldown_bars=getattr(req.plan, "cooldown_bars", 3),
        global_cooldown_seconds=getattr(req.plan, "global_cooldown_seconds", 30),
        max_consecutive_losses=getattr(req.plan, "max_consecutive_losses", 3),
        max_drawdown_pct_limit=getattr(req.plan, "max_drawdown_pct_limit", 0.08),
        correlation_filter_enabled=getattr(req.plan, "correlation_filter_enabled", True),
        pause_duration_minutes=getattr(req.plan, "pause_duration_minutes", 15),
        asset_blacklist=getattr(req.plan, "asset_blacklist", []),
        asset_whitelist=getattr(req.plan, "asset_whitelist", []),
        toxic_filter_enabled=getattr(req.plan, "toxic_filter_enabled", True),
        session_filter_enabled=getattr(req.plan, "session_filter_enabled", True),
        allowed_strategies=getattr(req.plan, "allowed_strategies", []),
        bar_edge_guard_seconds=getattr(req.plan, "bar_edge_guard_seconds", 3.0),
        use_closed_bar_only=getattr(req.plan, "use_closed_bar_only", True),
        dynamic_strategy_switching_enabled=getattr(
            req.plan, "dynamic_strategy_switching_enabled", False
        ),
        asset_governor_enabled=getattr(req.plan, "asset_governor_enabled", True),
        otc_stake_multiplier=getattr(req.plan, "otc_stake_multiplier", 0.25),
        otc_min_payout_rate=getattr(req.plan, "otc_min_payout_rate", 0.90),
        governor_min_trades_for_mute=getattr(req.plan, "governor_min_trades_for_mute", 20),
        governor_mute_duration_minutes=getattr(req.plan, "governor_mute_duration_minutes", 240),
        governor_promotion_min_trades=getattr(req.plan, "governor_promotion_min_trades", 400),
    )

    summary = await start_live_bot(plan=plan, gateway=feed)
    return _build_status_response(summary)


@router.post("/stop", response_model=BotStatusResponse)
async def stop_bot_endpoint() -> BotStatusResponse:
    """Stops the active live demo trading session."""
    summary = await stop_live_bot()
    return _build_status_response(summary)


@router.post("/pause", response_model=BotStatusResponse, summary="Pause active trading session")
async def pause_bot_endpoint(req: PauseBotRequest | None = None) -> BotStatusResponse:
    """Pauses active trading bot, preventing new trade entries while active positions settle."""
    duration = req.duration_seconds if req else None
    reason = req.reason if req and req.reason else ""
    summary = await pause_live_bot(duration_seconds=duration, reason=reason)
    return _build_status_response(summary)


@router.post("/resume", response_model=BotStatusResponse, summary="Resume paused trading session")
async def resume_bot_endpoint() -> BotStatusResponse:
    """Resumes trading bot from PAUSED or circuit breaker state."""
    summary = await resume_live_bot()
    return _build_status_response(summary)


@router.get("/status", response_model=BotStatusResponse)
def get_bot_status_endpoint() -> BotStatusResponse:
    """Fetches real-time status and active positions of the trading bot."""
    summary = get_live_bot_status()
    return _build_status_response(summary)


@router.get("/trades", response_model=list[LiveTradeResponse])
def get_bot_trades_endpoint(limit: int = 100, offset: int = 0) -> list[LiveTradeResponse]:
    """Lists recent trades from persistent SQLite store with indicator snapshots."""
    records = get_live_bot_trades(limit=limit, offset=offset)
    return [
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
            indicator_snapshot=t.indicator_snapshot.to_dict(),
            confidence=t.confidence,
            reason=t.reason,
            payout_rate=float(t.payout_rate),
            outcome=t.outcome.value,
            pnl=float(t.pnl),
            balance_after=float(t.balance_after) if t.balance_after is not None else None,
            is_merged_with_broker=t.is_merged_with_broker,
            broker_profit=float(t.broker_profit) if t.broker_profit is not None else None,
            slippage=float(t.slippage) if t.slippage is not None else None,
        )
        for t in records
    ]


@router.post("/clear-trades")
def clear_bot_trades_endpoint() -> dict[str, Any]:
    """Deletes all trade records from the persistent store and engine memory."""
    count = clear_live_bot_trades()
    return {"status": "ok", "cleared_trades": count}


def _build_status_response(s: Any) -> BotStatusResponse:
    status_str = s.status.value if hasattr(s.status, "value") else str(s.status)
    cb_triggered = bool(
        getattr(s, "circuit_breaker_triggered", False) or status_str == "HALTED_BY_CIRCUIT_BREAKER"
    )

    return BotStatusResponse(
        status=status_str,
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
        consecutive_losses=getattr(s, "consecutive_losses", 0),
        peak_balance=float(getattr(s, "peak_balance", s.initial_balance)),
        current_drawdown_pct=float(getattr(s, "current_drawdown_pct", 0.0)),
        paused_until=s.paused_until.isoformat() if getattr(s, "paused_until", None) else None,
        is_paused=bool(getattr(s, "is_paused", False) or status_str == "PAUSED"),
        circuit_breaker_triggered=cb_triggered,
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
