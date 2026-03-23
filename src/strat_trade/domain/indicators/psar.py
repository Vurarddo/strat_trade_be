from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module

import pandas as pd

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError
from strat_trade.domain.indicators.types import IndicatorSeries

_PSAR_COMPONENTS = {"sar"}


class PsarCalculator:
    """Parabolic SAR powered by `ta`; output length matches input candle count."""

    __slots__ = ("_step", "_max_step", "_component")

    def __init__(self, *, step: float, max_step: float, component: str) -> None:
        if step <= 0:
            raise IndicatorParameterError("PSAR `step` must be > 0.")
        if max_step <= 0:
            raise IndicatorParameterError("PSAR `max_step` must be > 0.")
        if step > max_step:
            raise IndicatorParameterError("PSAR requires `step` <= `max_step`.")
        if component not in _PSAR_COMPONENTS:
            raise IndicatorParameterError("PSAR `component` must be: sar.")
        self._step = step
        self._max_step = max_step
        self._component = component

    @property
    def indicator_id(self) -> str:
        return "psar"

    @classmethod
    def from_params(cls, params: Mapping[str, object]) -> PsarCalculator:
        step = _require_number_param(params, "step", default=0.02)
        max_step = _require_number_param(params, "max_step", default=0.2)
        raw_component = params.get("component", "sar")
        if not isinstance(raw_component, str):
            raise IndicatorParameterError("PSAR `component` must be a string.")
        component = raw_component.strip().lower()
        return cls(step=step, max_step=max_step, component=component)

    def compute(self, candles: list[Candle]) -> IndicatorSeries:
        highs = pd.Series([float(c.high) for c in candles], dtype="float64")
        lows = pd.Series([float(c.low) for c in candles], dtype="float64")
        closes = pd.Series([float(c.close) for c in candles], dtype="float64")
        psar_values = _psar_values(
            highs,
            lows,
            closes,
            step=self._step,
            max_step=self._max_step,
            component=self._component,
        )
        return IndicatorSeries(
            indicator_id=self.indicator_id,
            params={
                "step": self._step,
                "max_step": self._max_step,
                "component": self._component,
            },
            values=psar_values,
        )


def _require_number_param(params: Mapping[str, object], name: str, *, default: float) -> float:
    raw = params.get(name, default)
    if isinstance(raw, bool):
        raise IndicatorParameterError(f"PSAR `{name}` must be a number.")
    if isinstance(raw, int | float):
        return float(raw)
    raise IndicatorParameterError(f"PSAR `{name}` must be a number.")


def _psar_values(
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    *,
    step: float,
    max_step: float,
    component: str,
) -> list[float | None]:
    try:
        trend = import_module("ta.trend")
        psar_indicator = trend.PSARIndicator  # type: ignore[attr-defined]
    except Exception as exc:
        raise IndicatorParameterError(
            "Technical indicators package `ta` is not available in this environment."
        ) from exc

    calc = psar_indicator(
        high=highs,
        low=lows,
        close=closes,
        step=step,
        max_step=max_step,
    )
    up = calc.psar_up()
    down = calc.psar_down()
    series = up.combine_first(down)
    return [None if pd.isna(v) else float(v) for v in series.tolist()]
