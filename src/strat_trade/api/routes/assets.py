from __future__ import annotations

from fastapi import APIRouter, Query

from strat_trade.api.deps import TradingGatewayDep
from strat_trade.api.schemas import BrokerAssetResponse, BrokerAssetsResponse
from strat_trade.use_cases.list_assets import fetch_assets

router = APIRouter(prefix="/market")


@router.get(
    "/assets",
    response_model=BrokerAssetsResponse,
    summary="Pocket Option tradable asset catalog",
    description=(
        "Returns instruments from the live Pocket Option session (after asset sync). "
        "Each row includes **is_active** when the broker provides it; use **`active_only=true`** "
        "to return only rows marked active. The underlying SDK call is "
        "`PocketOptionAsync.active_assets()` — inactive instruments may be omitted entirely "
        "depending on broker payload."
    ),
    operation_id="getMarketAssets",
)
async def read_assets(
    gateway: TradingGatewayDep,
    active_only: bool = Query(
        False,
        description="If true, only assets with is_active=true are returned.",
    ),
) -> BrokerAssetsResponse:
    rows = await fetch_assets(gateway, active_only=active_only)
    return BrokerAssetsResponse(
        active_only=active_only,
        assets=[
            BrokerAssetResponse(
                asset_id=a.asset_id,
                symbol=a.symbol,
                name=a.name,
                asset_type=a.asset_type,
                payout=a.payout,
                is_otc=a.is_otc,
                is_active=a.is_active,
                allowed_candles=list(a.allowed_candles),
            )
            for a in rows
        ],
    )
