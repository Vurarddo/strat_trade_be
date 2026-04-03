from typing import Any

from fastapi import APIRouter, Depends

from strat_trade.api.deps import get_trading_gateway
from strat_trade.ports.trading_gateway import TradingGateway

router = APIRouter(prefix="/assets", tags=["Market data"])


@router.get("", summary="Get all available assets")
async def get_available_assets(
    gateway: TradingGateway = Depends(get_trading_gateway),
) -> list[dict[str, Any]]:
    """
    Fetch a list of all available assets and their full data from the broker.
    """
    return await gateway.get_available_assets()
