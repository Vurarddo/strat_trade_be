from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module

import pandas as pd

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError
from strat_trade.domain.indicators.types import IndicatorSeries


class RsiCalculator:
    """RSI powered by `ta`; output length matches input candle count."""

    __slots__ = ("_period",)

    def __init__(self, period: int) -> None:
        if period < 2:
            raise IndicatorParameterError("RSI `period` must be >= 2.")
        if period > 1000:
            raise IndicatorParameterError("RSI `period` must be <= 1000.")
        self._period = period

    @property
    def indicator_id(self) -> str:
        return "rsi"

    @classmethod
    def from_params(cls, params: Mapping[str, object]) -> RsiCalculator:
        raw = params.get("period", 14)
        if raw is None:
            period = 14
        elif isinstance(raw, bool):
            raise IndicatorParameterError("RSI `period` must be an integer.")
        elif isinstance(raw, int):
            period = raw
        else:
            raise IndicatorParameterError("RSI `period` must be an integer.")
        return cls(period)

    def compute(self, candles: list[Candle]) -> IndicatorSeries:
        closes = [float(c.close) for c in candles]
        values = _rsi_values(closes, self._period)
        return IndicatorSeries(
            indicator_id=self.indicator_id,
            params={"period": self._period},
            values=values,
        )


def _rsi_values(closes: list[float], period: int) -> list[float | None]:
    series = pd.Series(closes, dtype="float64")
    try:
        momentum = import_module("ta.momentum")
        rsi_indicator = momentum.RSIIndicator  # type: ignore[attr-defined]
    except Exception as exc:
        raise IndicatorParameterError(
            "Technical indicators package `ta` is not available in this environment."
        ) from exc
    rsi = rsi_indicator(close=series, window=period).rsi()
    return [None if pd.isna(v) else float(v) for v in rsi.tolist()]
