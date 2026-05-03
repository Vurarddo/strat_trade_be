from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import IndicatorParameterError, UnknownIndicatorError
from strat_trade.domain.indicators import default_indicator_registry


def _candle(i: int, close: float) -> Candle:
    t = datetime(2025, 1, 1, 12, 0, tzinfo=UTC) + timedelta(minutes=i)
    d = Decimal(str(close))
    return Candle(open_time=t, open=d, high=d, low=d, close=d, volume=Decimal("1"))


def test_rsi_period_two_matches_pandas_ta() -> None:
    closes = [10.0, 11.0, 10.0, 11.0, 12.0]
    candles = [_candle(i, c) for i, c in enumerate(closes)]
    series = default_indicator_registry().build("rsi", {"length": 2}).compute(candles)
    assert series.values[0] is None
    assert series.values[1:] == pytest.approx([100.0, 50.0, 75.0, 87.5])


def test_rsi_rejects_invalid_period() -> None:
    with pytest.raises(IndicatorParameterError):
        default_indicator_registry().build("rsi", {"length": 1})


def test_registry_unknown_indicator() -> None:
    reg = default_indicator_registry()
    with pytest.raises(UnknownIndicatorError):
        reg.build("not_an_indicator", {})


def test_registry_accepts_uppercase_id() -> None:
    reg = default_indicator_registry()
    calc = reg.build("RSI", {"period": 2})
    assert calc.indicator_id == "rsi"
