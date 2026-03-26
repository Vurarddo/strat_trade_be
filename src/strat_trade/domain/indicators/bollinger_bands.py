from __future__ import annotations

import math
from collections.abc import Sequence

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError

BOLLINGER_BANDS_ID = "bollinger_bands"
BB_OUTPUT_MIDDLE = "middle"
BB_OUTPUT_UPPER = "upper"
BB_OUTPUT_LOWER = "lower"

BOLLINGER_TITLE = "Bollinger Bands"
BOLLINGER_SUMMARY = (
    "Volatility envelopes around a simple moving average: middle = SMA(close, length); "
    "upper/lower = middle ± multiplier × population standard deviation (÷ length)."
)
BOLLINGER_FORMULA = (
    "Middle = SMA(source, length). "
    "σ = sqrt( (1/length) × Σ (x_i − Middle)² ) over the same length closes. "
    "Upper = Middle + mult × σ; Lower = Middle − mult × σ."
)


def compute_bollinger_bands(
    closes: list[float],
    length: int,
    multiplier: float,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """
    Classic Bollinger Bands with SMA middle and population stdev (variance divisor = length).

    First defined bar at index ``length - 1`` (0-based).
    """
    n = len(closes)
    middle: list[float | None] = [None] * n
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    if length < 1 or n < length:
        return middle, upper, lower

    for j in range(length - 1, n):
        s = 0.0
        start = j - length + 1
        for k in range(start, j + 1):
            s += closes[k]
        m = s / length
        sum_sq = 0.0
        for k in range(start, j + 1):
            d = closes[k] - m
            sum_sq += d * d
        var_pop = sum_sq / length
        sigma = math.sqrt(var_pop) if var_pop > 0.0 else 0.0
        middle[j] = m
        upper[j] = m + multiplier * sigma
        lower[j] = m - multiplier * sigma

    return middle, upper, lower


class BollingerBandsCalculator:
    """Bollinger Bands on close (SMA middle, population σ, John Bollinger-style bands)."""

    __slots__ = ("_length", "_multiplier")

    def __init__(self, length: int = 20, multiplier: float = 2.0) -> None:
        if length < 1:
            raise IndicatorParameterError("Bollinger length must be >= 1.")
        if multiplier <= 0.0:
            raise IndicatorParameterError("Bollinger multiplier must be > 0.")
        self._length = length
        self._multiplier = multiplier

    @property
    def indicator_id(self) -> str:
        return BOLLINGER_BANDS_ID

    def compute(self, candles: Sequence[Candle]) -> dict[str, list[float | None]]:
        closes = [float(c.close) for c in candles]
        mid, up, lo = compute_bollinger_bands(closes, self._length, self._multiplier)
        return {
            BB_OUTPUT_MIDDLE: mid,
            BB_OUTPUT_UPPER: up,
            BB_OUTPUT_LOWER: lo,
        }
