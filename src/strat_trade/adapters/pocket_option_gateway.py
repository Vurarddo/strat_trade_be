"""Pocket Option gateway adapter. All broker-specific code and library fixes here."""

import asyncio
import logging
import time
from typing import Any

from strat_trade.domain.entities import Balance, Candle
from strat_trade.ports.trading_gateway import TradingGateway

logger = logging.getLogger(__name__)


def _apply_library_logger_fix() -> None:
    """BinaryOptionsToolsV2 Logger may lack .warn(); Python 3 uses .warning()."""
    try:
        import BinaryOptionsToolsV2.tracing as _tracing
        if not hasattr(_tracing.Logger, "warn"):
            _tracing.Logger.warn = lambda self, msg: None  # noqa: ARG005
    except Exception:  # noqa: S110
        pass


def _candle_from_dict(data: dict[str, Any]) -> Candle:
    """Map broker candle dict to domain Candle."""
    return Candle(
        open=float(data.get("open", 0)),
        high=float(data.get("high", 0)),
        low=float(data.get("low", 0)),
        close=float(data.get("close", 0)),
        time=int(data.get("time", data.get("timestamp", 0))),
    )


class PocketOptionGateway(TradingGateway):
    """Implements TradingGateway using BinaryOptionsTools-v2 PocketOptionAsync."""

    def __init__(self, client: Any) -> None:
        """Store the async client (PocketOptionAsync). Do not log or store SSID."""
        self._client = client

    async def balance(self) -> Balance:
        """Return current account balance from Pocket Option."""
        value = await self._client.balance()
        return Balance(value=float(value))

    async def candles(self, asset: str, period: int, limit: int = 100) -> list[Candle]:
        """Return historical candles: subscribe and collect up to limit with timeout."""
        _apply_library_logger_fix()
        result: list[Candle] = []
        try:
            stream = await self._client.subscribe_symbol(asset)
            timeout_seconds = 30
            deadline = time.monotonic() + timeout_seconds
            async for raw in stream:
                if time.monotonic() > deadline:
                    break
                try:
                    result.append(_candle_from_dict(raw))
                except (TypeError, ValueError, KeyError) as e:
                    logger.debug("Skip invalid candle payload: %s", e)
                    continue
                if len(result) >= limit:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Candles stream error: %s", e, exc_info=True)
            raise
        return result
