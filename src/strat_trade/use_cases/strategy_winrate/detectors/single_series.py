from __future__ import annotations

from collections.abc import Sequence

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import InvalidMarketParametersError
from strat_trade.domain.strategy_testing import SignalSide, StrategySignal


def detect_psar_reversal_signals(
    candles: Sequence[Candle],
    psar_values: Sequence[float | None],
) -> list[StrategySignal]:
    if len(candles) != len(psar_values):
        raise InvalidMarketParametersError(
            "PSAR series length must match candle count for strategy evaluation."
        )
    if len(candles) < 2:
        return []

    signals: list[StrategySignal] = []
    for idx in range(1, len(candles)):
        prev_psar = psar_values[idx - 1]
        curr_psar = psar_values[idx]
        if prev_psar is None or curr_psar is None:
            continue

        prev_close = float(candles[idx - 1].close)
        curr_close = float(candles[idx].close)

        prev_psar_above = prev_psar > prev_close
        curr_psar_above = curr_psar > curr_close
        if prev_psar_above and not curr_psar_above:
            signals.append(
                StrategySignal(
                    index=idx,
                    side=SignalSide.BUY,
                    open_time=candles[idx].open_time,
                    entry_close=curr_close,
                )
            )
        elif (not prev_psar_above) and curr_psar_above:
            signals.append(
                StrategySignal(
                    index=idx,
                    side=SignalSide.SELL,
                    open_time=candles[idx].open_time,
                    entry_close=curr_close,
                )
            )
    return signals


def detect_cci_level_cross_signals(
    candles: Sequence[Candle],
    cci_values: Sequence[float | None],
) -> list[StrategySignal]:
    """BUY: cross +100 from below (cci[i-1] < 100 and cci[i] >= 100). SELL: cross -100 from above."""
    if len(candles) != len(cci_values):
        raise InvalidMarketParametersError(
            "CCI series length must match candle count for strategy evaluation."
        )
    if len(candles) < 2:
        return []

    signals: list[StrategySignal] = []
    for idx in range(1, len(candles)):
        prev_cci = cci_values[idx - 1]
        curr_cci = cci_values[idx]
        if prev_cci is None or curr_cci is None:
            continue

        curr_close = float(candles[idx].close)
        if prev_cci < 100 and curr_cci >= 100:
            signals.append(
                StrategySignal(
                    index=idx,
                    side=SignalSide.BUY,
                    open_time=candles[idx].open_time,
                    entry_close=curr_close,
                )
            )
        elif prev_cci > -100 and curr_cci <= -100:
            signals.append(
                StrategySignal(
                    index=idx,
                    side=SignalSide.SELL,
                    open_time=candles[idx].open_time,
                    entry_close=curr_close,
                )
            )
    return signals


def detect_rsi_threshold_signals(
    candles: Sequence[Candle],
    rsi_values: Sequence[float | None],
    *,
    lower: float,
    upper: float,
) -> list[StrategySignal]:
    if len(candles) != len(rsi_values):
        raise InvalidMarketParametersError("RSI series length must match candle count.")
    signals: list[StrategySignal] = []
    for idx, rsi in enumerate(rsi_values):
        if rsi is None:
            continue
        close = float(candles[idx].close)
        if rsi < lower:
            signals.append(
                StrategySignal(
                    index=idx,
                    side=SignalSide.BUY,
                    open_time=candles[idx].open_time,
                    entry_close=close,
                )
            )
        elif rsi > upper:
            signals.append(
                StrategySignal(
                    index=idx,
                    side=SignalSide.SELL,
                    open_time=candles[idx].open_time,
                    entry_close=close,
                )
            )
    return signals


def signals_for_operator(
    candles: Sequence[Candle],
    operator: str,
    series_values: Sequence[float | None],
) -> list[StrategySignal]:
    op = operator.strip().lower()
    if op == "psar_reversal":
        return detect_psar_reversal_signals(candles, series_values)
    if op == "cci_level_cross":
        return detect_cci_level_cross_signals(candles, series_values)
    raise InvalidMarketParametersError(
        f"Unknown single-series condition operator {operator!r} (ema_cross uses two series)."
    )
