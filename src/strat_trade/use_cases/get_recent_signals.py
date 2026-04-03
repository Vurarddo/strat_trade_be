from strat_trade.domain.trade_record import TradeSignalRecord
from strat_trade.ports.signal_repository import SignalRepository


class GetRecentSignalsUseCase:
    """Use case to retrieve the most recent trade signals and statistics."""

    def __init__(self, signal_repository: SignalRepository) -> None:
        self._signal_repository = signal_repository

    async def execute(self, limit: int = 50) -> dict:
        signals = await self._signal_repository.get_recent_signals(limit)
        stats = await self._signal_repository.get_trade_statistics()
        return {
            "stats": stats,
            "signals": signals
        }
