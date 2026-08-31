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


class AssetItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(description="Broker asset identifier (e.g. EURUSD_otc).")
    name: str = Field(description="Human-readable asset name (e.g. EUR/USD OTC).")
    payout: int = Field(default=80, description="Current payout percentage (e.g. 92 = 92%).")
    is_otc: bool = Field(default=True, description="True for OTC assets.")
    asset_type: str = Field(
        default="currency",
        description="Asset category (currency, cryptocurrency, stock, commodity, index).",
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


class TvCandleResponse(BaseModel):
    """One bar from TradingView (tvdatafeed), normalized to UTC timestamps."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime = Field(description="Bar open time (UTC).")
    open: float | None = Field(None, description="Open; null if missing in source row.")
    high: float | None = Field(None, description="High; null if missing in source row.")
    low: float | None = Field(None, description="Low; null if missing in source row.")
    close: float | None = Field(None, description="Close; null if missing in source row.")
    volume: float | None = Field(None, description="Volume; null if missing in source row.")


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
        description='Indicator-specific parameters (e.g. rsi: `{ "period": 14 }`).',
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


class IndicatorCatalogItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Stable indicator id used in POST /market/indicators `id`.")
    name: str = Field(description="Human-readable name.")
    category: str = Field(
        description="Indicator family (Oscillator, Trend, Volatility, Volume, Other).",
    )
    default_params: dict[str, Any] = Field(
        default_factory=dict,
        description="Default tunable parameters merged with client `params` on compute.",
    )
    fill_sparse: bool = Field(
        False,
        description="If true, sparse series are forward-filled before trimming for the API.",
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


class BacktestRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "asset": "EURUSD_otc",
                "timeframe_seconds": 60,
                "initial_deposit": 1000.0,
                "stake_model": "flat",
                "stake_amount": 10.0,
                "stake_percent": 1.0,
                "martingale_multiplier": 2.0,
                "martingale_max_steps": 2,
                "payout_rate": 0.85,
                "min_payout_rate": 0.80,
                "expiration_bars": 3,
                "adaptive_expiration": False,
                "daily_stop_loss_pct": 0.05,
                "strategy_name": "hybrid_multifactors",
                "candle_count": 500,
            }
        },
    )

    asset: str = Field("EURUSD_otc", min_length=1, max_length=128, description="Asset symbol")
    timeframe_seconds: int = Field(60, ge=1, le=2_592_000, description="Bar period in seconds")
    initial_deposit: float = Field(1000.0, ge=1.0, description="Starting test balance")
    stake_model: Literal["flat", "percent", "martingale"] = Field(
        "flat", description="Money management model"
    )
    stake_amount: float = Field(10.0, ge=0.1, description="Base stake amount ($)")
    stake_percent: float = Field(1.0, ge=0.1, le=100.0, description="Stake % for percent model")
    martingale_multiplier: float = Field(2.0, ge=1.0, le=5.0, description="Martingale multiplier")
    martingale_max_steps: int = Field(
        2, ge=1, le=10, description="Max consecutive martingale steps"
    )
    payout_rate: float = Field(0.85, ge=0.1, le=1.0, description="Broker payout (e.g. 0.85 = 85%)")
    min_payout_rate: float = Field(
        0.80, ge=0.1, le=1.0, description="Minimum payout filter threshold"
    )
    expiration_bars: int = Field(
        3, ge=1, le=100, description="Duration in bars (e.g. 3 bars on M1 = 180s)"
    )
    expiration_seconds: int | None = Field(
        None, ge=1, le=86400, description="Optional explicit expiration duration in seconds"
    )
    adaptive_expiration: bool = Field(False, description="Enable ATR-adaptive expiration duration")
    daily_stop_loss_pct: float = Field(
        0.05, ge=0.01, le=1.0, description="Daily stop-loss limit (e.g. 0.05 = 5%)"
    )
    strategy_name: str = Field("hybrid_multifactors", description="Selected strategy module")
    candle_count: int = Field(500, ge=60, le=2000, description="Historical candles count to test")
    end_at: datetime | None = Field(None, description="Anchor timestamp for history (UTC)")


class BacktestTradeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_index: int
    exit_index: int
    entry_time: datetime
    exit_time: datetime
    action: Literal["CALL", "PUT"]
    entry_price: float
    exit_price: float
    stake: float
    payout_rate: float
    pnl: float
    outcome: Literal["WIN", "LOSS", "DRAW"]
    balance_after: float
    confidence: float
    expiration_seconds: int
    asset: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class EquityPointResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    balance: float
    drawdown_pct: float


class BacktestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str
    timeframe_seconds: int
    initial_deposit: float
    final_balance: float
    net_profit: float
    roi_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    win_rate_pct: float
    profit_factor: float
    max_drawdown_amount: float
    max_drawdown_pct: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    trades: list[BacktestTradeResponse]
    equity_curve: list[EquityPointResponse]
    strategy_name: str


class AssetPerformanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str
    name: str
    payout_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    win_rate_pct: float
    net_profit: float
    roi_pct: float
    profit_factor: float
    max_drawdown_amount: float
    max_drawdown_pct: float
    trades_count_pct: float


class PortfolioBacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[str] = Field(
        default_factory=lambda: ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc"],
        description="List of broker asset symbols to trade concurrently.",
    )
    max_concurrent_trades: int = Field(
        3, ge=1, le=20, description="Max open trades across the portfolio simultaneously"
    )
    timeframe_seconds: int = Field(
        60, description="Candle timeframe in seconds (5, 15, 30, 60, 300)"
    )
    initial_deposit: float = Field(
        1000.0, gt=0, description="Starting shared portfolio balance ($)"
    )
    stake_model: Literal["flat", "percent", "martingale"] = Field(
        "flat", description="Position sizing model"
    )
    stake_amount: float = Field(10.0, gt=0, description="Fixed bet amount for flat/martingale ($)")
    stake_percent: float = Field(
        1.0, ge=0.1, le=100.0, description="Bet size percentage for dynamic model"
    )
    martingale_multiplier: float = Field(2.0, ge=1.0, le=5.0, description="Multiplier after loss")
    martingale_max_steps: int = Field(
        2, ge=1, le=10, description="Max consecutive martingale steps"
    )
    payout_rates: dict[str, float] = Field(
        default_factory=dict, description="Custom payout rate override per asset (e.g. 0.92)"
    )
    min_payout_rate: float = Field(
        0.80, ge=0.1, le=1.0, description="Minimum payout filter threshold"
    )
    expiration_bars: int = Field(
        3, ge=1, le=100, description="Duration in bars (e.g. 3 bars on M1 = 180s)"
    )
    expiration_seconds: int | None = Field(
        None, ge=1, le=86400, description="Optional explicit expiration duration in seconds"
    )
    adaptive_expiration: bool = Field(False, description="Enable ATR-adaptive expiration duration")
    daily_stop_loss_pct: float = Field(
        0.05, ge=0.01, le=1.0, description="Daily stop-loss limit (e.g. 0.05 = 5%)"
    )
    cooldown_bars: int = Field(
        0, ge=0, le=50, description="Post-trade settlement cooldown in bars per asset"
    )
    global_cooldown_seconds: int = Field(
        0, ge=0, le=3600, description="Delay in seconds between consecutive portfolio trades"
    )
    correlation_filter_enabled: bool = Field(
        False, description="Enable currency pair correlation and exposure filter"
    )
    max_consecutive_losses: int = Field(
        0, ge=0, le=20, description="Consecutive losses before pause (0 = disabled)"
    )
    max_drawdown_pct_limit: float = Field(
        0.08, ge=0.01, le=0.50, description="Peak-to-trough drawdown threshold for halt"
    )
    strategy_name: str = Field("hybrid_multifactors", description="Selected strategy module")
    candle_count: int = Field(
        500, ge=60, le=2000, description="Historical candles count to test per asset"
    )
    end_at: datetime | None = Field(None, description="Anchor timestamp for history (UTC)")


class PortfolioBacktestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[str]
    timeframe_seconds: int
    initial_deposit: float
    final_balance: float
    net_profit: float
    roi_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    win_rate_pct: float
    profit_factor: float
    max_drawdown_amount: float
    max_drawdown_pct: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    per_asset_stats: list[AssetPerformanceResponse]
    trades: list[BacktestTradeResponse]
    equity_curve: list[EquityPointResponse]
    strategy_name: str


class StrategyParameterDefResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str
    type: str
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[Any] | None = None
    description: str = ""


class StrategyMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    category: str
    description: str
    recommended_timeframes: list[int]
    recommended_assets: list[str]
    parameters: list[StrategyParameterDefResponse]


class OptimizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_name: str = Field("bollinger_atr_reversion", description="Target strategy ID")
    asset: str = Field("EURUSD_otc", description="Target asset for optimization")
    timeframe_seconds: int = Field(60, ge=5, le=86400, description="Candle timeframe in seconds")
    candle_count: int = Field(300, ge=60, le=2000, description="Number of candles for training")
    initial_deposit: float = Field(1000.0, ge=1.0, description="Starting test deposit")
    payout_rate: float | None = Field(None, ge=0.1, le=1.0, description="Payout rate override")
    stake_model: str = Field("flat", description="Stake sizing model (flat, percent)")
    stake_amount: float = Field(10.0, ge=1.0, description="Flat stake amount")
    stake_percent: float = Field(1.0, ge=0.1, le=100.0, description="Stake percent")
    daily_stop_loss_pct: float = Field(0.05, ge=0.01, le=1.0, description="Daily stop-loss limit")
    parameter_grid: dict[str, list[Any]] | None = Field(
        None, description="Custom grid parameter ranges. If omitted, uses standard defaults."
    )
    max_combinations: int = Field(
        60, ge=1, le=200, description="Maximum parameter sets to evaluate"
    )


class OptimizationResultItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int
    params: dict[str, Any]
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    win_rate_pct: float
    profit_factor: float
    net_profit: float
    roi_pct: float
    max_drawdown_pct: float
    max_consecutive_losses: int
    rank_score: float


class OptimizationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_name: str
    asset: str
    timeframe_seconds: int
    total_combinations_tested: int
    candle_count: int
    best_params: dict[str, Any]
    results: list[OptimizationResultItemResponse]


class TradeBatchResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_index: int
    start_trade_index: int
    end_trade_index: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    win_rate_pct: float
    net_pnl: float
    max_consecutive_losses: int
    roi_pct: float
    passed: bool
    is_partial: bool = False
    start_time: datetime | None = None
    end_time: datetime | None = None
    total_staked: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    max_consecutive_wins: int = 0
    max_drawdown_amount: float = 0.0
    max_drawdown_pct: float = 0.0
    failure_reasons: list[str] = Field(default_factory=list)
    failure_reason: str | None = None


class RollingVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str = Field("EURUSD_otc", description="Target broker asset symbol")
    timeframe_seconds: int = Field(60, ge=5, le=86400, description="Candle timeframe in seconds")
    strategy_name: str = Field("bollinger_atr_reversion", description="Strategy identifier")
    strategy_params: dict[str, Any] = Field(
        default_factory=dict, description="Initial strategy hyperparameters"
    )
    payout_rate: float = Field(0.92, ge=0.1, le=1.0, description="Broker payout rate (default 92%)")
    min_payout_rate: float = Field(0.80, ge=0.1, le=1.0, description="Minimum allowed payout")
    initial_deposit: float = Field(1000.0, ge=1.0, description="Session starting capital")
    stake_amount: float = Field(10.0, ge=1.0, description="Stake per trade")
    stake_model: str = Field("flat", description="Stake sizing model")
    batch_size: int = Field(15, ge=1, le=100, description="Validation batch size (default 15)")
    min_win_rate_pct: float = Field(
        53.4, ge=0.0, le=100.0, description="Minimum batch win rate threshold"
    )
    candle_count: int = Field(500, ge=60, le=2000, description="Historical candles count to test")
    auto_tune: bool = Field(
        False, description="Automatically trigger parameter tuning if any batch fails"
    )
    parameter_grid: dict[str, list[Any]] | None = Field(
        None, description="Custom parameter search space for auto-tuning"
    )
    max_combinations: int = Field(
        60, ge=1, le=200, description="Maximum tuning combinations to evaluate"
    )
    end_at: datetime | None = Field(None, description="Anchor timestamp for candle fetching (UTC)")


class RollingVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_name: str
    asset: str
    timeframe_seconds: int = 60
    payout_rate: float = 0.92
    batch_size: int = 15
    total_trades: int
    total_batches: int
    passed_batches: int
    failed_batches: int
    all_batches_passed: bool
    status: str
    overall_win_rate_pct: float
    overall_net_pnl: float
    min_batch_win_rate_pct: float = 0.0
    max_batch_win_rate_pct: float = 0.0
    avg_batch_win_rate_pct: float = 0.0
    min_batch_net_pnl: float = 0.0
    max_batch_net_pnl: float = 0.0
    max_consecutive_losses_overall: int = 0
    batches: list[TradeBatchResultResponse]
    rolling_windows: list[TradeBatchResultResponse] = Field(default_factory=list)
    auto_tuned: bool = False
    initial_params: dict[str, Any] = Field(default_factory=dict)
    optimized_params: dict[str, Any] | None = None
    tuning_iterations: int = 0
    tuning_report: dict[str, Any] | None = None


# =========================================================================
# BOT & AUDIT SCHEMAS
# =========================================================================


class PauseBotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_seconds: int | None = Field(
        None,
        ge=1,
        le=86400,
        description="Optional pause duration in seconds. If omitted, pauses until manual resume.",
    )
    reason: str | None = Field(
        None,
        max_length=256,
        description="Optional operator reason for pausing (e.g. 'manual', 'high-impact news').",
    )


class StrategyAssignmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str
    strategy_id: str
    strategy_name: str
    category: str
    parameters: dict[str, Any]
    estimated_win_rate_pct: float
    estimated_profit_factor: float
    estimated_trades_count: int
    quantum_score: float
    rationale: str


class ExecutionGovernanceFields(BaseModel):
    """Entry-timing gates and statistical asset governance shared by plan I/O."""

    bar_edge_guard_seconds: float = Field(
        3.0, ge=0.0, le=30.0, description="Block entries during the opening seconds of a bar"
    )
    use_closed_bar_only: bool = Field(
        True, description="Evaluate indicators on closed bars only, never the forming bar"
    )
    dynamic_strategy_switching_enabled: bool = Field(
        False, description="Allow the regime detector to substitute the assigned strategy"
    )
    asset_governor_enabled: bool = Field(
        True, description="Enable the Wilson-bound per-asset stake governor"
    )
    otc_stake_multiplier: float = Field(
        0.25, ge=0.0, le=1.0, description="Fraction of the stake risked on OTC assets"
    )
    otc_min_payout_rate: float = Field(
        0.90, ge=0.5, le=1.0, description="Minimum broker payout required for OTC assets"
    )
    governor_min_trades_for_mute: int = Field(
        20, ge=5, le=500, description="Decided trades required before the governor may mute"
    )
    governor_mute_duration_minutes: int = Field(
        240, ge=5, le=10080, description="Base mute duration, doubled for repeat offenders"
    )
    governor_promotion_min_trades: int = Field(
        400, ge=20, le=100000, description="Decided trades required before a stake promotion"
    )


class AutoAssignRequest(ExecutionGovernanceFields):
    model_config = ConfigDict(extra="forbid")

    assets: list[str] = Field(..., min_length=1, description="List of target assets to profile")
    initial_deposit: float = Field(1000.0, ge=10.0, description="Session starting capital")
    stake_model: str = Field("flat", description="flat or percent")
    stake_amount: float = Field(10.0, ge=1.0, description="Flat stake amount")
    stake_percent: float = Field(1.0, ge=0.1, le=100.0, description="Dynamic percent stake")
    expiration_seconds: int = Field(180, ge=5, le=86400, description="Trade duration in seconds")
    daily_stop_loss_pct: float = Field(0.05, ge=0.01, le=0.5, description="Stop-loss % of deposit")
    daily_take_profit_pct: float = Field(
        0.025, ge=0.005, le=0.5, description="Session take-profit target % of deposit"
    )
    trailing_profit_lock_enabled: bool = Field(
        True, description="Enable trailing profit retention lock"
    )
    trailing_profit_lock_threshold_usd: float = Field(
        500.0, ge=10.0, description="Profit threshold to activate trailing lock"
    )
    trailing_profit_retention_pct: float = Field(
        0.75, ge=0.1, le=0.99, description="Percentage of peak profit to retain"
    )
    per_asset_degradation_guard_enabled: bool = Field(
        True, description="Mute individual underperforming assets dynamically"
    )
    per_asset_max_consecutive_losses: int = Field(
        2, ge=1, le=10, description="Mute asset after consecutive losses"
    )
    per_asset_min_winrate_pct: float = Field(
        40.0, ge=10.0, le=90.0, description="Mute asset if session win rate falls below floor"
    )
    max_concurrent_trades: int = Field(3, ge=1, le=20, description="Max open trades allowed")
    min_payout_rate: float = Field(
        0.80, ge=0.5, le=1.0, description="Minimum allowed broker payout"
    )
    cooldown_bars: int = Field(
        3, ge=0, le=50, description="Post-trade settlement cooldown in bars per asset"
    )
    global_cooldown_seconds: int = Field(
        30, ge=0, le=3600, description="Delay in seconds between consecutive portfolio trades"
    )
    max_consecutive_losses: int = Field(
        3, ge=1, le=20, description="Consecutive losses before circuit breaker pause"
    )
    max_drawdown_pct_limit: float = Field(
        0.08, ge=0.01, le=0.50, description="Peak-to-trough drawdown threshold for circuit halt"
    )
    correlation_filter_enabled: bool = Field(
        True, description="Enable currency pair correlation and exposure filter"
    )
    pause_duration_minutes: int = Field(
        15, ge=1, le=1440, description="Cooling-off pause duration in minutes"
    )
    asset_blacklist: list[str] = Field(
        default_factory=list, description="Optional custom toxic asset blacklist"
    )
    asset_whitelist: list[str] = Field(
        default_factory=list, description="Optional custom high-winrate asset whitelist"
    )
    toxic_filter_enabled: bool = Field(True, description="Enforce toxic asset blacklist filtering")
    session_filter_enabled: bool = Field(
        True, description="Enable automatic session liquidity and schedule filtering"
    )
    allowed_strategies: list[str] = Field(
        default_factory=list,
        description="Optional list of allowed strategy IDs for automatic assignment",
    )


class PreTradingPlanResponse(ExecutionGovernanceFields):
    model_config = ConfigDict(extra="forbid")

    assignments: list[StrategyAssignmentResponse]
    total_assets: int
    initial_deposit: float
    stake_model: str
    stake_amount: float
    stake_percent: float
    expiration_seconds: int
    daily_stop_loss_pct: float
    stop_loss_amount: float
    daily_take_profit_pct: float = 0.025
    take_profit_amount: float = 1000.0
    trailing_profit_lock_enabled: bool = True
    trailing_profit_lock_threshold_usd: float = 500.0
    trailing_profit_retention_pct: float = 0.75
    per_asset_degradation_guard_enabled: bool = True
    per_asset_max_consecutive_losses: int = 2
    per_asset_min_winrate_pct: float = 40.0
    max_concurrent_trades: int = 3
    min_payout_rate: float = 0.80
    cooldown_bars: int = 3
    global_cooldown_seconds: int = 30
    max_consecutive_losses: int = 3
    max_drawdown_pct_limit: float = 0.08
    correlation_filter_enabled: bool = True
    pause_duration_minutes: int = 15
    asset_blacklist: list[str] = Field(default_factory=list)
    asset_whitelist: list[str] = Field(default_factory=list)
    toxic_filter_enabled: bool = True
    session_filter_enabled: bool = True
    allowed_strategies: list[str] = Field(default_factory=list)
    created_at: str


class StartBotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: PreTradingPlanResponse = Field(..., description="Approved pre-trading plan")


class LiveTradeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trade_id: str
    broker_order_id: str | None = None
    asset: str
    action: str
    stake: float
    open_time: str
    expiration_seconds: int
    open_price: float
    close_time: str | None = None
    close_price: float | None = None
    strategy_id: str
    strategy_name: str
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    indicator_snapshot: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    reason: str = ""
    payout_rate: float = 0.0
    outcome: str
    pnl: float = 0.0
    balance_after: float | None = None
    is_merged_with_broker: bool = False
    broker_profit: float | None = None
    slippage: float | None = None
    executed_params: dict[str, Any] = Field(default_factory=dict)
    asset_tier: str = "NORMAL"
    stake_multiplier: float = 1.0
    entry_second: int = 0
    is_otc: bool = False
    open_price_source: str = "candle"
    settlement_source: str = "candle"


class BotStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    started_at: str | None
    initial_balance: float
    current_balance: float
    net_profit: float
    roi_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    draw_trades: int
    pending_trades: int
    win_rate_pct: float
    max_drawdown_pct: float
    stop_loss_reached: bool
    consecutive_losses: int = 0
    peak_balance: float = 1000.0
    current_drawdown_pct: float = 0.0
    paused_until: str | None = None
    is_paused: bool = False
    circuit_breaker_triggered: bool = False
    active_assignments: list[StrategyAssignmentResponse]
    recent_trades: list[LiveTradeResponse]


class StrategyAuditItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_name: str
    strategy_id: str
    total_trades: int
    wins: int
    losses: int
    draws: int
    win_rate_pct: float
    profit_factor: float
    net_profit: float


class AssetAuditItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str
    total_trades: int
    wins: int
    losses: int
    win_rate_pct: float
    net_profit: float


class MergedRecordItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    asset: str
    direction: str
    open_time: str
    close_time: str
    broker_open_price: float
    broker_close_price: float
    trade_amount: float
    broker_profit: float
    outcome: str
    is_bot_trade: bool
    strategy_id: str | None
    strategy_name: str | None
    strategy_params: dict[str, Any]
    indicator_snapshot: dict[str, Any]
    confidence: float | None
    reason: str | None
    internal_open_price: float | None
    slippage: float | None
    entry_second: int | None = None
    open_price_source: str | None = None
    settlement_source: str | None = None


class BrokerReportAuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_broker_trades: int
    matched_trades_count: int
    match_rate_pct: float
    total_broker_profit: float
    average_slippage: float
    strategy_breakdown: list[StrategyAuditItem]
    asset_breakdown: list[AssetAuditItem]
    merged_records: list[MergedRecordItem]
