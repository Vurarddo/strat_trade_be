from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from strat_trade.domain.entities import Candle


@runtime_checkable
class IndicatorCalculator(Protocol):
    """Pure computation over OHLC series; implementations are registered by stable string id."""

    @property
    def indicator_id(self) -> str: ...

    def compute(self, candles: Sequence[Candle]) -> dict[str, list[float | None]]:
        """Named output series, each list aligned 1:1 with `candles` (leading Nones until warmup)."""
        ...
