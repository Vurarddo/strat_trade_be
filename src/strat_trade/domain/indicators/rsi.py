from __future__ import annotations

from collections.abc import Mapping

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError
from strat_trade.domain.indicators.types import IndicatorSeries


def _float_close(c: Candle) -> float:
    return float(c.close)


class RsiCalculator:
    """Wilder-smoothed RSI; output length matches input candle count."""

    __slots__ = ("_period",)

    def __init__(self, period: int) -> None:
        if period < 2:
            raise IndicatorParameterError("RSI `period` must be >= 2.")
        if period > 1000:
            raise IndicatorParameterError("RSI `period` must be <= 1000.")
        self._period = period

    @property
    def indicator_id(self) -> str:
        return "rsi"

    @classmethod
    def from_params(cls, params: Mapping[str, object]) -> RsiCalculator:
        raw = params.get("period", 14)
        if raw is None:
            period = 14
        elif isinstance(raw, bool):
            raise IndicatorParameterError("RSI `period` must be an integer.")
        elif isinstance(raw, int):
            period = raw
        else:
            raise IndicatorParameterError("RSI `period` must be an integer.")
        return cls(period)

    def compute(self, candles: list[Candle]) -> IndicatorSeries:
        closes = [_float_close(c) for c in candles]
        values = _rsi_wilder(closes, self._period)
        return IndicatorSeries(
            indicator_id=self.indicator_id,
            params={"period": self._period},
            values=values,
        )


def _rsi_wilder(closes: list[float], period: int) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, n):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out[period] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(period + 1, n):
        g = gains[i - 1]
        loss = losses[i - 1]
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi_from_averages(avg_gain, avg_loss)

    return out


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0.0 else 50.0
    if avg_gain == 0.0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))
