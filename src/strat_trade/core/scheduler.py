import asyncio
import logging
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from strat_trade.adapters.db.sqlite_signal_repository import SqliteSignalRepository
from strat_trade.adapters.gemini_adapter import GeminiAdapter
from strat_trade.core.bot_state import state
from strat_trade.use_cases.evaluate_pending_signals import EvaluatePendingSignalsUseCase
from strat_trade.use_cases.generate_trading_signal import GenerateTradingSignalUseCase

logger = logging.getLogger(__name__)

async def poll_assets_job(app: FastAPI) -> None:
    """Job to poll multiple assets for trading signals."""
    if not state.is_running:
        return

    logger.info("Starting poll_assets_job...")
    
    settings = app.state.settings
    trading_gateway = app.state.trading_gateway
    candle_feed = trading_gateway
    
    llm_gateway = GeminiAdapter(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
    )
    signal_repository = SqliteSignalRepository()
    
    use_case = GenerateTradingSignalUseCase(
        candle_feed=candle_feed,
        llm_gateway=llm_gateway,
        signal_repository=signal_repository,
        trading_gateway=trading_gateway,
    )
    
    for asset in state.assets:
        try:
            # Overlap check
            if await signal_repository.has_unresolved_signal(asset):
                logger.info(f"Skipping {asset}: active trade exists.")
                continue

            logger.info(f"Polling asset {asset}...")
            result = await use_case.execute(
                asset=asset,
                timeframe_seconds=state.timeframe_seconds,
                count=state.count,
                auto_trade=state.auto_trade,
                amount=state.amount,
            )
            logger.info(f"Poll result for {asset}: {result.get('llm_signal', {}).get('direction')}")
        except Exception as e:
            logger.error(f"Error polling asset {asset}: {e}", exc_info=True)
            
        # Small sleep to avoid hitting rate limits
        await asyncio.sleep(1.0)
        
    logger.info("Finished poll_assets_job.")


async def resolve_pending_trades_job(app: FastAPI) -> None:
    """Job to resolve pending trades and update their PnL status."""
    logger.info("Starting resolve_pending_trades_job...")
    
    trading_gateway = app.state.trading_gateway
    candle_feed = trading_gateway
    signal_repository = SqliteSignalRepository()
    
    use_case = EvaluatePendingSignalsUseCase(
        signal_repository=signal_repository,
        candle_feed=candle_feed,
    )
    
    try:
        result = await use_case.execute()
        logger.info(f"Resolved {result.get('signals_evaluated', 0)} pending trades.")
    except Exception as e:
        logger.error(f"Error resolving pending trades: {e}", exc_info=True)


def start_scheduler(app: FastAPI) -> AsyncIOScheduler:
    """Initialize and start the APScheduler."""
    scheduler = AsyncIOScheduler()
    
    # Add poll_assets_job to run every 60 seconds
    scheduler.add_job(
        poll_assets_job,
        "interval",
        seconds=60,
        args=[app],
        id="poll_assets_job",
        replace_existing=True,
    )
    
    # Add resolve_pending_trades_job to run every 30 seconds
    scheduler.add_job(
        resolve_pending_trades_job,
        "interval",
        seconds=30,
        args=[app],
        id="resolve_pending_trades_job",
        replace_existing=True,
    )
    
    scheduler.start()
    logger.info("APScheduler started with background jobs.")
    
    return scheduler
