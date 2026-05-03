from __future__ import annotations

from typing import Protocol, runtime_checkable

from strat_trade.domain.entities import Candle
from strat_trade.domain.indicators.types import IndicatorMetadata, IndicatorSeries


@runtime_checkable
class IndicatorCalculator(Protocol):
    """Pure computation over OHLC series; implementations are registered by stable string id."""

    @property
    def indicator_id(self) -> str: ...

    def compute(self, candles: list[Candle]) -> IndicatorSeries:
        """
        Return one value per input candle (use None where the indicator is not yet defined).
        `params` in the result must echo the effective parameters used.
        """
        ...


__all__ = ["IndicatorCalculator", "IndicatorMetadata", "IndicatorSeries"]
