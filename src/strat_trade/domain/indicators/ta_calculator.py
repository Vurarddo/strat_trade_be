from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd
import pandas_ta  # noqa: F401  — registers `DataFrame.ta` accessor

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError
from strat_trade.domain.indicators.ohlcv import candles_to_ohlcv_df
from strat_trade.domain.indicators.types import IndicatorSeries

TaComputeFn = Callable[[pd.DataFrame, dict[str, Any]], pd.Series]


class TaSeriesCalculator:
    """Runs a vectorized pandas-ta (or manual) series aligned 1:1 with OHLCV rows."""

    __slots__ = ("_compute", "_fill_sparse", "_indicator_id", "_params")

    def __init__(
        self,
        indicator_id: str,
        params: dict[str, Any],
        compute: TaComputeFn,
        *,
        fill_sparse: bool,
    ) -> None:
        self._indicator_id = indicator_id
        self._params = params
        self._compute = compute
        self._fill_sparse = fill_sparse

    @property
    def indicator_id(self) -> str:
        return self._indicator_id

    def compute(self, candles: list[Candle]) -> IndicatorSeries:
        df = candles_to_ohlcv_df(candles)
        if df.empty:
            return IndicatorSeries(
                indicator_id=self._indicator_id,
                params=dict(self._params),
                values=[],
            )
        series = self._compute(df, self._params)
        if not isinstance(series, pd.Series):
            msg = f"Internal error: indicator {self._indicator_id!r} did not return a Series."
            raise IndicatorParameterError(msg)
        if len(series) != len(df):
            series = series.reindex(df.index)
        if self._fill_sparse:
            series = series.ffill()
        values: list[float | None] = []
        for v in series.tolist():
            values.append(None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v))
        return IndicatorSeries(
            indicator_id=self._indicator_id,
            params=dict(self._params),
            values=values,
        )


def merge_params(defaults: Mapping[str, Any], params: Mapping[str, object]) -> dict[str, Any]:
    merged: dict[str, Any] = {**dict(defaults), **dict(params)}
    return merged


def require_int(
    name: str,
    value: object,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IndicatorParameterError(f"{name} must be an integer.")
    if minimum is not None and value < minimum:
        raise IndicatorParameterError(f"{name} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise IndicatorParameterError(f"{name} must be <= {maximum}.")
    return value


def optional_int(
    name: str,
    value: object,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if value is None:
        return default
    return require_int(name, value, minimum=minimum, maximum=maximum)


def require_float(name: str, value: object, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IndicatorParameterError(f"{name} must be a number.")
    out = float(value)
    if minimum is not None and out < minimum:
        raise IndicatorParameterError(f"{name} must be >= {minimum}.")
    return out


def optional_float(name: str, value: object, default: float) -> float:
    if value is None:
        return default
    return require_float(name, value)
