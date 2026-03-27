from __future__ import annotations

from collections.abc import Sequence

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError

MACD_ID = "macd"
MACD_OUTPUT_LINE = "macd"
MACD_OUTPUT_SIGNAL = "signal"
MACD_OUTPUT_HISTOGRAM = "histogram"

MACD_TITLE = "MACD"
MACD_SUMMARY = (
    "Moving Average Convergence Divergence: MACD line = EMA(fast) − EMA(slow) on source; "
    "signal = EMA(MACD, signal length); histogram = MACD − signal."
)
MACD_FORMULA = (
    "MACD = EMA(close, fast_length) − EMA(close, slow_length). "
    "Signal = EMA(MACD, signal_length). Histogram = MACD − Signal. "
    "EMA uses smoothing α = 2/(period+1) with initial seed = SMA of the first `period` values."
)


def compute_ema(values: list[float], period: int) -> list[float | None]:
    """EMA with SMA seed at index ``period - 1`` (standard trading platform convention)."""
    n = len(values)
    out: list[float | None] = [None] * n
    if period < 1 or n < period:
        return out
    k = 2.0 / (period + 1.0)
    sma = sum(values[0:period]) / period
    out[period - 1] = sma
    for i in range(period, n):
        prev = out[i - 1]
        if prev is None:
            break
        out[i] = values[i] * k + prev * (1.0 - k)
    return out


def compute_ema_optional(base: list[float | None], period: int) -> list[float | None]:
    """EMA on a series that may start with Nones; SMA seed on first ``period`` non-missing values."""
    n = len(base)
    out: list[float | None] = [None] * n
    start = 0
    while start < n and base[start] is None:
        start += 1
    if start >= n or start + period - 1 >= n:
        return out
    for j in range(start, start + period):
        if base[j] is None:
            return out
    seed = sum(base[start : start + period]) / period
    seed_idx = start + period - 1
    out[seed_idx] = seed
    k = 2.0 / (period + 1.0)
    prev = seed
    for i in range(seed_idx + 1, n):
        v = base[i]
        if v is None:
            out[i] = None
            continue
        prev = v * k + prev * (1.0 - k)
        out[i] = prev
    return out


def compute_macd(
    closes: list[float],
    fast_length: int,
    slow_length: int,
    signal_length: int,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    n = len(closes)
    macd_line: list[float | None] = [None] * n
    signal_line: list[float | None] = [None] * n
    histogram: list[float | None] = [None] * n

    fast_ema = compute_ema(closes, fast_length)
    slow_ema = compute_ema(closes, slow_length)
    for i in range(n):
        f, s = fast_ema[i], slow_ema[i]
        if f is not None and s is not None:
            macd_line[i] = f - s

    signal_line = compute_ema_optional(macd_line, signal_length)

    for i in range(n):
        m, sig = macd_line[i], signal_line[i]
        if m is not None and sig is not None:
            histogram[i] = m - sig

    return macd_line, signal_line, histogram


class MacdCalculator:
    """MACD with EMA-based MACD line, signal, and histogram (close prices)."""

    __slots__ = ("_fast", "_slow", "_signal")

    def __init__(self, fast_length: int = 12, slow_length: int = 26, signal_length: int = 9) -> None:
        if fast_length < 1 or slow_length < 1 or signal_length < 1:
            raise IndicatorParameterError("MACD lengths must be >= 1.")
        self._fast = fast_length
        self._slow = slow_length
        self._signal = signal_length

    @property
    def indicator_id(self) -> str:
        return MACD_ID

    def compute(self, candles: Sequence[Candle]) -> dict[str, list[float | None]]:
        closes = [float(c.close) for c in candles]
        macd_l, sig_l, hist = compute_macd(closes, self._fast, self._slow, self._signal)
        return {
            MACD_OUTPUT_LINE: macd_l,
            MACD_OUTPUT_SIGNAL: sig_l,
            MACD_OUTPUT_HISTOGRAM: hist,
        }


def min_bars_macd(fast_length: int, slow_length: int, signal_length: int) -> int:
    """Smallest bar count so histogram (last series) can be defined at the newest index."""
    return max(fast_length, slow_length) + signal_length - 1
