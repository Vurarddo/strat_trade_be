from __future__ import annotations

from strat_trade.domain.indicators.cci import CciCalculator, compute_cci


def test_cci_symmetric_window_zero() -> None:
    """Flat TP → mean deviation 0 → CCI 0."""
    n = 10
    highs = [2.0] * n
    lows = [2.0] * n
    closes = [2.0] * n
    out = compute_cci(highs, lows, closes, length=5)
    assert out[4] == 0.0


def test_cci_three_bar_manual() -> None:
    highs = [4.0, 5.0, 6.0]
    lows = [2.0, 3.0, 4.0]
    closes = [3.0, 4.0, 5.0]
    tp = [3.0, 4.0, 5.0]
    mean_tp = sum(tp) / 3.0
    md = (abs(3.0 - mean_tp) + abs(4.0 - mean_tp) + abs(5.0 - mean_tp)) / 3.0
    expected = (tp[2] - mean_tp) / (0.015 * md)
    out = compute_cci(highs, lows, closes, length=3)
    assert out[2] is not None
    assert abs(out[2] - expected) < 1e-9


def test_cci_calculator() -> None:
    calc = CciCalculator(length=3)
    assert calc.indicator_id == "cci"
