"""Volume and Elder-style power indicators."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from strat_trade.domain.indicators.indicator_support import (
    TaRun,
    bears_power,
    bulls_power,
    register_indicator,
    series,
)
from strat_trade.domain.indicators.registry import IndicatorRegistry
from strat_trade.domain.indicators.ta_calculator import merge_params, optional_int
from strat_trade.domain.indicators.types import IndicatorCategory, IndicatorMetadata


def register(reg: IndicatorRegistry) -> None:
    def b_vol(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        _ = merge_params({}, prm)

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            _ = p
            return series(df, "volume").astype("float64")

        return {}, run

    register_indicator(
        reg, IndicatorMetadata("volume", "Volume", IndicatorCategory.VOLUME, {}), b_vol
    )

    def b_bulls(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 13}, prm)
        ln = optional_int("length", m.get("length"), 13, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return bulls_power(df, p)

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata("bulls_power", "Bulls Power", IndicatorCategory.VOLUME, {"length": 13}),
        b_bulls,
    )

    def b_bears(prm: Mapping[str, object]) -> tuple[dict[str, Any], TaRun]:
        m = merge_params({"length": 13}, prm)
        ln = optional_int("length", m.get("length"), 13, minimum=2, maximum=5000)
        out = {"length": ln}

        def run(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
            return bears_power(df, p)

        return out, run

    register_indicator(
        reg,
        IndicatorMetadata("bears_power", "Bears Power", IndicatorCategory.VOLUME, {"length": 13}),
        b_bears,
    )
