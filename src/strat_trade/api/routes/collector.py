from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from strat_trade.api.deps import TradingGatewayDep
from strat_trade.api.routes.candles import _CURATED_ASSETS
from strat_trade.api.schemas import (
    CollectorAssetResponse,
    CollectorStatusResponse,
    StartCollectorRequest,
)
from strat_trade.use_cases.manage_collector import (
    get_collector_engine,
    get_collector_status,
    start_collector,
    stop_collector,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/collector", tags=["Market Data Collector"])


@router.get(
    "/available-assets",
    response_model=list[CollectorAssetResponse],
    summary="List available broker assets for collection",
    description=(
        "Returns live active assets from Pocket Option via shared gateway with curated fallback."
    ),
    operation_id="getCollectorAvailableAssets",
)
async def get_available_assets(gateway: TradingGatewayDep) -> list[CollectorAssetResponse]:
    if hasattr(gateway, "get_assets"):
        try:
            raw_assets = await gateway.get_assets()
            if raw_assets:
                return [
                    CollectorAssetResponse(
                        symbol=a["symbol"],
                        name=a.get("name", a["symbol"]),
                        payout=int(a.get("payout", 80)),
                        is_otc=bool(a.get("is_otc", True)),
                        asset_type=str(a.get("asset_type", "currency")),
                    )
                    for a in raw_assets
                ]
        except Exception as exc:
            logger.warning("Error querying broker assets for collector: %s", exc)

    return [
        CollectorAssetResponse(
            symbol=a["symbol"],
            name=a["name"],
            payout=int(a["payout"]),
            is_otc=bool(a["is_otc"]),
            asset_type=str(a["asset_type"]),
        )
        for a in _CURATED_ASSETS
    ]


@router.get(
    "/status",
    response_model=CollectorStatusResponse,
    summary="Get background data collector status",
    description=(
        "Returns current collector running state, cycle progress, and database candle stats."
    ),
    operation_id="getCollectorStatus",
)
def get_status(request: Request) -> CollectorStatusResponse:
    store = getattr(request.app.state, "market_data_store", None)
    return get_collector_status(store=store)


@router.post(
    "/start",
    response_model=CollectorStatusResponse,
    summary="Start background candle collector task",
    description="Launches or updates the background S1/M1 candle collection loop inside FastAPI.",
    operation_id="startCollector",
)
async def start_collection(
    req: StartCollectorRequest,
    gateway: TradingGatewayDep,
    request: Request,
) -> CollectorStatusResponse:
    store = getattr(request.app.state, "market_data_store", None)
    return await start_collector(
        gateway=gateway,
        assets=req.assets,
        timeframe_seconds=req.timeframe_seconds,
        candles_count=req.candles_count,
        interval_seconds=req.interval_seconds,
        throttle_delay=req.throttle_delay,
        store=store,
    )


@router.post(
    "/stop",
    response_model=CollectorStatusResponse,
    summary="Stop background candle collector task",
    description="Gracefully halts the background collection loop.",
    operation_id="stopCollector",
)
async def stop_collection(request: Request) -> CollectorStatusResponse:
    store = getattr(request.app.state, "market_data_store", None)
    if store is not None:
        get_collector_engine().set_store(store)
    return await stop_collector()
