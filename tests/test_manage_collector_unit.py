from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import (
    BrokerUnavailableError,
    InvalidMarketParametersError,
)
from strat_trade.domain.trading.market_data_store import MarketDataStore
from strat_trade.use_cases.manage_collector import (
    AsyncCollectorEngine,
    CollectorStatus,
    get_collector_engine,
    get_collector_status,
    start_collector,
    stop_collector,
)
from strat_trade.web.routes import collector as web_collector_module


def _make_candles(count: int = 5, start_ts: float = 1700000000.0) -> list[Candle]:
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
class TestManageCollectorUnit:
    """Detailed unit tests for AsyncCollectorEngine."""

    async def test_collector_status_enum(self) -> None:
        assert CollectorStatus.IDLE == "IDLE"
        assert CollectorStatus.RUNNING == "RUNNING"
        assert CollectorStatus.STOPPED == "STOPPED"

    async def test_engine_initialization_and_set_store(self, tmp_path: Path) -> None:
        store1 = MarketDataStore(tmp_path / "store1.db")
        store2 = MarketDataStore(tmp_path / "store2.db")

        engine = AsyncCollectorEngine(store=store1)
        assert engine.status == CollectorStatus.IDLE
        assert not engine.is_running
        assert engine.store is store1

        engine.set_store(store2)
        assert engine.store is store2

    async def test_engine_empty_assets_rejected(self, tmp_path: Path) -> None:
        store = MarketDataStore(tmp_path / "test.db")
        engine = AsyncCollectorEngine(store=store)
        gateway = AsyncMock()

        with pytest.raises(InvalidMarketParametersError):
            await engine.start(gateway=gateway, assets=[])

        with pytest.raises(InvalidMarketParametersError):
            await engine.start(gateway=gateway, assets=["", "   "])

    async def test_engine_start_stop_lifecycle(self, tmp_path: Path) -> None:
        store = MarketDataStore(tmp_path / "test.db")
        engine = AsyncCollectorEngine(store=store)
        gateway = AsyncMock()
        gateway.get_candles = AsyncMock(return_value=_make_candles(5))

        status_init = engine.get_status()
        assert status_init.status == "IDLE"
        assert status_init.is_running is False
        assert status_init.total_database_candles == 0

        # Start engine
        status_start = await engine.start(
            gateway=gateway,
            assets=["EURUSD_otc", "GBPUSD_otc"],
            timeframe_seconds=1,
            candles_count=5,
            interval_seconds=0.05,
            throttle_delay=0.01,
        )
        assert status_start.status == "RUNNING"
        assert status_start.is_running is True
        assert status_start.active_assets == ["EURUSD_otc", "GBPUSD_otc"]

        # Allow 1 cycle
        await asyncio.sleep(0.08)

        status_running = engine.get_status()
        assert status_running.is_running is True
        assert status_running.cycles_completed >= 1
        assert status_running.total_candles_saved >= 5
        assert store.count_candles("EURUSD_otc") == 5

        # Stop engine
        status_stop = await engine.stop()
        assert status_stop.status == "STOPPED"
        assert status_stop.is_running is False

        # Stop again (idempotent)
        status_stop2 = await engine.stop()
        assert status_stop2.status == "STOPPED"
        assert status_stop2.is_running is False

    async def test_engine_fault_tolerance_in_loop(self, tmp_path: Path) -> None:
        """Tests that exceptions on individual assets do not kill the loop."""
        store = MarketDataStore(tmp_path / "fault.db")
        engine = AsyncCollectorEngine(store=store)
        gateway = AsyncMock()

        call_count = 0

        async def _mock_get_candles(asset: str, timeframe: int, count: int):
            nonlocal call_count
            call_count += 1
            if asset == "FAIL_BROKER_otc":
                raise BrokerUnavailableError("Broker offline")
            if asset == "FAIL_TIMEOUT_otc":
                raise TimeoutError("Socket timeout")
            if asset == "FAIL_INVALID_otc":
                raise InvalidMarketParametersError("Bad params")
            if asset == "FAIL_CONN_otc":
                raise ConnectionError("Conn reset")
            if asset == "FAIL_OS_otc":
                raise OSError("Pipe error")
            if asset == "FAIL_GENERIC_otc":
                raise RuntimeError("Unexpected error")
            return _make_candles(10)

        gateway.get_candles = AsyncMock(side_effect=_mock_get_candles)

        assets = [
            "FAIL_BROKER_otc",
            "FAIL_TIMEOUT_otc",
            "FAIL_INVALID_otc",
            "FAIL_CONN_otc",
            "FAIL_OS_otc",
            "FAIL_GENERIC_otc",
            "GOOD_ASSET_otc",
        ]

        await engine.start(
            gateway=gateway,
            assets=assets,
            interval_seconds=0.05,
            throttle_delay=0.005,
        )

        await asyncio.sleep(0.12)
        await engine.stop()

        assert store.count_candles("GOOD_ASSET_otc") == 10
        assert store.count_candles("FAIL_BROKER_otc") == 0

    async def test_global_singleton_helpers(self, tmp_path: Path) -> None:
        store = MarketDataStore(tmp_path / "global.db")
        engine = get_collector_engine()
        engine.set_store(store)
        gateway = AsyncMock()
        gateway.get_candles = AsyncMock(return_value=_make_candles(5))

        try:
            status = await start_collector(
                gateway=gateway,
                assets=["EURUSD_otc"],
                interval_seconds=0.05,
                throttle_delay=0.01,
                store=store,
            )
            assert status.is_running is True

            st = get_collector_status(store=store)
            assert st.is_running is True
        finally:
            await stop_collector()

    async def test_web_routes_reexport(self) -> None:
        assert hasattr(web_collector_module, "router")
        assert hasattr(web_collector_module, "get_available_assets")
        assert hasattr(web_collector_module, "get_status")
        assert hasattr(web_collector_module, "start_collection")
        assert hasattr(web_collector_module, "stop_collection")
