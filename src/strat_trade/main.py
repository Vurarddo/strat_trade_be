"""FastAPI app: lifespan sets up Pocket Option client and gateway; Swagger at /docs."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from strat_trade.adapters.pocket_option_gateway import PocketOptionGateway
from strat_trade.api.routes import balance, candles
from strat_trade.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create Pocket Option client and gateway on startup; close client on shutdown."""
    settings = get_settings()
    client = None
    app.state.trading_gateway = None
    try:
        ssid = settings.get_ssid()
        logger.info("Pocket Option SSID loaded (len=%d)", len(ssid))
        from BinaryOptionsToolsV2 import PocketOptionAsync
        client = PocketOptionAsync(ssid=ssid)
        await client.__aenter__()
        gateway = PocketOptionGateway(client)
        app.state.trading_gateway = gateway
        logger.info("Pocket Option gateway ready")
        yield
    except ValueError as e:
        logger.warning("Pocket Option not configured: %s", e)
        yield
    except Exception as e:
        err_msg = str(e).lower()
        if "parse ssid" in err_msg or "session data" in err_msg:
            logger.warning(
                "Pocket Option SSID rejected by library (expected full auth message). "
                "Copy the complete 42[\"auth\",{...}] from browser: F12 → Network → WS → "
                "Socket.IO connection → Messages → copy the auth message (includes long \"session\" string). Error: %s",
                e,
            )
        else:
            logger.warning("Pocket Option connection failed: %s", e, exc_info=True)
        yield
    finally:
        if client is not None:
            try:
                await client.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("Client shutdown: %s", e)


app = FastAPI(
    title="Strat Trade API",
    description="Pocket Option–backed trading API for balance and market data (candles).",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(balance.router, prefix="/api")
app.include_router(candles.router, prefix="/api")
