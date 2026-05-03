"""Pocket Option–style indicator catalog: pandas-ta + small vectorized fallbacks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

import numpy as np
import pandas as pd
import pandas_ta as pta

from strat_trade.domain.errors import IndicatorParameterError
from strat_trade.domain.indicators.registry import IndicatorRegistry
from strat_trade.domain.indicators.ta_calculator import (
    TaSeriesCalculator,
    merge_params,
    optional_float,
    optional_int,
    require_float,
)
from strat_trade.domain.indicators.types import IndicatorCategory, IndicatorMetadata

TaRun = Callable[[pd.DataFrame, dict[str, Any]], pd.Series]


def _reg(
    reg: IndicatorRegistry,
    meta: IndicatorMetadata,
    build: Any,
) -> None:
    def factory(params: Mapping[str, object]) -> TaSeriesCalculator:
        merged, run = build(params)
        return TaSeriesCalculator(meta.id, merged, run, fill_sparse=meta.fill_sparse)

    reg.register(meta, factory)


def _first_col(frame: pd.DataFrame, prefix: str) -> pd.Series:
    for c in frame.columns:
        if str(c).startswith(prefix):
            sel = frame[c]
            if isinstance(sel, pd.DataFrame):
                msg = (
                    f"Ambiguous column match for prefix {prefix!r}: "
                    f"got a DataFrame (duplicate labels?). Columns: {list(frame.columns)}."
                )
                raise ValueError(msg)
            # pandas stubs: __getitem__ is Series | DataFrame; duplicates are ruled out above.
            return cast(pd.Series, sel)
    msg = f"No column starting with {prefix!r} in {list(frame.columns)}."
    raise ValueError(msg)


def _series(df: pd.DataFrame, name: str) -> pd.Series:
    """One OHLCV column as ``Series`` (stubs type ``DataFrame.__getitem__`` as union)."""
    s = df[name]
    if isinstance(s, pd.DataFrame):
        raise IndicatorParameterError(f"Expected one column {name!r}, got an ambiguous selection.")
    return cast(pd.Series, s)


def _demarker(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    length = int(p["length"])
    hi = _series(df, "high")
    lo = _series(df, "low")
    hh = hi.diff().clip(lower=0.0)
    ll = (-lo.diff()).clip(lower=0.0)
    demax = hh.rolling(length, min_periods=length).mean()
    demin = ll.rolling(length, min_periods=length).mean()
    ratio = demax / (demax + demin)
    return cast(pd.Series, ratio).reindex(df.index)


def _accelerator(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    fast, slow = int(p["fast"]), int(p["slow"])
    ao = pta.ao(high=_series(df, "high"), low=_series(df, "low"), fast=fast, slow=slow)
    return (ao - ao.rolling(5, min_periods=5).mean()).reindex(df.index)


def _envelopes_upper(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    length, pct = int(p["length"]), float(p["percent"])
    kind = str(p["kind"]).lower()
    if kind == "sma":
        mid = df.ta.sma(length=length, close=df["close"])
    elif kind == "ema":
        mid = df.ta.ema(length=length, close=df["close"])
    elif kind == "wma":
        mid = df.ta.wma(length=length, close=df["close"])
    else:
        raise IndicatorParameterError("envelopes `kind` must be sma, ema, or wma.")
    return (mid * (1.0 + pct / 100.0)).reindex(df.index)


def _bulls_power(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    length = int(p["length"])
    ema_c = df.ta.ema(length=length, close=df["close"])
    return (df["high"] - ema_c).reindex(df.index)


def _bears_power(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    length = int(p["length"])
    ema_c = df.ta.ema(length=length, close=df["close"])
    return (df["low"] - ema_c).reindex(df.index)


def _williams_fractals_up(df: pd.DataFrame) -> pd.Series:
    h = df["high"]
    a, b, c, d, e = h.shift(2), h.shift(1), h, h.shift(-1), h.shift(-2)
    mask = (c > a) & (c > b) & (c > d) & (c > e)
    return pd.Series(np.where(mask, c, np.nan), index=df.index, dtype="float64")


def _williams_fractals_down(df: pd.DataFrame) -> pd.Series:
    lo = df["low"]
    a, b, c, d, e = lo.shift(2), lo.shift(1), lo, lo.shift(-1), lo.shift(-2)
    mask = (c < a) & (c < b) & (c < d) & (c < e)
    return pd.Series(np.where(mask, c, np.nan), index=df.index, dtype="float64")


def _fractal_mid(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    _ = p
    up, dn = _williams_fractals_up(df), _williams_fractals_down(df)
    return pd.concat([up, dn], axis=1).mean(axis=1).reindex(df.index)


def _fcb_mid(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    window = int(p["window"])
    up = _williams_fractals_up(df).ffill()
    dn = _williams_fractals_down(df).ffill()
    upper = up.rolling(window, min_periods=1).max()
    lower = dn.rolling(window, min_periods=1).min()
    return ((upper + lower) / 2.0).reindex(df.index)


def register_all(reg: IndicatorRegistry) -> None:
    # --- Oscillators (12) ---
    def b_rsi(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        raw = dict(prm)
        period_sent = raw.pop("period", None)
        if period_sent is not None and "length" not in raw:
            raw["length"] = period_sent
        m = merge_params({"length": 14}, raw)
        ln = optional_int("length", m.get("length"), 14, minimum=2, maximum=5000)
        out: dict[str, Any] = {"length": ln}
        if period_sent is not None:
            out["period"] = ln

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return df.ta.rsi(length=int(p["length"]))

        return out, run

    _reg(reg, IndicatorMetadata("rsi", "RSI", IndicatorCategory.OSCILLATOR, {"length": 14}), b_rsi)

    def b_stoch(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"k": 14, "d": 3, "smooth_k": 3}, prm)
        k = optional_int("k", m.get("k"), 14, minimum=2, maximum=5000)
        d_ = optional_int("d", m.get("d"), 3, minimum=1, maximum=5000)
        sk = optional_int("smooth_k", m.get("smooth_k"), 3, minimum=1, maximum=5000)
        out = {"k": k, "d": d_, "smooth_k": sk}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.stoch(k=int(p["k"]), d=int(p["d"]), smooth_k=int(p["smooth_k"]))
            return _first_col(fr, "STOCHk")

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "stoch", "Stochastic", IndicatorCategory.OSCILLATOR, {"k": 14, "d": 3, "smooth_k": 3}
        ),
        b_stoch,
    )

    def b_cci(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 20}, prm)
        ln = optional_int("length", m.get("length"), 20, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return df.ta.cci(length=int(p["length"]))

        return out, run

    _reg(reg, IndicatorMetadata("cci", "CCI", IndicatorCategory.OSCILLATOR, {"length": 20}), b_cci)

    def b_mom(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 10}, prm)
        ln = optional_int("length", m.get("length"), 10, minimum=1, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return df.ta.mom(length=int(p["length"]))

        return out, run

    _reg(
        reg,
        IndicatorMetadata("momentum", "Momentum", IndicatorCategory.OSCILLATOR, {"length": 10}),
        b_mom,
    )

    def b_macd(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"fast": 12, "slow": 26, "signal": 9}, prm)
        f = optional_int("fast", m.get("fast"), 12, minimum=2, maximum=5000)
        s = optional_int("slow", m.get("slow"), 26, minimum=2, maximum=5000)
        sig = optional_int("signal", m.get("signal"), 9, minimum=1, maximum=5000)
        out = {"fast": f, "slow": s, "signal": sig}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.macd(fast=int(p["fast"]), slow=int(p["slow"]), signal=int(p["signal"]))
            return _first_col(fr, "MACD_")

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "macd", "MACD", IndicatorCategory.OSCILLATOR, {"fast": 12, "slow": 26, "signal": 9}
        ),
        b_macd,
    )

    def b_osma(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"fast": 12, "slow": 26, "signal": 9}, prm)
        f = optional_int("fast", m.get("fast"), 12, minimum=2, maximum=5000)
        s = optional_int("slow", m.get("slow"), 26, minimum=2, maximum=5000)
        sig = optional_int("signal", m.get("signal"), 9, minimum=1, maximum=5000)
        out = {"fast": f, "slow": s, "signal": sig}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.macd(fast=int(p["fast"]), slow=int(p["slow"]), signal=int(p["signal"]))
            return _first_col(fr, "MACDh")

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "osma",
            "OsMA (MACD histogram)",
            IndicatorCategory.OSCILLATOR,
            {"fast": 12, "slow": 26, "signal": 9},
        ),
        b_osma,
    )

    def b_roc(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 10}, prm)
        ln = optional_int("length", m.get("length"), 10, minimum=1, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return df.ta.roc(length=int(p["length"]))

        return out, run

    _reg(
        reg,
        IndicatorMetadata("roc", "Rate of Change", IndicatorCategory.OSCILLATOR, {"length": 10}),
        b_roc,
    )

    def b_willr(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 14}, prm)
        ln = optional_int("length", m.get("length"), 14, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return df.ta.willr(length=int(p["length"]))

        return out, run

    _reg(
        reg,
        IndicatorMetadata("willr", "Williams %R", IndicatorCategory.OSCILLATOR, {"length": 14}),
        b_willr,
    )

    def b_ao(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"fast": 5, "slow": 34}, prm)
        fa = optional_int("fast", m.get("fast"), 5, minimum=2, maximum=5000)
        sl = optional_int("slow", m.get("slow"), 34, minimum=2, maximum=5000)
        out = {"fast": fa, "slow": sl}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return pta.ao(
                high=_series(df, "high"),
                low=_series(df, "low"),
                fast=int(p["fast"]),
                slow=int(p["slow"]),
            )

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "ao", "Awesome Oscillator", IndicatorCategory.OSCILLATOR, {"fast": 5, "slow": 34}
        ),
        b_ao,
    )

    def b_ac(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"fast": 5, "slow": 34}, prm)
        fa = optional_int("fast", m.get("fast"), 5, minimum=2, maximum=5000)
        sl = optional_int("slow", m.get("slow"), 34, minimum=2, maximum=5000)
        out = {"fast": fa, "slow": sl}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return _accelerator(df, p)

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "ac",
            "Accelerator Oscillator",
            IndicatorCategory.OSCILLATOR,
            {"fast": 5, "slow": 34},
        ),
        b_ac,
    )

    def b_demarker(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 14}, prm)
        ln = optional_int("length", m.get("length"), 14, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return _demarker(df, p)

        return out, run

    _reg(
        reg,
        IndicatorMetadata("demarker", "DeMarker", IndicatorCategory.OSCILLATOR, {"length": 14}),
        b_demarker,
    )

    def b_stc(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"tc_length": 10, "fast": 23, "slow": 50}, prm)
        tclen = optional_int("tc_length", m.get("tc_length"), 10, minimum=2, maximum=5000)
        fast = optional_int("fast", m.get("fast"), 23, minimum=2, maximum=5000)
        slow = optional_int("slow", m.get("slow"), 50, minimum=2, maximum=5000)
        out = {"tc_length": tclen, "fast": fast, "slow": slow}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.stc(
                close=df["close"],
                tc_length=int(p["tc_length"]),
                fast=int(p["fast"]),
                slow=int(p["slow"]),
            )
            return _first_col(fr, "STC")

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "stc",
            "Schaff Trend Cycle",
            IndicatorCategory.OSCILLATOR,
            {"tc_length": 10, "fast": 23, "slow": 50},
        ),
        b_stc,
    )

    # --- Trend (12) ---
    def b_ma(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"kind": "sma", "length": 20}, prm)
        kind = str(m.get("kind", "sma")).strip().lower()
        if kind not in {"sma", "ema", "wma"}:
            raise IndicatorParameterError("moving_average `kind` must be sma, ema, or wma.")
        ln = optional_int("length", m.get("length"), 20, minimum=1, maximum=5000)
        out = {"kind": kind, "length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            k = str(p["kind"]).lower()
            ln_ = int(p["length"])
            if k == "sma":
                return df.ta.sma(length=ln_, close=df["close"])
            if k == "ema":
                return df.ta.ema(length=ln_, close=df["close"])
            return df.ta.wma(length=ln_, close=df["close"])

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "moving_average",
            "Moving Average (SMA / EMA / WMA)",
            IndicatorCategory.TREND,
            {"kind": "sma", "length": 20},
        ),
        b_ma,
    )

    def b_bbands(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 20, "std": 2.0}, prm)
        ln = optional_int("length", m.get("length"), 20, minimum=2, maximum=5000)
        std = require_float("std", m.get("std", 2.0), minimum=0.01)
        out = {"length": ln, "std": std}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.bbands(length=int(p["length"]), std=float(p["std"]))
            return _first_col(fr, "BBM_")

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "bbands", "Bollinger Bands", IndicatorCategory.TREND, {"length": 20, "std": 2.0}
        ),
        b_bbands,
    )

    def b_bbw(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 20, "std": 2.0}, prm)
        ln = optional_int("length", m.get("length"), 20, minimum=2, maximum=5000)
        std = require_float("std", m.get("std", 2.0), minimum=0.01)
        out = {"length": ln, "std": std}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.bbands(length=int(p["length"]), std=float(p["std"]))
            return _first_col(fr, "BBB_")

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "bb_width",
            "Bollinger Bands Width",
            IndicatorCategory.TREND,
            {"length": 20, "std": 2.0},
        ),
        b_bbw,
    )

    def b_env(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"kind": "sma", "length": 20, "percent": 0.1}, prm)
        kind = str(m.get("kind", "sma")).strip().lower()
        if kind not in {"sma", "ema", "wma"}:
            raise IndicatorParameterError("envelopes `kind` must be sma, ema, or wma.")
        ln = optional_int("length", m.get("length"), 20, minimum=1, maximum=5000)
        pct = require_float("percent", m.get("percent", 0.1), minimum=0.0)
        out = {"kind": kind, "length": ln, "percent": pct}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return _envelopes_upper(df, p)

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "envelopes",
            "Envelopes",
            IndicatorCategory.TREND,
            {"kind": "sma", "length": 20, "percent": 0.1},
        ),
        b_env,
    )

    def b_ichi(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"tenkan": 9, "kijun": 26, "senkou": 52}, prm)
        t = optional_int("tenkan", m.get("tenkan"), 9, minimum=2, maximum=5000)
        k = optional_int("kijun", m.get("kijun"), 26, minimum=2, maximum=5000)
        s = optional_int("senkou", m.get("senkou"), 52, minimum=2, maximum=5000)
        out = {"tenkan": t, "kijun": k, "senkou": s}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            ich = pta.ichimoku(
                high=_series(df, "high"),
                low=_series(df, "low"),
                close=_series(df, "close"),
                tenkan=int(p["tenkan"]),
                kijun=int(p["kijun"]),
                senkou=int(p["senkou"]),
            )
            frame = ich[0]
            if frame is None:
                return pd.Series(np.nan, index=df.index)
            return _first_col(frame, "ISA_")

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "ichimoku",
            "Ichimoku",
            IndicatorCategory.TREND,
            {"tenkan": 9, "kijun": 26, "senkou": 52},
        ),
        b_ichi,
    )

    def b_psar(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"af0": 0.02, "af": 0.02, "max_af": 0.2}, prm)
        af0 = optional_float("af0", m.get("af0"), 0.02)
        af = optional_float("af", m.get("af"), 0.02)
        max_af = optional_float("max_af", m.get("max_af"), 0.2)
        out = {"af0": af0, "af": af, "max_af": max_af}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = pta.psar(
                high=_series(df, "high"),
                low=_series(df, "low"),
                close=_series(df, "close"),
                af0=float(p["af0"]),
                af=float(p["af"]),
                max_af=float(p["max_af"]),
            )
            # Prefer long PSAR line when present
            for pref in ("PSARl", "PSARs"):
                try:
                    return _first_col(fr, pref)
                except ValueError:
                    continue
            raise ValueError("psar: no PSAR column found")

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "psar",
            "Parabolic SAR",
            IndicatorCategory.TREND,
            {"af0": 0.02, "af": 0.02, "max_af": 0.2},
        ),
        b_psar,
    )

    def b_super(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 7, "multiplier": 3.0}, prm)
        ln = optional_int("length", m.get("length"), 7, minimum=2, maximum=5000)
        mult = require_float("multiplier", m.get("multiplier", 3.0), minimum=0.1)
        out = {"length": ln, "multiplier": mult}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.supertrend(length=int(p["length"]), multiplier=float(p["multiplier"]))
            return _first_col(fr, "SUPERT_")

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "supertrend",
            "SuperTrend",
            IndicatorCategory.TREND,
            {"length": 7, "multiplier": 3.0},
        ),
        b_super,
    )

    def b_adx(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 14}, prm)
        ln = optional_int("length", m.get("length"), 14, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.adx(length=int(p["length"]))
            return _first_col(fr, "ADX_")

        return out, run

    _reg(reg, IndicatorMetadata("adx", "ADX", IndicatorCategory.TREND, {"length": 14}), b_adx)

    def b_aroon(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 14}, prm)
        ln = optional_int("length", m.get("length"), 14, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.aroon(length=int(p["length"]))
            return _first_col(fr, "AROONU_")

        return out, run

    _reg(reg, IndicatorMetadata("aroon", "Aroon", IndicatorCategory.TREND, {"length": 14}), b_aroon)

    def b_zig(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"deviation": 5.0, "legs": 10}, prm)
        dev = require_float("deviation", m.get("deviation", 5.0), minimum=0.01)
        legs = optional_int("legs", m.get("legs"), 10, minimum=2, maximum=5000)
        out = {"deviation": dev, "legs": legs}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = pta.zigzag(
                high=_series(df, "high"),
                low=_series(df, "low"),
                close=_series(df, "close"),
                deviation=float(p["deviation"]),
                legs=int(p["legs"]),
            )
            return _first_col(fr, "ZIGZAGv_")

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "zigzag",
            "ZigZag",
            IndicatorCategory.TREND,
            {"deviation": 5.0, "legs": 10},
            True,
        ),
        b_zig,
    )

    def b_alli(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"jaw": 13, "teeth": 8, "lips": 5}, prm)
        jaw = optional_int("jaw", m.get("jaw"), 13, minimum=2, maximum=5000)
        teeth = optional_int("teeth", m.get("teeth"), 8, minimum=2, maximum=5000)
        lips = optional_int("lips", m.get("lips"), 5, minimum=2, maximum=5000)
        out = {"jaw": jaw, "teeth": teeth, "lips": lips}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = pta.alligator(
                close=_series(df, "close"),
                jaw=int(p["jaw"]),
                teeth=int(p["teeth"]),
                lips=int(p["lips"]),
            )
            return _first_col(fr, "AGl_")

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "alligator",
            "Alligator",
            IndicatorCategory.TREND,
            {"jaw": 13, "teeth": 8, "lips": 5},
        ),
        b_alli,
    )

    def b_vortex(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 14}, prm)
        ln = optional_int("length", m.get("length"), 14, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.vortex(length=int(p["length"]))
            return _first_col(fr, "VTXP_")

        return out, run

    _reg(
        reg,
        IndicatorMetadata("vortex", "Vortex", IndicatorCategory.TREND, {"length": 14}),
        b_vortex,
    )

    # --- Volatility (3) ---
    def b_atr(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 14}, prm)
        ln = optional_int("length", m.get("length"), 14, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return df.ta.atr(length=int(p["length"]))

        return out, run

    _reg(reg, IndicatorMetadata("atr", "ATR", IndicatorCategory.VOLATILITY, {"length": 14}), b_atr)

    def b_don(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 20}, prm)
        ln = optional_int("length", m.get("length"), 20, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            # DataFrame accessor: same values as pta.donchian(..., close=, length=); cleaner stubs.
            fr = df.ta.donchian(length=int(p["length"]))
            return _first_col(fr, "DCM_")

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "donchian", "Donchian Channels", IndicatorCategory.VOLATILITY, {"length": 20}
        ),
        b_don,
    )

    def b_kc(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 20, "scalar": 2.0}, prm)
        ln = optional_int("length", m.get("length"), 20, minimum=2, maximum=5000)
        sc = require_float("scalar", m.get("scalar", 2.0), minimum=0.01)
        out = {"length": ln, "scalar": sc}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.kc(length=int(p["length"]), scalar=float(p["scalar"]))
            return _first_col(fr, "KCBe_")

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "keltner",
            "Keltner Channel",
            IndicatorCategory.VOLATILITY,
            {"length": 20, "scalar": 2.0},
        ),
        b_kc,
    )

    # --- Volume (3) ---
    def b_vol(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        _ = merge_params({}, prm)

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            _ = p
            return _series(df, "volume").astype("float64")

        return {}, run

    _reg(reg, IndicatorMetadata("volume", "Volume", IndicatorCategory.VOLUME, {}), b_vol)

    def b_bulls(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 13}, prm)
        ln = optional_int("length", m.get("length"), 13, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return _bulls_power(df, p)

        return out, run

    _reg(
        reg,
        IndicatorMetadata("bulls_power", "Bulls Power", IndicatorCategory.VOLUME, {"length": 13}),
        b_bulls,
    )

    def b_bears(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 13}, prm)
        ln = optional_int("length", m.get("length"), 13, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return _bears_power(df, p)

        return out, run

    _reg(
        reg,
        IndicatorMetadata("bears_power", "Bears Power", IndicatorCategory.VOLUME, {"length": 13}),
        b_bears,
    )

    # --- Other (2) ---
    def b_frac(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        out = dict(merge_params({}, prm))

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            _ = p
            return _fractal_mid(df, {})

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "fractal", "Fractal (Williams midpoint)", IndicatorCategory.OTHER, {}, True
        ),
        b_frac,
    )

    def b_fcb(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"window": 10}, prm)
        w = optional_int("window", m.get("window"), 10, minimum=2, maximum=5000)
        out = {"window": w}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return _fcb_mid(df, p)

        return out, run

    _reg(
        reg,
        IndicatorMetadata(
            "fractal_chaos_bands",
            "Fractal Chaos Bands (midline)",
            IndicatorCategory.OTHER,
            {"window": 10},
            True,
        ),
        b_fcb,
    )
