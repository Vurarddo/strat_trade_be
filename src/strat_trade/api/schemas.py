from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class BrokerAssetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(description="Broker-stable instrument id (stringified if numeric).")
    symbol: str = Field(
        description="Trading symbol, e.g. EURUSD_otc.",
        examples=["EURUSD_otc"],
    )
    name: str = Field(description="Display name from the broker catalog.")
    asset_type: str = Field(
        description="Broker category (e.g. currency, cryptocurrency, stock).",
        examples=["currency"],
    )
    payout: float | None = Field(
        None,
        description="Payout percentage when provided by the broker.",
    )
    is_otc: bool = Field(description="True if the instrument is OTC.")
    is_active: bool = Field(
        description="Whether the broker marks the asset as open for trading right now.",
    )
    allowed_candles: list[int] = Field(
        description="Native bar periods in seconds supported for this asset (Pocket Option).",
        examples=[[1, 5, 60, 300]],
    )


class BrokerAssetsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[BrokerAssetResponse] = Field(description="Catalog rows in no guaranteed order.")
    active_only: bool = Field(
        description="Echo of the request query: list was filtered to ``is_active`` when true.",
    )


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
        description=(
            "Bar width in seconds. Pocket Option only serves 1, 5, 15, 30, 60, 300 "
            "(e.g. 1m=60, 5m=300); larger frames need client-side aggregation."
        ),
        examples=[60, 300],
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


class IndicatorParameterField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Parameter name.")
    type: str = Field(description="JSON/OpenAPI style type hint.", examples=["integer"])
    default: int | float | str | bool | None = Field(description="Default when omitted.")
    min_value: int | float | None = Field(
        None,
        description="Inclusive minimum when applicable.",
    )
    description: str = Field(description="Human-readable meaning.")


class RsiWilderIndicatorInfoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_id: str = Field(
        default="rsi_wilder",
        description="Stable id used in strategy configs and registry.",
    )
    title: str = Field(description="Display title.")
    summary: str = Field(description="Short description of what the indicator measures.")
    source: str = Field(
        default="close",
        description="Price series used for changes (Wilder used close-to-close).",
    )
    formula: str = Field(description="Definition of RS and RSI plus Wilder smoothing.")
    parameters: list[IndicatorParameterField] = Field(
        description="Configurable inputs; period defaults to Wilder’s 14.",
    )
    reference_levels: dict[str, float] = Field(
        default_factory=lambda: {"overbought": 70.0, "oversold": 30.0},
        description="Common horizontal levels (not trading signals by themselves).",
    )


class BollingerBandsIndicatorInfoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_id: str = Field(
        default="bollinger_bands",
        description="Stable id for POST /market/indicators.",
    )
    title: str = Field(description="Display title.")
    summary: str = Field(description="Short description of bands and volatility.")
    source: str = Field(
        default="close",
        description="Price series for SMA and standard deviation.",
    )
    formula: str = Field(description="Middle, σ, upper and lower band definitions.")
    parameters: list[IndicatorParameterField] = Field(
        description="Length (SMA/stdev window) and multiplier (classic 20 / 2.0).",
    )
    outputs: list[str] = Field(
        default_factory=lambda: ["middle", "upper", "lower"],
        description="Series names returned in `POST /market/indicators` for this id.",
    )


class MacdIndicatorInfoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_id: str = Field(default="macd", description="Stable id for POST /market/indicators.")
    title: str = Field(description="Display title.")
    summary: str = Field(description="Short description of MACD, signal, and histogram.")
    source: str = Field(
        default="close",
        description="Price series for fast and slow EMAs.",
    )
    formula: str = Field(description="EMA definitions for MACD line, signal, and histogram.")
    parameters: list[IndicatorParameterField] = Field(
        description="fast_length, slow_length, signal_length (classic 12 / 26 / 9).",
    )
    outputs: list[str] = Field(
        default_factory=lambda: ["macd", "signal", "histogram"],
        description="Series names in API responses for this id.",
    )


class IndicatorRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_id: str = Field(
        min_length=1,
        max_length=128,
        description="Registered calculator id: rsi_wilder, bollinger_bands, macd, …",
        examples=["rsi_wilder", "bollinger_bands", "macd"],
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Indicator-specific parameters (e.g. rsi_wilder: length).",
    )
    key: str | None = Field(
        None,
        min_length=1,
        max_length=128,
        description=(
            "Optional unique label per run (duplicate `key` in one request → 400). "
            "Response `indicators` array follows the same order as this list; omit `key` to use "
            "internal labels `run_0`, `run_1`, … only for validation."
        ),
        examples=["rsi_14", "rsi_21"],
    )


class MarketIndicatorsBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str = Field(min_length=1, max_length=128, examples=["EURUSD_otc"])
    timeframe_seconds: int = Field(
        ge=1,
        le=2_592_000,
        examples=[60, 300],
        description="Bar period in seconds (Pocket Option native: 1, 5, 15, 30, 60, 300).",
    )
    count: int = Field(
        ge=1,
        le=5000,
        description="Bars to fetch; must cover the largest warmup among `indicators`.",
    )
    end_at: datetime | None = Field(
        None,
        description="First page only: broker window end (UTC). Omit for “now”.",
    )
    cursor: datetime | None = Field(
        None,
        description="Older pages: `next_cursor` from a prior candles or indicators response.",
    )
    indicators: list[IndicatorRunRequest] = Field(
        min_length=1,
        description="Ordered list; the same id may appear twice with different params.",
    )


class GeminiMarketIndicatorsRequest(MarketIndicatorsBatchRequest):
    """Same as `POST /market/indicators` plus optional Gemini expiry constraint."""

    expiration_time_seconds: int | None = Field(
        None,
        ge=1,
        le=86_400,
        description=(
            "If set, the model must suggest an `expiration` duration that does not exceed this "
            "many seconds (binary option expiry cap)."
        ),
    )


class IndicatorOutputPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open_time: str = Field(
        description=(
            "Candle open time (ISO 8601), same string as `candles[].open_time` in this response."
        ),
    )
    value: float = Field(description="Indicator value at that bar.")


class IndicatorRunSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_id: str
    params: dict[str, Any] = Field(description="Resolved parameters for this run.")
    outputs: dict[str, list[IndicatorOutputPoint]] = Field(
        description=(
            "Output line name → chronological list of `{ open_time, value }`. "
            "Warmup bars omitted. Join to `candles` by matching `open_time`."
        ),
    )


class MarketIndicatorsBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str = Field(description="Same as GET /market/candles.")
    timeframe_seconds: int = Field(description="Same as GET /market/candles.")
    align_by: Literal["open_time"] = Field(
        default="open_time",
        description=(
            "Each `indicators[*].outputs[*][]` item uses `open_time` strings equal to "
            "`candles[i].open_time` in this JSON response."
        ),
    )
    candles: list[CandleBarResponse] = Field(
        description="Same shape as `candles` in GET /api/v1/market/candles.",
    )
    indicators: list[IndicatorRunSnapshotResponse] = Field(
        description="Same order as request `indicators[]`; join values to candles via `align_by`.",
    )
    has_more: bool = Field(description="Same semantics as GET /market/candles.")
    next_cursor: datetime | None = Field(
        None,
        description="Same semantics as GET /market/candles.",
    )


class GeminiLlmJsonPayload(BaseModel):
    """Validated shape of the JSON object returned by Gemini (ProTrader prompt)."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    direction: str = Field(description="CALL, PUT, or NEUTRAL.")
    expiration: str = Field(description="Expiry hint, e.g. 2 min.")
    win_probability: str = Field(description='Percentage string, e.g. "78%".')
    analysis: str = Field(description="Qualitative analysis only.")

    @field_validator("direction")
    @classmethod
    def direction_upper(cls, v: str) -> str:
        u = v.strip().upper()
        if u not in ("CALL", "PUT", "NEUTRAL"):
            msg = f"direction must be CALL, PUT, or NEUTRAL; got {v!r}"
            raise ValueError(msg)
        return u


class GeminiMarketIndicatorsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: str = Field(
        description='Trading bias: CALL, PUT, or NEUTRAL (from Gemini JSON).',
        examples=["CALL", "PUT", "NEUTRAL"],
    )
    expiration: str = Field(
        description="Suggested expiry window as short text (e.g. 2 min).",
        examples=["2 min", "1-3 min"],
    )
    win_probability: str = Field(
        description='Estimated win probability as a percentage string (e.g. "78%").',
        examples=["78%"],
    )
    analysis: str = Field(
        description=(
            "Qualitative market analysis from Gemini (trend, indicators, patterns, logic)."
        ),
    )
    model: str = Field(description="Gemini model id used for this call.")
    asset: str = Field(description="Echo from request.")
    timeframe_seconds: int = Field(description="Echo from request.")

