from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SignalSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class StrategySignal:
    index: int
    side: SignalSide
    open_time: datetime
    entry_close: float


@dataclass(frozen=True, slots=True)
class StrategyWinrateResult:
    asset: str
    timeframe_seconds: int
    expiry_seconds: int
    total_signals: int
    wins: int
    losses: int
    skipped_signals: int
    winrate_percent: float
    period_from: datetime
    period_to: datetime
