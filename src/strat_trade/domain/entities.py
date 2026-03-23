from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


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
