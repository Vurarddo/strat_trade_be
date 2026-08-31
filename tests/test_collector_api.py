"""Unit and REST API tests for Stage 3 S1 Market Data Collector.

Covers Tier 1 (Feature Contracts) and Tier 2 (Boundary Values & Error Handling):
- Available assets discovery endpoint
- Collector lifecycle status inspection (IDLE / RUNNING / STOPPED)
- Start collector payload validation, sanitization, parameter customization
- Stop collector graceful cancellation and idempotence
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import BrokerUnavailableError
from strat_trade.domain.trading.market_data_store import MarketDataStore


@pytest.mark.asyncio
class TestCollectorAvailableAssetsAPI:
    """Tests for GET /api/v1/collector/available-assets."""

    async def test_get_available_assets_success(
        self,
        async_test_client: AsyncClient,
        mock_trading_gateway: AsyncMock,
    ) -> None:
        """TC-1.1: Verify available assets endpoint returns correctly structured asset items."""
        response = await async_test_client.get("/api/v1/collector/available-assets")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

        first = data[0]
        assert "symbol" in first
        assert "name" in first
        assert "payout" in first
        assert "is_otc" in first
        assert "asset_type" in first

        symbols = [a["symbol"] for a in data]
        assert "EURUSD_otc" in symbols
        assert "GOLD_otc" in symbols

    async def test_get_available_assets_gateway_error_resilience(
        self,
        async_test_client: AsyncClient,
        mock_trading_gateway: AsyncMock,
    ) -> None:
        """TC-2.6: Verify graceful fallback when gateway raises BrokerUnavailableError."""
        mock_trading_gateway.get_assets.side_effect = BrokerUnavailableError(
            "Pocket Option connection down"
        )
        response = await async_test_client.get("/api/v1/collector/available-assets")
        # Should return fallback assets (200) or handled 503/200 empty list
        assert response.status_code in (200, 503)
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)


@pytest.mark.asyncio
class TestCollectorStatusAPI:
    """Tests for GET /api/v1/collector/status."""

    async def test_get_collector_status_initial_idle(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-1.2: Initial collector state before starting is IDLE or STOPPED."""
        # Ensure stopped first
        await async_test_client.post("/api/v1/collector/stop")

        response = await async_test_client.get("/api/v1/collector/status")
        assert response.status_code == 200
        data = response.json()
        assert data["is_running"] is False
        assert data["status"] in ("IDLE", "STOPPED")
        assert isinstance(data["active_assets"], list)
        assert len(data["active_assets"]) == 0

    async def test_get_collector_status_with_database_candle_stats(
        self,
        async_test_client: AsyncClient,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-1.4: Verify status endpoint aggregates counts from MarketDataStore."""
        # Seed test candles
        now = datetime.now(UTC)
        candles = [
            Candle(
                open_time=now,
                open=Decimal("1.0850"),
                high=Decimal("1.0860"),
                low=Decimal("1.0840"),
                close=Decimal("1.0855"),
                volume=Decimal("10.0"),
            )
        ]
        isolated_market_store.insert_candles("EURUSD_otc", candles)

        response = await async_test_client.get("/api/v1/collector/status")
        assert response.status_code == 200
        data = response.json()
        assert data["total_database_candles"] >= 1
        if "asset_stats" in data and isinstance(data["asset_stats"], list):
            eurusd_stat = next(
                (s for s in data["asset_stats"] if s["asset"] == "EURUSD_otc"),
                None,
            )
            if eurusd_stat is not None:
                assert eurusd_stat["count"] >= 1


@pytest.mark.asyncio
class TestCollectorStartAPI:
    """Tests for POST /api/v1/collector/start."""

    async def test_post_collector_start_valid_assets(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-1.3: Starting collector with valid asset list spawns background loop."""
        # Stop first in case previous test ran
        await async_test_client.post("/api/v1/collector/stop")

        payload = {
            "assets": ["EURUSD_otc", "GOLD_otc"],
            "timeframe_seconds": 1,
            "candles_count": 50,
            "interval_seconds": 30.0,
            "throttle_delay": 0.05,
        }
        response = await async_test_client.post("/api/v1/collector/start", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["is_running"] is True
        assert data["status"] == "RUNNING"
        assert "EURUSD_otc" in data["active_assets"]
        assert "GOLD_otc" in data["active_assets"]
        assert data["timeframe_seconds"] == 1
        assert data["candles_count"] == 50
        assert data["interval_seconds"] == 30.0
        assert data["throttle_delay"] == 0.05

        # Clean up
        await async_test_client.post("/api/v1/collector/stop")

    async def test_post_collector_start_sanitization(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-2.2: Input sanitization strips whitespace, empty strings, and deduplicates."""
        await async_test_client.post("/api/v1/collector/stop")

        payload = {
            "assets": ["  EURUSD_otc  ", "EURUSD_otc", "", "   ", "GOLD_otc  "],
        }
        response = await async_test_client.post("/api/v1/collector/start", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["is_running"] is True
        assert sorted(data["active_assets"]) == ["EURUSD_otc", "GOLD_otc"]

        # Clean up
        await async_test_client.post("/api/v1/collector/stop")

    async def test_post_collector_start_empty_assets_rejected(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-2.1: Empty asset list or whitespace-only list is rejected with HTTP 422/400."""
        await async_test_client.post("/api/v1/collector/stop")

        # Empty array
        r1 = await async_test_client.post("/api/v1/collector/start", json={"assets": []})
        assert r1.status_code in (400, 422)

        # Whitespace-only array
        r2 = await async_test_client.post(
            "/api/v1/collector/start", json={"assets": ["", "   ", "\t"]}
        )
        assert r2.status_code in (400, 422)

    async def test_post_collector_start_invalid_parameter_bounds(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-2.1: Negative or out-of-range numerical parameters return HTTP 422."""
        await async_test_client.post("/api/v1/collector/stop")

        # Negative timeframe
        r1 = await async_test_client.post(
            "/api/v1/collector/start",
            json={"assets": ["EURUSD_otc"], "timeframe_seconds": -1},
        )
        assert r1.status_code == 422

        # Zero candle count
        r2 = await async_test_client.post(
            "/api/v1/collector/start",
            json={"assets": ["EURUSD_otc"], "candles_count": 0},
        )
        assert r2.status_code == 422

        # Negative interval
        r3 = await async_test_client.post(
            "/api/v1/collector/start",
            json={"assets": ["EURUSD_otc"], "interval_seconds": -10.0},
        )
        assert r3.status_code == 422

    async def test_post_collector_start_already_running_handling(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-2.3: Starting collector while running returns 409 Conflict or idempotent 200."""
        await async_test_client.post("/api/v1/collector/stop")

        payload = {"assets": ["EURUSD_otc"], "interval_seconds": 60.0}
        r1 = await async_test_client.post("/api/v1/collector/start", json=payload)
        assert r1.status_code == 200
        assert r1.json()["is_running"] is True

        # Second start attempt
        r2 = await async_test_client.post("/api/v1/collector/start", json=payload)
        assert r2.status_code in (200, 409)
        if r2.status_code == 200:
            assert r2.json()["is_running"] is True

        # Clean up
        await async_test_client.post("/api/v1/collector/stop")


@pytest.mark.asyncio
class TestCollectorStopAPI:
    """Tests for POST /api/v1/collector/stop."""

    async def test_post_collector_stop_running_task(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-1.5: Halts running background collection task cleanly."""
        # Start
        await async_test_client.post(
            "/api/v1/collector/start",
            json={"assets": ["EURUSD_otc"], "interval_seconds": 60.0},
        )

        # Stop
        response = await async_test_client.post("/api/v1/collector/stop")
        assert response.status_code == 200
        data = response.json()
        assert data["is_running"] is False
        assert data["status"] in ("STOPPED", "IDLE")

        # Verify status endpoint reflects stopped state
        status_resp = await async_test_client.get("/api/v1/collector/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["is_running"] is False

    async def test_post_collector_stop_idle_is_safe_noop(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-2.4: Stopping an already stopped or idle collector is an idempotent no-op."""
        # Ensure stopped
        await async_test_client.post("/api/v1/collector/stop")

        # Second stop
        response = await async_test_client.post("/api/v1/collector/stop")
        assert response.status_code == 200
        data = response.json()
        assert data["is_running"] is False
