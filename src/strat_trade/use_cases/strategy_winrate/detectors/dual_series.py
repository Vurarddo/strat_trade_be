from __future__ import annotations

from collections.abc import Sequence

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import InvalidMarketParametersError
from strat_trade.domain.strategy_testing import SignalSide, StrategySignal


def detect_ema_cross_signals(
    candles: Sequence[Candle],
    fast_values: Sequence[float | None],
    slow_values: Sequence[float | None],
) -> list[StrategySignal]:
    """
    EMA cross on bar close (index i), **strict** inequalities.

    - **BUY**: fast was below slow on the previous bar and above on this bar:
      ``fast[i-1] < slow[i-1]`` and ``fast[i] > slow[i]``.
    - **SELL**: ``fast[i-1] > slow[i-1]`` and ``fast[i] < slow[i]``.

    If any of ``fast[i-1], fast[i], slow[i-1], slow[i]`` is None, skip that bar.
    """
    if len(candles) != len(fast_values) or len(candles) != len(slow_values):
        raise InvalidMarketParametersError(
            "Fast and slow EMA series lengths must match candle count for strategy evaluation."
        )
    if len(candles) < 2:
        return []

    signals: list[StrategySignal] = []
    for idx in range(1, len(candles)):
        pf, cf = fast_values[idx - 1], fast_values[idx]
        ps, cs = slow_values[idx - 1], slow_values[idx]
        if pf is None or cf is None or ps is None or cs is None:
            continue

        curr_close = float(candles[idx].close)
        if pf < ps and cf > cs:
            signals.append(
                StrategySignal(
                    index=idx,
                    side=SignalSide.BUY,
                    open_time=candles[idx].open_time,
                    entry_close=curr_close,
                )
            )
        elif pf > ps and cf < cs:
            signals.append(
                StrategySignal(
                    index=idx,
                    side=SignalSide.SELL,
                    open_time=candles[idx].open_time,
                    entry_close=curr_close,
                )
            )
    return signals


def detect_macd_signal_cross_signals(
    candles: Sequence[Candle],
    macd_line: Sequence[float | None],
    signal_line: Sequence[float | None],
) -> list[StrategySignal]:
    """
    MACD line vs signal line cross on bar close (index ``i``), with **zero half-plane** filters.

    - **BUY**: bullish cross ``macd[i-1] < signal[i-1]`` and ``macd[i] > signal[i]``, and on the
      crossing bar both lines are **strictly below zero**: ``macd[i] < 0`` and ``signal[i] < 0``.
    - **SELL**: bearish cross ``macd[i-1] > signal[i-1]`` and ``macd[i] < signal[i]``, and
      ``macd[i] > 0`` and ``signal[i] > 0``.

    If any of the four samples at ``i-1``/``i`` is ``None``, skip the bar.

    **Ambiguous zero / straddle:** if after a detected cross the half-plane rules are not met
    (e.g. one line is ``<= 0`` while the other is ``>= 0``, or either line is exactly ``0``),
    **no signal** is emitted for that bar.
    """
    if len(candles) != len(macd_line) or len(candles) != len(signal_line):
        raise InvalidMarketParametersError(
            "MACD and signal series lengths must match candle count for strategy evaluation."
        )
    if len(candles) < 2:
        return []

    signals: list[StrategySignal] = []
    for idx in range(1, len(candles)):
        pm, cm = macd_line[idx - 1], macd_line[idx]
        ps, cs = signal_line[idx - 1], signal_line[idx]
        if pm is None or cm is None or ps is None or cs is None:
            continue

        curr_close = float(candles[idx].close)
        bullish_cross = pm < ps and cm > cs
        bearish_cross = pm > ps and cm < cs
        if not bullish_cross and not bearish_cross:
            continue

        if bullish_cross:
            if cm < 0 and cs < 0:
                signals.append(
                    StrategySignal(
                        index=idx,
                        side=SignalSide.BUY,
                        open_time=candles[idx].open_time,
                        entry_close=curr_close,
                    )
                )
        elif bearish_cross:
            if cm > 0 and cs > 0:
                signals.append(
                    StrategySignal(
                        index=idx,
                        side=SignalSide.SELL,
                        open_time=candles[idx].open_time,
                        entry_close=curr_close,
                    )
                )
    return signals


def detect_stochastic_dual_threshold_signals(
    candles: Sequence[Candle],
    k_values: Sequence[float | None],
    d_values: Sequence[float | None],
    *,
    lower: float,
    upper: float,
) -> list[StrategySignal]:
    if len(candles) != len(k_values) or len(candles) != len(d_values):
        raise InvalidMarketParametersError("Stochastic K/D series lengths must match candle count.")
    signals: list[StrategySignal] = []
    for idx in range(len(candles)):
        k = k_values[idx]
        d = d_values[idx]
        if k is None or d is None:
            continue
        close = float(candles[idx].close)
        if k < lower and d < lower:
            signals.append(
                StrategySignal(
                    index=idx,
                    side=SignalSide.BUY,
                    open_time=candles[idx].open_time,
                    entry_close=close,
                )
            )
        elif k > upper and d > upper:
            signals.append(
                StrategySignal(
                    index=idx,
                    side=SignalSide.SELL,
                    open_time=candles[idx].open_time,
                    entry_close=close,
                )
            )
    return signals


def detect_ema_cross_or_trend_signals(
    candles: Sequence[Candle],
    fast_values: Sequence[float | None],
    slow_values: Sequence[float | None],
    *,
    max_ema_separation: float | None,
) -> list[StrategySignal]:
    if len(candles) != len(fast_values) or len(candles) != len(slow_values):
        raise InvalidMarketParametersError("Fast/slow EMA series lengths must match candle count.")
    if max_ema_separation is not None and max_ema_separation < 0:
        raise InvalidMarketParametersError("max_ema_separation must be >= 0.")

    signals: list[StrategySignal] = []
    for idx in range(1, len(candles)):
        pf, cf = fast_values[idx - 1], fast_values[idx]
        ps, cs = slow_values[idx - 1], slow_values[idx]
        if pf is None or cf is None or ps is None or cs is None:
            continue
        if max_ema_separation is not None and abs(cf - cs) > max_ema_separation:
            continue

        bullish_cross = pf < ps and cf > cs
        bearish_cross = pf > ps and cf < cs
        bullish_trend = cf > cs
        bearish_trend = cf < cs
        close = float(candles[idx].close)

        if bullish_cross or bullish_trend:
            signals.append(
                StrategySignal(
                    index=idx,
                    side=SignalSide.BUY,
                    open_time=candles[idx].open_time,
                    entry_close=close,
                )
            )
        elif bearish_cross or bearish_trend:
            signals.append(
                StrategySignal(
                    index=idx,
                    side=SignalSide.SELL,
                    open_time=candles[idx].open_time,
                    entry_close=close,
                )
            )
    return signals
