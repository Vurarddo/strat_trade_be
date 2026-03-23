from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from strat_trade.domain.entities import Candle
from strat_trade.domain.strategy_testing import SignalSide, StrategySignal
from strat_trade.use_cases.test_strategy_winrate import (
    detect_psar_reversal_signals,
    evaluate_signal_outcomes,
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
