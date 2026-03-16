"""Domain value objects: no framework or I/O."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Balance:
    """Account balance value."""

    value: float


@dataclass(frozen=True)
class Candle:
    """OHLC candle."""

    open: float
    high: float
    low: float
    close: float
    time: int
