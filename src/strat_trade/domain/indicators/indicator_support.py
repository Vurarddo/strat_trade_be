"""Shared helpers and registration glue for pandas-ta indicator category modules."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

import numpy as np
import pandas as pd
import pandas_ta as pta

from strat_trade.domain.errors import IndicatorParameterError
from strat_trade.domain.indicators.registry import IndicatorRegistry
from strat_trade.domain.indicators.ta_calculator import TaSeriesCalculator
from strat_trade.domain.indicators.types import IndicatorMetadata

TaRun = Callable[[pd.DataFrame, dict[str, Any]], pd.Series]


def register_indicator(
    reg: IndicatorRegistry,
    meta: IndicatorMetadata,
    build: Any,
) -> None:
    def factory(params: Mapping[str, object]) -> TaSeriesCalculator:
        merged, run = build(params)
        return TaSeriesCalculator(meta.id, merged, run, fill_sparse=meta.fill_sparse)

    reg.register(meta, factory)


def first_col(frame: pd.DataFrame, prefix: str) -> pd.Series:
    for c in frame.columns:
        if str(c).startswith(prefix):
            sel = frame[c]
            if isinstance(sel, pd.DataFrame):
                msg = (
                    f"Ambiguous column match for prefix {prefix!r}: "
                    f"got a DataFrame (duplicate labels?). Columns: {list(frame.columns)}."
                )
                raise ValueError(msg)
            return cast(pd.Series, sel)
    msg = f"No column starting with {prefix!r} in {list(frame.columns)}."
    raise ValueError(msg)


def series(df: pd.DataFrame, name: str) -> pd.Series:
    """One OHLCV column as ``Series`` (stubs type ``DataFrame.__getitem__`` as union)."""
    s = df[name]
    if isinstance(s, pd.DataFrame):
        raise IndicatorParameterError(f"Expected one column {name!r}, got an ambiguous selection.")
    return cast(pd.Series, s)


def demarker(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    length = int(p["length"])
    hi = series(df, "high")
    lo = series(df, "low")
    hh = hi.diff().clip(lower=0.0)
    ll = (-lo.diff()).clip(lower=0.0)
    demax = hh.rolling(length, min_periods=length).mean()
    demin = ll.rolling(length, min_periods=length).mean()
    ratio = demax / (demax + demin)
    return cast(pd.Series, ratio).reindex(df.index)


def accelerator(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    fast, slow = int(p["fast"]), int(p["slow"])
    ao = pta.ao(high=series(df, "high"), low=series(df, "low"), fast=fast, slow=slow)
    return (ao - ao.rolling(5, min_periods=5).mean()).reindex(df.index)


def envelopes_upper(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    length, pct = int(p["length"]), float(p["percent"])
    kind = str(p["kind"]).lower()
    close = series(df, "close")
    if kind == "sma":
        mid = df.ta.sma(length=length, close=close)
    elif kind == "ema":
        mid = df.ta.ema(length=length, close=close)
    elif kind == "wma":
        mid = df.ta.wma(length=length, close=close)
    else:
        raise IndicatorParameterError("envelopes `kind` must be sma, ema, or wma.")
    return (mid * (1.0 + pct / 100.0)).reindex(df.index)


def bulls_power(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    length = int(p["length"])
    ema_c = df.ta.ema(length=length, close=series(df, "close"))
    return (series(df, "high") - ema_c).reindex(df.index)


def bears_power(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    length = int(p["length"])
    ema_c = df.ta.ema(length=length, close=series(df, "close"))
    return (series(df, "low") - ema_c).reindex(df.index)


def williams_fractals_up(df: pd.DataFrame) -> pd.Series:
    h = series(df, "high")
    a, b, c, d, e = h.shift(2), h.shift(1), h, h.shift(-1), h.shift(-2)
    mask = (c > a) & (c > b) & (c > d) & (c > e)
    return pd.Series(np.where(mask, c, np.nan), index=df.index, dtype="float64")


def williams_fractals_down(df: pd.DataFrame) -> pd.Series:
    lo = series(df, "low")
    a, b, c, d, e = lo.shift(2), lo.shift(1), lo, lo.shift(-1), lo.shift(-2)
    mask = (c < a) & (c < b) & (c < d) & (c < e)
    return pd.Series(np.where(mask, c, np.nan), index=df.index, dtype="float64")


def fractal_mid(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    _ = p
    up, dn = williams_fractals_up(df), williams_fractals_down(df)
    return pd.concat([up, dn], axis=1).mean(axis=1).reindex(df.index)


def fcb_mid(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    window = int(p["window"])
    up = williams_fractals_up(df).ffill()
    dn = williams_fractals_down(df).ffill()
    upper = up.rolling(window, min_periods=1).max()
    lower = dn.rolling(window, min_periods=1).min()
    return ((upper + lower) / 2.0).reindex(df.index)
