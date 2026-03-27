from __future__ import annotations

from collections.abc import Sequence

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError

RSI_WILDER_ID = "rsi_wilder"
RSI_WILDER_OUTPUT_RSI = "rsi"

# Static metadata for API / docs (J. Welles Wilder, New Concepts in Technical Trading Systems)
RSI_WILDER_TITLE = "Relative Strength Index (Wilder)"
RSI_WILDER_SUMMARY = (
    "RSI compares average magnitude of gains vs losses over N periods using Wilder smoothing "
    "(not a simple moving average of RS)."
)
RSI_WILDER_FORMULA = (
    "RS = AverageGain / AverageLoss; RSI = 100 - (100 / (1 + RS)). "
    "First averages: sum of gains (or losses) over N periods / N. "
    "Subsequent: NewAvg = (PreviousAvg × (N-1) + Current) / N."
)


def compute_rsi_wilder(closes: list[float], length: int) -> list[float | None]:
    """
    Wilder RSI aligned with TradingView `ta.rsi` (RMA of gains/losses).

    First RSI value appears at bar index `length` (0-based): requires `length + 1` closes.
    """
    n = len(closes)
    out: list[float | None] = [None] * n
    if length < 1 or n < length + 1:
        return out

    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        ch = closes[i] - closes[i - 1]
        gains[i] = ch if ch > 0.0 else 0.0
        losses[i] = (-ch) if ch < 0.0 else 0.0

    first_idx = length
    sum_g = sum(gains[1 : length + 1])
    sum_l = sum(losses[1 : length + 1])
    avg_gain = sum_g / length
    avg_loss = sum_l / length
    out[first_idx] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(first_idx + 1, n):
        avg_gain = (avg_gain * (length - 1) + gains[i]) / length
        avg_loss = (avg_loss * (length - 1) + losses[i]) / length
        out[i] = _rsi_from_averages(avg_gain, avg_loss)

    return out


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        return 50.0 if avg_gain == 0.0 else 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


class RsiWilderCalculator:
    """RSI with Wilder smoothing on average gain and average loss (close-to-close changes)."""

    __slots__ = ("_length",)

    def __init__(self, length: int = 14) -> None:
        if length < 1:
            raise IndicatorParameterError("RSI length must be >= 1.")
        self._length = length

    @property
    def indicator_id(self) -> str:
        return RSI_WILDER_ID

    def compute(self, candles: Sequence[Candle]) -> dict[str, list[float | None]]:
        closes = [float(c.close) for c in candles]
        series = compute_rsi_wilder(closes, self._length)
        return {RSI_WILDER_OUTPUT_RSI: series}
