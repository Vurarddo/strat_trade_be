from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError, UnknownIndicatorError
from strat_trade.domain.indicators import MacdCalculator, RsiCalculator, default_indicator_registry


def _candle(i: int, close: float) -> Candle:
    t = datetime(2025, 1, 1, 12, 0, tzinfo=UTC) + timedelta(minutes=i)
    d = Decimal(str(close))
    return Candle(open_time=t, open=d, high=d, low=d, close=d, volume=Decimal("1"))


def test_rsi_period_two_matches_ta_library() -> None:
    closes = [10.0, 11.0, 10.0, 11.0, 12.0]
    candles = [_candle(i, c) for i, c in enumerate(closes)]
    series = RsiCalculator(2).compute(candles)
    assert series.values[0] is None
    assert series.values[1:] == pytest.approx(
        [100.0, 33.33333333333333, 71.42857142857143, 86.66666666666667]
    )


def test_rsi_rejects_invalid_period() -> None:
    with pytest.raises(IndicatorParameterError):
        RsiCalculator(1)


def test_registry_unknown_indicator() -> None:
    reg = default_indicator_registry()
    with pytest.raises(UnknownIndicatorError):
        reg.build("unknown_indicator", {})


def test_registry_accepts_uppercase_id() -> None:
    reg = default_indicator_registry()
    calc = reg.build("RSI", {"period": 2})
    assert calc.indicator_id == "rsi"


def test_macd_defaults_and_component_hist() -> None:
    closes = [float(i) for i in range(1, 80)]
    candles = [_candle(i, c) for i, c in enumerate(closes)]
    series = MacdCalculator.from_params({"component": "hist"}).compute(candles)
    assert series.indicator_id == "macd"
    assert series.params["component"] == "hist"
    assert len(series.values) == len(candles)
    assert any(v is not None for v in series.values)


def test_macd_rejects_invalid_period_order() -> None:
    with pytest.raises(IndicatorParameterError):
        MacdCalculator.from_params({"fast_period": 26, "slow_period": 12})
