import abc
from datetime import datetime

from strat_trade.domain.trade_record import TradeSignalRecord


class SignalRepository(abc.ABC):
    """Port for persisting and retrieving generated trade signals."""

    @abc.abstractmethod
    async def save_signal(self, record: TradeSignalRecord) -> TradeSignalRecord:
        """Saves a trade signal record to persistence."""
    @abc.abstractmethod
    async def get_recent_signals(self, limit: int = 50) -> list[TradeSignalRecord]:
        """Retrieves a list of recent trade signals."""

    @abc.abstractmethod
    async def get_unresolved_signals(self, up_to_time: datetime) -> list[TradeSignalRecord]:
        """Signals not yet resolved whose expected close time is on or before `up_to_time`."""

    @abc.abstractmethod
    async def update_signal_resolution(
        self, signal_id: int, actual_close_price: float, pnl_result: str
    ) -> None:
        """Persist settlement price, PnL label, and mark the signal resolved."""

    @abc.abstractmethod
    async def delete_signal(self, signal_id: int) -> bool:
        """Remove a signal row by primary key. Returns True if a row was deleted."""

    @abc.abstractmethod
    async def has_unresolved_signal(self, asset: str) -> bool:
        """Returns True if there is an active/unresolved trade for the given asset."""

    @abc.abstractmethod
    async def get_trade_statistics(self) -> dict:
        """Returns a dictionary with aggregated PnL statistics."""
