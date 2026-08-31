"""Centralized pytest fixtures and test harness for Strat Trade test suite.

Provides isolated SQLite database instances, standardized AsyncMock trading gateways,
realistic S1/M1 candle feeds, and asynchronous ASGI HTTP test clients.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from strat_trade.domain.entities import Candle
from strat_trade.domain.trading.market_data_store import MarketDataStore
from strat_trade.main import app as main_app
from strat_trade.settings import Settings


@pytest.fixture
def isolated_market_store(tmp_path: Path) -> MarketDataStore:
    """Provides a fresh, isolated MarketDataStore backed by a temporary SQLite database."""
    db_file = tmp_path / "test_market_data.db"
    return MarketDataStore(db_path=db_file)


@pytest.fixture
def sample_assets_list() -> list[dict[str, Any]]:
    """Standardized list of broker asset descriptors."""
    return [
        {
            "symbol": "EURUSD_otc",
            "name": "EUR/USD OTC",
            "payout": 92,
            "is_otc": True,
            "asset_type": "currency",
        },
        {
            "symbol": "GOLD_otc",
            "name": "Gold OTC",
            "payout": 88,
            "is_otc": True,
            "asset_type": "commodity",
        },
        {
            "symbol": "AUDNZD_otc",
            "name": "AUD/NZD OTC",
            "payout": 85,
            "is_otc": True,
            "asset_type": "currency",
        },
        {
            "symbol": "USDJPY_otc",
            "name": "USD/JPY OTC",
            "payout": 90,
            "is_otc": True,
            "asset_type": "currency",
        },
        {
            "symbol": "BTCUSD",
            "name": "Bitcoin",
            "payout": 75,
            "is_otc": False,
            "asset_type": "cryptocurrency",
        },
    ]


def generate_candle_series(
    count: int = 300,
    start_ts: float = 1700000000.0,
    base_price: float = 1.0850,
    step_seconds: int = 1,
) -> list[Candle]:
    """Generates realistic synthetic candle series with monotonic UTC timestamps."""
    candles: list[Candle] = []
    for i in range(count):
        ts = start_ts + (i * step_seconds)
        dt = datetime.fromtimestamp(ts, tz=UTC)
        drift = (i % 10 - 5) * 0.0001
        open_p = Decimal(f"{base_price + drift:.5f}")
        high_p = Decimal(f"{base_price + drift + 0.0005:.5f}")
        low_p = Decimal(f"{base_price + drift - 0.0005:.5f}")
        close_p = Decimal(f"{base_price + drift + 0.0002:.5f}")
        candles.append(
            Candle(
                open_time=dt,
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
                volume=Decimal("100.0"),
            )
        )
    return candles


@pytest.fixture
def sample_s1_candles() -> list[Candle]:
    """Sample sequence of 100 1-second candles."""
    return generate_candle_series(count=100, step_seconds=1)


@pytest.fixture
def mock_trading_gateway(sample_assets_list: list[dict[str, Any]]) -> AsyncMock:
    """Standardized AsyncMock conforming to TradingGateway and CandleFeed ports."""
    gateway = AsyncMock()
    gateway.get_assets = AsyncMock(return_value=list(sample_assets_list))

    def _default_get_candles(
        asset: str,
        timeframe: int | str = 1,
        *,
        count: int = 300,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        step = int(timeframe) if str(timeframe).isdigit() else 1
        return generate_candle_series(count=count, step_seconds=step)

    gateway.get_candles = AsyncMock(side_effect=_default_get_candles)
    gateway.get_recent_candles = AsyncMock(side_effect=_default_get_candles)
    gateway.aclose = AsyncMock()
    return gateway


@pytest.fixture
async def async_test_client(
    mock_trading_gateway: AsyncMock,
    isolated_market_store: MarketDataStore,
) -> AsyncGenerator[AsyncClient, None]:
    """Async ASGI test client bound to FastAPI main_app with injected mocks.

    Uses httpx.ASGITransport to guarantee that tests, background tasks,
    and HTTP endpoints run on the same asyncio event loop.
    """
    main_app.state.trading_gateway = mock_trading_gateway
    main_app.state.market_data_store = isolated_market_store
    if not hasattr(main_app.state, "settings") or main_app.state.settings is None:
        main_app.state.settings = Settings()

    transport = ASGITransport(app=main_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
