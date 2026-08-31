"""Empirical Concurrency, Stress, Fault Injection & Deduplication Suite for Stage 3 Collector.

Challenger 1 Verification Test Harness:
- TC-1: Rapid start/stop cycling (50+ toggles, race swarm, reconfigs, zero orphan tasks)
- TC-2: Simultaneous API queries during heavy DB writes (no WAL locks, low latency)
- TC-3: Corrupted or invalid broker responses (None, NaNs, unparseable data, errors)
- TC-4: Task cancellation across distinct states (throttle sleep, interval wait, I/O)
- TC-5: MarketDataStore deduplication under concurrent writes (race, overlapping, sorting)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import random
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest
from httpx import AsyncClient

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import (
    InvalidMarketParametersError,
)
from strat_trade.domain.trading.market_data_store import MarketDataStore
from strat_trade.use_cases.manage_collector import (
    AsyncCollectorEngine,
    CollectorStatus,
    get_collector_engine,
)


def _generate_synthetic_candles(
    count: int = 100,
    start_ts: float = 1700000000.0,
    base_price: float = 1.0850,
    step_seconds: int = 1,
) -> list[Candle]:
    """Generates deterministic synthetic candle sequence with strict UTC timestamps."""
    candles: list[Candle] = []
    for i in range(count):
        ts = start_ts + (i * step_seconds)
        dt = datetime.fromtimestamp(ts, tz=UTC)
        drift = (i % 10 - 5) * 0.0001
        candles.append(
            Candle(
                open_time=dt,
                open=Decimal(f"{base_price + drift:.5f}"),
                high=Decimal(f"{base_price + drift + 0.0004:.5f}"),
                low=Decimal(f"{base_price + drift - 0.0004:.5f}"),
                close=Decimal(f"{base_price + drift + 0.0001:.5f}"),
                volume=Decimal("50.0"),
            )
        )
    return candles


@pytest.mark.asyncio
class TestRapidStartStopStress:
    """Empirical challenge on collector task lifecycle and orphan task prevention."""

    async def test_50_sequential_rapid_start_stop_cycles(
        self,
        async_test_client: AsyncClient,
        mock_trading_gateway: AsyncMock,
    ) -> None:
        """TC-1.1: 50 sequential rapid start/stop toggles without task leaks or deadlocks."""
        await async_test_client.post("/api/v1/collector/stop")

        payload = {
            "assets": ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc"],
            "interval_seconds": 0.02,
            "throttle_delay": 0.005,
        }

        latencies_ms: list[float] = []
        cycle_count = 50

        for i in range(cycle_count):
            t0 = time.perf_counter()

            r_start = await async_test_client.post("/api/v1/collector/start", json=payload)
            assert r_start.status_code == 200, f"Cycle {i} start failed: {r_start.text}"
            data_start = r_start.json()
            assert data_start["status"] == "RUNNING"
            assert data_start["is_running"] is True

            if i % 3 == 0:
                await asyncio.sleep(0.002)
            elif i % 3 == 1:
                await asyncio.sleep(0.01)

            r_stop = await async_test_client.post("/api/v1/collector/stop")
            assert r_stop.status_code == 200, f"Cycle {i} stop failed: {r_stop.text}"
            data_stop = r_stop.json()
            assert data_stop["status"] in ("STOPPED", "IDLE")
            assert data_stop["is_running"] is False

            t1 = time.perf_counter()
            latencies_ms.append((t1 - t0) * 1000.0)

        status_resp = await async_test_client.get("/api/v1/collector/status")
        assert status_resp.status_code == 200
        final_data = status_resp.json()
        assert final_data["is_running"] is False
        assert final_data["status"] == "STOPPED"

        engine = get_collector_engine()
        assert engine._task is None, "Engine internal task pointer must be None after stop"

        avg_latency = sum(latencies_ms) / len(latencies_ms)
        assert avg_latency < 100.0, f"Start/stop cycle too slow: {avg_latency:.2f}ms"

    async def test_concurrent_start_stop_race_swarm(
        self,
        async_test_client: AsyncClient,
        mock_trading_gateway: AsyncMock,
    ) -> None:
        """TC-1.2: High-concurrency swarm of simultaneous start and stop calls."""
        await async_test_client.post("/api/v1/collector/stop")

        payload = {
            "assets": ["EURUSD_otc", "AUDNZD_otc"],
            "interval_seconds": 0.05,
            "throttle_delay": 0.01,
        }

        async def _worker_start(worker_id: int) -> int:
            await asyncio.sleep(random.uniform(0.001, 0.015))
            resp = await async_test_client.post("/api/v1/collector/start", json=payload)
            return resp.status_code

        async def _worker_stop(worker_id: int) -> int:
            await asyncio.sleep(random.uniform(0.001, 0.015))
            resp = await async_test_client.post("/api/v1/collector/stop")
            return resp.status_code

        start_tasks = [_worker_start(i) for i in range(20)]
        stop_tasks = [_worker_stop(i) for i in range(20)]
        all_tasks = start_tasks + stop_tasks
        random.shuffle(all_tasks)

        status_codes = await asyncio.gather(*all_tasks)
        assert all(code == 200 for code in status_codes), f"Unexpected status: {status_codes}"

        final_stop = await async_test_client.post("/api/v1/collector/stop")
        assert final_stop.status_code == 200

        status = await async_test_client.get("/api/v1/collector/status")
        assert status.json()["is_running"] is False

    async def test_dynamic_reconfiguration_while_running(
        self,
        async_test_client: AsyncClient,
        mock_trading_gateway: AsyncMock,
    ) -> None:
        """TC-1.3: Reconfiguration while running updates assets without duplicate tasks."""
        await async_test_client.post("/api/v1/collector/stop")

        r1 = await async_test_client.post(
            "/api/v1/collector/start",
            json={"assets": ["EURUSD_otc", "USDJPY_otc"], "interval_seconds": 1.0},
        )
        assert r1.status_code == 200
        engine = get_collector_engine()
        initial_task = engine._task
        assert initial_task is not None

        r2 = await async_test_client.post(
            "/api/v1/collector/start",
            json={
                "assets": ["EURUSD_otc", "USDJPY_otc", "GOLD_otc", "BTCUSD"],
                "interval_seconds": 1.0,
            },
        )
        assert r2.status_code == 200
        assert r2.json()["active_assets"] == ["EURUSD_otc", "USDJPY_otc", "GOLD_otc", "BTCUSD"]
        assert engine._task is initial_task

        await async_test_client.post("/api/v1/collector/stop")
        assert engine._task is None


@pytest.mark.asyncio
class TestSimultaneousApiQueriesUnderHeavyInsertions:
    """Empirical challenge verifying SQLite WAL non-blocking reads during continuous writes."""

    async def test_concurrent_api_reads_under_heavy_db_writes(
        self,
        async_test_client: AsyncClient,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-2.1: 120 concurrent API reads while background workers insert thousands of candles."""
        stop_event = asyncio.Event()
        write_errors: list[Exception] = []
        read_latencies_ms: list[float] = []

        async def _continuous_writer() -> None:
            ts_counter = 1700000000.0
            assets = ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "GOLD_otc", "AUDNZD_otc"]
            try:
                while not stop_event.is_set():
                    for asset in assets:
                        candles = _generate_synthetic_candles(count=50, start_ts=ts_counter)
                        isolated_market_store.insert_candles(asset, candles)
                        ts_counter += 50.0
                    await asyncio.sleep(0.005)
            except Exception as exc:
                write_errors.append(exc)

        writer_task = asyncio.create_task(_continuous_writer())

        async def _reader_worker(worker_id: int) -> list[int]:
            codes: list[int] = []
            for _ in range(15):
                t0 = time.perf_counter()
                endpoint = random.choice(
                    [
                        "/api/v1/collector/status",
                        "/api/v1/collector/available-assets",
                        "/api/v1/market/candles?asset=EURUSD_otc&timeframe_seconds=60&count=10",
                    ]
                )
                resp = await async_test_client.get(endpoint)
                t1 = time.perf_counter()
                codes.append(resp.status_code)
                read_latencies_ms.append((t1 - t0) * 1000.0)
                await asyncio.sleep(0.002)
            return codes

        readers = [_reader_worker(i) for i in range(8)]
        results = await asyncio.gather(*readers)

        stop_event.set()
        await writer_task

        assert len(write_errors) == 0, f"Write errors occurred: {write_errors}"
        all_codes = [c for worker_codes in results for c in worker_codes]
        assert len(all_codes) == 120
        assert all(c in (200, 404) for c in all_codes), f"Unexpected status codes: {set(all_codes)}"

        total_candles = isolated_market_store.get_total_candle_count()
        assert total_candles > 500, f"Expected > 500 candles inserted, got {total_candles}"

        p95_latency = float(np.percentile(read_latencies_ms, 95))
        assert p95_latency < 200.0, f"P95 read latency too high: {p95_latency:.2f}ms"


@pytest.mark.asyncio
class TestCorruptedAndAdversarialBrokerResponses:
    """Fault injection suite challenging collector resilience against corrupted broker data."""

    async def test_resilience_to_null_and_malformed_broker_payloads(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-3.1: Collector gracefully discards unparseable items without crashing."""
        engine = AsyncCollectorEngine(store=isolated_market_store)
        gateway = AsyncMock()

        valid_dict = {
            "time": 1700000002.0,
            "open": 1.085,
            "high": 1.086,
            "low": 1.084,
            "close": 1.0855,
            "volume": 10.0,
        }
        valid_entity = Candle(
            open_time=datetime.fromtimestamp(1700000003.0, tz=UTC),
            open=Decimal("1.0850"),
            high=Decimal("1.0860"),
            low=Decimal("1.0840"),
            close=Decimal("1.0855"),
            volume=Decimal("10.0"),
        )

        corrupt_candles: list[Any] = [
            None,
            {},
            {"invalid_key": 123},
            {"time": None, "open": 1.0},
            {"time": "invalid_date_string", "open": 1.0},
            {"time": 1700000000.0, "open": "not_a_float", "close": 1.085},
            {"time": 1700000001.0, "open": [1, 2, 3], "close": 1.085},
            "plain_string_instead_of_candle",
            123456,
            valid_dict,
            valid_entity,
        ]
        gateway.get_candles = AsyncMock(return_value=corrupt_candles)

        await engine.start(
            gateway=gateway,
            assets=["EURUSD_otc"],
            interval_seconds=0.05,
            throttle_delay=0.01,
        )

        await asyncio.sleep(0.1)
        await engine.stop()

        candles = isolated_market_store.get_candles("EURUSD_otc")
        assert len(candles) == 2, f"Expected exactly 2 valid candles, got {len(candles)}"
        timestamps = [c.open_time.timestamp() for c in candles]
        assert 1700000002.0 in timestamps
        assert 1700000003.0 in timestamps

    async def test_resilience_to_null_gateway_return_and_empty_list(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-3.2: Gateway returning None or empty list does not break engine."""
        engine = AsyncCollectorEngine(store=isolated_market_store)
        gateway = AsyncMock()
        gateway.get_candles = AsyncMock(return_value=None)

        await engine.start(
            gateway=gateway,
            assets=["EURUSD_otc"],
            interval_seconds=0.02,
            throttle_delay=0.005,
        )
        await asyncio.sleep(0.08)
        assert engine.status == CollectorStatus.RUNNING
        await engine.stop()
        assert engine.status == CollectorStatus.STOPPED
        assert isolated_market_store.count_candles("EURUSD_otc") == 0

    async def test_resilience_to_catastrophic_broker_exceptions(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-3.3: Gateway raising unexpected exceptions does not crash collector loop."""
        engine = AsyncCollectorEngine(store=isolated_market_store)
        gateway = AsyncMock()

        call_count = 0

        async def _flaky_get_candles(asset: str, *args: Any, **kwargs: Any) -> list[Candle]:
            nonlocal call_count
            call_count += 1
            if asset == "CHAOS_ASSET_1":
                raise RuntimeError("Broker WebSocket pipe broke violently")
            if asset == "CHAOS_ASSET_2":
                raise KeyError("Missing 'history' key in gateway response")
            if asset == "CHAOS_ASSET_3":
                raise ZeroDivisionError("Broker math overflow")
            return _generate_synthetic_candles(count=10, start_ts=1700000000.0 + call_count * 10)

        gateway.get_candles.side_effect = _flaky_get_candles

        await engine.start(
            gateway=gateway,
            assets=["CHAOS_ASSET_1", "CHAOS_ASSET_2", "EURUSD_otc", "CHAOS_ASSET_3"],
            interval_seconds=0.05,
            throttle_delay=0.005,
        )

        await asyncio.sleep(0.2)

        assert engine.status == CollectorStatus.RUNNING
        assert engine.is_running is True

        await engine.stop()
        assert engine.status == CollectorStatus.STOPPED

        stored_count = isolated_market_store.count_candles("EURUSD_otc")
        assert stored_count >= 10, f"Expected EURUSD_otc candles stored, got {stored_count}"


@pytest.mark.asyncio
class TestTaskCancellationInDistinctStates:
    """Empirical challenge verifying clean cancellation across all execution phases."""

    async def test_cancellation_during_throttle_delay_sleep(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-4.1: Cancellation while sleeping inside throttle delay halts immediately (<200ms)."""
        engine = AsyncCollectorEngine(store=isolated_market_store)
        gateway = AsyncMock()
        gateway.get_candles = AsyncMock(return_value=_generate_synthetic_candles(count=5))

        await engine.start(
            gateway=gateway,
            assets=["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc"],
            interval_seconds=60.0,
            throttle_delay=5.0,
        )

        await asyncio.sleep(0.05)
        assert engine.is_running is True

        t0 = time.perf_counter()
        await engine.stop()
        t1 = time.perf_counter()

        stop_elapsed_ms = (t1 - t0) * 1000.0
        assert stop_elapsed_ms < 200.0, f"Stop took too long: {stop_elapsed_ms:.2f}ms"
        assert engine.is_running is False
        assert engine._task is None

    async def test_cancellation_during_interval_wait_sleep(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-4.2: Cancellation while sleeping inside interval delay halts immediately (<200ms)."""
        engine = AsyncCollectorEngine(store=isolated_market_store)
        gateway = AsyncMock()
        gateway.get_candles = AsyncMock(return_value=_generate_synthetic_candles(count=5))

        await engine.start(
            gateway=gateway,
            assets=["EURUSD_otc"],
            interval_seconds=60.0,
            throttle_delay=0.0,
        )

        await asyncio.sleep(0.05)
        assert engine.is_running is True

        t0 = time.perf_counter()
        await engine.stop()
        t1 = time.perf_counter()

        stop_elapsed_ms = (t1 - t0) * 1000.0
        assert stop_elapsed_ms < 200.0, f"Stop took too long: {stop_elapsed_ms:.2f}ms"
        assert engine.is_running is False
        assert engine._task is None

    async def test_cancellation_during_gateway_await(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-4.3: Cancellation while awaiting a slow broker network call."""
        engine = AsyncCollectorEngine(store=isolated_market_store)
        gateway = AsyncMock()

        async def _slow_gateway(*args: Any, **kwargs: Any) -> list[Candle]:
            await asyncio.sleep(5.0)
            return _generate_synthetic_candles(count=5)

        gateway.get_candles = AsyncMock(side_effect=_slow_gateway)

        await engine.start(
            gateway=gateway,
            assets=["EURUSD_otc"],
            interval_seconds=10.0,
            throttle_delay=0.0,
        )

        await asyncio.sleep(0.05)
        assert engine.is_running is True

        t0 = time.perf_counter()
        await engine.stop()
        t1 = time.perf_counter()

        stop_elapsed_ms = (t1 - t0) * 1000.0
        assert stop_elapsed_ms < 200.0, f"Stop took too long: {stop_elapsed_ms:.2f}ms"
        assert engine.is_running is False

    async def test_zero_tick_immediate_start_stop(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-4.4: 10 back-to-back zero-delay start-then-stop invocations within the same tick."""
        engine = AsyncCollectorEngine(store=isolated_market_store)
        gateway = AsyncMock()
        gateway.get_candles = AsyncMock(return_value=_generate_synthetic_candles(count=5))

        for _ in range(10):
            await engine.start(
                gateway=gateway,
                assets=["EURUSD_otc"],
                interval_seconds=1.0,
                throttle_delay=0.1,
            )
            await engine.stop()

        assert engine.is_running is False
        assert engine.status == CollectorStatus.STOPPED
        assert engine._task is None


@pytest.mark.asyncio
class TestMarketDataStoreDeduplicationUnderConcurrentWrites:
    """Empirical challenge on SQLite INSERT OR IGNORE atomicity, deduplication, and ordering."""

    async def test_massive_multi_worker_duplicate_injection(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-5.1: 10 parallel workers writing identical 1,000 candles results in 1,000 rows."""
        unique_candles = _generate_synthetic_candles(count=1000, start_ts=1700000000.0)
        num_workers = 10

        worker_inserted_counts: list[int] = []

        async def _worker(worker_id: int) -> None:
            await asyncio.sleep(random.uniform(0.0001, 0.005))
            inserted = isolated_market_store.insert_candles("EURUSD_otc", unique_candles)
            worker_inserted_counts.append(inserted)

        workers = [_worker(i) for i in range(num_workers)]
        await asyncio.gather(*workers)

        total_count = isolated_market_store.count_candles("EURUSD_otc")
        assert total_count == 1000, f"Expected 1000 deduplicated rows, got {total_count}"

        sum_inserted = sum(worker_inserted_counts)
        assert sum_inserted == 1000, f"Sum of worker inserted counts ({sum_inserted}) != 1000"

    async def test_overlapping_and_out_of_order_concurrent_writes(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-5.2: Overlapping and out-of-order writes maintain strict chronological integrity."""
        seg1 = _generate_synthetic_candles(count=100, start_ts=1700000100.0)
        seg2 = _generate_synthetic_candles(count=100, start_ts=1700000150.0)
        seg3 = list(reversed(_generate_synthetic_candles(count=100, start_ts=1700000050.0)))
        seg4 = _generate_synthetic_candles(count=300, start_ts=1700000000.0)

        async def _write_seg(candles: list[Candle]) -> int:
            await asyncio.sleep(random.uniform(0.001, 0.005))
            return isolated_market_store.insert_candles("EURUSD_otc", candles)

        inserted_counts = await asyncio.gather(
            _write_seg(seg1),
            _write_seg(seg2),
            _write_seg(seg3),
            _write_seg(seg4),
        )

        total_count = isolated_market_store.count_candles("EURUSD_otc")
        assert total_count == 300, f"Expected 300 candles, got {total_count}"
        assert sum(inserted_counts) == 300

        df = isolated_market_store.get_candles_df("EURUSD_otc")
        assert len(df) == 300
        ts_diffs = df["timestamp"].diff().dropna()
        assert (ts_diffs == pd.Timedelta(seconds=1)).all()

    async def test_cross_asset_concurrent_interleaved_writes(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-5.3: Multiple workers writing distinct assets without cross-asset collisions."""
        assets = ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "GOLD_otc", "BTCUSD"]
        candles_per_asset = 250

        async def _asset_worker(asset_name: str) -> int:
            candles = _generate_synthetic_candles(count=candles_per_asset, start_ts=1700000000.0)
            await asyncio.sleep(random.uniform(0.001, 0.005))
            return isolated_market_store.insert_candles(asset_name, candles)

        results = await asyncio.gather(*[_asset_worker(a) for a in assets])

        assert all(count == candles_per_asset for count in results)

        for asset in assets:
            stats = isolated_market_store.get_asset_stats(asset)
            assert stats["count"] == candles_per_asset
            assert stats["asset"] == asset

        total = isolated_market_store.get_total_candle_count()
        assert total == len(assets) * candles_per_asset

        stored_assets = isolated_market_store.get_stored_assets()
        assert sorted(stored_assets) == sorted(assets)


@pytest.mark.asyncio
class TestMultithreadedAndBoundaryStress:
    """Empirical verification of thread safety, large bulk writes, and boundary configs."""

    async def test_multithreaded_concurrent_writes(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-6.1: Concurrent ThreadPool writes do not cause database lock or corruption."""
        candles = _generate_synthetic_candles(count=500, start_ts=1700000000.0)

        def _sync_writer(asset_name: str) -> int:
            return isolated_market_store.insert_candles(asset_name, candles)

        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            tasks = [
                loop.run_in_executor(executor, _sync_writer, f"THREAD_ASSET_{i}") for i in range(5)
            ]
            results = await asyncio.gather(*tasks)

        assert all(count == 500 for count in results)
        assert isolated_market_store.get_total_candle_count() == 2500

    async def test_large_bulk_candle_batch_insertion(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-6.2: Ingestion of 10,000 candles in a single call executes in < 500ms."""
        bulk_candles = _generate_synthetic_candles(count=10000, start_ts=1700000000.0)

        t0 = time.perf_counter()
        inserted = isolated_market_store.insert_candles("BULK_ASSET", bulk_candles)
        t1 = time.perf_counter()

        elapsed_ms = (t1 - t0) * 1000.0
        assert inserted == 10000
        assert elapsed_ms < 500.0, f"Bulk insertion too slow: {elapsed_ms:.2f}ms"
        assert isolated_market_store.count_candles("BULK_ASSET") == 10000

        range_df = isolated_market_store.get_candles_df(
            "BULK_ASSET",
            start_time=1700002000.0,
            end_time=1700003000.0,
        )
        assert len(range_df) == 1001

    async def test_boundary_asset_parameters_sanitization(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-6.3: Asset list with duplicates, whitespace, and empty strings is sanitized."""
        engine = AsyncCollectorEngine(store=isolated_market_store)
        gateway = AsyncMock()
        gateway.get_candles = AsyncMock(return_value=_generate_synthetic_candles(count=5))

        dirty_assets = ["  EURUSD_otc  ", "EURUSD_otc", "", "  ", "GBPUSD_otc"]

        status = await engine.start(
            gateway=gateway,
            assets=dirty_assets,
            interval_seconds=1.0,
        )
        assert engine.is_running is True
        assert status.active_assets == ["EURUSD_otc", "GBPUSD_otc"]

        await engine.stop()

        with pytest.raises(InvalidMarketParametersError):
            await engine.start(
                gateway=gateway,
                assets=["", "   "],
                interval_seconds=1.0,
            )
