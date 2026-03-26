from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from strat_trade.domain.entities import Candle
from strat_trade.domain.indicators.bollinger_bands import (
    BollingerBandsCalculator,
    compute_bollinger_bands,
)


def test_bollinger_constant_close_zero_bandwidth() -> None:
    closes = [100.0] * 25
    mid, up, lo = compute_bollinger_bands(closes, length=20, multiplier=2.0)
    assert mid[18] is None
    assert mid[19] == 100.0
    assert up[19] == 100.0
    assert lo[19] == 100.0


def test_bollinger_three_bar_window_manual() -> None:
    """length=3, first bar at index 2: middle=2, var=((1-2)^2+0+(3-2)^2)/3=2/3."""
    closes = [1.0, 2.0, 3.0, 3.0]
    mid, up, lo = compute_bollinger_bands(closes, length=3, multiplier=1.0)
    assert mid[0] is None and mid[1] is None
    assert mid[2] == 2.0
    sigma = math.sqrt(2.0 / 3.0)
    assert abs(up[2] - (2.0 + sigma)) < 1e-9
    assert abs(lo[2] - (2.0 - sigma)) < 1e-9


def test_calculator_matches_function() -> None:
    base = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    candles = [
        Candle(
            open_time=base + timedelta(minutes=i),
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal(str(100 + (i % 5))),
        )
        for i in range(40)
    ]
    calc = BollingerBandsCalculator(length=20, multiplier=2.0)
    out = calc.compute(candles)
    m1, u1, l1 = compute_bollinger_bands(
        [float(c.close) for c in candles],
        20,
        2.0,
    )
    assert out["middle"] == m1
    assert out["upper"] == u1
    assert out["lower"] == l1
