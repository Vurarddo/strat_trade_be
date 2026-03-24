from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable summary.")
    details: dict = Field(default_factory=dict, description="Optional structured context.")


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


def _ema_period_int_for_validation(params: dict[str, Any]) -> int:
    raw = params.get("period", 20)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError("EMA `period` in indicator params must be an integer for ema_cross validation.")
    return int(raw)


def _macd_period_int_for_validation(params: dict[str, Any], name: str, *, default: int) -> int:
    raw = params.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"MACD `{name}` in indicator params must be an integer for macd_signal_cross validation.")
    return int(raw)


class BalanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: float = Field(description="Balance in account currency.")
    currency: str = Field(
        description="ISO currency code or broker-specific label.",
        examples=["USD"],
    )
    is_demo: bool = Field(description="True if the balance refers to a demo wallet.")


class CandleBarResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open_time: datetime = Field(
        description="Candle open time (as returned by the broker; treat as UTC if naive)."
    )
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


class CandlesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str = Field(description="Broker symbol, e.g. EURUSD_otc.")
    timeframe_seconds: int = Field(
        description="Bar width in seconds (e.g. 60 = 1m, 300 = 5m).",
        examples=[60, 300, 3600],
    )
    candles: list[CandleBarResponse]
    has_more: bool = Field(
        description=(
            "`GET /market/candles`: another page exists; pass `next_cursor` as `cursor`. "
            "`GET /market/candles/range`: always false (full range in one response)."
        ),
    )
    next_cursor: datetime | None = Field(
        description=(
            "`GET /market/candles`: when `has_more`, oldest bar `open_time` on this page — pass as "
            "`cursor` for the next older chunk. "
            "`GET /market/candles/range`: always null."
        ),
    )
    total: int | None = Field(
        None,
        description=(
            "Only for /market/candles/range: bar count in [from, to]. Null for /market/candles."
        ),
    )
    broker_chunk_oldest: datetime | None = Field(
        None,
        description=(
            "Range only: oldest bar open_time in the raw broker bundle (UTC). "
            "If `total` is 0, compare [from,to] to this span — PO returns only a recent chunk."
        ),
    )
    broker_chunk_newest: datetime | None = Field(
        None,
        description="Range only: newest bar open_time in the raw broker bundle (UTC).",
    )
    broker_overlap: bool | None = Field(
        None,
        description=(
            "Range only: false if [from, to] is entirely before/after the broker chunk; "
            "null if the broker sent no rows."
        ),
    )


class IndicatorSpecBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    key: str = Field(
        min_length=1,
        max_length=64,
        description="Unique key for this instance in the response `indicators` map.",
        examples=["rsi_14"],
    )
    indicator_id: str = Field(
        alias="id",
        min_length=1,
        max_length=32,
        description="Registered indicator id (e.g. rsi).",
        examples=["rsi"],
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Indicator-specific parameters (e.g. rsi: `{ \"period\": 14 }`).",
        examples=[{"period": 14}],
    )


class RecentIndicatorWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["recent"] = "recent"
    count: int = Field(default=100, ge=1, le=5000)
    end_at: datetime | None = Field(
        None,
        description=(
            "First page only: broker window end (ISO 8601). Omit for “now”. "
            "**Mutually exclusive with `cursor`** — same rule as GET /market/candles."
        ),
    )
    cursor: datetime | None = Field(
        None,
        description=(
            "Older pages only: exclusive upper bound on bar open times (from prior "
            "`next_cursor`). **Mutually exclusive with `end_at`**."
        ),
    )


class RangeIndicatorWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["range"] = "range"
    range_from: datetime = Field(
        alias="from",
        description="Interval start (inclusive), UTC.",
    )
    range_to: datetime = Field(
        alias="to",
        description="Interval end (inclusive), UTC, not in the future.",
    )


class MarketIndicatorsRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "asset": "EURUSD_otc",
                "timeframe_seconds": 60,
                "window": {"type": "recent", "count": 100},
                "indicators": [
                    {"key": "rsi_14", "id": "rsi", "params": {"period": 14}},
                ],
                "include_candles": True,
            },
        },
    )

    asset: str = Field(min_length=1, max_length=128, examples=["EURUSD_otc"])
    timeframe_seconds: int = Field(
        ge=1,
        le=2_592_000,
        description="Bar width in seconds (Pocket Option native: 1, 5, 15, 30, 60, 300).",
        examples=[60],
    )
    window: Annotated[
        RecentIndicatorWindow | RangeIndicatorWindow,
        Field(discriminator="type"),
    ]
    indicators: list[IndicatorSpecBody] = Field(
        min_length=1,
        max_length=32,
        description=(
            "One or more indicator instances; each series uses `start_index` + `values` "
            "against shared `open_times`."
        ),
    )
    include_candles: bool = Field(
        True,
        description="If false, omit OHLCV in the response (only timestamps + indicator values).",
    )


class IndicatorSeriesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_id: str = Field(description="Canonical id of the calculator used.")
    params: dict[str, Any] = Field(description="Effective parameters after defaults.")
    start_index: int = Field(
        ge=0,
        description=(
            "Index into the response `open_times` (and `candles`, if present) for `values[0]`."
        ),
        examples=[14],
    )
    values: list[float] = Field(
        description=(
            "Defined samples only (no nulls). `values[i]` matches `open_times[start_index + i]`."
        ),
    )


class MarketIndicatorsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str
    timeframe_seconds: int
    open_times: list[datetime] = Field(
        description="Bar open times for the window (ascending), shared by all series.",
    )
    candles: list[CandleBarResponse] | None = Field(
        None,
        description="Present when `include_candles` was true in the request.",
    )
    indicators: dict[str, IndicatorSeriesResponse]
    has_more: bool = Field(
        description=(
            "Recent window only: another candles page exists (same as GET /market/candles)."
        ),
    )
    next_cursor: datetime | None = None
    total: int | None = Field(
        None,
        description="Range window only: number of bars in [from, to].",
    )
    broker_chunk_oldest: datetime | None = None
    broker_chunk_newest: datetime | None = None
    broker_overlap: bool | None = None


class StrategyConditionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_key: str = Field(
        min_length=1,
        max_length=64,
        description="Links this condition to an item from `indicators[*].key` (fast EMA for `ema_cross`).",
        examples=["psar_main"],
    )
    operator: Literal[
        "psar_reversal",
        "cci_level_cross",
        "ema_cross",
        "rsi_threshold",
        "stochastic_dual_threshold",
        "ema_cross_or_trend",
        "macd_signal_cross",
    ] = Field(
        description=(
            "Per-condition rule: `psar_reversal`, `cci_level_cross`, `ema_cross`, "
            "`rsi_threshold`, `stochastic_dual_threshold`, `ema_cross_or_trend`, `macd_signal_cross`. "
            "For single-indicator strategies must match `strategy.type`. For `composite`, each row "
            "picks its own operator."
        ),
    )
    slow_indicator_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description=(
            "Required for dual-series operators: `ema_cross` / `ema_cross_or_trend` (slow EMA), "
            "`stochastic_dual_threshold` (D), `macd_signal_cross` (MACD signal line vs `indicator_key` MACD line)."
        ),
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional condition parameters. Examples: "
            "`rsi_threshold`: `{lower, upper}`, "
            "`stochastic_dual_threshold`: `{lower, upper}`, "
            "`ema_cross_or_trend`: `{max_ema_separation}`."
        ),
    )


class StrategyConfigBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["psar_reversal", "cci_level_cross", "ema_cross", "composite"] = Field(
        description=(
            "Strategy type: `psar_reversal`, `cci_level_cross`, `ema_cross`, or `composite` "
            "(AND: all conditions on the same bar & side)."
        ),
    )
    combinator: Literal["all"] | None = Field(
        default=None,
        description="Required when `type` is `composite`: `all` = every condition agrees (same bar & side).",
    )
    signal_on_close: Literal[True] = Field(
        True,
        description="Signal is generated on candle close (MVP fixed to true).",
    )
    conditions: list[StrategyConditionBody] = Field(
        min_length=1,
        max_length=32,
        description="Data-driven list of strategy conditions for future combinations.",
    )

    @model_validator(mode="after")
    def validate_strategy_config(self) -> StrategyConfigBody:
        t = self.type
        if t == "composite":
            if self.combinator != "all":
                raise ValueError("strategy.type composite requires combinator=all.")
            if len(self.conditions) < 2:
                raise ValueError("composite strategy requires at least 2 conditions.")
            keys_flat: list[str] = []
            for c in self.conditions:
                keys_flat.append(c.indicator_key.strip())
                if c.slow_indicator_key:
                    keys_flat.append(c.slow_indicator_key.strip())
            if len(set(keys_flat)) != len(keys_flat):
                raise ValueError(
                    "composite: all `indicator_key` and `slow_indicator_key` values must be unique."
                )
            for c in self.conditions:
                if c.operator == "ema_cross":
                    if not c.slow_indicator_key:
                        raise ValueError("composite: ema_cross condition requires slow_indicator_key.")
                    if c.indicator_key.strip() == c.slow_indicator_key.strip():
                        raise ValueError("composite: ema_cross fast and slow keys must differ.")
                elif c.operator in ("stochastic_dual_threshold", "ema_cross_or_trend", "macd_signal_cross"):
                    if not c.slow_indicator_key:
                        raise ValueError(
                            f"composite: {c.operator} requires slow_indicator_key."
                        )
                    if c.indicator_key.strip() == c.slow_indicator_key.strip():
                        raise ValueError(
                            f"composite: {c.operator} requires distinct indicator keys."
                        )
                elif c.slow_indicator_key:
                    raise ValueError(
                        "slow_indicator_key is only allowed for ema_cross / stochastic_dual_threshold / "
                        "ema_cross_or_trend / macd_signal_cross (composite)."
                    )
        else:
            if self.combinator is not None:
                raise ValueError("combinator is only allowed when strategy.type is composite.")
            if len(self.conditions) != 1:
                raise ValueError("expected exactly one condition for this strategy type.")
            c0 = self.conditions[0]
            if t == "psar_reversal":
                if c0.operator != "psar_reversal":
                    raise ValueError("psar_reversal strategy requires operator psar_reversal.")
                if c0.slow_indicator_key:
                    raise ValueError("slow_indicator_key is only used with ema_cross.")
            elif t == "cci_level_cross":
                if c0.operator != "cci_level_cross":
                    raise ValueError("cci_level_cross strategy requires operator cci_level_cross.")
                if c0.slow_indicator_key:
                    raise ValueError("slow_indicator_key is only used with ema_cross.")
            elif t == "ema_cross":
                if c0.operator != "ema_cross":
                    raise ValueError("ema_cross strategy requires operator ema_cross.")
                if not c0.slow_indicator_key:
                    raise ValueError("ema_cross requires slow_indicator_key.")
                if c0.indicator_key.strip() == c0.slow_indicator_key.strip():
                    raise ValueError("ema_cross requires distinct fast and slow indicator keys.")
        return self


class StrategyRangeWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["range"] = "range"
    range_from: datetime = Field(
        alias="from",
        description="Interval start (inclusive), UTC ISO 8601.",
    )
    range_to: datetime = Field(
        alias="to",
        description="Interval end (inclusive), UTC ISO 8601.",
    )


class TestStrategyWinrateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "asset": "EURUSD_otc",
                "timeframe_seconds": 15,
                "expiry_seconds": 30,
                "window": {
                    "type": "range",
                    "from": "2026-03-22T00:00:00Z",
                    "to": "2026-03-22T02:00:00Z",
                },
                "indicators": [
                    {
                        "key": "psar_main",
                        "id": "psar",
                        "params": {"step": 0.02, "max_step": 0.2, "component": "sar"},
                    }
                ],
                "strategy": {
                    "type": "psar_reversal",
                    "signal_on_close": True,
                    "conditions": [
                        {"indicator_key": "psar_main", "operator": "psar_reversal"}
                    ],
                },
            },
        },
    )

    asset: str = Field(min_length=1, max_length=128, examples=["EURUSD_otc"])
    timeframe_seconds: Literal[3, 10, 15, 30, 60, 300] = Field(
        description="MVP supported timeframes in seconds.",
    )
    expiry_seconds: int = Field(
        ge=1,
        le=2_592_000,
        description="Expiry in seconds. Must be divisible by timeframe_seconds.",
        examples=[3, 10, 15, 30, 60],
    )
    window: StrategyRangeWindow
    indicators: list[IndicatorSpecBody] = Field(
        min_length=1,
        max_length=32,
        description="Indicator instances referenced by strategy conditions.",
    )
    strategy: StrategyConfigBody

    @model_validator(mode="after")
    def validate_expiry_multiple(self) -> TestStrategyWinrateRequest:
        if self.expiry_seconds % self.timeframe_seconds != 0:
            raise ValueError("expiry_seconds must be divisible by timeframe_seconds.")
        return self

    @model_validator(mode="after")
    def validate_ema_cross_indicator_bindings(self) -> Self:
        by_key = {spec.key.strip(): spec for spec in self.indicators}
        for cond in self.strategy.conditions:
            if cond.operator not in (
                "ema_cross",
                "ema_cross_or_trend",
                "stochastic_dual_threshold",
                "macd_signal_cross",
            ):
                continue
            sk = (cond.slow_indicator_key or "").strip()
            fk = cond.indicator_key.strip()
            fast_spec = by_key.get(fk)
            slow_spec = by_key.get(sk)
            if fast_spec is None or slow_spec is None:
                raise ValueError(
                    f"{cond.operator}: both indicator_key and slow_indicator_key must match entries in `indicators`."
                )
            if cond.operator in ("ema_cross", "ema_cross_or_trend"):
                if (
                    fast_spec.indicator_id.strip().lower() != "ema"
                    or slow_spec.indicator_id.strip().lower() != "ema"
                ):
                    raise ValueError(
                        f"{cond.operator} requires both linked indicators to have id `ema`."
                    )
                fp = _ema_period_int_for_validation(dict(fast_spec.params))
                sp = _ema_period_int_for_validation(dict(slow_spec.params))
                if fp >= sp:
                    raise ValueError(
                        f"{cond.operator} requires fast EMA period < slow EMA period (from `params.period`)."
                    )
            elif cond.operator == "macd_signal_cross":
                if (
                    fast_spec.indicator_id.strip().lower() != "macd"
                    or slow_spec.indicator_id.strip().lower() != "macd"
                ):
                    raise ValueError(
                        "macd_signal_cross requires both linked indicators to have id `macd`."
                    )
                mc = str(dict(fast_spec.params).get("component", "")).strip().lower()
                sc = str(dict(slow_spec.params).get("component", "")).strip().lower()
                if mc != "macd" or sc != "signal":
                    raise ValueError(
                        "macd_signal_cross requires `indicator_key` with `component='macd'` and "
                        "`slow_indicator_key` with `component='signal'` (same fast/slow/signal periods)."
                    )
                fp = dict(fast_spec.params)
                sp = dict(slow_spec.params)
                for name, default in (("fast_period", 12), ("slow_period", 26), ("signal_period", 9)):
                    if _macd_period_int_for_validation(fp, name, default=default) != _macd_period_int_for_validation(
                        sp, name, default=default
                    ):
                        raise ValueError(
                            "macd_signal_cross: MACD line and signal instances must use identical "
                            f"`{name}` (and matching `slow_period` / `signal_period`)."
                        )
            else:
                if (
                    fast_spec.indicator_id.strip().lower() != "stochastic"
                    or slow_spec.indicator_id.strip().lower() != "stochastic"
                ):
                    raise ValueError(
                        "stochastic_dual_threshold requires both linked indicators to have id `stochastic`."
                    )
        return self


class TestStrategyWinrateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str
    timeframe_seconds: int
    expiry_seconds: int
    total_signals: int = Field(description="Detected strategy signals (includes skipped).")
    wins: int = Field(description="Signals classified as wins.")
    losses: int = Field(description="Signals classified as losses (includes ties).")
    skipped_signals: int = Field(
        description="Signals ignored because there are not enough future candles for expiry."
    )
    winrate_percent: float = Field(
        description="wins / (wins + losses) * 100, rounded to 2 decimals."
    )
    period_from: datetime
    period_to: datetime
