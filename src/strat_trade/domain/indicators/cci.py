from __future__ import annotations

from collections.abc import Sequence

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError

CCI_ID = "cci"
CCI_OUTPUT_CCI = "cci"

CCI_TITLE = "Commodity Channel Index (CCI)"
CCI_SUMMARY = (
    "Measures how far typical price (high+low+close)/3 deviates from its mean, "
    "normalized by the mean absolute deviation (Lambert’s 0.015 constant)."
)
CCI_FORMULA = (
    "TP = (High + Low + Close) / 3. "
    "CCI = (TP − mean(TP over `length`)) / (0.015 × mean(|TP − mean(TP)| over the same window)). "
    "If mean deviation is 0, CCI is 0."
)


def compute_cci(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    length: int,
) -> list[float | None]:
    """
    Classic CCI (Donald Lambert). First value at bar index ``length - 1`` (needs ``length`` bars).
    """
    n = len(closes)
    out: list[float | None] = [None] * n
    if length < 1 or n < length:
        return out

    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]

    for i in range(length - 1, n):
        window = tp[i - length + 1 : i + 1]
        mean_tp = sum(window) / length
        md = sum(abs(x - mean_tp) for x in window) / length
        if md == 0.0:
            out[i] = 0.0
        else:
            out[i] = (tp[i] - mean_tp) / (0.015 * md)

    return out


class CciCalculator:
    """CCI on typical price from OHLC."""

    __slots__ = ("_length",)

    def __init__(self, length: int = 20) -> None:
        if length < 1:
            raise IndicatorParameterError("CCI length must be >= 1.")
        self._length = length

    @property
    def indicator_id(self) -> str:
        return CCI_ID

    def compute(self, candles: Sequence[Candle]) -> dict[str, list[float | None]]:
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        closes = [float(c.close) for c in candles]
        series = compute_cci(highs, lows, closes, self._length)
        return {CCI_OUTPUT_CCI: series}
