from datetime import UTC, datetime

from pydantic import BaseModel, Field


class TradeSignalRecord(BaseModel):
    id: int | None = None
    asset: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    direction: str  # "BUY", "SELL", "NEUTRAL"
    entry_price: float
    expiration_in_seconds: int
    expected_close_time: datetime
    strategy_name: str
    win_probability_percentage: int
    # Fields for later evaluation:
    is_resolved: bool = False
    auto_executed: bool = False
    actual_close_price: float | None = None
    pnl_result: str | None = None  # "WIN", "LOSS", "TIE"
    broker_trade_id: str | None = None
