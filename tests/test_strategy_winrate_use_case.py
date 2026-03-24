from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from strat_trade.domain.entities import Candle
from strat_trade.domain.strategy_testing import SignalSide, StrategySignal
from strat_trade.use_cases.test_strategy_winrate import (
    detect_cci_level_cross_signals,
    detect_ema_cross_signals,
    detect_macd_signal_cross_signals,
    detect_psar_reversal_signals,
    detect_rsi_threshold_signals,
    detect_stochastic_dual_threshold_signals,
    detect_ema_cross_or_trend_signals,
    evaluate_signal_outcomes,
    intersect_strategy_signals,
)

_BASE = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)


def _candle(i: int, close: str) -> Candle:
    return Candle(
        open_time=_BASE + timedelta(seconds=15 * i),
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=Decimal("10"),
    )


def test_detect_psar_reversal_signals_buy_and_sell() -> None:
    candles = [
        _candle(0, "100"),
        _candle(1, "101"),
        _candle(2, "99"),
        _candle(3, "100"),
    ]
    psar = [102.0, 100.0, 98.0, 101.0]

    signals = detect_psar_reversal_signals(candles, psar)

    assert len(signals) == 2
    assert signals[0].index == 1
    assert signals[0].side is SignalSide.BUY
    assert signals[1].index == 3
    assert signals[1].side is SignalSide.SELL


def test_detect_cci_level_cross_buy_crosses_100() -> None:
    candles = [_candle(i, "100") for i in range(4)]
    cci = [50.0, 99.0, 100.0, 120.0]

    signals = detect_cci_level_cross_signals(candles, cci)

    assert len(signals) == 1
    assert signals[0].index == 2
    assert signals[0].side is SignalSide.BUY
    assert signals[0].entry_close == 100.0


def test_detect_cci_level_cross_buy_exactly_at_100() -> None:
    """cci[i] >= 100 includes equality on the crossing bar."""
    candles = [_candle(i, "1") for i in range(3)]
    cci = [0.0, 99.0, 100.0]

    signals = detect_cci_level_cross_signals(candles, cci)

    assert len(signals) == 1
    assert signals[0].index == 2
    assert signals[0].side is SignalSide.BUY


def test_detect_cci_level_cross_no_buy_when_stays_above_100() -> None:
    candles = [_candle(i, "1") for i in range(3)]
    cci = [101.0, 102.0, 103.0]

    assert detect_cci_level_cross_signals(candles, cci) == []


def test_detect_cci_level_cross_no_buy_when_prev_already_at_or_above_100() -> None:
    candles = [_candle(i, "1") for i in range(3)]
    cci = [100.0, 100.0, 105.0]

    assert detect_cci_level_cross_signals(candles, cci) == []


def test_detect_cci_level_cross_sell_crosses_minus_100() -> None:
    candles = [_candle(i, "1") for i in range(4)]
    cci = [0.0, 50.0, -100.0, -150.0]

    signals = detect_cci_level_cross_signals(candles, cci)

    assert len(signals) == 1
    assert signals[0].index == 2
    assert signals[0].side is SignalSide.SELL


def test_detect_cci_level_cross_sell_exactly_at_minus_100() -> None:
    candles = [_candle(i, "1") for i in range(3)]
    cci = [0.0, 0.0, -100.0]

    signals = detect_cci_level_cross_signals(candles, cci)

    assert len(signals) == 1
    assert signals[0].index == 2
    assert signals[0].side is SignalSide.SELL


def test_detect_cci_level_cross_no_sell_when_prev_already_at_or_below_minus_100() -> None:
    candles = [_candle(i, "1") for i in range(3)]
    cci = [-100.0, -120.0, -130.0]

    assert detect_cci_level_cross_signals(candles, cci) == []


def test_detect_cci_level_cross_skips_bar_when_prev_cci_none() -> None:
    """Skip comparison at i when cci[i-1] is None (even if cci[i] would cross +100)."""
    candles = [_candle(i, "1") for i in range(3)]
    cci = [50.0, None, 100.0]

    signals = detect_cci_level_cross_signals(candles, cci)

    assert signals == []


def test_detect_cci_level_cross_skips_bar_when_curr_cci_none() -> None:
    candles = [_candle(i, "1") for i in range(3)]
    cci = [50.0, 99.0, None]

    assert detect_cci_level_cross_signals(candles, cci) == []


def test_detect_ema_cross_bullish_strict() -> None:
    candles = [_candle(i, "1") for i in range(5)]
    fast = [None, None, 1.0, 2.0, 5.0]
    slow = [None, None, 5.0, 4.0, 3.0]

    signals = detect_ema_cross_signals(candles, fast, slow)

    assert len(signals) == 1
    assert signals[0].index == 4
    assert signals[0].side is SignalSide.BUY


def test_detect_ema_cross_bearish_strict() -> None:
    candles = [_candle(i, "1") for i in range(5)]
    fast = [None, None, 5.0, 4.0, 2.0]
    slow = [None, None, 1.0, 3.0, 4.0]

    signals = detect_ema_cross_signals(candles, fast, slow)

    assert len(signals) == 1
    assert signals[0].index == 4
    assert signals[0].side is SignalSide.SELL


def test_detect_ema_cross_no_signal_when_fast_stays_below() -> None:
    candles = [_candle(i, "1") for i in range(4)]
    fast = [1.0, 1.0, 1.0, 1.0]
    slow = [2.0, 2.0, 2.0, 2.0]

    assert detect_ema_cross_signals(candles, fast, slow) == []


def test_detect_ema_cross_skips_when_any_value_none() -> None:
    candles = [_candle(i, "1") for i in range(4)]
    fast = [None, 1.0, 2.0, None]
    slow = [None, 5.0, 4.0, 3.0]

    assert detect_ema_cross_signals(candles, fast, slow) == []


def test_detect_ema_cross_equality_on_prev_bar_no_strict_cross() -> None:
    """fast[i-1] == slow[i-1] does not satisfy fast[i-1] < slow[i-1] (bullish)."""
    candles = [_candle(i, "1") for i in range(4)]
    fast = [1.0, 2.0, 2.0, 5.0]
    slow = [1.0, 2.0, 2.0, 3.0]

    assert detect_ema_cross_signals(candles, fast, slow) == []


def test_detect_rsi_threshold_signals_buy_and_sell() -> None:
    candles = [_candle(i, "1") for i in range(4)]
    rsi = [10.0, 50.0, 90.0, None]
    signals = detect_rsi_threshold_signals(candles, rsi, lower=18.0, upper=82.0)
    assert len(signals) == 2
    assert signals[0].side is SignalSide.BUY
    assert signals[1].side is SignalSide.SELL


def test_detect_stochastic_dual_threshold_signals() -> None:
    candles = [_candle(i, "1") for i in range(4)]
    k = [10.0, 20.0, 90.0, None]
    d = [12.0, 30.0, 95.0, 80.0]
    signals = detect_stochastic_dual_threshold_signals(candles, k, d, lower=15.0, upper=85.0)
    assert len(signals) == 2
    assert signals[0].side is SignalSide.BUY
    assert signals[1].side is SignalSide.SELL


def test_detect_ema_cross_or_trend_with_gap_filter() -> None:
    candles = [_candle(i, "1") for i in range(4)]
    fast = [None, 1.0, 2.0, 10.0]
    slow = [None, 2.0, 1.0, 1.0]
    signals = detect_ema_cross_or_trend_signals(
        candles,
        fast,
        slow,
        max_ema_separation=5.0,
    )
    # idx=2 -> BUY (cross), idx=3 filtered out by separation=9
    assert len(signals) == 1
    assert signals[0].index == 2 and signals[0].side is SignalSide.BUY


def test_detect_macd_signal_cross_buy_below_zero() -> None:
    candles = [_candle(i, "1") for i in range(4)]
    macd_line = [0.0, -2.0, -0.2, 0.0]
    signal_line = [0.0, -1.5, -0.3, 0.0]

    signals = detect_macd_signal_cross_signals(candles, macd_line, signal_line)

    assert len(signals) == 1
    assert signals[0].index == 2
    assert signals[0].side is SignalSide.BUY


def test_detect_macd_signal_cross_sell_above_zero() -> None:
    candles = [_candle(i, "1") for i in range(4)]
    macd_line = [0.0, 2.0, 0.2, 0.0]
    signal_line = [0.0, 1.5, 0.3, 0.0]

    signals = detect_macd_signal_cross_signals(candles, macd_line, signal_line)

    assert len(signals) == 1
    assert signals[0].index == 2
    assert signals[0].side is SignalSide.SELL


def test_detect_macd_signal_cross_no_signal_when_bullish_not_both_negative() -> None:
    """Bullish cross but lines straddle zero → half-plane filter rejects (no BUY)."""
    candles = [_candle(i, "1") for i in range(4)]
    macd_line = [0.0, -0.5, 0.1, 0.0]
    signal_line = [0.0, -0.4, -0.05, 0.0]

    assert detect_macd_signal_cross_signals(candles, macd_line, signal_line) == []


def test_detect_macd_signal_cross_no_signal_when_line_is_zero() -> None:
    """Exactly zero on a line fails strict `< 0` / `> 0` half-plane checks."""
    candles = [_candle(i, "1") for i in range(4)]
    macd_line = [0.0, -1.0, 0.0, 0.0]
    signal_line = [0.0, -2.0, -0.1, 0.0]

    assert detect_macd_signal_cross_signals(candles, macd_line, signal_line) == []


def test_detect_macd_signal_cross_skips_when_any_value_none() -> None:
    candles = [_candle(i, "1") for i in range(4)]
    macd_line = [0.0, -2.0, -0.2, 0.0]
    signal_line = [0.0, -1.5, None, 0.0]

    assert detect_macd_signal_cross_signals(candles, macd_line, signal_line) == []


def test_intersect_macd_and_psar_only_when_same_index_and_side() -> None:
    """Composite AND: MACD list + PSAR list must agree on (index, side)."""
    macd_buy = StrategySignal(index=2, side=SignalSide.BUY, open_time=_BASE, entry_close=1.0)
    psar_buy = StrategySignal(index=2, side=SignalSide.BUY, open_time=_BASE, entry_close=1.0)
    psar_late = StrategySignal(index=3, side=SignalSide.BUY, open_time=_BASE, entry_close=1.0)

    assert len(intersect_strategy_signals([[macd_buy], [psar_buy]])) == 1
    assert intersect_strategy_signals([[macd_buy], [psar_late]]) == []


def test_intersect_strategy_signals_same_bar_and_side() -> None:
    s2_buy = StrategySignal(index=2, side=SignalSide.BUY, open_time=_BASE, entry_close=1.0)
    a = [s2_buy]
    b = [StrategySignal(index=2, side=SignalSide.BUY, open_time=_BASE, entry_close=1.0)]
    out = intersect_strategy_signals([a, b])
    assert len(out) == 1
    assert out[0] is s2_buy


def test_intersect_strategy_signals_empty_when_side_differs() -> None:
    a = [StrategySignal(index=2, side=SignalSide.BUY, open_time=_BASE, entry_close=1.0)]
    b = [StrategySignal(index=2, side=SignalSide.SELL, open_time=_BASE, entry_close=1.0)]
    assert intersect_strategy_signals([a, b]) == []


def test_intersect_strategy_signals_three_lists() -> None:
    s = StrategySignal(index=1, side=SignalSide.SELL, open_time=_BASE, entry_close=5.0)
    assert len(intersect_strategy_signals([[s], [s], [s]])) == 1


def test_detect_cci_level_cross_buy_and_sell_same_series() -> None:
    candles = [_candle(i, "1") for i in range(6)]
    cci = [0.0, 90.0, 105.0, 0.0, -50.0, -120.0]

    signals = detect_cci_level_cross_signals(candles, cci)

    assert len(signals) == 2
    assert signals[0].index == 2 and signals[0].side is SignalSide.BUY
    assert signals[1].index == 5 and signals[1].side is SignalSide.SELL


def test_evaluate_signal_outcomes_with_skipped_and_tie_loss() -> None:
    candles = [
        _candle(0, "100"),
        _candle(1, "101"),
        _candle(2, "101"),
        _candle(3, "100"),
    ]
    signals = [
        StrategySignal(index=1, side=SignalSide.BUY, open_time=candles[1].open_time, entry_close=101.0),
        StrategySignal(index=2, side=SignalSide.SELL, open_time=candles[2].open_time, entry_close=101.0),
        StrategySignal(index=3, side=SignalSide.BUY, open_time=candles[3].open_time, entry_close=102.0),
    ]

    wins, losses, skipped = evaluate_signal_outcomes(candles, signals, expiry_bars=1)

    assert wins == 1
    assert losses == 1
    assert skipped == 1
