from __future__ import annotations

from fastapi import APIRouter

from strat_trade.api.deps import TradingGatewayDep
from strat_trade.api.schemas import BalanceResponse
from strat_trade.use_cases.get_balance import fetch_balance

router = APIRouter()


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
