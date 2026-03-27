from __future__ import annotations

from collections.abc import Sequence

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError

PARABOLIC_SAR_ID = "parabolic_sar"
PARABOLIC_SAR_OUTPUT_SAR = "sar"

PARABOLIC_SAR_TITLE = "Parabolic SAR"
PARABOLIC_SAR_SUMMARY = (
    "Wilder-style stop-and-reverse: trailing stop that accelerates toward the trend extreme (EP) "
    "with an increasing acceleration factor (AF), capped at af_max."
)
PARABOLIC_SAR_FORMULA = (
    "Long: SARᵢ = SARᵢ₋₁ + AF × (EP − SARᵢ₋₁), clamped vs prior lows; "
    "flip short when Low crosses SAR. "
    "Short: symmetric with highs. AF increases by af_increment on new extremes, "
    "from af_start up to af_max."
)


def compute_parabolic_sar(
    highs: list[float],
    lows: list[float],
    *,
    af_start: float,
    af_increment: float,
    af_max: float,
) -> list[float | None]:
    """
    Classic Parabolic SAR (J. Welles Wilder). ``out[0]`` is undefined; SAR from index 1 onward.
    """
    n = len(highs)
    out: list[float | None] = [None] * n
    if n < 2:
        return out

    bull = highs[1] + lows[1] > highs[0] + lows[0]
    if bull:
        sar = lows[0]
        ep = highs[0]
    else:
        sar = highs[0]
        ep = lows[0]
    af = af_start

    for i in range(1, n):
        if bull:
            sar = sar + af * (ep - sar)
            if i >= 2:
                sar = min(sar, lows[i - 1], lows[i - 2])
            else:
                sar = min(sar, lows[i - 1])
            if highs[i] > ep:
                ep = highs[i]
                af = min(af + af_increment, af_max)
            if lows[i] < sar:
                bull = False
                sar = ep
                ep = lows[i]
                af = af_start
        else:
            sar = sar + af * (ep - sar)
            if i >= 2:
                sar = max(sar, highs[i - 1], highs[i - 2])
            else:
                sar = max(sar, highs[i - 1])
            if lows[i] < ep:
                ep = lows[i]
                af = min(af + af_increment, af_max)
            if highs[i] >= sar:
                bull = True
                sar = ep
                ep = highs[i]
                af = af_start
        out[i] = sar

    return out


def min_bars_parabolic_sar() -> int:
    """SAR is defined from the second bar (index 1)."""
    return 2


class ParabolicSarCalculator:
    """Parabolic SAR from high/low series."""

    __slots__ = ("_af_start", "_af_increment", "_af_max")

    def __init__(
        self,
        af_start: float = 0.02,
        af_increment: float = 0.02,
        af_max: float = 0.2,
    ) -> None:
        if af_start <= 0.0 or af_increment <= 0.0 or af_max <= 0.0:
            raise IndicatorParameterError("Parabolic SAR AF parameters must be > 0.")
        if af_start > af_max:
            raise IndicatorParameterError("af_start must be <= af_max.")
        self._af_start = af_start
        self._af_increment = af_increment
        self._af_max = af_max

    @property
    def indicator_id(self) -> str:
        return PARABOLIC_SAR_ID

    def compute(self, candles: Sequence[Candle]) -> dict[str, list[float | None]]:
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        series = compute_parabolic_sar(
            highs,
            lows,
            af_start=self._af_start,
            af_increment=self._af_increment,
            af_max=self._af_max,
        )
        return {PARABOLIC_SAR_OUTPUT_SAR: series}
