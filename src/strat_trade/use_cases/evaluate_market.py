from strat_trade.domain.market_state import MarketStateVector
from strat_trade.domain.services.market_evaluator import MarketStateEvaluator
from strat_trade.ports.candles import CandleFeed
from strat_trade.use_cases.fetch_candles import fetch_recent_candles


class EvaluateMarketUseCase:
    """Use case to fetch candles and evaluate the market state."""

    def __init__(self, candle_feed: CandleFeed, max_count: int = 5000) -> None:
        self._candle_feed = candle_feed
        self._max_count = max_count

    async def execute(self, asset: str, timeframe_seconds: int, count: int) -> MarketStateVector:
        # 1. Fetch `count` historical candles for the given asset and timeframe_seconds
        page = await fetch_recent_candles(
            feed=self._candle_feed,
            asset=asset,
            timeframe_seconds=timeframe_seconds,
            count=count,
            max_count=self._max_count,
        )

        # 2. Instantiate MarketStateEvaluator
        evaluator = MarketStateEvaluator()

        # 3. Pass the fetched candles into the evaluator
        # 4. Return the resulting MarketStateVector
        return evaluator.evaluate(page.candles)
