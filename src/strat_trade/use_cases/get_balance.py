from __future__ import annotations

from strat_trade.domain.entities import AccountBalance
from strat_trade.ports.trading_gateway import TradingGateway


async def fetch_balance(gateway: TradingGateway) -> AccountBalance:
    """Load the live balance from the configured trading gateway."""
    return await gateway.get_balance()
