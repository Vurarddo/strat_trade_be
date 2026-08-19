from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from strat_trade.api.deps import CandleFeedDep, SettingsDep
from strat_trade.api.schemas import AssetItemResponse, CandleBarResponse, CandlesResponse
from strat_trade.use_cases.fetch_candles import fetch_candles_in_range, fetch_recent_candles

router = APIRouter(prefix="/market")

_CURATED_ASSETS = [
    {
        "symbol": "EURUSD_otc",
        "name": "EUR/USD OTC",
        "payout": 92,
        "is_otc": True,
        "asset_type": "currency",
    },
    {
        "symbol": "GBPUSD_otc",
        "name": "GBP/USD OTC",
        "payout": 92,
        "is_otc": True,
        "asset_type": "currency",
    },
    {
        "symbol": "USDJPY_otc",
        "name": "USD/JPY OTC",
        "payout": 92,
        "is_otc": True,
        "asset_type": "currency",
    },
    {
        "symbol": "AUDUSD_otc",
        "name": "AUD/USD OTC",
        "payout": 92,
        "is_otc": True,
        "asset_type": "currency",
    },
    {
        "symbol": "USDCAD_otc",
        "name": "USD/CAD OTC",
        "payout": 92,
        "is_otc": True,
        "asset_type": "currency",
    },
    {
        "symbol": "USDCHF_otc",
        "name": "USD/CHF OTC",
        "payout": 92,
        "is_otc": True,
        "asset_type": "currency",
    },
    {
        "symbol": "EURGBP_otc",
        "name": "EUR/GBP OTC",
        "payout": 92,
        "is_otc": True,
        "asset_type": "currency",
    },
    {
        "symbol": "EURJPY_otc",
        "name": "EUR/JPY OTC",
        "payout": 92,
        "is_otc": True,
        "asset_type": "currency",
    },
    {
        "symbol": "USDRUB_otc",
        "name": "USD/RUB OTC",
        "payout": 92,
        "is_otc": True,
        "asset_type": "currency",
    },
    {
        "symbol": "EURUSD",
        "name": "EUR/USD",
        "payout": 80,
        "is_otc": False,
        "asset_type": "currency",
    },
    {
        "symbol": "GBPUSD",
        "name": "GBP/USD",
        "payout": 80,
        "is_otc": False,
        "asset_type": "currency",
    },
    {
        "symbol": "USDJPY",
        "name": "USD/JPY",
        "payout": 80,
        "is_otc": False,
        "asset_type": "currency",
    },
    {
        "symbol": "AUDUSD",
        "name": "AUD/USD",
        "payout": 80,
        "is_otc": False,
        "asset_type": "currency",
    },
    {
        "symbol": "USDCAD",
        "name": "USD/CAD",
        "payout": 80,
        "is_otc": False,
        "asset_type": "currency",
    },
    {
        "symbol": "BTCUSD_otc",
        "name": "Bitcoin OTC",
        "payout": 85,
        "is_otc": True,
        "asset_type": "cryptocurrency",
    },
    {
        "symbol": "ETHUSD_otc",
        "name": "Ethereum OTC",
        "payout": 85,
        "is_otc": True,
        "asset_type": "cryptocurrency",
    },
    {
        "symbol": "LTCUSD_otc",
        "name": "Litecoin OTC",
        "payout": 80,
        "is_otc": True,
        "asset_type": "cryptocurrency",
    },
    {
        "symbol": "USCrude_otc",
        "name": "WTI Crude Oil OTC",
        "payout": 85,
        "is_otc": True,
        "asset_type": "commodity",
    },
    {
        "symbol": "AAPL_otc",
        "name": "Apple OTC",
        "payout": 85,
        "is_otc": True,
        "asset_type": "stock",
    },
    {
        "symbol": "AMZN_otc",
        "name": "Amazon OTC",
        "payout": 85,
        "is_otc": True,
        "asset_type": "stock",
    },
    {
        "symbol": "MSFT_otc",
        "name": "Microsoft OTC",
        "payout": 85,
        "is_otc": True,
        "asset_type": "stock",
    },
    {
        "symbol": "TSLA_otc",
        "name": "Tesla OTC",
        "payout": 85,
        "is_otc": True,
        "asset_type": "stock",
    },
]


def _bars_to_response(
    asset: str,
    timeframe_seconds: int,
    page,
) -> CandlesResponse:
    return CandlesResponse(
        asset=asset.strip(),
        timeframe_seconds=timeframe_seconds,
        candles=[
            CandleBarResponse(
                open_time=c.open_time,
                open=float(c.open),
                high=float(c.high),
                low=float(c.low),
                close=float(c.close),
                volume=None if c.volume is None else float(c.volume),
            )
            for c in page.candles
        ],
        has_more=page.has_more,
        next_cursor=page.next_cursor,
        total=page.total,
        broker_chunk_oldest=page.broker_chunk_oldest,
        broker_chunk_newest=page.broker_chunk_newest,
        broker_overlap=page.broker_overlap,
    )


@router.get(
    "/candles/range",
    response_model=CandlesResponse,
    summary="Candles inside a fixed time window",
    description=(
        "**What this endpoint is:** all candles from Pocket Option history for `[from, to]` "
        "in UTC in **one** response (ascending by open time), from a broker fetch anchored at "
        "`to`. "
        "Depth is capped by `STRAT_TRADE_MAX_CANDLES_PER_REQUEST`, "
        "`STRAT_TRADE_MAX_CANDLES_RANGE_TOTAL`, and native PO bar periods "
        "(1, 5, 15, 30, 60, 300 seconds). Very deep ranges may still need persisted candles "
        "(see `docs/PROJECT_CONTEXT.md`). "
        "\n\nBounds must not be in the future. "
        "`broker_chunk_*` shows the raw broker span—`[from, to]` should overlap it. "
        "**`YYYY-MM-DD`:** middle field is month (`02` February, `03` March)."
    ),
    operation_id="getMarketCandlesInRange",
)
async def read_candles_in_range(
    feed: CandleFeedDep,
    settings: SettingsDep,
    asset: str = Query(
        "EURUSD_otc",
        min_length=1,
        max_length=128,
        examples=["EURUSD_otc"],
        description="Pocket Option asset / pair identifier.",
    ),
    timeframe_seconds: int = Query(
        60,
        ge=1,
        le=2_592_000,
        examples=[60, 300],
        description=(
            "Candle period in seconds. Pocket Option native bars: 1, 5, 15, 30, 60, 300 "
            "(e.g. 1m=60, 5m=300). Other values return 400."
        ),
    ),
    range_start: datetime = Query(
        "2026-03-22T04:00:00Z",
        alias="from",
        description=(
            "Interval start (inclusive), ISO 8601 UTC (`YYYY-MM-DD`, MM=month). "
            "Must overlap `broker_chunk_oldest`…`broker_chunk_newest` (same calendar day/month)."
        ),
        examples=["2026-03-22T04:00:00Z"],
    ),
    range_end: datetime = Query(
        "2026-03-22T04:30:00Z",
        alias="to",
        description="Interval end (inclusive), not in the future (UTC).",
        examples=["2026-03-22T04:30:00Z"],
    ),
) -> CandlesResponse:
    page = await fetch_candles_in_range(
        feed,
        asset=asset,
        timeframe_seconds=timeframe_seconds,
        range_start=range_start,
        range_end=range_end,
        max_chunk=settings.max_candles_per_request,
        max_bars_in_range=settings.max_candles_range_total,
    )
    return _bars_to_response(asset, timeframe_seconds, page)


@router.get(
    "/candles",
    response_model=CandlesResponse,
    summary="Recent candles (tail history)",
    description=(
        "Latest `count` bars from Pocket Option, ascending by open time within the page. "
        "Optional `end_at` anchors the window end (omit for broker “now”). "
        "Older data: repeat with `cursor` = `next_cursor` (do not send `end_at` with `cursor`). "
        "`count` is capped by `STRAT_TRADE_MAX_CANDLES_PER_REQUEST`."
    ),
    operation_id="getMarketCandles",
)
async def read_recent_candles(
    feed: CandleFeedDep,
    settings: SettingsDep,
    asset: str = Query(
        "EURUSD_otc",
        min_length=1,
        max_length=128,
        examples=["EURUSD_otc"],
        description="Pocket Option asset / pair identifier.",
    ),
    timeframe_seconds: int = Query(
        60,
        ge=1,
        le=2_592_000,
        examples=[60, 300],
        description=(
            "Candle period in seconds. Pocket Option native bars: 1, 5, 15, 30, 60, 300 "
            "(e.g. 1m=60, 5m=300). Other values return 400."
        ),
    ),
    count: int = Query(
        100,
        ge=1,
        le=5000,
        description="Page size (max bars per request, capped by server settings).",
    ),
    end_at: datetime | None = Query(
        None,
        description="First page only: broker window end (ISO 8601). Omit for “now”.",
    ),
    cursor: datetime | None = Query(
        None,
        description=(
            "Older pages: `next_cursor` from the previous response (exclusive upper bound "
            "on bar open times for the next chunk)."
        ),
    ),
) -> CandlesResponse:
    page = await fetch_recent_candles(
        feed,
        asset=asset,
        timeframe_seconds=timeframe_seconds,
        count=count,
        max_count=settings.max_candles_per_request,
        end_at=end_at,
        cursor=cursor,
    )
    return _bars_to_response(asset, timeframe_seconds, page)


@router.get(
    "/assets",
    response_model=list[AssetItemResponse],
    summary="List available trading assets and payout rates",
    description=(
        "Returns all active assets from Pocket Option with human-readable names and payout rates."
    ),
    operation_id="getMarketAssets",
)
async def read_active_assets(
    feed: CandleFeedDep,
) -> list[AssetItemResponse]:
    if hasattr(feed, "get_assets"):
        raw_assets = await feed.get_assets()
        if raw_assets:
            return [AssetItemResponse(**a) for a in raw_assets]
    return [AssetItemResponse(**a) for a in _CURATED_ASSETS]
