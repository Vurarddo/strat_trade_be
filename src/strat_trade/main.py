from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from strat_trade.adapters.pocket_option_gateway import PocketOptionTradingGateway
from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.backtest import router as backtest_router
from strat_trade.api.routes.balance import router as balance_router
from strat_trade.api.routes.candles import router as candles_router
from strat_trade.api.routes.indicator_catalog import router as indicator_catalog_router
from strat_trade.api.routes.indicators import router as indicators_router
from strat_trade.api.routes.tradingview import router as tradingview_router
from strat_trade.api.routes.web import router as web_router
from strat_trade.settings import Settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    gateway = PocketOptionTradingGateway(
        ssid=settings.pocket_option_ssid,
        is_demo=settings.pocket_option_is_demo,
        region=settings.pocket_option_region,
        use_raw_auth_frame=settings.pocket_option_use_raw_auth_frame,
        sdk_debug=settings.pocket_option_sdk_debug,
    )
    app.state.settings = settings
    app.state.trading_gateway = gateway
    logger.info("Strat Trade started (Pocket Option demo=%s).", settings.pocket_option_is_demo)
    yield
    await gateway.aclose()
    logger.info("Strat Trade shutdown complete.")


app = FastAPI(
    title="Strat Trade API",
    version="0.1.0",
    description="Backend for strategy composition, backtests, and Pocket Option market data.",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Web UI", "description": "Interactive Web Dashboard and endpoint test console."},
        {"name": "Backtest", "description": "Binary options backtesting and strategy evaluation."},
        {"name": "Account", "description": "Broker-linked account views (balance, etc.)."},
        {"name": "Market data", "description": "Historical candles and read-only market series."},
        {
            "name": "TradingView",
            "description": "TradingView historical OHLCV for data preview before backtests.",
        },
        {"name": "System", "description": "Health and process metadata."},
    ],
)

register_domain_exception_handlers(app)


@app.get("/health", tags=["System"], summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(web_router)
app.include_router(backtest_router, prefix="/api/v1")
app.include_router(balance_router, prefix="/api/v1", tags=["Account"])
app.include_router(candles_router, prefix="/api/v1", tags=["Market data"])
app.include_router(indicators_router, prefix="/api/v1", tags=["Market data"])
app.include_router(indicator_catalog_router, prefix="/api/v1", tags=["Market data"])
app.include_router(tradingview_router, prefix="/api/v1", tags=["TradingView"])
