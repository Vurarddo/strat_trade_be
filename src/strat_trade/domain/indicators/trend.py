"""Trend-family indicators."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd
import pandas_ta as pta

from strat_trade.domain.errors import IndicatorParameterError
from strat_trade.domain.indicators.indicator_support import (
    TaRun,
    envelopes_upper,
    first_col,
    register_indicator,
    series,
)
from strat_trade.domain.indicators.registry import IndicatorRegistry
from strat_trade.domain.indicators.ta_calculator import (
    merge_params,
    optional_float,
    optional_int,
    require_float,
)
from strat_trade.domain.indicators.types import IndicatorCategory, IndicatorMetadata


def register(reg: IndicatorRegistry) -> None:
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
            cl = series(df, "close")
            if k == "sma":
                return df.ta.sma(length=ln_, close=cl)
            if k == "ema":
                return df.ta.ema(length=ln_, close=cl)
            return df.ta.wma(length=ln_, close=cl)

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata(
            "moving_average",
            "Moving Average (SMA / EMA / WMA)",
            IndicatorCategory.TREND,
            {"kind": "sma", "length": 20},
        ),
        b_ma,
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
            return envelopes_upper(df, p)

        return out, run

    register_indicator(
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
                high=series(df, "high"),
                low=series(df, "low"),
                close=series(df, "close"),
                tenkan=int(p["tenkan"]),
                kijun=int(p["kijun"]),
                senkou=int(p["senkou"]),
            )
            frame = ich[0]
            if frame is None:
                return pd.Series(np.nan, index=df.index)
            return first_col(frame, "ISA_")

        return out, run

    register_indicator(
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
                high=series(df, "high"),
                low=series(df, "low"),
                close=series(df, "close"),
                af0=float(p["af0"]),
                af=float(p["af"]),
                max_af=float(p["max_af"]),
            )
            for pref in ("PSARl", "PSARs"):
                try:
                    return first_col(fr, pref)
                except ValueError:
                    continue
            raise ValueError("psar: no PSAR column found")

        return out, run

    register_indicator(
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
            return first_col(fr, "SUPERT_")

        return out, run

    register_indicator(
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
            return first_col(fr, "ADX_")

        return out, run

    register_indicator(
        reg, IndicatorMetadata("adx", "ADX", IndicatorCategory.TREND, {"length": 14}), b_adx
    )

    def b_aroon(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 14}, prm)
        ln = optional_int("length", m.get("length"), 14, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.aroon(length=int(p["length"]))
            return first_col(fr, "AROONU_")

        return out, run

    register_indicator(
        reg, IndicatorMetadata("aroon", "Aroon", IndicatorCategory.TREND, {"length": 14}), b_aroon
    )

    def b_zig(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"deviation": 5.0, "legs": 10}, prm)
        dev = require_float("deviation", m.get("deviation", 5.0), minimum=0.01)
        legs = optional_int("legs", m.get("legs"), 10, minimum=2, maximum=5000)
        out = {"deviation": dev, "legs": legs}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = pta.zigzag(
                high=series(df, "high"),
                low=series(df, "low"),
                close=series(df, "close"),
                deviation=float(p["deviation"]),
                legs=int(p["legs"]),
            )
            return first_col(fr, "ZIGZAGv_")

        return out, run

    register_indicator(
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

    def b_vortex(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 14}, prm)
        ln = optional_int("length", m.get("length"), 14, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.vortex(length=int(p["length"]))
            return first_col(fr, "VTXP_")

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata("vortex", "Vortex", IndicatorCategory.TREND, {"length": 14}),
        b_vortex,
    )
