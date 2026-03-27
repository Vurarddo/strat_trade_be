from __future__ import annotations

from collections.abc import Sequence

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError

STOCHASTIC_ID = "stochastic"
STOCHASTIC_OUTPUT_K = "k"
STOCHASTIC_OUTPUT_D = "d"

STOCHASTIC_TITLE = "Stochastic Oscillator"
STOCHASTIC_SUMMARY = (
    "Compares the closing price to the high–low range over K periods; "
    "%D is a simple moving average of the (optionally smoothed) %K line."
)
STOCHASTIC_FORMULA = (
    "Raw %K = 100 × (Close − Lowest Low) / (Highest High − Lowest Low) over `k_length` bars "
    "(range 0 → %K = 50). Optional `smooth_k`-period SMA of raw %K. "
    "%D = SMA of that series over `d_length` bars."
)


def _sma_tail(values: list[float | None], period: int, start_idx: int) -> list[float | None]:
    """SMA over `period` consecutive floats starting at `start_idx`; leading indices are None."""
    n = len(values)
    out: list[float | None] = [None] * n
    if period < 1:
        return out
    for i in range(start_idx + period - 1, n):
        window = values[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        out[i] = sum(float(v) for v in window) / period
    return out


def compute_stochastic(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    k_length: int,
    d_length: int,
    smooth_k: int,
) -> tuple[list[float | None], list[float | None]]:
    """
    Classic Stochastic: raw %K from high/low/close window, optional SMA smoothing,
    then %D = SMA(%K).

    First %K (after smoothing) at index ``k_length - 1 + smooth_k - 1``; first %D after ``d_length``
    samples of the smoothed %K series.
    """
    n = len(closes)
    raw_k: list[float | None] = [None] * n
    if k_length < 1 or n < k_length:
        return raw_k, [None] * n

    for i in range(k_length - 1, n):
        lo = min(lows[i - k_length + 1 : i + 1])
        hi = max(highs[i - k_length + 1 : i + 1])
        c = closes[i]
        if hi == lo:
            raw_k[i] = 50.0
        else:
            raw_k[i] = 100.0 * (c - lo) / (hi - lo)

    if smooth_k <= 1:
        k_line = raw_k
    else:
        k_line = _sma_tail(raw_k, smooth_k, k_length - 1)

    first_k_idx = k_length - 1 + max(0, smooth_k - 1)
    d_line = _sma_tail(k_line, d_length, first_k_idx)
    return k_line, d_line


def min_bars_stochastic(k_length: int, d_length: int, smooth_k: int) -> int:
    """Smallest bar count so the newest bar can have a defined %D."""
    sk = max(1, smooth_k)
    return k_length + sk + d_length - 2


class StochasticCalculator:
    """Stochastic %K / %D on OHLC (classic high/low range and close)."""

    __slots__ = ("_k", "_d", "_smooth_k")

    def __init__(self, k_length: int = 14, d_length: int = 3, smooth_k: int = 1) -> None:
        if k_length < 1 or d_length < 1:
            raise IndicatorParameterError("Stochastic k_length and d_length must be >= 1.")
        if smooth_k < 1:
            raise IndicatorParameterError("Stochastic smooth_k must be >= 1.")
        self._k = k_length
        self._d = d_length
        self._smooth_k = smooth_k

    @property
    def indicator_id(self) -> str:
        return STOCHASTIC_ID

    def compute(self, candles: Sequence[Candle]) -> dict[str, list[float | None]]:
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        closes = [float(c.close) for c in candles]
        k_line, d_line = compute_stochastic(
            highs,
            lows,
            closes,
            k_length=self._k,
            d_length=self._d,
            smooth_k=self._smooth_k,
        )
        return {STOCHASTIC_OUTPUT_K: k_line, STOCHASTIC_OUTPUT_D: d_line}
