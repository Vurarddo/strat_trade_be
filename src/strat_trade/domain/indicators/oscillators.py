"""Oscillator-family indicators (pandas-ta + DeMarker, STC)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from strat_trade.domain.indicators.indicator_support import (
    TaRun,
    demarker,
    first_col,
    register_indicator,
    series,
)
from strat_trade.domain.indicators.registry import IndicatorRegistry
from strat_trade.domain.indicators.ta_calculator import merge_params, optional_int
from strat_trade.domain.indicators.types import IndicatorCategory, IndicatorMetadata


def register(reg: IndicatorRegistry) -> None:
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

    register_indicator(
        reg, IndicatorMetadata("rsi", "RSI", IndicatorCategory.OSCILLATOR, {"length": 14}), b_rsi
    )

    def b_stoch(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"k": 14, "d": 3, "smooth_k": 3}, prm)
        k = optional_int("k", m.get("k"), 14, minimum=2, maximum=5000)
        d_ = optional_int("d", m.get("d"), 3, minimum=1, maximum=5000)
        sk = optional_int("smooth_k", m.get("smooth_k"), 3, minimum=1, maximum=5000)
        out = {"k": k, "d": d_, "smooth_k": sk}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.stoch(k=int(p["k"]), d=int(p["d"]), smooth_k=int(p["smooth_k"]))
            return first_col(fr, "STOCHk")

        return out, run

    register_indicator(
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

    register_indicator(
        reg, IndicatorMetadata("cci", "CCI", IndicatorCategory.OSCILLATOR, {"length": 20}), b_cci
    )

    def b_mom(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 10}, prm)
        ln = optional_int("length", m.get("length"), 10, minimum=1, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return df.ta.mom(length=int(p["length"]))

        return out, run

    register_indicator(
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
            return first_col(fr, "MACD_")

        return out, run

    register_indicator(
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
            return first_col(fr, "MACDh")

        return out, run

    register_indicator(
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

    register_indicator(
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

    register_indicator(
        reg,
        IndicatorMetadata("willr", "Williams %R", IndicatorCategory.OSCILLATOR, {"length": 14}),
        b_willr,
    )

    def b_demarker(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 14}, prm)
        ln = optional_int("length", m.get("length"), 14, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return demarker(df, p)

        return out, run

    register_indicator(
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
                close=series(df, "close"),
                tc_length=int(p["tc_length"]),
                fast=int(p["fast"]),
                slow=int(p["slow"]),
            )
            return first_col(fr, "STC")

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata(
            "stc",
            "Schaff Trend Cycle",
            IndicatorCategory.OSCILLATOR,
            {"tc_length": 10, "fast": 23, "slow": 50},
        ),
        b_stc,
    )
