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
    """For `ema_cross`, `indicator_key` is fast EMA; set `slow_indicator_key` for slow EMA."""

    indicator_key: str
    operator: str
    slow_indicator_key: str | None = None


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


def _dedupe_indicator_keys(specs: Sequence[StrategyIndicatorSpec]) -> None:
    seen: set[str] = set()
    for spec in specs:
        if spec.key in seen:
            raise InvalidMarketParametersError(f"Duplicate indicator key {spec.key!r}.")
        seen.add(spec.key)


def _resolve_strategy_indicator_key(
    *,
    strategy_type: str,
    indicators_by_key: Mapping[str, str],
    conditions: Sequence[StrategyConditionSpec],
) -> str:
    if len(conditions) != 1:
        raise InvalidMarketParametersError("MVP strategy currently supports exactly one condition.")
    condition = conditions[0]
    if condition.slow_indicator_key:
        raise InvalidMarketParametersError(
            "`slow_indicator_key` is only used with strategy type `ema_cross` (or composite)."
        )
    st = strategy_type.strip().lower()
    op = condition.operator.strip().lower()

    if st == "psar_reversal":
        if op != "psar_reversal":
            raise InvalidMarketParametersError(
                "For strategy type `psar_reversal`, condition operator must be `psar_reversal`."
            )
        required_id = "psar"
    elif st == "cci_level_cross":
        if op != "cci_level_cross":
            raise InvalidMarketParametersError(
                "For strategy type `cci_level_cross`, condition operator must be `cci_level_cross`."
            )
        required_id = "cci"
    else:
        raise InvalidMarketParametersError(
            "Unsupported strategy type for single-indicator resolution (expected `psar_reversal` or "
            "`cci_level_cross`)."
        )

    indicator_id = indicators_by_key.get(condition.indicator_key)
    if indicator_id is None:
        raise InvalidMarketParametersError(
            f"Condition references unknown indicator key {condition.indicator_key!r}."
        )
    if indicator_id.strip().lower() != required_id:
        raise InvalidMarketParametersError(
            f"Strategy `{st}` requires an indicator with id `{required_id}` for the linked key."
        )
    return condition.indicator_key


def _find_indicator_spec(
    indicators: Sequence[StrategyIndicatorSpec],
    key: str,
) -> StrategyIndicatorSpec:
    for item in indicators:
        if item.key == key:
            return item
    raise InvalidMarketParametersError(f"Unknown indicator key {key!r}.")


def _extract_ema_period_from_params(params: Mapping[str, object]) -> int:
    raw = params.get("period", 20)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise InvalidMarketParametersError("EMA `period` in indicator params must be an integer.")
    return int(raw)


def _validate_fast_slower_period_than_slow(fast: StrategyIndicatorSpec, slow: StrategyIndicatorSpec) -> None:
    if fast.indicator_id.strip().lower() != "ema" or slow.indicator_id.strip().lower() != "ema":
        raise InvalidMarketParametersError("ema_cross requires both indicators with id `ema`.")
    fp = _extract_ema_period_from_params(fast.params)
    sp = _extract_ema_period_from_params(slow.params)
    if fp >= sp:
        raise InvalidMarketParametersError(
            "ema_cross requires fast EMA `period` < slow EMA `period` (from indicator params)."
        )


def _resolve_ema_cross_keys(
    condition: StrategyConditionSpec,
    indicators_by_key: Mapping[str, str],
) -> tuple[str, str]:
    sk_raw = condition.slow_indicator_key
    if sk_raw is None or not str(sk_raw).strip():
        raise InvalidMarketParametersError(
            "ema_cross requires `slow_indicator_key` on the condition (slow EMA instance)."
        )
    fk = condition.indicator_key.strip()
    sk = str(sk_raw).strip()
    if fk == sk:
        raise InvalidMarketParametersError(
            "ema_cross requires two different indicator keys (fast vs slow EMA)."
        )
    for key, label in ((fk, "fast"), (sk, "slow")):
        iid = indicators_by_key.get(key)
        if iid is None:
            raise InvalidMarketParametersError(
                f"Condition references unknown {label} indicator key {key!r}."
            )
        if iid.strip().lower() != "ema":
            raise InvalidMarketParametersError(
                f"ema_cross {label} EMA must use indicator id `ema`, got {iid!r}."
            )
    return fk, sk


def _validate_operator_matches_indicator_id(operator: str, indicator_id: str) -> None:
    op = operator.strip().lower()
    iid = indicator_id.strip().lower()
    if op == "psar_reversal" and iid != "psar":
        raise InvalidMarketParametersError(
            "Operator `psar_reversal` requires an indicator with id `psar`."
        )
    if op == "cci_level_cross" and iid != "cci":
        raise InvalidMarketParametersError(
            "Operator `cci_level_cross` requires an indicator with id `cci`."
        )
    if op not in ("psar_reversal", "cci_level_cross"):
        raise InvalidMarketParametersError(f"Unknown single-indicator condition operator {operator!r}.")


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
    combinator: str | None = None,
    conditions: Sequence[StrategyConditionSpec],
    max_candles_per_request: int,
    max_candles_range_total: int,
    max_candles_range_fetch_rounds: int,
) -> StrategyWinrateResult:
    st = strategy_type.strip().lower()
    if st not in ("psar_reversal", "cci_level_cross", "ema_cross", "composite"):
        raise InvalidMarketParametersError(
            "Unsupported strategy type. Supported: `psar_reversal`, `cci_level_cross`, `ema_cross`, "
            "`composite`."
        )
    if not signal_on_close:
        raise InvalidMarketParametersError("MVP supports only `signal_on_close = true`.")
    if expiry_seconds % timeframe_seconds != 0:
        raise InvalidMarketParametersError(
            "expiry_seconds must be divisible by timeframe_seconds for candle-based expiry."
        )

    _dedupe_indicator_keys(indicators)
    indicators_by_key = {item.key: item.indicator_id for item in indicators}

    page = await fetch_candles_in_range(
        feed,
        asset=asset,
        timeframe_seconds=timeframe_seconds,
        range_start=range_start,
        range_end=range_end,
        max_chunk=max_candles_per_request,
        max_bars_in_range=max_candles_range_total,
        max_fetch_rounds=max_candles_range_fetch_rounds,
    )
    candles = page.candles

    if st == "composite":
        comb = (combinator or "").strip().lower()
        if comb != "all":
            raise InvalidMarketParametersError("Strategy type `composite` requires `combinator=all`.")
        if len(conditions) < 2:
            raise InvalidMarketParametersError(
                "Composite strategy requires at least two conditions (one per indicator)."
            )
        all_keys: list[str] = []
        for c in conditions:
            all_keys.append(c.indicator_key.strip())
            if c.slow_indicator_key:
                all_keys.append(str(c.slow_indicator_key).strip())
        if len(set(all_keys)) != len(all_keys):
            raise InvalidMarketParametersError(
                "Composite strategy requires unique indicator keys across all conditions "
                "(including `slow_indicator_key` for `ema_cross`)."
            )
        signal_lists: list[list[StrategySignal]] = []
        for cond in conditions:
            opn = cond.operator.strip().lower()
            if opn == "ema_cross":
                fk, sk = _resolve_ema_cross_keys(cond, indicators_by_key)
                fast_spec = _find_indicator_spec(indicators, fk)
                slow_spec = _find_indicator_spec(indicators, sk)
                _validate_fast_slower_period_than_slow(fast_spec, slow_spec)
                fast_series = registry.build(fast_spec.indicator_id, fast_spec.params).compute(candles)
                slow_series = registry.build(slow_spec.indicator_id, slow_spec.params).compute(candles)
                signal_lists.append(
                    detect_ema_cross_signals(candles, fast_series.values, slow_series.values)
                )
            else:
                if cond.slow_indicator_key:
                    raise InvalidMarketParametersError(
                        "`slow_indicator_key` is only allowed when operator is `ema_cross`."
                    )
                ind_id = indicators_by_key.get(cond.indicator_key)
                if ind_id is None:
                    raise InvalidMarketParametersError(
                        f"Condition references unknown indicator key {cond.indicator_key!r}."
                    )
                _validate_operator_matches_indicator_id(cond.operator, ind_id)
                spec = _find_indicator_spec(indicators, cond.indicator_key)
                calculator = registry.build(spec.indicator_id, spec.params)
                series = calculator.compute(candles)
                signal_lists.append(signals_for_operator(candles, cond.operator, series.values))
        signals = intersect_strategy_signals(signal_lists)
    elif st == "ema_cross":
        if len(conditions) != 1:
            raise InvalidMarketParametersError("ema_cross strategy requires exactly one condition.")
        cond = conditions[0]
        if cond.operator.strip().lower() != "ema_cross":
            raise InvalidMarketParametersError(
                "For strategy type `ema_cross`, condition operator must be `ema_cross`."
            )
        fk, sk = _resolve_ema_cross_keys(cond, indicators_by_key)
        fast_spec = _find_indicator_spec(indicators, fk)
        slow_spec = _find_indicator_spec(indicators, sk)
        _validate_fast_slower_period_than_slow(fast_spec, slow_spec)
        fast_series = registry.build(fast_spec.indicator_id, fast_spec.params).compute(candles)
        slow_series = registry.build(slow_spec.indicator_id, slow_spec.params).compute(candles)
        signals = detect_ema_cross_signals(candles, fast_series.values, slow_series.values)
    else:
        if conditions[0].slow_indicator_key:
            raise InvalidMarketParametersError(
                "`slow_indicator_key` is only used with strategy type `ema_cross` or composite `ema_cross`."
            )
        indicator_key = _resolve_strategy_indicator_key(
            strategy_type=strategy_type,
            indicators_by_key=indicators_by_key,
            conditions=conditions,
        )
        spec = _find_indicator_spec(indicators, indicator_key)
        calculator = registry.build(spec.indicator_id, spec.params)
        series = calculator.compute(candles)
        signals = signals_for_operator(candles, conditions[0].operator, series.values)
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
