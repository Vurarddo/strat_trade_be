from __future__ import annotations

from collections.abc import Mapping, Sequence

from strat_trade.domain.errors import InvalidMarketParametersError
from strat_trade.use_cases.strategy_winrate.specs import StrategyConditionSpec, StrategyIndicatorSpec


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


def _validate_macd_line_signal_pair(fast_spec: StrategyIndicatorSpec, slow_spec: StrategyIndicatorSpec) -> None:
    if (
        fast_spec.indicator_id.strip().lower() != "macd"
        or slow_spec.indicator_id.strip().lower() != "macd"
    ):
        raise InvalidMarketParametersError("macd_signal_cross requires both indicators with id `macd`.")
    mc = str(fast_spec.params.get("component", "")).strip().lower()
    sc = str(slow_spec.params.get("component", "")).strip().lower()
    if mc != "macd" or sc != "signal":
        raise InvalidMarketParametersError(
            "macd_signal_cross requires `indicator_key` to be MACD line (`component='macd'`) "
            "and `slow_indicator_key` to be signal line (`component='signal'`)."
        )
    for name in ("fast_period", "slow_period", "signal_period"):
        if fast_spec.params.get(name) != slow_spec.params.get(name):
            raise InvalidMarketParametersError(
                f"macd_signal_cross: MACD line and signal must share the same `{name}` in params."
            )


def _resolve_macd_signal_keys(
    condition: StrategyConditionSpec,
    indicators_by_key: Mapping[str, str],
) -> tuple[str, str]:
    sk_raw = condition.slow_indicator_key
    if sk_raw is None or not str(sk_raw).strip():
        raise InvalidMarketParametersError(
            "macd_signal_cross requires `slow_indicator_key` on the condition (signal line instance)."
        )
    fk = condition.indicator_key.strip()
    sk = str(sk_raw).strip()
    if fk == sk:
        raise InvalidMarketParametersError(
            "macd_signal_cross requires two different indicator keys (MACD line vs signal line)."
        )
    for key, label in ((fk, "macd_line"), (sk, "signal_line")):
        iid = indicators_by_key.get(key)
        if iid is None:
            raise InvalidMarketParametersError(
                f"Condition references unknown {label} indicator key {key!r}."
            )
        if iid.strip().lower() != "macd":
            raise InvalidMarketParametersError(
                f"macd_signal_cross {label} must use indicator id `macd`, got {iid!r}."
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
    if op == "rsi_threshold" and iid != "rsi":
        raise InvalidMarketParametersError("Operator `rsi_threshold` requires indicator id `rsi`.")
    if op not in ("psar_reversal", "cci_level_cross", "rsi_threshold"):
        raise InvalidMarketParametersError(f"Unknown single-indicator condition operator {operator!r}.")


def _number_param(params: Mapping[str, object], key: str, *, default: float) -> float:
    raw = params.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise InvalidMarketParametersError(f"Condition param `{key}` must be a number.")
    return float(raw)
