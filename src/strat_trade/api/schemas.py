from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable summary.")
    details: dict = Field(default_factory=dict, description="Optional structured context.")


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


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
