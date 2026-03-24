from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from strat_trade.domain.errors import InvalidMarketParametersError
from strat_trade.domain.indicators import IndicatorRegistry
from strat_trade.domain.strategy_testing import StrategySignal, StrategyWinrateResult
from strat_trade.ports.candles import CandleFeed
from strat_trade.use_cases.fetch_candles import fetch_candles_in_range
from strat_trade.use_cases.strategy_winrate.detectors.dual_series import (
    detect_ema_cross_or_trend_signals,
    detect_ema_cross_signals,
    detect_macd_signal_cross_signals,
    detect_stochastic_dual_threshold_signals,
)
from strat_trade.use_cases.strategy_winrate.detectors.single_series import (
    detect_rsi_threshold_signals,
    signals_for_operator,
)
from strat_trade.use_cases.strategy_winrate.evaluation import (
    evaluate_signal_outcomes,
    intersect_strategy_signals,
)
from strat_trade.use_cases.strategy_winrate.specs import StrategyConditionSpec, StrategyIndicatorSpec
from strat_trade.use_cases.strategy_winrate.validation import (
    _dedupe_indicator_keys,
    _find_indicator_spec,
    _number_param,
    _resolve_ema_cross_keys,
    _resolve_macd_signal_keys,
    _resolve_strategy_indicator_key,
    _validate_fast_slower_period_than_slow,
    _validate_macd_line_signal_pair,
    _validate_operator_matches_indicator_id,
)


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
            elif opn == "ema_cross_or_trend":
                fk, sk = _resolve_ema_cross_keys(cond, indicators_by_key)
                fast_spec = _find_indicator_spec(indicators, fk)
                slow_spec = _find_indicator_spec(indicators, sk)
                _validate_fast_slower_period_than_slow(fast_spec, slow_spec)
                fast_series = registry.build(fast_spec.indicator_id, fast_spec.params).compute(candles)
                slow_series = registry.build(slow_spec.indicator_id, slow_spec.params).compute(candles)
                signal_lists.append(
                    detect_ema_cross_or_trend_signals(
                        candles,
                        fast_series.values,
                        slow_series.values,
                        max_ema_separation=(
                            _number_param(cond.params, "max_ema_separation", default=1e18)
                            if "max_ema_separation" in cond.params
                            else None
                        ),
                    )
                )
            elif opn == "stochastic_dual_threshold":
                d_key = (cond.slow_indicator_key or "").strip()
                if not d_key:
                    raise InvalidMarketParametersError(
                        "stochastic_dual_threshold requires `slow_indicator_key` for D component."
                    )
                k_key = cond.indicator_key.strip()
                if k_key == d_key:
                    raise InvalidMarketParametersError(
                        "stochastic_dual_threshold requires different keys for K and D."
                    )
                k_spec = _find_indicator_spec(indicators, k_key)
                d_spec = _find_indicator_spec(indicators, d_key)
                if (
                    k_spec.indicator_id.strip().lower() != "stochastic"
                    or d_spec.indicator_id.strip().lower() != "stochastic"
                ):
                    raise InvalidMarketParametersError(
                        "stochastic_dual_threshold requires stochastic indicators for K and D keys."
                    )
                k_component = str(k_spec.params.get("component", "")).strip().lower()
                d_component = str(d_spec.params.get("component", "")).strip().lower()
                if k_component != "k" or d_component != "d":
                    raise InvalidMarketParametersError(
                        "stochastic_dual_threshold requires K indicator with component='k' and D with component='d'."
                    )
                k_series = registry.build(k_spec.indicator_id, k_spec.params).compute(candles)
                d_series = registry.build(d_spec.indicator_id, d_spec.params).compute(candles)
                signal_lists.append(
                    detect_stochastic_dual_threshold_signals(
                        candles,
                        k_series.values,
                        d_series.values,
                        lower=_number_param(cond.params, "lower", default=15.0),
                        upper=_number_param(cond.params, "upper", default=85.0),
                    )
                )
            elif opn == "macd_signal_cross":
                fk, sk = _resolve_macd_signal_keys(cond, indicators_by_key)
                m_spec = _find_indicator_spec(indicators, fk)
                s_spec = _find_indicator_spec(indicators, sk)
                _validate_macd_line_signal_pair(m_spec, s_spec)
                m_series = registry.build(m_spec.indicator_id, m_spec.params).compute(candles)
                s_series = registry.build(s_spec.indicator_id, s_spec.params).compute(candles)
                signal_lists.append(
                    detect_macd_signal_cross_signals(candles, m_series.values, s_series.values)
                )
            else:
                if cond.slow_indicator_key:
                    raise InvalidMarketParametersError(
                        "`slow_indicator_key` is only allowed for `ema_cross`, "
                        "`stochastic_dual_threshold`, `ema_cross_or_trend`, or `macd_signal_cross`."
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
                if opn == "rsi_threshold":
                    signal_lists.append(
                        detect_rsi_threshold_signals(
                            candles,
                            series.values,
                            lower=_number_param(cond.params, "lower", default=18.0),
                            upper=_number_param(cond.params, "upper", default=82.0),
                        )
                    )
                else:
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
                "`slow_indicator_key` is only used with strategy type `ema_cross` or composite dual-series "
                "operators (`ema_cross`, `stochastic_dual_threshold`, `ema_cross_or_trend`, `macd_signal_cross`)."
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
