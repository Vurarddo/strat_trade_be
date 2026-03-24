from __future__ import annotations

from collections.abc import Sequence

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import InvalidMarketParametersError
from strat_trade.domain.strategy_testing import SignalSide, StrategySignal


def evaluate_signal_outcomes(
    candles: Sequence[Candle],
    signals: Sequence[StrategySignal],
    *,
    expiry_bars: int,
) -> tuple[int, int, int]:
    if expiry_bars < 1:
        raise InvalidMarketParametersError("expiry_seconds / timeframe_seconds must be >= 1.")

    wins = 0
    losses = 0
    skipped = 0
    for signal in signals:
        target_index = signal.index + expiry_bars
        if target_index >= len(candles):
            skipped += 1
            continue

        expiry_close = float(candles[target_index].close)
        entry_close = signal.entry_close
        if signal.side is SignalSide.BUY:
            is_win = expiry_close > entry_close
        else:
            is_win = expiry_close < entry_close

        if is_win:
            wins += 1
        else:
            losses += 1
    return wins, losses, skipped


def intersect_strategy_signals(signal_lists: list[list[StrategySignal]]) -> list[StrategySignal]:
    """
    Keep only (bar index, side) pairs present in every list. Entry metadata is taken from the first list.
    """
    if not signal_lists:
        return []
    maps: list[dict[tuple[int, SignalSide], StrategySignal]] = []
    for lst in signal_lists:
        maps.append({(s.index, s.side): s for s in lst})
    common = set(maps[0])
    for m in maps[1:]:
        common &= set(m)
    ordered = sorted(common, key=lambda k: (k[0], k[1].value))
    return [maps[0][k] for k in ordered]
