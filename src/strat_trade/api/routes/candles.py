"""Candles API route."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from strat_trade.ports.trading_gateway import TradingGateway
from strat_trade.use_cases.get_candles import get_candles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/candles", tags=["Market data"])


def _get_gateway(request: Request) -> TradingGateway:
    gateway = getattr(request.app.state, "trading_gateway", None)
    if gateway is None:
        raise HTTPException(status_code=503, detail="Trading gateway not available")
    return gateway


@router.get("", response_model=dict)
async def api_candles(
    request: Request,
    asset: str = Query(..., example="EURUSD_otc", description="Asset symbol (e.g. EURUSD_otc)"),
    period: int = 60,
    limit: int = 100,
    gateway: TradingGateway = Depends(_get_gateway),
) -> dict:
    """Return OHLC candles for the given asset and period (seconds)."""
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
    if period < 1:
        raise HTTPException(status_code=400, detail="period must be positive")
    try:
        candles = await get_candles(gateway, asset=asset, period=period, limit=limit)
        return {
            "candles": [
                {"open": c.open, "high": c.high, "low": c.low, "close": c.close, "time": c.time}
                for c in candles
            ],
        }
    except Exception as e:
        logger.warning("Candles request failed: %s", e, exc_info=True)
        if "auth" in str(e).lower() or "session" in str(e).lower():
            raise HTTPException(status_code=401, detail="Invalid or expired session") from e
        raise HTTPException(
            status_code=503,
            detail="Trading service temporarily unavailable",
        ) from e
