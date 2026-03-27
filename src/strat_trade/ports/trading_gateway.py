from __future__ import annotations

from typing import Protocol

from strat_trade.domain.entities import AccountBalance, BrokerAsset


class TradingGateway(Protocol):
    """Broker-facing operations used by use cases. Implementations live in adapters."""

    async def get_balance(self) -> AccountBalance:
        """Return the current account balance in the broker's session."""
        ...

    async def list_assets(self) -> list[BrokerAsset]:
        """Return the broker's asset catalog (see each row's ``is_active`` for tradability)."""
        ...

    async def aclose(self) -> None:
        """Release connections and other resources held by the gateway."""
        ...
