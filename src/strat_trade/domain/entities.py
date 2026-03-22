from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """Normalized account balance from any broker implementing TradingGateway."""

    amount: Decimal
    currency: str
    is_demo: bool
