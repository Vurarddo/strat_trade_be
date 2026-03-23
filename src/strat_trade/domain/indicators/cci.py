from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module

import pandas as pd

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError
from strat_trade.domain.indicators.types import IndicatorSeries


class CciCalculator:
    """CCI powered by `ta`; output length matches input candle count."""

    __slots__ = ("_constant", "_period")

    def __init__(self, *, period: int, constant: float) -> None:
        if period < 2:
            raise IndicatorParameterError("CCI `period` must be >= 2.")
        if period > 1000:
            raise IndicatorParameterError("CCI `period` must be <= 1000.")
        if constant <= 0:
            raise IndicatorParameterError("CCI `constant` must be > 0.")
        self._period = period
        self._constant = constant

    @property
    def indicator_id(self) -> str:
        return "cci"

    @classmethod
    def from_params(cls, params: Mapping[str, object]) -> CciCalculator:
        period = _require_int_param(params, "period", default=20)
        constant = _require_number_param(params, "constant", default=0.015)
        return cls(period=period, constant=constant)

    def compute(self, candles: list[Candle]) -> IndicatorSeries:
        highs = pd.Series([float(c.high) for c in candles], dtype="float64")
        lows = pd.Series([float(c.low) for c in candles], dtype="float64")
        closes = pd.Series([float(c.close) for c in candles], dtype="float64")
        values = _cci_values(highs, lows, closes, period=self._period, constant=self._constant)
        return IndicatorSeries(
            indicator_id=self.indicator_id,
            params={"period": self._period, "constant": self._constant},
            values=values,
        )


def _require_int_param(params: Mapping[str, object], name: str, *, default: int) -> int:
    raw = params.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise IndicatorParameterError(f"CCI `{name}` must be an integer.")
    return raw


def _require_number_param(params: Mapping[str, object], name: str, *, default: float) -> float:
    raw = params.get(name, default)
    if isinstance(raw, bool):
        raise IndicatorParameterError(f"CCI `{name}` must be a number.")
    if isinstance(raw, int | float):
        return float(raw)
    raise IndicatorParameterError(f"CCI `{name}` must be a number.")


def _cci_values(
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    *,
    period: int,
    constant: float,
) -> list[float | None]:
    try:
        trend = import_module("ta.trend")
        cci_indicator = trend.CCIIndicator  # type: ignore[attr-defined]
    except Exception as exc:
        raise IndicatorParameterError(
            "Technical indicators package `ta` is not available in this environment."
        ) from exc

    series = cci_indicator(
        high=highs,
        low=lows,
        close=closes,
        window=period,
        constant=constant,
    ).cci()
    return [None if pd.isna(v) else float(v) for v in series.tolist()]
