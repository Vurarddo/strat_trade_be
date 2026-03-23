from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import InvalidMarketParametersError
from strat_trade.domain.indicators import IndicatorRegistry
from strat_trade.domain.strategy_testing import SignalSide, StrategySignal, StrategyWinrateResult
from strat_trade.ports.candles import CandleFeed
from strat_trade.use_cases.fetch_candles import fetch_candles_in_range


@dataclass(frozen=True, slots=True)
class StrategyIndicatorSpec:
    key: str
    indicator_id: str
    params: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class StrategyConditionSpec:
    indicator_key: str
    operator: str


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


def _dedupe_indicator_keys(specs: Sequence[StrategyIndicatorSpec]) -> None:
    seen: set[str] = set()
    for spec in specs:
        if spec.key in seen:
            raise InvalidMarketParametersError(f"Duplicate indicator key {spec.key!r}.")
        seen.add(spec.key)


def _resolve_psar_indicator_key(
    *,
    indicators_by_key: Mapping[str, str],
    conditions: Sequence[StrategyConditionSpec],
) -> str:
    if len(conditions) != 1:
        raise InvalidMarketParametersError("MVP strategy currently supports exactly one condition.")
    condition = conditions[0]
    if condition.operator.strip().lower() != "psar_reversal":
        raise InvalidMarketParametersError("Only condition operator `psar_reversal` is supported.")

    indicator_id = indicators_by_key.get(condition.indicator_key)
    if indicator_id is None:
        raise InvalidMarketParametersError(
            f"Condition references unknown indicator key {condition.indicator_key!r}."
        )
    if indicator_id.strip().lower() != "psar":
        raise InvalidMarketParametersError(
            "MVP `psar_reversal` condition requires an indicator with id `psar`."
        )
    return condition.indicator_key


async def run_strategy_winrate_test(
    feed: CandleFeed,
    registry: IndicatorRegistry,
    *,
    asset: str,
    timeframe_seconds: int,
    expiry_seconds: int,
    range_start: datetime,
    range_end: datetime,
    indicators: Sequence[StrategyIndicatorSpec],
    strategy_type: str,
    signal_on_close: bool,
    conditions: Sequence[StrategyConditionSpec],
    max_candles_per_request: int,
    max_candles_range_total: int,
) -> StrategyWinrateResult:
    if strategy_type.strip().lower() != "psar_reversal":
        raise InvalidMarketParametersError("Only strategy type `psar_reversal` is supported in MVP.")
    if not signal_on_close:
        raise InvalidMarketParametersError("MVP supports only `signal_on_close = true`.")
    if expiry_seconds % timeframe_seconds != 0:
        raise InvalidMarketParametersError(
            "expiry_seconds must be divisible by timeframe_seconds for candle-based expiry."
        )

    _dedupe_indicator_keys(indicators)
    indicators_by_key = {item.key: item.indicator_id for item in indicators}
    psar_key = _resolve_psar_indicator_key(indicators_by_key=indicators_by_key, conditions=conditions)

    page = await fetch_candles_in_range(
        feed,
        asset=asset,
        timeframe_seconds=timeframe_seconds,
        range_start=range_start,
        range_end=range_end,
        max_chunk=max_candles_per_request,
        max_bars_in_range=max_candles_range_total,
    )
    candles = page.candles

    psar_spec = next(item for item in indicators if item.key == psar_key)
    psar_calculator = registry.build(psar_spec.indicator_id, psar_spec.params)
    psar_series = psar_calculator.compute(candles)

    signals = detect_psar_reversal_signals(candles, psar_series.values)
    expiry_bars = expiry_seconds // timeframe_seconds
    wins, losses, skipped = evaluate_signal_outcomes(candles, signals, expiry_bars=expiry_bars)
    evaluated = wins + losses
    winrate = (wins / evaluated * 100.0) if evaluated > 0 else 0.0

    return StrategyWinrateResult(
        asset=asset.strip(),
        timeframe_seconds=timeframe_seconds,
        expiry_seconds=expiry_seconds,
        total_signals=len(signals),
        wins=wins,
        losses=losses,
        skipped_signals=skipped,
        winrate_percent=round(winrate, 2),
        period_from=range_start,
        period_to=range_end,
    )
