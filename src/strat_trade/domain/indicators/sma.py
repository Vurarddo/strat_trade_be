from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module

import pandas as pd

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError
from strat_trade.domain.indicators.types import IndicatorSeries


class SmaCalculator:
    """SMA powered by `ta`; output length matches input candle count."""

    __slots__ = ("_period",)

    def __init__(self, period: int) -> None:
        if period < 2:
            raise IndicatorParameterError("SMA `period` must be >= 2.")
        if period > 1000:
            raise IndicatorParameterError("SMA `period` must be <= 1000.")
        self._period = period

    @property
    def indicator_id(self) -> str:
        return "sma"

    @classmethod
    def from_params(cls, params: Mapping[str, object]) -> SmaCalculator:
        raw = params.get("period", 20)
        if raw is None:
            period = 20
        elif isinstance(raw, bool) or not isinstance(raw, int):
            raise IndicatorParameterError("SMA `period` must be an integer.")
        else:
            period = raw
        return cls(period)

    def compute(self, candles: list[Candle]) -> IndicatorSeries:
        closes = pd.Series([float(c.close) for c in candles], dtype="float64")
        values = _sma_values(closes, self._period)
        return IndicatorSeries(
            indicator_id=self.indicator_id,
            params={"period": self._period},
            values=values,
        )


def _sma_values(closes: pd.Series, period: int) -> list[float | None]:
    try:
        trend = import_module("ta.trend")
        sma_indicator = trend.SMAIndicator  # type: ignore[attr-defined]
    except Exception as exc:
        raise IndicatorParameterError(
            "Technical indicators package `ta` is not available in this environment."
        ) from exc
    series = sma_indicator(close=closes, window=period).sma_indicator()
    return [None if pd.isna(v) else float(v) for v in series.tolist()]
