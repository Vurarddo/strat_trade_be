"""Get account balance use case."""

from strat_trade.domain.entities import Balance
from strat_trade.ports.trading_gateway import TradingGateway


async def get_balance(gateway: TradingGateway) -> Balance:
    """Return current balance from the given gateway."""
    return await gateway.balance()
