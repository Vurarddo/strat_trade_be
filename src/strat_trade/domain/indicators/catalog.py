"""Side-effect registration of the Pocket Option–style indicator catalog."""

from __future__ import annotations

from strat_trade.domain.indicators.indicator_defs import register_all

__all__ = ["register_all"]
