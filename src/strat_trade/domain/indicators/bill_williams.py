"""Bill Williams style indicators (Alligator, AO, AC, fractals, chaos bands)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd
import pandas_ta as pta

from strat_trade.domain.indicators.indicator_support import (
    TaRun,
    accelerator,
    fcb_mid,
    first_col,
    fractal_mid,
    register_indicator,
    series,
)
from strat_trade.domain.indicators.registry import IndicatorRegistry
from strat_trade.domain.indicators.ta_calculator import merge_params, optional_int
from strat_trade.domain.indicators.types import IndicatorCategory, IndicatorMetadata


def register(reg: IndicatorRegistry) -> None:
    def b_alli(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"jaw": 13, "teeth": 8, "lips": 5}, prm)
        jaw = optional_int("jaw", m.get("jaw"), 13, minimum=2, maximum=5000)
        teeth = optional_int("teeth", m.get("teeth"), 8, minimum=2, maximum=5000)
        lips = optional_int("lips", m.get("lips"), 5, minimum=2, maximum=5000)
        out = {"jaw": jaw, "teeth": teeth, "lips": lips}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            fr = pta.alligator(
                close=series(df, "close"),
                jaw=int(p["jaw"]),
                teeth=int(p["teeth"]),
                lips=int(p["lips"]),
            )
            return first_col(fr, "AGl_")

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata(
            "alligator",
            "Alligator",
            IndicatorCategory.BILL_WILLIAMS,
            {"jaw": 13, "teeth": 8, "lips": 5},
        ),
        b_alli,
    )

    def b_ao(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"fast": 5, "slow": 34}, prm)
        fa = optional_int("fast", m.get("fast"), 5, minimum=2, maximum=5000)
        sl = optional_int("slow", m.get("slow"), 34, minimum=2, maximum=5000)
        out = {"fast": fa, "slow": sl}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return pta.ao(
                high=series(df, "high"),
                low=series(df, "low"),
                fast=int(p["fast"]),
                slow=int(p["slow"]),
            )

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata(
            "ao",
            "Awesome Oscillator",
            IndicatorCategory.BILL_WILLIAMS,
            {"fast": 5, "slow": 34},
        ),
        b_ao,
    )

    def b_ac(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"fast": 5, "slow": 34}, prm)
        fa = optional_int("fast", m.get("fast"), 5, minimum=2, maximum=5000)
        sl = optional_int("slow", m.get("slow"), 34, minimum=2, maximum=5000)
        out = {"fast": fa, "slow": sl}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return accelerator(df, p)

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata(
            "ac",
            "Accelerator Oscillator",
            IndicatorCategory.BILL_WILLIAMS,
            {"fast": 5, "slow": 34},
        ),
        b_ac,
    )

    def b_frac(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        out = dict(merge_params({}, prm))

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            _ = p
            return fractal_mid(df, {})

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata(
            "fractal",
            "Fractal (Williams midpoint)",
            IndicatorCategory.BILL_WILLIAMS,
            {},
            True,
        ),
        b_frac,
    )

    def b_fcb(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"window": 10}, prm)
        w = optional_int("window", m.get("window"), 10, minimum=2, maximum=5000)
        out = {"window": w}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return fcb_mid(df, p)

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata(
            "fractal_chaos_bands",
            "Fractal Chaos Bands (midline)",
            IndicatorCategory.BILL_WILLIAMS,
            {"window": 10},
            True,
        ),
        b_fcb,
    )
