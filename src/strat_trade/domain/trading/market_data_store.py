from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from strat_trade.domain.entities import Candle


class MarketDataStore:
    """Persistent SQLite store for historical high-frequency (S1/M1) candles."""

    def __init__(self, db_path: str | Path = "data/market_data.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS candles_s1 (
                    asset TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL DEFAULT 0.0,
                    UNIQUE(asset, timestamp)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_candles_s1_asset_timestamp "
                "ON candles_s1(asset, timestamp)"
            )
            conn.commit()

    @staticmethod
    def _extract_ts(ts_val: datetime | float | int | str) -> float:
        if isinstance(ts_val, datetime):
            if ts_val.tzinfo is None:
                ts_val = ts_val.replace(tzinfo=UTC)
            return float(ts_val.timestamp())
        if isinstance(ts_val, (int, float)):
            f = float(ts_val)
            return f / 1000.0 if f > 1e11 else f
        if isinstance(ts_val, str):
            dt = datetime.fromisoformat(ts_val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return float(dt.timestamp())
        raise ValueError(f"Unsupported timestamp type: {type(ts_val)}")

    def insert_candles(
        self,
        asset: str,
        candles: Sequence[Candle | dict[str, Any]],
    ) -> int:
        """Batch inserts candles using INSERT OR IGNORE, suppressing duplicates.

        Returns the number of newly inserted rows.
        """
        if not candles:
            return 0
        asset_clean = asset.strip()
        rows: list[tuple[str, float, float, float, float, float, float]] = []

        for c in candles:
            if isinstance(c, Candle):
                ts = float(c.open_time.timestamp())
                open_price = float(c.open)
                high_price = float(c.high)
                low_price = float(c.low)
                close_price = float(c.close)
                volume_val = float(c.volume) if c.volume is not None else 0.0
            elif isinstance(c, dict):
                raw_t = c.get("time", c.get("timestamp", c.get("open_time", c.get("t"))))
                if raw_t is None:
                    continue
                try:
                    ts = self._extract_ts(raw_t)
                except (ValueError, TypeError):
                    continue
                try:
                    raw_o = c.get("open") if c.get("open") is not None else c.get("o", 0.0)
                    open_price = float(raw_o) if raw_o is not None else 0.0
                    raw_h = c.get("high") if c.get("high") is not None else c.get("h", open_price)
                    high_price = float(raw_h) if raw_h is not None else open_price
                    raw_l = c.get("low") if c.get("low") is not None else c.get("l", open_price)
                    low_price = float(raw_l) if raw_l is not None else open_price
                    raw_c = c.get("close") if c.get("close") is not None else c.get("c", open_price)
                    close_price = float(raw_c) if raw_c is not None else open_price
                    raw_v = c.get("volume") if c.get("volume") is not None else c.get("v", 0.0)
                    volume_val = float(raw_v) if raw_v is not None else 0.0
                except (ValueError, TypeError):
                    continue
            else:
                continue
            rows.append(
                (asset_clean, ts, open_price, high_price, low_price, close_price, volume_val)
            )

        if not rows:
            return 0

        with self._get_connection() as conn:
            initial_changes = conn.total_changes
            conn.executemany(
                """
                INSERT OR IGNORE INTO candles_s1 (
                    asset, timestamp, open, high, low, close, volume
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            inserted = conn.total_changes - initial_changes
            conn.commit()
            return max(0, inserted)

    def save_candles(self, asset: str, candles: Sequence[Candle]) -> int:
        """Alias for insert_candles accepting a sequence of domain Candle entities."""
        return self.insert_candles(asset, candles)

    def insert_candle(self, asset: str, candle: Candle | dict[str, Any]) -> bool:
        """Inserts a single candle, returning True if newly inserted."""
        return self.insert_candles(asset, [candle]) > 0

    def get_candles(
        self,
        asset: str,
        start_time: datetime | float | int | None = None,
        end_time: datetime | float | int | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        """Queries stored candles for asset, returning domain Candle objects with UTC datetime."""
        query = (
            "SELECT asset, timestamp, open, high, low, close, volume "
            "FROM candles_s1 WHERE asset = ?"
        )
        params: list[Any] = [asset.strip()]

        if start_time is not None:
            ts_start = self._extract_ts(start_time)
            query += " AND timestamp >= ?"
            params.append(ts_start)

        if end_time is not None:
            ts_end = self._extract_ts(end_time)
            query += " AND timestamp <= ?"
            params.append(ts_end)

        query += " ORDER BY timestamp ASC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()

        candles: list[Candle] = []
        for r in rows:
            dt = datetime.fromtimestamp(float(r["timestamp"]), tz=UTC)
            vol = Decimal(str(r["volume"])) if r["volume"] is not None else None
            candles.append(
                Candle(
                    open_time=dt,
                    open=Decimal(str(r["open"])),
                    high=Decimal(str(r["high"])),
                    low=Decimal(str(r["low"])),
                    close=Decimal(str(r["close"])),
                    volume=vol,
                )
            )
        return candles

    def get_candles_df(
        self,
        asset: str,
        start_time: datetime | float | int | None = None,
        end_time: datetime | float | int | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """Returns canonical DataFrame ['timestamp', 'open', 'high', 'low', 'close', 'volume'].

        `timestamp` is a UTC datetime series, sorted ascending, ready for BinaryBacktestEngine.
        """
        query = "SELECT timestamp, open, high, low, close, volume FROM candles_s1 WHERE asset = ?"
        params: list[Any] = [asset.strip()]

        if start_time is not None:
            ts_start = self._extract_ts(start_time)
            query += " AND timestamp >= ?"
            params.append(ts_start)

        if end_time is not None:
            ts_end = self._extract_ts(end_time)
            query += " AND timestamp <= ?"
            params.append(ts_end)

        query += " ORDER BY timestamp ASC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()

        if not rows:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            ).astype(
                {
                    "open": float,
                    "high": float,
                    "low": float,
                    "close": float,
                    "volume": float,
                }
            )

        data = {
            "timestamp": [datetime.fromtimestamp(float(r["timestamp"]), tz=UTC) for r in rows],
            "open": [float(r["open"]) for r in rows],
            "high": [float(r["high"]) for r in rows],
            "low": [float(r["low"]) for r in rows],
            "close": [float(r["close"]) for r in rows],
            "volume": [float(r["volume"]) if r["volume"] is not None else 0.0 for r in rows],
        }
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    def get_stored_assets(self) -> list[str]:
        """Returns list of distinct assets present in the database."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT DISTINCT asset FROM candles_s1 ORDER BY asset").fetchall()
            return [str(r["asset"]) for r in rows]

    def get_asset_stats(self, asset: str) -> dict[str, Any]:
        """Returns summary statistics for a stored asset."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) as count, MIN(timestamp) as min_ts, MAX(timestamp) as max_ts
                FROM candles_s1 WHERE asset = ?
                """,
                [asset.strip()],
            ).fetchone()

        if not row or row["count"] == 0:
            return {
                "asset": asset.strip(),
                "count": 0,
                "first_timestamp": None,
                "last_timestamp": None,
                "first_time": None,
                "last_time": None,
            }

        min_ts = float(row["min_ts"]) if row["min_ts"] is not None else None
        max_ts = float(row["max_ts"]) if row["max_ts"] is not None else None

        return {
            "asset": asset.strip(),
            "count": int(row["count"]),
            "first_timestamp": min_ts,
            "last_timestamp": max_ts,
            "first_time": datetime.fromtimestamp(min_ts, tz=UTC) if min_ts is not None else None,
            "last_time": datetime.fromtimestamp(max_ts, tz=UTC) if max_ts is not None else None,
        }

    def count_candles(self, asset: str | None = None) -> int:
        """Returns candle count for a specific asset or across the entire database."""
        with self._get_connection() as conn:
            if asset is None:
                row = conn.execute("SELECT COUNT(*) as count FROM candles_s1").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as count FROM candles_s1 WHERE asset = ?",
                    [asset.strip()],
                ).fetchone()
            return int(row["count"]) if row else 0

    def get_total_candle_count(self) -> int:
        """Returns total candle count across all assets."""
        return self.count_candles(None)

    def get_latest_timestamp(self, asset: str) -> float | None:
        """Returns the latest stored timestamp for the given asset."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT MAX(timestamp) as max_ts FROM candles_s1 WHERE asset = ?",
                [asset.strip()],
            ).fetchone()
            return float(row["max_ts"]) if row and row["max_ts"] is not None else None

    def clear_candles(self, asset: str | None = None) -> int:
        """Deletes stored candles for a specific asset or all candles if asset is None."""
        with self._get_connection() as conn:
            if asset is None:
                cursor = conn.execute("DELETE FROM candles_s1")
            else:
                cursor = conn.execute("DELETE FROM candles_s1 WHERE asset = ?", [asset.strip()])
            deleted = cursor.rowcount
            conn.commit()
            return max(0, deleted)
