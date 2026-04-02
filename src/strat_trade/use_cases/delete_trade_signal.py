from strat_trade.ports.signal_repository import SignalRepository


class DeleteTradeSignalUseCase:
    """Remove a persisted forward-test signal by id."""

    def __init__(self, signal_repository: SignalRepository) -> None:
        self._signal_repository = signal_repository

    async def execute(self, signal_id: int) -> bool:
        return await self._signal_repository.delete_signal(signal_id)
