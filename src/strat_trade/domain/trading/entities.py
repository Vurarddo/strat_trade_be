from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class BotStatus(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    HALTED_BY_STOP_LOSS = "HALTED_BY_STOP_LOSS"
    HALTED_BY_CIRCUIT_BREAKER = "HALTED_BY_CIRCUIT_BREAKER"
    HALTED_BY_TAKE_PROFIT = "HALTED_BY_TAKE_PROFIT"
    HALTED_BY_TRAILING_PROFIT_LOCK = "HALTED_BY_TRAILING_PROFIT_LOCK"


class TradeOutcome(StrEnum):
    PENDING = "PENDING"
    WIN = "WIN"
    LOSS = "LOSS"
    DRAW = "DRAW"


@dataclass
class IndicatorSnapshot:
    """Snapshot of technical indicators at the precise moment of signal generation."""

    rsi: float | None = None
    adx: float | None = None
    atr: float | None = None
    stoch_k: float | None = None
    stoch_d: float | None = None
    bb_upper: float | None = None
    bb_lower: float | None = None
    bb_middle: float | None = None
    ema_fast: float | None = None
    ema_slow: float | None = None
    raw_indicators: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rsi": round(self.rsi, 2) if self.rsi is not None else None,
            "adx": round(self.adx, 2) if self.adx is not None else None,
            "atr": round(self.atr, 6) if self.atr is not None else None,
            "stoch_k": round(self.stoch_k, 2) if self.stoch_k is not None else None,
            "stoch_d": round(self.stoch_d, 2) if self.stoch_d is not None else None,
            "bb_upper": round(self.bb_upper, 5) if self.bb_upper is not None else None,
            "bb_lower": round(self.bb_lower, 5) if self.bb_lower is not None else None,
            "bb_middle": round(self.bb_middle, 5) if self.bb_middle is not None else None,
            "ema_fast": round(self.ema_fast, 5) if self.ema_fast is not None else None,
            "ema_slow": round(self.ema_slow, 5) if self.ema_slow is not None else None,
            "raw_indicators": self.raw_indicators,
        }


@dataclass
class StrategyAssignment:
    """Optimal strategy assigned to an asset after automated quantum profiling."""

    asset: str
    strategy_id: str
    strategy_name: str
    category: str
    parameters: dict[str, Any]
    estimated_win_rate_pct: float
    estimated_profit_factor: float
    estimated_trades_count: int
    quantum_score: float
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "category": self.category,
            "parameters": self.parameters,
            "estimated_win_rate_pct": round(self.estimated_win_rate_pct, 2),
            "estimated_profit_factor": round(self.estimated_profit_factor, 2),
            "estimated_trades_count": self.estimated_trades_count,
            "quantum_score": round(self.quantum_score, 2),
            "rationale": self.rationale,
        }


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
    daily_take_profit_pct: float = 0.025
    take_profit_amount: Decimal = Decimal("1000.00")
    trailing_profit_lock_enabled: bool = True
    trailing_profit_lock_threshold_usd: Decimal = Decimal("500.00")
    trailing_profit_retention_pct: float = 0.75
    per_asset_degradation_guard_enabled: bool = True
    per_asset_max_consecutive_losses: int = 2
    per_asset_min_winrate_pct: float = 40.0
    max_concurrent_trades: int = 3
    min_payout_rate: float = 0.80
    cooldown_bars: int = 3
    global_cooldown_seconds: int = 30
    max_consecutive_losses: int = 3
    max_drawdown_pct_limit: float = 0.08
    correlation_filter_enabled: bool = True
    pause_duration_minutes: int = 15
    asset_blacklist: list[str] = field(default_factory=list)
    asset_whitelist: list[str] = field(default_factory=list)
    toxic_filter_enabled: bool = True
    session_filter_enabled: bool = True
    allowed_strategies: list[str] = field(default_factory=list)
    # Entry-timing gates (see domain/trading/execution_gates.py)
    bar_edge_guard_seconds: float = 3.0
    use_closed_bar_only: bool = True
    # Strategy integrity: when False the asset trades exactly the strategy the
    # optimiser assigned to it, so live results stay comparable to the backtest.
    dynamic_strategy_switching_enabled: bool = False
    # Statistical per-asset governor (see domain/trading/asset_governor.py)
    asset_governor_enabled: bool = True
    otc_stake_multiplier: float = 0.25
    otc_min_payout_rate: float = 0.90
    governor_min_trades_for_mute: int = 20
    governor_mute_duration_minutes: int = 240
    governor_promotion_min_trades: int = 400
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
            "daily_take_profit_pct": round(self.daily_take_profit_pct * 100.0, 2),
            "take_profit_amount": float(self.take_profit_amount),
            "trailing_profit_lock_enabled": self.trailing_profit_lock_enabled,
            "trailing_profit_lock_threshold_usd": float(self.trailing_profit_lock_threshold_usd),
            "trailing_profit_retention_pct": round(self.trailing_profit_retention_pct * 100.0, 2),
            "per_asset_degradation_guard_enabled": self.per_asset_degradation_guard_enabled,
            "per_asset_max_consecutive_losses": self.per_asset_max_consecutive_losses,
            "per_asset_min_winrate_pct": self.per_asset_min_winrate_pct,
            "max_concurrent_trades": self.max_concurrent_trades,
            "min_payout_rate": self.min_payout_rate,
            "cooldown_bars": self.cooldown_bars,
            "global_cooldown_seconds": self.global_cooldown_seconds,
            "max_consecutive_losses": self.max_consecutive_losses,
            "max_drawdown_pct_limit": self.max_drawdown_pct_limit,
            "correlation_filter_enabled": self.correlation_filter_enabled,
            "pause_duration_minutes": self.pause_duration_minutes,
            "asset_blacklist": self.asset_blacklist,
            "asset_whitelist": self.asset_whitelist,
            "toxic_filter_enabled": self.toxic_filter_enabled,
            "session_filter_enabled": self.session_filter_enabled,
            "allowed_strategies": self.allowed_strategies,
            "bar_edge_guard_seconds": self.bar_edge_guard_seconds,
            "use_closed_bar_only": self.use_closed_bar_only,
            "dynamic_strategy_switching_enabled": self.dynamic_strategy_switching_enabled,
            "asset_governor_enabled": self.asset_governor_enabled,
            "otc_stake_multiplier": self.otc_stake_multiplier,
            "otc_min_payout_rate": self.otc_min_payout_rate,
            "governor_min_trades_for_mute": self.governor_min_trades_for_mute,
            "governor_mute_duration_minutes": self.governor_mute_duration_minutes,
            "governor_promotion_min_trades": self.governor_promotion_min_trades,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class LiveTradeRecord:
    """Telemetry record of a live / demo trade persisted in SQLite."""

    trade_id: str
    asset: str
    action: str  # "CALL" or "PUT"
    stake: Decimal
    open_time: datetime
    expiration_seconds: int
    open_price: Decimal
    strategy_id: str
    strategy_name: str
    strategy_params: dict[str, Any]
    indicator_snapshot: IndicatorSnapshot
    confidence: float
    reason: str
    payout_rate: Decimal
    broker_order_id: str | None = (
        None  # UUID from Pocket Option (e.g. e384a8f6-c371-4b8f-916a-112ae0a60456)
    )
    close_time: datetime | None = None
    close_price: Decimal | None = None
    outcome: TradeOutcome = TradeOutcome.PENDING
    pnl: Decimal = Decimal("0.00")
    balance_after: Decimal | None = None
    is_merged_with_broker: bool = False
    broker_profit: Decimal | None = None
    slippage: Decimal | None = None
    # Execution forensics: without these, a losing week cannot be attributed to
    # a cause. `executed_params` is what the strategy actually ran with, which
    # may differ from `strategy_params` when the regime detector substitutes.
    executed_params: dict[str, Any] = field(default_factory=dict)
    asset_tier: str = "NORMAL"
    stake_multiplier: float = 1.0
    entry_second: int = 0
    is_otc: bool = False
    # The candle feed only serves closed bars, so a candle-derived price can be a
    # full bar stale. These record whether the broker answered, so a session can be
    # audited without guessing which prices were authoritative.
    open_price_source: str = "candle"
    settlement_source: str = "candle"


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
    circuit_breaker_triggered: bool = False
    active_assignments: list[StrategyAssignment] = field(default_factory=list)
    recent_trades: list[LiveTradeRecord] = field(default_factory=list)


@dataclass
class BrokerTradeRow:
    """Row parsed directly from Pocket Option exported XLS/CSV report."""

    direction: str  # "call" or "put"
    order_id: str  # e384a8f6-c371-4b8f-916a-112ae0a60456
    expiration: str  # e.g. "S3", "M1", "M3"
    asset: str  # e.g. "USD/CHF OTC"
    open_time: datetime
    close_time: datetime
    open_price: Decimal
    close_price: Decimal
    trade_amount: Decimal
    profit: Decimal  # e.g. 9.2
    currency: str  # "USD"


@dataclass
class MergedAuditRecord:
    """Merged trade record joining broker official record with bot internal telemetry."""

    order_id: str
    asset: str
    direction: str
    open_time: datetime
    close_time: datetime
    broker_open_price: Decimal
    broker_close_price: Decimal
    trade_amount: Decimal
    broker_profit: Decimal
    outcome: str  # "WIN", "LOSS", "DRAW"
    # Internal Bot Telemetry (if matched)
    is_bot_trade: bool
    strategy_id: str | None = None
    strategy_name: str | None = None
    strategy_params: dict[str, Any] = field(default_factory=dict)
    indicator_snapshot: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    reason: str | None = None
    internal_open_price: Decimal | None = None
    slippage: Decimal | None = None
    entry_second: int | None = None
    open_price_source: str | None = None
    settlement_source: str | None = None
