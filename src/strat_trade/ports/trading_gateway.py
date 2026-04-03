from __future__ import annotations

from typing import Any, Protocol

from strat_trade.domain.entities import AccountBalance


class TradingGateway(Protocol):
    """Broker-facing operations used by use cases. Implementations live in adapters."""

    async def get_balance(self) -> AccountBalance:
        """Return the current account balance in the broker's session."""
        ...

    async def aclose(self) -> None:
        """Release connections and other resources held by the gateway."""
        ...

    async def place_trade(
        self, asset: str, direction: str, amount: float, expiration_in_seconds: int
    ) -> dict[str, Any]:
        """
        Places a trade on the broker platform.
        Must return a dict containing at least:
        - "success": bool
        - "trade_id": str (if successful)
        - "strike_price": float (the exact entry price on the broker)
        """
        ...

    async def get_available_assets(self) -> list[dict[str, Any]]:
        """Return a list of available assets and their full data from the broker."""
        ...

