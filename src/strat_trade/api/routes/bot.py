from fastapi import APIRouter
from pydantic import BaseModel
from strat_trade.core.bot_state import state

router = APIRouter(prefix="/bot", tags=["Bot Control"])

class StartBotRequest(BaseModel):
    assets: list[str]
    auto_trade: bool = False
    amount: float = 1.0
    timeframe_seconds: int = 60
    count: int = 200
    min_payout: int = 75

@router.post("/start", summary="Start the auto-trading bot")
async def start_bot(req: StartBotRequest):
    state.is_running = True
    state.assets = req.assets
    state.auto_trade = req.auto_trade
    state.amount = req.amount
    state.timeframe_seconds = req.timeframe_seconds
    state.count = req.count
    state.min_payout = req.min_payout
    return {"message": "Bot started", "state": state.__dict__}

@router.post("/stop", summary="Stop the auto-trading bot")
async def stop_bot():
    state.is_running = False
    return {"message": "Bot stopped", "state": state.__dict__}
