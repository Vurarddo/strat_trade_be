"""Side-effect registration of the Pocket Option–style indicator catalog."""

from __future__ import annotations

from . import bill_williams, oscillators, trend, volatility, volume
from .registry import IndicatorRegistry


def register_all(reg: IndicatorRegistry) -> None:
    oscillators.register(reg)
    trend.register(reg)
    volatility.register(reg)
    volume.register(reg)
    bill_williams.register(reg)


__all__ = ["register_all"]
