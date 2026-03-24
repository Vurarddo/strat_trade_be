from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class StrategyIndicatorSpec:
    key: str
    indicator_id: str
    params: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class StrategyConditionSpec:
    """For `ema_cross`, `indicator_key` is fast EMA; set `slow_indicator_key` for slow EMA."""

    indicator_key: str
    operator: str
    slow_indicator_key: str | None = None
    params: Mapping[str, object] = field(default_factory=dict)
