from typing import List

class BotState:
    is_running: bool = False
    assets: List[str] = ["EURUSD_otc"]
    auto_trade: bool = False
    amount: float = 1.0

# Global singleton
state = BotState()
