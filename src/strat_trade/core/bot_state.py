from typing import List

class BotState:
    is_running: bool = False
    assets: List[str] = ["EURUSD_otc"]
    auto_trade: bool = False
    amount: float = 1.0
    timeframe_seconds: int = 60
    count: int = 200

# Global singleton
state = BotState()
