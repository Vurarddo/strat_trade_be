"""Abstract trading/market gateway (port)."""

from abc import ABC, abstractmethod

from strat_trade.domain.entities import Balance, Candle


class TradingGateway(ABC):
    """Port: get balance and candles. Implemented by adapters."""

    @abstractmethod
    async def balance(self) -> Balance:
        """Return current account balance."""
        ...

    @abstractmethod
    async def candles(self, asset: str, period: int, limit: int = 100) -> list[Candle]:
        """Return historical OHLC candles for asset and period (seconds)."""
        ...
