from __future__ import annotations

from datetime import datetime
from typing import Protocol

from strat_trade.domain.entities import Candle


class CandleFeed(Protocol):
    """Historical OHLCV series from a broker or other market-data source."""

    async def get_candles(
        self,
        asset: str,
        timeframe: int | str,
        *,
        count: int,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        """Return up to `count` candles ending at `end_time` (or now)."""
        ...
