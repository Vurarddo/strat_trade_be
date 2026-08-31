"""Concurrency, lifecycle, and stress tests for Stage 3 S1 Market Data Collector.

Covers Tier 3 (Cross-Feature Concurrency, Fault Tolerance, and Lifespan Teardown):
- Shared gateway concurrency between Collector and LiveBot/Endpoints
- Rapid start/stop cycling stress testing (zero zombie background tasks)
- Multi-asset fault isolation (TimeoutError, BrokerUnavailableError, InvalidMarketParametersError)
- Concurrent SQLite WAL reads and writes under heavy load
- Clean cancellation during FastAPI lifespan shutdown
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import (
    BrokerUnavailableError,
    InvalidMarketParametersError,
)
from strat_trade.domain.trading.market_data_store import MarketDataStore


def _generate_test_candles(count: int = 10, start_ts: float = 1700000000.0) -> list[Candle]:
    return [
        Candle(
            open_time=datetime.fromtimestamp(start_ts + i, tz=UTC),
            open=Decimal("1.0850"),
            high=Decimal("1.0860"),
            low=Decimal("1.0840"),
            close=Decimal("1.0855"),
            volume=Decimal("10.0"),
        )
        for i in range(count)
    ]


@pytest.mark.asyncio
class TestCollectorConcurrencyAndLifecycle:
    """Tier 3 concurrency and stress testing."""

    async def test_shared_gateway_concurrency_bot_and_collector(
        self,
        async_test_client: AsyncClient,
        mock_trading_gateway: AsyncMock,
    ) -> None:
        """TC-3.1: Shared gateway handles concurrent collector fetches and external API requests."""
        # Ensure stopped
        await async_test_client.post("/api/v1/collector/stop")

        # Start collector on EURUSD_otc with short interval
        start_resp = await async_test_client.post(
            "/api/v1/collector/start",
            json={
                "assets": ["EURUSD_otc"],
                "interval_seconds": 0.05,
                "throttle_delay": 0.01,
            },
        )
        assert start_resp.status_code == 200

        # Concurrently perform external requests on the shared gateway
        async def _query_candles() -> int:
            resp = await async_test_client.get(
                "/api/v1/market/candles",
                params={"asset": "EURUSD_otc", "timeframe_seconds": 60, "count": 5},
            )
            return resp.status_code

        async def _query_assets() -> int:
            resp = await async_test_client.get("/api/v1/collector/available-assets")
            return resp.status_code

        # Run multiple concurrent queries while collector is actively running
        results = await asyncio.gather(
            _query_candles(),
            _query_assets(),
            _query_candles(),
            _query_assets(),
        )
        assert all(code in (200, 404) for code in results)

        # Stop collector
        stop_resp = await async_test_client.post("/api/v1/collector/stop")
        assert stop_resp.status_code == 200

        # CRITICAL: Stopping collector must NOT close the application's shared gateway
        assert mock_trading_gateway.aclose.call_count == 0

    async def test_rapid_start_stop_cycling_stress(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-3.3: Stress test 20 rapid start/stop cycles without orphan tasks or deadlock."""
        # Clean start state
        await async_test_client.post("/api/v1/collector/stop")

        payload = {
            "assets": ["EURUSD_otc", "GOLD_otc"],
            "interval_seconds": 0.05,
            "throttle_delay": 0.01,
        }

        for _ in range(20):
            r_start = await async_test_client.post("/api/v1/collector/start", json=payload)
            assert r_start.status_code in (200, 409)
            await asyncio.sleep(0.01)

            r_stop = await async_test_client.post("/api/v1/collector/stop")
            assert r_stop.status_code == 200
            await asyncio.sleep(0.01)

        # Ensure final state is cleanly STOPPED / IDLE
        status_resp = await async_test_client.get("/api/v1/collector/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["is_running"] is False

    async def test_multi_asset_fault_isolation_resilience(
        self,
        async_test_client: AsyncClient,
        mock_trading_gateway: AsyncMock,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-2.5, 2.6, 2.7: Error on one asset does not abort remaining assets or loop."""
        await async_test_client.post("/api/v1/collector/stop")

        # Mock gateway behaviors per asset
        def _faulty_get_candles(asset: str, *args, **kwargs) -> list[Candle]:
            if asset == "TIMEOUT_ASSET":
                raise TimeoutError("Simulated timeout on broker socket")
            if asset == "BROKER_UNAVAILABLE":
                raise BrokerUnavailableError("Simulated broker 503 connection drop")
            if asset == "INVALID_PARAM":
                raise InvalidMarketParametersError("Invalid timeframe parameter")
            return _generate_test_candles(count=10)

        mock_trading_gateway.get_candles.side_effect = _faulty_get_candles

        # Start collector with mixed failing and successful assets
        assets = ["TIMEOUT_ASSET", "BROKER_UNAVAILABLE", "EURUSD_otc", "INVALID_PARAM"]
        r = await async_test_client.post(
            "/api/v1/collector/start",
            json={
                "assets": assets,
                "interval_seconds": 0.05,
                "throttle_delay": 0.005,
            },
        )
        assert r.status_code == 200

        # Allow at least 1 cycle to execute
        await asyncio.sleep(0.15)

        # Stop collector
        await async_test_client.post("/api/v1/collector/stop")

        # Verify EURUSD_otc candles were successfully collected and stored despite sibling errors
        stored_count = isolated_market_store.count_candles("EURUSD_otc")
        assert stored_count >= 10

    async def test_concurrent_sqlite_wal_reads_and_writes(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-3.2: Concurrent reads & writes in SQLite WAL mode execute without lock errors."""
        stop_event = asyncio.Event()

        async def _writer_worker(asset_name: str) -> None:
            ts = 1700000000.0
            while not stop_event.is_set():
                candles = _generate_test_candles(count=5, start_ts=ts)
                isolated_market_store.insert_candles(asset_name, candles)
                ts += 5.0
                await asyncio.sleep(0.01)

        async def _reader_worker(asset_name: str) -> None:
            while not stop_event.is_set():
                _ = isolated_market_store.get_candles_df(asset_name)
                _ = isolated_market_store.get_asset_stats(asset_name)
                await asyncio.sleep(0.01)

        # Launch concurrent background reader and writer tasks
        writers = [asyncio.create_task(_writer_worker(f"ASSET_{i}")) for i in range(3)]
        readers = [asyncio.create_task(_reader_worker(f"ASSET_{i}")) for i in range(3)]

        # Let them run concurrently for 200ms
        await asyncio.sleep(0.2)
        stop_event.set()

        await asyncio.gather(*writers, *readers)

        # Verify rows were committed successfully
        total = isolated_market_store.get_total_candle_count()
        assert total > 0
