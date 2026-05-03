"""Volatility / channel indicators."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from strat_trade.domain.indicators.indicator_support import TaRun, first_col, register_indicator
from strat_trade.domain.indicators.registry import IndicatorRegistry
from strat_trade.domain.indicators.ta_calculator import merge_params, optional_int, require_float
from strat_trade.domain.indicators.types import IndicatorCategory, IndicatorMetadata


def register(reg: IndicatorRegistry) -> None:
    def b_atr(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 14}, prm)
        ln = optional_int("length", m.get("length"), 14, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return df.ta.atr(length=int(p["length"]))

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata("atr", "ATR", IndicatorCategory.VOLATILITY, {"length": 14}),
        b_atr,
    )

    def b_bbands(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 20, "std": 2.0}, prm)
        ln = optional_int("length", m.get("length"), 20, minimum=2, maximum=5000)
        std = require_float("std", m.get("std", 2.0), minimum=0.01)
        out = {"length": ln, "std": std}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.bbands(length=int(p["length"]), std=float(p["std"]))
            return first_col(fr, "BBM_")

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata(
            "bbands",
            "Bollinger Bands",
            IndicatorCategory.VOLATILITY,
            {"length": 20, "std": 2.0},
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
            return first_col(fr, "BBB_")

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata(
            "bb_width",
            "Bollinger Bands Width",
            IndicatorCategory.VOLATILITY,
            {"length": 20, "std": 2.0},
        ),
        b_bbw,
    )

    def b_don(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 20}, prm)
        ln = optional_int("length", m.get("length"), 20, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = df.ta.donchian(length=int(p["length"]))
            return first_col(fr, "DCM_")

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata(
            "donchian",
            "Donchian Channels",
            IndicatorCategory.VOLATILITY,
            {"length": 20},
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
            return first_col(fr, "KCBe_")

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata(
            "keltner",
            "Keltner Channel",
            IndicatorCategory.VOLATILITY,
            {"length": 20, "scalar": 2.0},
        ),
        b_kc,
    )
