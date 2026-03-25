from __future__ import annotations

from strat_trade.domain.entities import BrokerAsset
from strat_trade.ports.trading_gateway import TradingGateway


async def fetch_assets(
    gateway: TradingGateway,
    *,
    active_only: bool = False,
) -> list[BrokerAsset]:
    """Load the broker asset catalog; optionally keep only rows with ``is_active``."""
    rows = await gateway.list_assets()
    if not active_only:
        return rows
    return [a for a in rows if a.is_active]
