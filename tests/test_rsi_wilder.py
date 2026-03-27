from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from strat_trade.domain.entities import Candle
from strat_trade.domain.indicators.rsi_wilder import RsiWilderCalculator, compute_rsi_wilder


def test_wilder_rsi_constant_series_is_neutral() -> None:
    """No gains or losses → average gain/loss both 0 → RSI 50 (Wilder convention)."""
    closes = [100.0] * 25
    out = compute_rsi_wilder(closes, 14)
    assert out[13] is None
    assert out[14] == 50.0
    assert all(x == 50.0 for x in out[15:])


def test_wilder_rsi_all_up_moves_to_100() -> None:
    closes = [float(i) for i in range(30)]
    out = compute_rsi_wilder(closes, 14)
    assert out[-1] == 100.0


def test_calculator_matches_function() -> None:
    base = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    candles = [
        Candle(
            open_time=base + timedelta(minutes=i),
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal(str(100 + i * 0.1)),
        )
        for i in range(30)
    ]
    calc = RsiWilderCalculator(length=14)
    a = calc.compute(candles)["rsi"]
    b = compute_rsi_wilder([float(c.close) for c in candles], 14)
    assert a == b
