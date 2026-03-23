from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IndicatorSeries:
    """One indicator run aligned bar-for-bar with the candle list passed into compute()."""

    indicator_id: str
    params: dict[str, object]
    values: list[float | None]
