from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from strat_trade.domain.errors import IndicatorParameterError, UnknownIndicatorError
from strat_trade.domain.indicators.protocol import IndicatorCalculator
from strat_trade.domain.indicators.rsi_wilder import RSI_WILDER_ID, RsiWilderCalculator

# Known indicator ids for validation / OpenAPI; new indicators extend this set.
REGISTERED_INDICATOR_IDS = frozenset({RSI_WILDER_ID})

_MAX_RSI_LENGTH = 500


def _coerce_positive_int(value: object, field: str, *, default: int, max_value: int) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise IndicatorParameterError(f"{field} must be an integer.")
    if isinstance(value, int):
        n = value
    elif isinstance(value, float) and value == int(value):
        n = int(value)
    else:
        raise IndicatorParameterError(f"{field} must be an integer.")
    if n < 1:
        raise IndicatorParameterError(f"{field} must be >= 1.")
    if n > max_value:
        raise IndicatorParameterError(f"{field} must be <= {max_value}.")
    return n


def min_bars_for_indicator(indicator_id: str, params: Mapping[str, Any]) -> int:
    """Minimum candle count so the first bar can have a defined value (per indicator rules)."""
    if indicator_id == RSI_WILDER_ID:
        length = _coerce_positive_int(
            params.get("length", 14),
            "length",
            default=14,
            max_value=_MAX_RSI_LENGTH,
        )
        return length + 1
    raise UnknownIndicatorError(f"Unknown indicator_id: {indicator_id!r}.")


def build_calculator(indicator_id: str, params: Mapping[str, Any]) -> IndicatorCalculator:
    if indicator_id == RSI_WILDER_ID:
        length = _coerce_positive_int(
            params.get("length", 14),
            "length",
            default=14,
            max_value=_MAX_RSI_LENGTH,
        )
        return RsiWilderCalculator(length=length)
    raise UnknownIndicatorError(f"Unknown indicator_id: {indicator_id!r}.")


def build_rsi_wilder(length: int = 14) -> RsiWilderCalculator:
    return RsiWilderCalculator(length=length)
