from __future__ import annotations

from typing import Protocol

from strat_trade.domain.entities import AccountBalance


class TradingGateway(Protocol):
    """Broker-facing operations used by use cases. Implementations live in adapters."""

    async def get_balance(self) -> AccountBalance:
        """Return the current account balance in the broker's session."""
        ...

    async def aclose(self) -> None:
        """Release connections and other resources held by the gateway."""
        ...

    async def place_trade(self, asset: str, direction: str, amount: float, expiration_in_seconds: int) -> bool:
        """Places a trade on the broker platform. Returns True if successful."""
        ...

