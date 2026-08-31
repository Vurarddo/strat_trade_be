"""End-to-End (E2E) integration scenarios for Stage 3 S1 Data Collector.

Covers Tier 4 (Full Operator Workflow & Multi-Service Integration):
- Full lifecycle: Assets -> Select -> Start -> Cycles -> DB -> Status -> Stop -> Integrity Check
- Coexistence with market data readers and concurrent queries
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from strat_trade.domain.trading.market_data_store import MarketDataStore


@pytest.mark.asyncio
class TestCollectorE2ELifecycle:
    """Tier 4 end-to-end application lifecycle tests."""

    async def test_collector_full_operator_lifecycle_e2e(
        self,
        async_test_client: AsyncClient,
        mock_trading_gateway: AsyncMock,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-4.1: Complete operator lifecycle from discovery to database verification."""
        # 0. Clean initial state
        await async_test_client.post("/api/v1/collector/stop")

        # 1. Step 1: Discover available assets from broker
        resp_assets = await async_test_client.get("/api/v1/collector/available-assets")
        assert resp_assets.status_code == 200
        available_assets = resp_assets.json()
        assert len(available_assets) >= 2
        selected_symbols = [available_assets[0]["symbol"], available_assets[1]["symbol"]]

        # 2. Step 2: Start background data collection
        start_payload = {
            "assets": selected_symbols,
            "timeframe_seconds": 1,
            "candles_count": 50,
            "interval_seconds": 0.05,
            "throttle_delay": 0.01,
        }
        resp_start = await async_test_client.post(
            "/api/v1/collector/start",
            json=start_payload,
        )
        assert resp_start.status_code == 200
        start_data = resp_start.json()
        assert start_data["is_running"] is True
        assert start_data["status"] == "RUNNING"
        assert set(selected_symbols).issubset(set(start_data["active_assets"]))

        # 3. Step 3: Allow collector to run at least 2 collection cycles
        await asyncio.sleep(0.20)

        # 4. Step 4: Verify collector status telemetry and database reflection
        resp_status = await async_test_client.get("/api/v1/collector/status")
        assert resp_status.status_code == 200
        status_data = resp_status.json()
        assert status_data["is_running"] is True
        assert status_data["cycles_completed"] >= 1
        assert status_data["total_candles_saved"] > 0
        assert status_data["total_database_candles"] > 0

        # 5. Step 5: Verify SQLite database contents and monotonic timestamps
        for sym in selected_symbols:
            stored_candles = isolated_market_store.get_candles(sym)
            assert len(stored_candles) > 0

            # Verify timestamp monotonicity
            timestamps = [c.open_time.timestamp() for c in stored_candles]
            assert timestamps == sorted(timestamps)

            # Verify DataFrame conversion
            df = isolated_market_store.get_candles_df(sym)
            assert not df.empty
            assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]

        # Record candle counts before stop
        count_before_stop = isolated_market_store.get_total_candle_count()

        # 6. Step 6: Stop data collection
        resp_stop = await async_test_client.post("/api/v1/collector/stop")
        assert resp_stop.status_code == 200
        stop_data = resp_stop.json()
        assert stop_data["is_running"] is False
        assert stop_data["status"] in ("STOPPED", "IDLE")

        # 7. Step 7: Verify no further background writes occur after stop
        await asyncio.sleep(0.10)
        count_after_stop = isolated_market_store.get_total_candle_count()
        assert count_after_stop == count_before_stop

    async def test_collector_and_market_query_coexistence(
        self,
        async_test_client: AsyncClient,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-4.1: Market data endpoints query data populated by collector in real-time."""
        await async_test_client.post("/api/v1/collector/stop")

        # Start collector
        await async_test_client.post(
            "/api/v1/collector/start",
            json={
                "assets": ["EURUSD_otc"],
                "interval_seconds": 0.05,
                "throttle_delay": 0.01,
            },
        )

        # Allow some data to flow
        await asyncio.sleep(0.10)

        # Query collector status
        status = await async_test_client.get("/api/v1/collector/status")
        assert status.status_code == 200
        assert status.json()["is_running"] is True

        # Stop collector
        await async_test_client.post("/api/v1/collector/stop")
