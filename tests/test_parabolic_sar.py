from __future__ import annotations

from strat_trade.domain.indicators.parabolic_sar import (
    ParabolicSarCalculator,
    compute_parabolic_sar,
    min_bars_parabolic_sar,
)


def test_min_bars_parabolic_sar() -> None:
    assert min_bars_parabolic_sar() == 2


def test_parabolic_sar_first_bar_none() -> None:
    highs = [10.0, 11.0, 12.0]
    lows = [9.0, 10.0, 10.5]
    out = compute_parabolic_sar(highs, lows, af_start=0.02, af_increment=0.02, af_max=0.2)
    assert out[0] is None
    assert out[1] is not None
    assert out[2] is not None


def test_parabolic_sar_calculator_id() -> None:
    calc = ParabolicSarCalculator()
    assert calc.indicator_id == "parabolic_sar"
