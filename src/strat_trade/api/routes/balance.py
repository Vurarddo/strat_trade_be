"""Balance API route."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from strat_trade.ports.trading_gateway import TradingGateway
from strat_trade.use_cases.get_balance import get_balance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/balance", tags=["Account"])


def _get_gateway(request: Request) -> TradingGateway:
    gateway = getattr(request.app.state, "trading_gateway", None)
    if gateway is None:
        raise HTTPException(status_code=503, detail="Trading gateway not available")
    return gateway


@router.get("", response_model=dict)
async def api_balance(
    request: Request,
    gateway: TradingGateway = Depends(_get_gateway),
) -> dict:
    """Return current account balance."""
    try:
        balance = await get_balance(gateway)
        return {"balance": balance.value}
    except Exception as e:
        logger.warning("Balance request failed: %s", e, exc_info=True)
        if "auth" in str(e).lower() or "session" in str(e).lower():
            raise HTTPException(status_code=401, detail="Invalid or expired session") from e
        raise HTTPException(
            status_code=503,
            detail="Trading service temporarily unavailable",
        ) from e
