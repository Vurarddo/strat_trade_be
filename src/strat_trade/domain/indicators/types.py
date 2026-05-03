from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IndicatorCategory(StrEnum):
    OSCILLATOR = "Oscillator"
    TREND = "Trend"
    VOLATILITY = "Volatility"
    VOLUME = "Volume"
    OTHER = "Other"


@dataclass(frozen=True, slots=True)
class IndicatorMetadata:
    """Catalog entry for Pocket-Option-style indicators (pandas-ta backed)."""

    id: str
    name: str
    category: IndicatorCategory
    default_params: dict[str, object]
    fill_sparse: bool = False


@dataclass(frozen=True, slots=True)
class IndicatorSeries:
    """One indicator run aligned bar-for-bar with the candle list passed into compute()."""

    indicator_id: str
    params: dict[str, object]
    values: list[float | None]
