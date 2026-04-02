from strat_trade.domain.trade_record import TradeSignalRecord
from strat_trade.ports.signal_repository import SignalRepository


class GetRecentSignalsUseCase:
    """Use case to retrieve the most recent trade signals."""

    def __init__(self, signal_repository: SignalRepository) -> None:
        self._signal_repository = signal_repository

    async def execute(self, limit: int = 50) -> list[TradeSignalRecord]:
        return await self._signal_repository.get_recent_signals(limit)
