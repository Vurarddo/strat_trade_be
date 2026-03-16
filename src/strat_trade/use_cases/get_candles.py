"""Get candles use case."""

from strat_trade.domain.entities import Candle
from strat_trade.ports.trading_gateway import TradingGateway


async def get_candles(
    gateway: TradingGateway,
    asset: str,
    period: int,
    limit: int = 100,
) -> list[Candle]:
    """Return historical OHLC candles for asset and period (seconds)."""
    return await gateway.candles(asset=asset, period=period, limit=limit)
