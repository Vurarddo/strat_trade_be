from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from strat_trade.domain.entities import Candle
from strat_trade.domain.indicators.macd import MacdCalculator, compute_macd, min_bars_macd


def test_min_bars_macd_classic() -> None:
    assert min_bars_macd(12, 26, 9) == 34


def test_macd_flat_price_histogram_zero() -> None:
    closes = [100.0] * 50
    m, s, h = compute_macd(closes, 12, 26, 9)
    assert h[33] is not None
    assert m[33] == 0.0
    assert s[33] == 0.0
    assert h[33] == 0.0


def test_calculator_matches_compute() -> None:
    base = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    candles = [
        Candle(
            open_time=base + timedelta(minutes=i),
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal(str(1.0 + i * 0.01)),
        )
        for i in range(60)
    ]
    calc = MacdCalculator(12, 26, 9)
    out = calc.compute(candles)
    m2, s2, h2 = compute_macd([float(c.close) for c in candles], 12, 26, 9)
    assert out["macd"] == m2
    assert out["signal"] == s2
    assert out["histogram"] == h2
