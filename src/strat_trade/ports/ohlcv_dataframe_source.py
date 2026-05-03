from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import pandas as pd


@runtime_checkable
class OhlcvDataFrameSource(Protocol):
    """Synchronous historical OHLCV as a normalized columnar frame (adapters implement)."""

    def get_historical_ohlcv(
        self,
        ticker: str,
        exchange: str,
        interval: str,
        n_bars: int,
    ) -> pd.DataFrame:
        """Return a frame with lowercase columns; oldest row first; plain RangeIndex."""
        ...
