from __future__ import annotations

from strat_trade.domain.entities import Candle
from strat_trade.domain.indicators.stochastic import (
    StochasticCalculator,
    compute_stochastic,
    min_bars_stochastic,
)


def test_min_bars_stochastic_default() -> None:
    assert min_bars_stochastic(14, 3, 1) == 16


def test_stochastic_flat_range_k_50() -> None:
    highs = [2.0] * 10
    lows = [2.0] * 10
    closes = [2.0] * 10
    k, d = compute_stochastic(highs, lows, closes, k_length=5, d_length=2, smooth_k=1)
    assert k[4] == 50.0
    assert d[5] == 50.0


def test_stochastic_three_bar_window() -> None:
    highs = [3.0, 4.0, 5.0, 4.0]
    lows = [1.0, 2.0, 3.0, 2.0]
    closes = [2.0, 3.0, 4.0, 3.5]
    k, d = compute_stochastic(highs, lows, closes, k_length=3, d_length=2, smooth_k=1)
    # i=2: window [0..2] hi=5, lo=1, close=4 -> 100*(4-1)/(5-1)=75
    assert k[2] is not None and abs(k[2] - 75.0) < 1e-9
    assert d[3] is not None and abs(d[3] - (k[2] + k[3]) / 2.0) < 1e-9


def test_stochastic_calculator_matches_compute() -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    base = datetime(2025, 1, 1, tzinfo=UTC)
    candles = [
        Candle(
            open_time=base,
            open=Decimal("1"),
            high=Decimal(str(h)),
            low=Decimal(str(lo)),
            close=Decimal(str(c)),
            volume=Decimal("1"),
        )
        for h, lo, c in zip([3, 4, 5, 4], [1, 2, 3, 2], [2, 3, 4, 3.5], strict=True)
    ]
    calc = StochasticCalculator(k_length=3, d_length=2, smooth_k=1)
    out = calc.compute(candles)
    k2, d2 = compute_stochastic(
        [3.0, 4.0, 5.0, 4.0],
        [1.0, 2.0, 3.0, 2.0],
        [2.0, 3.0, 4.0, 3.5],
        k_length=3,
        d_length=2,
        smooth_k=1,
    )
    assert out["k"] == k2
    assert out["d"] == d2
