from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


from pydantic import BaseModel

@dataclass(frozen=True, slots=True)
class Candle:
    """Single OHLC bar in broker-neutral form (open time + prices)."""

    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """Normalized account balance from any broker implementing TradingGateway."""

    amount: Decimal
    currency: str
    is_demo: bool


from strat_trade.domain.trade_record import TradeSignalRecord

class HistoryStats(BaseModel):
    total_trades: int
    total_won_trades: int
    total_loss_trades: int
    total_tied_trades: int

class HistoryResponse(BaseModel):
    stats: HistoryStats
    signals: list[TradeSignalRecord]



