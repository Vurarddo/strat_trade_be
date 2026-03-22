from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from strat_trade.api.schemas import BalanceResponse
from strat_trade.ports.trading_gateway import TradingGateway
from strat_trade.use_cases.get_balance import fetch_balance

router = APIRouter()


def get_trading_gateway(request: Request) -> TradingGateway:
    gateway = getattr(request.app.state, "trading_gateway", None)
    if gateway is None:
        raise RuntimeError("Trading gateway is not configured on the application.")
    return gateway


TradingGatewayDep = Annotated[TradingGateway, Depends(get_trading_gateway)]


@router.get(
    "/balance",
    response_model=BalanceResponse,
    summary="Get Pocket Option account balance",
    description=(
        "Returns the current balance for the Pocket Option session configured via "
        "`POCKET_OPTION_SSID` (or `STRAT_TRADE_POCKET_OPTION_SSID`). Values are normalized; "
        "they are not raw broker payloads."
    ),
    operation_id="getAccountBalance",
)
async def read_balance(gateway: TradingGatewayDep) -> BalanceResponse:
    balance = await fetch_balance(gateway)
    return BalanceResponse(
        amount=float(balance.amount),
        currency=balance.currency,
        is_demo=balance.is_demo,
    )
