from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from strat_trade.domain.entities import Candle
from strat_trade.domain.trading.market_data_store import MarketDataStore


def _sample_candle(
    ts: float,
    open_p: float = 1.1000,
    high_p: float = 1.1010,
    low_p: float = 1.0990,
    close_p: float = 1.1005,
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


class TestMarketDataStore:
    def test_schema_and_pragmas_initialization(self, tmp_path: Path) -> None:
        db_file = tmp_path / "deep" / "nested" / "market.db"
        store = MarketDataStore(db_path=db_file)
        assert db_file.is_file()
        assert store.get_total_candle_count() == 0

        with sqlite3.connect(db_file) as conn:
            # Check table existence and columns
            cursor = conn.execute("PRAGMA table_info(candles_s1)")
            cols = {row[1]: row[2] for row in cursor.fetchall()}
            assert "asset" in cols
            assert "timestamp" in cols
            assert "open" in cols
            assert "high" in cols
            assert "low" in cols
            assert "close" in cols
            assert "volume" in cols

            # Check WAL mode
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"

            # Check index existence
            idx_rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_candles_s1_asset_timestamp'"
            ).fetchall()
            assert len(idx_rows) == 1

    def test_insert_and_get_candles_domain_entities(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "test.db")
        base_ts = 1700000000.0
        candles = [
            _sample_candle(base_ts + i, open_p=1.0850 + i * 0.0001, close_p=1.0855 + i * 0.0001)
            for i in range(5)
        ]

        inserted = store.insert_candles("EURUSD_otc", candles)
        assert inserted == 5

        retrieved = store.get_candles("EURUSD_otc")
        assert len(retrieved) == 5
        for i, c in enumerate(retrieved):
            assert isinstance(c, Candle)
            assert c.open_time.tzinfo is not None
            assert c.open_time == datetime.fromtimestamp(base_ts + i, tz=UTC)
            assert c.open == Decimal(f"{1.0850 + i * 0.0001:.4f}")
            assert c.close == Decimal(f"{1.0855 + i * 0.0001:.4f}")
            assert c.volume == Decimal("100.0")

    def test_insert_raw_dicts_and_timestamp_formats(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "test.db")
        base_ts = 1700001000.0

        raw_dicts: list[dict[str, Any]] = [
            # Standard time key
            {
                "time": base_ts,
                "open": 1.2000,
                "high": 1.2010,
                "low": 1.1990,
                "close": 1.2005,
                "volume": 50.0,
            },
            # timestamp key, missing volume
            {
                "timestamp": base_ts + 1,
                "open": 1.2005,
                "high": 1.2015,
                "low": 1.2000,
                "close": 1.2010,
            },
            # open_time + short keys (o, h, l, c, v)
            {
                "open_time": base_ts + 2,
                "o": 1.2010,
                "h": 1.2020,
                "l": 1.2005,
                "c": 1.2015,
                "v": 75.0,
            },
            # Millisecond timestamp (> 1e11)
            {
                "t": (base_ts + 3) * 1000.0,
                "open": 1.2015,
                "high": 1.2025,
                "low": 1.2010,
                "close": 1.2020,
                "volume": 20.0,
            },
            # ISO datetime string
            {
                "time": datetime.fromtimestamp(base_ts + 4, tz=UTC).isoformat(),
                "open": 1.2020,
                "high": 1.2030,
                "low": 1.2015,
                "close": 1.2025,
            },
        ]

        inserted = store.insert_candles("GBPUSD_otc", raw_dicts)
        assert inserted == 5

        retrieved = store.get_candles("GBPUSD_otc")
        assert len(retrieved) == 5
        for i in range(5):
            assert retrieved[i].open_time == datetime.fromtimestamp(base_ts + i, tz=UTC)

    def test_unique_constraint_idempotent_deduplication(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "test.db")
        base_ts = 1700002000.0

        # Batch 1: t=0..4 (5 candles)
        batch1 = [_sample_candle(base_ts + i) for i in range(5)]
        inserted1 = store.insert_candles("EURUSD_otc", batch1)
        assert inserted1 == 5
        assert store.count_candles("EURUSD_otc") == 5

        # Batch 2 (overlapping): t=2..6 (5 candles: t=2,3,4 duplicates, t=5,6 new)
        batch2 = [_sample_candle(base_ts + i) for i in range(2, 7)]
        inserted2 = store.insert_candles("EURUSD_otc", batch2)
        assert inserted2 == 2
        assert store.count_candles("EURUSD_otc") == 7

        # Batch 3: exact duplicate of Batch 1 -> 0 new rows
        inserted3 = store.insert_candles("EURUSD_otc", batch1)
        assert inserted3 == 0
        assert store.count_candles("EURUSD_otc") == 7

    def test_multi_asset_isolation(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "test.db")
        ts = 1700003000.0

        candle_eur = _sample_candle(ts, open_p=1.0500)
        candle_gold = _sample_candle(ts, open_p=2050.0)

        # Same timestamp for different assets must not conflict
        ins1 = store.insert_candles("EURUSD_otc", [candle_eur])
        ins2 = store.insert_candles("GOLD_otc", [candle_gold])
        assert ins1 == 1
        assert ins2 == 1

        assert store.count_candles("EURUSD_otc") == 1
        assert store.count_candles("GOLD_otc") == 1
        assert store.get_total_candle_count() == 2

        assets = store.get_stored_assets()
        assert assets == ["EURUSD_otc", "GOLD_otc"]

        eur_candles = store.get_candles("EURUSD_otc")
        gold_candles = store.get_candles("GOLD_otc")
        assert len(eur_candles) == 1
        assert len(gold_candles) == 1
        assert eur_candles[0].open == Decimal("1.0500")
        assert gold_candles[0].open == Decimal("2050.0")

    def test_insert_candle_and_save_candles_alias(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "test.db")
        c1 = _sample_candle(100.0)
        c2 = _sample_candle(101.0)

        # insert_candle single
        assert store.insert_candle("AUDNZD_otc", c1) is True
        assert store.insert_candle("AUDNZD_otc", c1) is False  # duplicate

        # save_candles alias
        assert store.save_candles("AUDNZD_otc", [c2]) == 1
        assert store.count_candles("AUDNZD_otc") == 2

    def test_get_candles_filtering_and_limits(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "test.db")
        base_ts = 1700004000.0
        candles = [_sample_candle(base_ts + i) for i in range(20)]
        store.insert_candles("EURUSD_otc", candles)

        # Start time filter (epoch float)
        res_start = store.get_candles("EURUSD_otc", start_time=base_ts + 5)
        assert len(res_start) == 15
        assert res_start[0].open_time == datetime.fromtimestamp(base_ts + 5, tz=UTC)

        # End time filter (datetime)
        end_dt = datetime.fromtimestamp(base_ts + 10, tz=UTC)
        res_end = store.get_candles("EURUSD_otc", end_time=end_dt)
        assert len(res_end) == 11
        assert res_end[-1].open_time == end_dt

        # Range filter [start, end]
        res_range = store.get_candles("EURUSD_otc", start_time=base_ts + 5, end_time=base_ts + 10)
        assert len(res_range) == 6

        # Limit filter
        res_limit = store.get_candles("EURUSD_otc", limit=5)
        assert len(res_limit) == 5
        assert res_limit[0].open_time == datetime.fromtimestamp(base_ts, tz=UTC)
        assert res_limit[-1].open_time == datetime.fromtimestamp(base_ts + 4, tz=UTC)

    def test_get_candles_df_structure_and_types(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "test.db")
        base_ts = 1700005000.0
        candles = [_sample_candle(base_ts + i, open_p=1.1000 + i * 0.0001) for i in range(10)]
        store.insert_candles("EURUSD_otc", candles)

        df = store.get_candles_df("EURUSD_otc")
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
        assert len(df) == 10
        assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])
        assert df["timestamp"].dt.tz is not None
        assert float(df["open"].iloc[0]) == pytest.approx(1.1000)
        assert float(df["open"].iloc[9]) == pytest.approx(1.1009)

        # Empty DataFrame for non-existent asset
        empty_df = store.get_candles_df("NON_EXISTENT")
        assert isinstance(empty_df, pd.DataFrame)
        assert list(empty_df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
        assert len(empty_df) == 0

    def test_asset_stats_and_metadata_inspection(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "test.db")
        ts1 = 1700006000.0
        ts2 = 1700007000.0

        candles_eur = [_sample_candle(ts1 + i) for i in range(10)]
        candles_gold = [_sample_candle(ts2 + i) for i in range(5)]

        store.insert_candles("EURUSD_otc", candles_eur)
        store.insert_candles("GOLD_otc", candles_gold)

        stats_eur = store.get_asset_stats("EURUSD_otc")
        assert stats_eur["asset"] == "EURUSD_otc"
        assert stats_eur["count"] == 10
        assert stats_eur["first_timestamp"] == ts1
        assert stats_eur["last_timestamp"] == ts1 + 9
        assert stats_eur["first_time"] == datetime.fromtimestamp(ts1, tz=UTC)
        assert stats_eur["last_time"] == datetime.fromtimestamp(ts1 + 9, tz=UTC)

        assert store.get_latest_timestamp("EURUSD_otc") == ts1 + 9
        assert store.get_latest_timestamp("GOLD_otc") == ts2 + 4
        assert store.get_latest_timestamp("UNKNOWN") is None

        empty_stats = store.get_asset_stats("UNKNOWN")
        assert empty_stats["count"] == 0
        assert empty_stats["first_timestamp"] is None

    def test_clear_candles_selective_and_all(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "test.db")
        store.insert_candles("EURUSD_otc", [_sample_candle(100.0), _sample_candle(101.0)])
        store.insert_candles("GOLD_otc", [_sample_candle(200.0)])

        assert store.get_total_candle_count() == 3

        # Clear only EURUSD_otc
        deleted = store.clear_candles("EURUSD_otc")
        assert deleted == 2
        assert store.count_candles("EURUSD_otc") == 0
        assert store.count_candles("GOLD_otc") == 1

        # Clear all
        deleted_all = store.clear_candles(None)
        assert deleted_all == 1
        assert store.get_total_candle_count() == 0

    def test_edge_cases_and_malformed_inputs(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "test.db")

        # Empty sequence
        assert store.insert_candles("EURUSD_otc", []) == 0

        # Malformed dicts (missing timestamps or unparseable fields)
        malformed: list[Any] = [
            {"foo": "bar"},
            {"time": None, "open": 1.0},
            {"timestamp": "invalid_date_string", "open": 1.0},
            "not_even_a_dict_or_candle",
            None,
        ]
        assert store.insert_candles("EURUSD_otc", malformed) == 0
        assert store.count_candles("EURUSD_otc") == 0
