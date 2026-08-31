from __future__ import annotations

import concurrent.futures
import random
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import BacktestConfig
from strat_trade.domain.entities import Candle
from strat_trade.domain.trading.market_data_store import MarketDataStore


def _generate_candle_entity(
    ts: float,
    open_p: float = 1.0850,
    high_p: float = 1.0860,
    low_p: float = 1.0840,
    close_p: float = 1.0855,
    volume: float = 100.0,
) -> Candle:
    return Candle(
        open_time=datetime.fromtimestamp(ts, tz=UTC),
        open=Decimal(str(round(open_p, 5))),
        high=Decimal(str(round(high_p, 5))),
        low=Decimal(str(round(low_p, 5))),
        close=Decimal(str(round(close_p, 5))),
        volume=Decimal(str(round(volume, 2))),
    )


def _multiprocess_worker(db_path: str, asset: str, start_ts: float, count: int) -> int:
    store = MarketDataStore(db_path=db_path)
    candles = [
        {
            "time": start_ts + i,
            "open": 1.1000 + (i % 100) * 0.0001,
            "high": 1.1010 + (i % 100) * 0.0001,
            "low": 1.0990 + (i % 100) * 0.0001,
            "close": 1.1005 + (i % 100) * 0.0001,
            "volume": 50.0,
        }
        for i in range(count)
    ]
    return store.insert_candles(asset, candles)


class TestMarketDataStoreEmpiricalStress:
    """Adversarial stress and boundary suite for MarketDataStore."""

    def test_volume_shuffle_and_chronological_ordering(self, tmp_path: Path) -> None:
        """Inserts 10,000 candles with shuffled timestamps and verifies strict ordering."""
        db_file = tmp_path / "stress_volume.db"
        store = MarketDataStore(db_path=db_file)

        base_ts = 1700000000.0
        n_candles = 10000
        timestamps = [base_ts + i for i in range(n_candles)]

        # Generate candles with distinct, verifiable prices
        candles = [
            _generate_candle_entity(
                ts=ts,
                open_p=1.0 + (i % 1000) * 0.0001,
                high_p=1.0 + (i % 1000) * 0.0001 + 0.0005,
                low_p=1.0 + (i % 1000) * 0.0001 - 0.0005,
                close_p=1.0 + (i % 1000) * 0.0001 + 0.0002,
                volume=10.0 + (i % 50),
            )
            for i, ts in enumerate(timestamps)
        ]

        # Shuffle candles completely
        rng = random.Random(42)
        shuffled_candles = list(candles)
        rng.shuffle(shuffled_candles)

        # Insert in chunks of irregular sizes
        chunk_sizes = [1, 7, 33, 128, 500, 1000, 2000, 6331]
        offset = 0
        total_inserted = 0
        for sz in chunk_sizes:
            chunk = shuffled_candles[offset : offset + sz]
            if not chunk:
                break
            inserted = store.insert_candles("EURUSD_otc", chunk)
            total_inserted += inserted
            offset += sz

        assert total_inserted == n_candles
        assert store.count_candles("EURUSD_otc") == n_candles

        # Retrieve all as domain entities
        retrieved = store.get_candles("EURUSD_otc")
        assert len(retrieved) == n_candles

        # Verify strict ascending order and data fidelity
        for i in range(len(retrieved)):
            expected_ts = datetime.fromtimestamp(base_ts + i, tz=UTC)
            assert retrieved[i].open_time == expected_ts
            assert retrieved[i].open == Decimal(f"{1.0 + (i % 1000) * 0.0001:.5f}")
            if i > 0:
                assert retrieved[i].open_time > retrieved[i - 1].open_time

        # Retrieve as DataFrame
        df = store.get_candles_df("EURUSD_otc")
        assert len(df) == n_candles
        assert df["timestamp"].is_monotonic_increasing
        assert (df["timestamp"].diff().dropna() == pd.Timedelta(seconds=1)).all()
        assert df["open"].iloc[0] == pytest.approx(1.0)
        assert df["close"].iloc[9999] == pytest.approx(1.0 + (9999 % 1000) * 0.0001 + 0.0002)

    def test_heavy_sliding_window_overlap_deduplication(self, tmp_path: Path) -> None:
        """Simulates 50 collector cycles fetching 300-bar windows with 240-bar (80%) overlap."""
        db_file = tmp_path / "stress_overlap.db"
        store = MarketDataStore(db_path=db_file)

        base_ts = 1700000000.0
        cycle_step = 60  # seconds between cycles
        window_size = 300  # bars per fetch
        num_cycles = 50

        total_unique_expected = window_size + (num_cycles - 1) * cycle_step
        total_reported_inserted = 0

        for cycle in range(num_cycles):
            start_offset = cycle * cycle_step
            batch = [
                {
                    "time": base_ts + start_offset + i,
                    "open": 1.1000 + i * 0.0001,
                    "high": 1.1010 + i * 0.0001,
                    "low": 1.0990 + i * 0.0001,
                    "close": 1.1005 + i * 0.0001,
                    "volume": 100.0,
                }
                for i in range(window_size)
            ]
            inserted = store.insert_candles("AUDNZD_otc", batch)
            total_reported_inserted += inserted

            if cycle == 0:
                assert inserted == window_size
            else:
                assert inserted == cycle_step

        assert total_reported_inserted == total_unique_expected
        assert store.count_candles("AUDNZD_otc") == total_unique_expected

        # Re-inserting an identical batch of already saved candles yields 0
        reinsert_count = store.insert_candles("AUDNZD_otc", batch)
        assert reinsert_count == 0
        assert store.count_candles("AUDNZD_otc") == total_unique_expected

    def test_multi_threaded_concurrent_reads_and_writes(self, tmp_path: Path) -> None:
        """Stress-tests WAL mode with 12 concurrent writer threads and 6 reader threads."""
        db_file = tmp_path / "concurrent_stress.db"
        store = MarketDataStore(db_path=db_file)

        base_ts = 1700000000.0
        n_writers = 12
        candles_per_writer = 500
        exceptions: list[Exception] = []

        def writer_task(worker_id: int) -> int:
            worker_store = MarketDataStore(db_path=db_file)
            if worker_id < 6:
                start = worker_id * candles_per_writer
            else:
                start = (worker_id - 6) * candles_per_writer + 100

            candles = [
                {
                    "timestamp": base_ts + start + i,
                    "open": 1.0500 + worker_id * 0.01,
                    "high": 1.0550 + worker_id * 0.01,
                    "low": 1.0450 + worker_id * 0.01,
                    "close": 1.0520 + worker_id * 0.01,
                    "volume": float(worker_id * 10),
                }
                for i in range(candles_per_writer)
            ]
            try:
                return worker_store.insert_candles("EURUSD_otc", candles)
            except Exception as e:
                exceptions.append(e)
                raise

        def reader_task(reader_id: int) -> int:
            reader_store = MarketDataStore(db_path=db_file)
            try:
                c1 = reader_store.count_candles("EURUSD_otc")
                stats = reader_store.get_asset_stats("EURUSD_otc")
                df = reader_store.get_candles_df("EURUSD_otc", limit=100)
                candles = reader_store.get_candles("EURUSD_otc", limit=50)
                assert c1 >= 0
                assert isinstance(stats, dict)
                assert isinstance(df, pd.DataFrame)
                assert isinstance(candles, list)
                return len(df)
            except Exception as e:
                exceptions.append(e)
                raise

        with concurrent.futures.ThreadPoolExecutor(max_workers=18) as executor:
            writer_futures = [executor.submit(writer_task, wid) for wid in range(n_writers)]
            reader_futures = [executor.submit(reader_task, rid) for rid in range(6)]

            concurrent.futures.wait(writer_futures + reader_futures)

        assert len(exceptions) == 0, f"Encountered exceptions during concurrency: {exceptions}"

        expected_unique_count = 6 * candles_per_writer + 100  # 3100
        actual_count = store.count_candles("EURUSD_otc")
        assert actual_count == expected_unique_count

        df = store.get_candles_df("EURUSD_otc")
        assert len(df) == expected_unique_count
        assert df["timestamp"].is_monotonic_increasing

    def test_multi_process_concurrent_writes(self, tmp_path: Path) -> None:
        """Stress-tests multi-process access across distinct operating system processes."""
        db_file = str(tmp_path / "process_stress.db")
        store = MarketDataStore(db_path=db_file)

        base_ts = 1700000000.0
        n_procs = 4
        candles_per_proc = 500

        with concurrent.futures.ProcessPoolExecutor(max_workers=n_procs) as executor:
            futures = [
                executor.submit(
                    _multiprocess_worker,
                    db_file,
                    f"ASSET_{pid % 2}",
                    base_ts + pid * 200,
                    candles_per_proc,
                )
                for pid in range(n_procs)
            ]
            results = [f.result() for f in futures]

        assert len(results) == n_procs
        assert all(r > 0 for r in results)

        # Ensure database is clean and accessible
        assert store.count_candles("ASSET_0") > 0
        assert store.count_candles("ASSET_1") > 0
        assets = store.get_stored_assets()
        assert set(assets) == {"ASSET_0", "ASSET_1"}

    def test_database_level_unique_constraint_enforcement(self, tmp_path: Path) -> None:
        """Verifies that SQLite table constraint UNIQUE(asset, timestamp) rejects duplicates."""
        db_file = tmp_path / "constraint_test.db"
        store = MarketDataStore(db_path=db_file)
        store.insert_candles("GOLD_otc", [_generate_candle_entity(1700000000.0)])

        with sqlite3.connect(db_file) as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO candles_s1 (asset, timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("GOLD_otc", 1700000000.0, 2000.0, 2005.0, 1995.0, 2002.0, 50.0),
                )

    def test_non_standard_and_boundary_timestamp_formats(self, tmp_path: Path) -> None:
        """Verifies parsing and sanitization across varied timestamp inputs."""
        db_file = tmp_path / "timestamps_test.db"
        store = MarketDataStore(db_path=db_file)

        fixed_dt_utc = datetime(2026, 8, 31, 15, 0, 0, tzinfo=UTC)
        fixed_epoch = fixed_dt_utc.timestamp()

        # 1. Aware datetime with non-UTC offset (+03:00)
        tz_plus3 = timezone(timedelta(hours=3))
        dt_plus3 = datetime(2026, 8, 31, 18, 0, 0, tzinfo=tz_plus3)
        assert dt_plus3.timestamp() == fixed_epoch

        # 2. Naive datetime (treated as UTC)
        dt_naive = datetime(2026, 8, 31, 15, 0, 1)

        # 3. Milliseconds epoch integer (> 1e11)
        ts_ms = int(fixed_epoch + 2) * 1000

        # 4. ISO8601 string with Z
        iso_z = "2026-08-31T15:00:03Z"

        # 5. ISO8601 string with offset
        iso_offset = "2026-08-31T17:00:04+02:00"

        # 6. Float sub-second timestamp
        ts_subsecond = fixed_epoch + 5.5

        test_items: list[dict[str, Any]] = [
            {"time": dt_plus3, "open": 1.0},
            {"timestamp": dt_naive, "open": 1.1},
            {"t": ts_ms, "open": 1.2},
            {"open_time": iso_z, "open": 1.3},
            {"time": iso_offset, "open": 1.4},
            {"time": ts_subsecond, "open": 1.5},
        ]

        inserted = store.insert_candles("EURUSD_otc", test_items)
        assert inserted == 6

        candles = store.get_candles("EURUSD_otc")
        assert len(candles) == 6
        assert candles[0].open_time == fixed_dt_utc
        assert candles[1].open_time == datetime(2026, 8, 31, 15, 0, 1, tzinfo=UTC)
        assert candles[2].open_time == datetime(2026, 8, 31, 15, 0, 2, tzinfo=UTC)
        assert candles[3].open_time == datetime(2026, 8, 31, 15, 0, 3, tzinfo=UTC)
        assert candles[4].open_time == datetime(2026, 8, 31, 15, 0, 4, tzinfo=UTC)
        assert candles[5].open_time.timestamp() == pytest.approx(fixed_epoch + 5.5)

    def test_submillisecond_timestamps_and_microsecond_resolution(self, tmp_path: Path) -> None:
        """Verifies sub-millisecond timestamps are accurately stored and sorted."""
        db_file = tmp_path / "subms_test.db"
        store = MarketDataStore(db_path=db_file)

        base_ts = 1700000000.0
        micro_items = [{"time": base_ts + 0.000001 * i, "open": 1.0 + i * 0.001} for i in range(5)]
        assert store.insert_candles("HIGH_FREQ", micro_items) == 5

        df = store.get_candles_df("HIGH_FREQ")
        assert len(df) == 5
        assert df["timestamp"].is_monotonic_increasing

    def test_corrupted_empty_and_fault_injection_records(self, tmp_path: Path) -> None:
        """Verifies that invalid or corrupted records are skipped safely without crashes."""
        db_file = tmp_path / "fault_test.db"
        store = MarketDataStore(db_path=db_file)

        base_ts = 1700000000.0

        mixed_payload: list[Any] = [
            # Valid 1
            {"time": base_ts + 1, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05},
            # Missing timestamp
            {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05},
            # Unparseable timestamp string
            {"time": "corrupted-date-xyz", "open": 1.0},
            # Non-dict non-candle object
            "random_string_payload",
            12345,
            None,
            # Timestamp None
            {"time": None, "open": 1.0},
            # Unparseable price values (strings that cannot convert to float)
            {"time": base_ts + 2, "open": "not_a_float", "close": 1.0},
            # Valid 2
            _generate_candle_entity(base_ts + 3),
            # Valid 3 with default missing volume
            {"time": base_ts + 4, "open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085},
            # Corrupted nested structure
            {"time": base_ts + 5, "open": {"nested": "dict"}},
        ]

        inserted = store.insert_candles("EURUSD_otc", mixed_payload)
        assert inserted == 3  # Only Valid 1, Valid 2, Valid 3
        assert store.count_candles("EURUSD_otc") == 3

        retrieved = store.get_candles("EURUSD_otc")
        assert len(retrieved) == 3
        assert retrieved[0].open_time.timestamp() == base_ts + 1
        assert retrieved[1].open_time.timestamp() == base_ts + 3
        assert retrieved[2].open_time.timestamp() == base_ts + 4

    def test_boundary_values_and_extreme_ranges(self, tmp_path: Path) -> None:
        """Tests zero prices, extreme price values, inverted query bounds, and limit edge cases."""
        db_file = tmp_path / "boundary_test.db"
        store = MarketDataStore(db_path=db_file)

        base_ts = 1700000000.0

        # Boundary prices: 0.0, very small, very large
        extreme_candles = [
            {"time": base_ts, "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "volume": 0.0},
            {
                "time": base_ts + 1,
                "open": 1e-8,
                "high": 2e-8,
                "low": 0.5e-8,
                "close": 1.5e-8,
                "volume": 0.0,
            },
            {
                "time": base_ts + 2,
                "open": 100000.0,
                "high": 100050.0,
                "low": 99950.0,
                "close": 100020.0,
                "volume": 1e8,
            },
        ]
        assert store.insert_candles("EXTREME_otc", extreme_candles) == 3

        df = store.get_candles_df("EXTREME_otc")
        assert len(df) == 3
        assert df["open"].iloc[0] == 0.0
        assert df["open"].iloc[1] == pytest.approx(1e-8)
        assert df["close"].iloc[2] == pytest.approx(100020.0)
        assert df["volume"].iloc[2] == pytest.approx(1e8)

        # Inverted query bounds (start > end) -> empty result
        inv_candles = store.get_candles("EXTREME_otc", start_time=base_ts + 10, end_time=base_ts)
        assert inv_candles == []

        inv_df = store.get_candles_df("EXTREME_otc", start_time=base_ts + 10, end_time=base_ts)
        assert isinstance(inv_df, pd.DataFrame)
        assert len(inv_df) == 0

        # Limit = 0 -> empty result
        zero_lim_candles = store.get_candles("EXTREME_otc", limit=0)
        assert zero_lim_candles == []

        zero_lim_df = store.get_candles_df("EXTREME_otc", limit=0)
        assert len(zero_lim_df) == 0

        # Limit larger than count -> returns all rows
        large_lim_df = store.get_candles_df("EXTREME_otc", limit=1000)
        assert len(large_lim_df) == 3

    def test_asset_whitespace_normalization_and_isolation(self, tmp_path: Path) -> None:
        """Verifies that asset names with leading/trailing whitespaces are stripped and isolated."""
        db_file = tmp_path / "whitespace_test.db"
        store = MarketDataStore(db_path=db_file)

        store.insert_candles(" EURUSD_otc ", [_generate_candle_entity(100.0)])
        store.insert_candles("EURUSD_otc", [_generate_candle_entity(200.0)])
        store.insert_candles("GBPUSD_otc\n", [_generate_candle_entity(100.0)])

        assert store.get_stored_assets() == ["EURUSD_otc", "GBPUSD_otc"]
        assert store.count_candles("EURUSD_otc") == 2
        assert store.count_candles("GBPUSD_otc") == 1
        assert store.get_total_candle_count() == 3

        stats = store.get_asset_stats(" EURUSD_otc ")
        assert stats["count"] == 2
        assert stats["first_timestamp"] == 100.0
        assert stats["last_timestamp"] == 200.0

        # Clear with whitespace
        assert store.clear_candles(" EURUSD_otc\t") == 2
        assert store.count_candles("EURUSD_otc") == 0
        assert store.count_candles("GBPUSD_otc") == 1

    def test_end_to_end_backtest_engine_compatibility(self, tmp_path: Path) -> None:
        """Verifies that get_candles_df output directly executes through BinaryBacktestEngine."""
        db_file = tmp_path / "backtest_compat.db"
        store = MarketDataStore(db_path=db_file)

        # Generate 200 M1/S1 candles with oscillating swings
        base_ts = 1700000000.0
        candles = [
            {
                "time": base_ts + i * 60,
                "open": 1.0800 + 0.0010 * (i % 5),
                "high": 1.0815 + 0.0010 * (i % 5),
                "low": 1.0790 + 0.0010 * (i % 5),
                "close": 1.0805 + 0.0010 * ((i + 1) % 5),
                "volume": 100.0,
            }
            for i in range(200)
        ]
        store.insert_candles("EURUSD_otc", candles)

        df = store.get_candles_df("EURUSD_otc")
        assert len(df) == 200

        config = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            strategy_name="support_resistance_pinbar",
            initial_deposit=Decimal("1000.0"),
            payout_rate=Decimal("0.85"),
            expiration_bars=3,
        )
        engine = BinaryBacktestEngine(config=config)
        summary = engine.run(df)

        assert summary is not None
        assert summary.initial_deposit == Decimal("1000.0")
        assert summary.total_trades >= 0
