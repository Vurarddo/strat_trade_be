from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class StakeModel(StrEnum):
    FLAT = "flat"
    PERCENT = "percent"
    MARTINGALE = "martingale"


class TradeAction(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


class TradeOutcome(StrEnum):
    WIN = "WIN"
    LOSS = "LOSS"
    DRAW = "DRAW"


@dataclass(frozen=True)
class BacktestConfig:
    asset: str
    timeframe_seconds: int
    initial_deposit: Decimal = Decimal("1000.0")
    stake_model: StakeModel = StakeModel.FLAT
    stake_amount: Decimal = Decimal("10.0")
    stake_percent: Decimal = Decimal("1.0")  # used if StakeModel.PERCENT
    martingale_multiplier: Decimal = Decimal("2.0")  # used if StakeModel.MARTINGALE
    martingale_max_steps: int = 2
    payout_rate: Decimal = Decimal("0.85")  # e.g. 0.85 = 85%
    min_payout_rate: Decimal = Decimal("0.80")  # Minimum required payout filter
    expiration_bars: int = 3  # e.g. 3 bars on 60s timeframe = 180s
    adaptive_expiration: bool = False
    daily_stop_loss_pct: Decimal = Decimal("0.05")  # 5% max daily drawdown
    strategy_name: str = "hybrid_multifactors"
    strategy_params: dict[str, Any] = field(default_factory=dict)
    expiration_seconds: int | None = None


@dataclass
class BacktestTrade:
    entry_index: int
    exit_index: int
    entry_time: datetime
    exit_time: datetime
    action: TradeAction
    entry_price: Decimal
    exit_price: Decimal
    stake: Decimal
    payout_rate: Decimal
    pnl: Decimal
    outcome: TradeOutcome
    balance_after: Decimal
    confidence: float
    expiration_seconds: int
    asset: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EquityPoint:
    timestamp: datetime
    balance: Decimal
    drawdown_pct: Decimal


@dataclass
class BacktestSummary:
    asset: str
    timeframe_seconds: int
    initial_deposit: Decimal
    final_balance: Decimal
    net_profit: Decimal
    roi_pct: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    win_rate_pct: Decimal
    profit_factor: Decimal
    max_drawdown_amount: Decimal
    max_drawdown_pct: Decimal
    max_consecutive_wins: int
    max_consecutive_losses: int
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    strategy_name: str = "hybrid_multifactors"


@dataclass
class AssetPerformance:
    asset: str
    name: str
    payout_rate: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    win_rate_pct: Decimal
    net_profit: Decimal
    roi_pct: Decimal
    profit_factor: Decimal
    max_drawdown_amount: Decimal
    max_drawdown_pct: Decimal
    trades_count_pct: Decimal = Decimal("0.0")


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
    cooldown_bars: int = 0
    global_cooldown_seconds: int = 0
    correlation_filter_enabled: bool = False
    max_consecutive_losses: int = 0
    max_drawdown_pct_limit: Decimal = Decimal("0.08")
    strategy_name: str = "hybrid_multifactors"
    strategy_params: dict[str, Any] = field(default_factory=dict)
    expiration_seconds: int | None = None


@dataclass
class PortfolioBacktestSummary:
    assets: list[str]
    timeframe_seconds: int
    initial_deposit: Decimal
    final_balance: Decimal
    net_profit: Decimal
    roi_pct: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    win_rate_pct: Decimal
    profit_factor: Decimal
    max_drawdown_amount: Decimal
    max_drawdown_pct: Decimal
    max_consecutive_wins: int
    max_consecutive_losses: int
    per_asset_stats: list[AssetPerformance] = field(default_factory=list)
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    strategy_name: str = "hybrid_multifactors"
