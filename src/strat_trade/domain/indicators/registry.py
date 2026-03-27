from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from strat_trade.domain.errors import IndicatorParameterError, UnknownIndicatorError
from strat_trade.domain.indicators.bollinger_bands import (
    BOLLINGER_BANDS_ID,
    BollingerBandsCalculator,
)
from strat_trade.domain.indicators.cci import CCI_ID, CciCalculator
from strat_trade.domain.indicators.macd import (
    MACD_ID,
    MacdCalculator,
    min_bars_macd,
)
from strat_trade.domain.indicators.parabolic_sar import (
    PARABOLIC_SAR_ID,
    ParabolicSarCalculator,
    min_bars_parabolic_sar,
)
from strat_trade.domain.indicators.protocol import IndicatorCalculator
from strat_trade.domain.indicators.rsi_wilder import RSI_WILDER_ID, RsiWilderCalculator
from strat_trade.domain.indicators.stochastic import (
    STOCHASTIC_ID,
    StochasticCalculator,
    min_bars_stochastic,
)

# Known indicator ids for validation / OpenAPI; new indicators extend this set.
REGISTERED_INDICATOR_IDS = frozenset(
    {
        RSI_WILDER_ID,
        BOLLINGER_BANDS_ID,
        MACD_ID,
        STOCHASTIC_ID,
        CCI_ID,
        PARABOLIC_SAR_ID,
    }
)

_MAX_RSI_LENGTH = 500
_MAX_BB_LENGTH = 500
_MAX_BB_MULT = 50.0
_MAX_MACD_LENGTH = 500
_MAX_STOCH_LENGTH = 500
_MAX_CCI_LENGTH = 500
_MAX_SAR_AF = 1.0


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


def _coerce_positive_float(value: object, field: str, *, default: float, max_value: float) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise IndicatorParameterError(f"{field} must be a number.")
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise IndicatorParameterError(f"{field} must be a number.") from None
    if x <= 0.0:
        raise IndicatorParameterError(f"{field} must be > 0.")
    if x > max_value:
        raise IndicatorParameterError(f"{field} must be <= {max_value}.")
    return x


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
    if indicator_id == BOLLINGER_BANDS_ID:
        length = _coerce_positive_int(
            params.get("length", 20),
            "length",
            default=20,
            max_value=_MAX_BB_LENGTH,
        )
        return length
    if indicator_id == MACD_ID:
        fast = _coerce_positive_int(
            params.get("fast_length", 12),
            "fast_length",
            default=12,
            max_value=_MAX_MACD_LENGTH,
        )
        slow = _coerce_positive_int(
            params.get("slow_length", 26),
            "slow_length",
            default=26,
            max_value=_MAX_MACD_LENGTH,
        )
        sig = _coerce_positive_int(
            params.get("signal_length", 9),
            "signal_length",
            default=9,
            max_value=_MAX_MACD_LENGTH,
        )
        return min_bars_macd(fast, slow, sig)
    if indicator_id == STOCHASTIC_ID:
        k = _coerce_positive_int(
            params.get("k_length", 14),
            "k_length",
            default=14,
            max_value=_MAX_STOCH_LENGTH,
        )
        d = _coerce_positive_int(
            params.get("d_length", 3),
            "d_length",
            default=3,
            max_value=_MAX_STOCH_LENGTH,
        )
        sk = _coerce_positive_int(
            params.get("smooth_k", 1),
            "smooth_k",
            default=1,
            max_value=_MAX_STOCH_LENGTH,
        )
        return min_bars_stochastic(k, d, sk)
    if indicator_id == CCI_ID:
        length = _coerce_positive_int(
            params.get("length", 20),
            "length",
            default=20,
            max_value=_MAX_CCI_LENGTH,
        )
        return length
    if indicator_id == PARABOLIC_SAR_ID:
        return min_bars_parabolic_sar()
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
    if indicator_id == BOLLINGER_BANDS_ID:
        length = _coerce_positive_int(
            params.get("length", 20),
            "length",
            default=20,
            max_value=_MAX_BB_LENGTH,
        )
        mult = _coerce_positive_float(
            params.get("mult", 2.0),
            "mult",
            default=2.0,
            max_value=_MAX_BB_MULT,
        )
        return BollingerBandsCalculator(length=length, multiplier=mult)
    if indicator_id == MACD_ID:
        fast = _coerce_positive_int(
            params.get("fast_length", 12),
            "fast_length",
            default=12,
            max_value=_MAX_MACD_LENGTH,
        )
        slow = _coerce_positive_int(
            params.get("slow_length", 26),
            "slow_length",
            default=26,
            max_value=_MAX_MACD_LENGTH,
        )
        sig = _coerce_positive_int(
            params.get("signal_length", 9),
            "signal_length",
            default=9,
            max_value=_MAX_MACD_LENGTH,
        )
        return MacdCalculator(fast_length=fast, slow_length=slow, signal_length=sig)
    if indicator_id == STOCHASTIC_ID:
        k = _coerce_positive_int(
            params.get("k_length", 14),
            "k_length",
            default=14,
            max_value=_MAX_STOCH_LENGTH,
        )
        d = _coerce_positive_int(
            params.get("d_length", 3),
            "d_length",
            default=3,
            max_value=_MAX_STOCH_LENGTH,
        )
        sk = _coerce_positive_int(
            params.get("smooth_k", 1),
            "smooth_k",
            default=1,
            max_value=_MAX_STOCH_LENGTH,
        )
        return StochasticCalculator(k_length=k, d_length=d, smooth_k=sk)
    if indicator_id == CCI_ID:
        length = _coerce_positive_int(
            params.get("length", 20),
            "length",
            default=20,
            max_value=_MAX_CCI_LENGTH,
        )
        return CciCalculator(length=length)
    if indicator_id == PARABOLIC_SAR_ID:
        af_start = _coerce_positive_float(
            params.get("af_start", 0.02),
            "af_start",
            default=0.02,
            max_value=_MAX_SAR_AF,
        )
        af_inc = _coerce_positive_float(
            params.get("af_increment", 0.02),
            "af_increment",
            default=0.02,
            max_value=_MAX_SAR_AF,
        )
        af_max = _coerce_positive_float(
            params.get("af_max", 0.2),
            "af_max",
            default=0.2,
            max_value=_MAX_SAR_AF,
        )
        if af_start > af_max:
            raise IndicatorParameterError("af_start must be <= af_max.")
        if af_inc > af_max:
            raise IndicatorParameterError("af_increment must be <= af_max.")
        return ParabolicSarCalculator(
            af_start=af_start,
            af_increment=af_inc,
            af_max=af_max,
        )
    raise UnknownIndicatorError(f"Unknown indicator_id: {indicator_id!r}.")


def build_rsi_wilder(length: int = 14) -> RsiWilderCalculator:
    return RsiWilderCalculator(length=length)
