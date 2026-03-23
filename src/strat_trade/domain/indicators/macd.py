from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module

import pandas as pd

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError
from strat_trade.domain.indicators.types import IndicatorSeries

_MACD_COMPONENTS = {"macd", "signal", "hist"}


class MacdCalculator:
    """MACD powered by `ta`; output length matches input candle count."""

    __slots__ = ("_fast_period", "_signal_period", "_slow_period", "_component")

    def __init__(
        self,
        *,
        fast_period: int,
        slow_period: int,
        signal_period: int,
        component: str,
    ) -> None:
        if fast_period < 2:
            raise IndicatorParameterError("MACD `fast_period` must be >= 2.")
        if slow_period < 2:
            raise IndicatorParameterError("MACD `slow_period` must be >= 2.")
        if signal_period < 2:
            raise IndicatorParameterError("MACD `signal_period` must be >= 2.")
        if fast_period >= slow_period:
            raise IndicatorParameterError("MACD requires `fast_period` < `slow_period`.")
        if component not in _MACD_COMPONENTS:
            raise IndicatorParameterError(
                "MACD `component` must be one of: macd, signal, hist."
            )
        self._fast_period = fast_period
        self._slow_period = slow_period
        self._signal_period = signal_period
        self._component = component

    @property
    def indicator_id(self) -> str:
        return "macd"

    @classmethod
    def from_params(cls, params: Mapping[str, object]) -> MacdCalculator:
        fast_period = _require_int_param(params, "fast_period", default=12)
        slow_period = _require_int_param(params, "slow_period", default=26)
        signal_period = _require_int_param(params, "signal_period", default=9)
        raw_component = params.get("component", "macd")
        if not isinstance(raw_component, str):
            raise IndicatorParameterError("MACD `component` must be a string.")
        component = raw_component.strip().lower()
        return cls(
            fast_period=fast_period,
            slow_period=slow_period,
            signal_period=signal_period,
            component=component,
        )

    def compute(self, candles: list[Candle]) -> IndicatorSeries:
        closes = pd.Series([float(c.close) for c in candles], dtype="float64")
        macd_values = _macd_values(
            closes,
            fast_period=self._fast_period,
            slow_period=self._slow_period,
            signal_period=self._signal_period,
            component=self._component,
        )
        return IndicatorSeries(
            indicator_id=self.indicator_id,
            params={
                "fast_period": self._fast_period,
                "slow_period": self._slow_period,
                "signal_period": self._signal_period,
                "component": self._component,
            },
            values=macd_values,
        )


def _require_int_param(params: Mapping[str, object], name: str, *, default: int) -> int:
    raw = params.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise IndicatorParameterError(f"MACD `{name}` must be an integer.")
    return raw


def _macd_values(
    closes: pd.Series,
    *,
    fast_period: int,
    slow_period: int,
    signal_period: int,
    component: str,
) -> list[float | None]:
    try:
        trend = import_module("ta.trend")
        macd_indicator = trend.MACD  # type: ignore[attr-defined]
    except Exception as exc:
        raise IndicatorParameterError(
            "Technical indicators package `ta` is not available in this environment."
        ) from exc

    calc = macd_indicator(
        close=closes,
        window_fast=fast_period,
        window_slow=slow_period,
        window_sign=signal_period,
    )
    if component == "macd":
        series = calc.macd()
    elif component == "signal":
        series = calc.macd_signal()
    else:
        series = calc.macd_diff()
    return [None if pd.isna(v) else float(v) for v in series.tolist()]
