from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module

import pandas as pd

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError
from strat_trade.domain.indicators.types import IndicatorSeries

_STOCH_COMPONENTS = {"k", "d"}


class StochasticCalculator:
    """Stochastic Oscillator powered by `ta`; output length matches input candle count."""

    __slots__ = ("_component", "_period", "_smooth_window")

    def __init__(self, *, period: int, smooth_window: int, component: str) -> None:
        if period < 2:
            raise IndicatorParameterError("Stochastic `period` must be >= 2.")
        if period > 1000:
            raise IndicatorParameterError("Stochastic `period` must be <= 1000.")
        if smooth_window < 1:
            raise IndicatorParameterError("Stochastic `smooth_window` must be >= 1.")
        if smooth_window > 1000:
            raise IndicatorParameterError("Stochastic `smooth_window` must be <= 1000.")
        if component not in _STOCH_COMPONENTS:
            raise IndicatorParameterError("Stochastic `component` must be one of: k, d.")
        self._period = period
        self._smooth_window = smooth_window
        self._component = component

    @property
    def indicator_id(self) -> str:
        return "stochastic"

    @classmethod
    def from_params(cls, params: Mapping[str, object]) -> StochasticCalculator:
        period = _require_int_param(params, "period", default=14)
        smooth_window = _require_int_param(params, "smooth_window", default=3)
        raw_component = params.get("component", "k")
        if not isinstance(raw_component, str):
            raise IndicatorParameterError("Stochastic `component` must be a string.")
        component = raw_component.strip().lower()
        return cls(period=period, smooth_window=smooth_window, component=component)

    def compute(self, candles: list[Candle]) -> IndicatorSeries:
        highs = pd.Series([float(c.high) for c in candles], dtype="float64")
        lows = pd.Series([float(c.low) for c in candles], dtype="float64")
        closes = pd.Series([float(c.close) for c in candles], dtype="float64")
        values = _stochastic_values(
            highs,
            lows,
            closes,
            period=self._period,
            smooth_window=self._smooth_window,
            component=self._component,
        )
        return IndicatorSeries(
            indicator_id=self.indicator_id,
            params={
                "period": self._period,
                "smooth_window": self._smooth_window,
                "component": self._component,
            },
            values=values,
        )


def _require_int_param(params: Mapping[str, object], name: str, *, default: int) -> int:
    raw = params.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise IndicatorParameterError(f"Stochastic `{name}` must be an integer.")
    return raw


def _stochastic_values(
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    *,
    period: int,
    smooth_window: int,
    component: str,
) -> list[float | None]:
    try:
        momentum = import_module("ta.momentum")
        stochastic_oscillator = momentum.StochasticOscillator  # type: ignore[attr-defined]
    except Exception as exc:
        raise IndicatorParameterError(
            "Technical indicators package `ta` is not available in this environment."
        ) from exc

    calc = stochastic_oscillator(
        high=highs,
        low=lows,
        close=closes,
        window=period,
        smooth_window=smooth_window,
    )
    series = calc.stoch() if component == "k" else calc.stoch_signal()
    return [None if pd.isna(v) else float(v) for v in series.tolist()]
