# Stage 2 Exploration & Design Report: SQLite MarketDataStore & S1 Data Collector

## 1. Observation

Direct investigation of the codebase revealed the following structural details and integration points:

### 1.1 Existing Domain & Entity Models
- `src/strat_trade/domain/entities.py` (lines 8–18):
  ```python
  @dataclass(frozen=True, slots=True)
  class Candle:
      """Single OHLC bar in broker-neutral form (open time + prices)."""
      open_time: datetime
      open: Decimal
      high: Decimal
      low: Decimal
      close: Decimal
      volume: Decimal | None = None
  ```
- `src/strat_trade/adapters/pocket_option_gateway.py`:
  - Line 21: `_PO_NATIVE_PERIODS: frozenset[int] = frozenset({1, 5, 15, 30, 60, 300})` confirms native 1-second (`timeframe=1`) candle support.
  - Lines 368–430: `get_candles(self, asset: str, timeframe: int | str, *, count: int, end_time: datetime | None = None) -> list[Candle]` fetches normalized `Candle` objects from Pocket Option.
  - Lines 257–278: Constructor accepts `ssid: str`, `is_demo: bool = True`, `region: str | None = None`, `use_raw_auth_frame: bool = True`, `sdk_debug: bool = False`.

### 1.2 Established SQLite Persistence Patterns
- `src/strat_trade/domain/trading/trade_store.py` (lines 20–30):
  - Path management: `self.db_path = Path(db_path); self.db_path.parent.mkdir(parents=True, exist_ok=True)`
  - Connection configuration: `conn = sqlite3.connect(self.db_path); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA journal_mode=WAL")`
  - Safe transaction execution with `with self._get_connection() as conn:` context managers.

### 1.3 Backtest Engine Consumption
- `src/strat_trade/domain/backtest/engine.py` (lines 46–114):
  - `BinaryBacktestEngine.run(df_raw)` accepts either a `pd.DataFrame` with columns `['timestamp', 'open', 'high', 'low', 'close', 'volume']` (with `timestamp` as UTC datetime) or a list of `Candle` objects.
  - Time-based matching implemented in Stage 1 relies on indexed timestamp comparisons `timestamp >= target_exit_time`.

### 1.4 Settings & Configuration
- `src/strat_trade/settings.py` (lines 10–59):
  - Reads `POCKET_OPTION_SSID` / `STRAT_TRADE_POCKET_OPTION_SSID` from environment or `.env` / `.ssid` file.
  - Fallback to dummy/demo credentials if running offline or in simulated environments.

---

## 2. Logic Chain

1. **Storage Requirements**:
   - The user requested persisting 1-second (S1) candles into a local SQLite database at `data/market_data.db` to fuel time-based backtests.
   - Table `candles_s1` must have columns: `asset` (TEXT), `timestamp` (REAL/INTEGER UTC epoch), `open` (REAL), `high` (REAL), `low` (REAL), `close` (REAL), `volume` (REAL).
   - A `UNIQUE(asset, timestamp)` constraint is mandatory to prevent duplicate candle rows during overlapping periodic polling.
   - Creating an index on `(asset, timestamp)` optimizes time-range queries (`WHERE asset = ? AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC`).

2. **Store Component (`MarketDataStore`)**:
   - Location: `src/strat_trade/domain/trading/market_data_store.py`.
   - Methods:
     - `insert_candle(asset: str, candle: Candle) -> bool`
     - `insert_candles(asset: str, candles: Sequence[Candle | dict[str, Any]]) -> int` (batch insertion via `executemany` using `INSERT OR IGNORE INTO candles_s1 ...` or `INSERT OR REPLACE INTO candles_s1 ...`)
     - `get_candles(asset: str, start_time: datetime | float | None = None, end_time: datetime | float | None = None, limit: int | None = None) -> list[Candle]`
     - `get_candles_df(asset: str, start_time: datetime | float | None = None, end_time: datetime | float | None = None, limit: int | None = None) -> pd.DataFrame` (converts directly to DataFrame ready for `BinaryBacktestEngine`)
     - Metadata inspection: `get_stored_assets() -> list[str]`, `get_asset_stats(asset: str) -> dict[str, Any]`, `get_total_candle_count() -> int`, `clear_candles(asset: str | None = None) -> int`.
   - Concurrency & Performance:
     - `PRAGMA journal_mode=WAL;`
     - `PRAGMA synchronous=NORMAL;`
     - `PRAGMA busy_timeout=5000;`

3. **Collector Script (`scripts/collect_s1_data.py`)**:
   - Standalone executable CLI script with `asyncio` main loop.
   - Target assets default to `["EURUSD_otc", "GOLD_otc", "AUDNZD_otc"]` (or CLI options `--assets`).
   - Polls `gateway.get_candles(asset, timeframe=1, count=300)` every 60–120s (configurable via `--interval`, default `60`).
   - Resilient error handling per asset and cycle: catches `BrokerUnavailableError`, `TimeoutError`, `InvalidMarketParametersError`, and network errors, logging warnings and resuming without crashing.
   - Graceful shutdown on SIGINT / SIGTERM closing gateway connections (`await gateway.aclose()`).
   - CLI flags: `--assets`, `--interval`, `--count`, `--db-path`, `--once` (single-pass test mode), `--max-iterations`, `--ssid`.

---

## 3. Recommended Design & Detailed Interfaces

### 3.1 `MarketDataStore` Specification (`src/strat_trade/domain/trading/market_data_store.py`)

```python
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
    """Persistent SQLite store for historical high-resolution (S1/M1) candles."""

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
                "CREATE INDEX IF NOT EXISTS idx_candles_s1_asset_ts ON candles_s1(asset, timestamp)"
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
        """Batch inserts candles with safe duplicate suppression."""
        if not candles:
            return 0
        asset_clean = asset.strip()
        rows: list[tuple[str, float, float, float, float, float, float]] = []

        for c in candles:
            if isinstance(c, Candle):
                ts = float(c.open_time.timestamp())
                o = float(c.open)
                h = float(c.high)
                l = float(c.low)
                cl = float(c.close)
                v = float(c.volume) if c.volume is not None else 0.0
            elif isinstance(c, dict):
                raw_t = c.get("time", c.get("timestamp", c.get("open_time", c.get("t"))))
                if raw_t is None:
                    continue
                ts = self._extract_ts(raw_t)
                o = float(c.get("open", c.get("o", 0.0)))
                h = float(c.get("high", c.get("h", o)))
                l = float(c.get("low", c.get("l", o)))
                cl = float(c.get("close", c.get("c", o)))
                vol = c.get("volume", c.get("v", 0.0))
                v = float(vol) if vol is not None else 0.0
            else:
                continue
            rows.append((asset_clean, ts, o, h, l, cl, v))

        if not rows:
            return 0

        with self._get_connection() as conn:
            cursor = conn.executemany(
                """
                INSERT OR IGNORE INTO candles_s1 (
                    asset, timestamp, open, high, low, close, volume
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            inserted = cursor.rowcount
            conn.commit()
            return max(0, inserted)

    def get_candles(
        self,
        asset: str,
        start_time: datetime | float | None = None,
        end_time: datetime | float | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        """Queries stored candles for asset, returning domain Candle objects."""
        # Builds dynamic query with optional start, end, limit
        ...

    def get_candles_df(
        self,
        asset: str,
        start_time: datetime | float | None = None,
        end_time: datetime | float | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """Returns canonical DataFrame with ['timestamp', 'open', 'high', 'low', 'close', 'volume']."""
        ...

    def get_stored_assets(self) -> list[str]:
        ...

    def get_asset_stats(self, asset: str) -> dict[str, Any]:
        ...

    def get_total_candle_count(self) -> int:
        ...

    def clear_candles(self, asset: str | None = None) -> int:
        ...
```

### 3.2 `collect_s1_data.py` Specification (`scripts/collect_s1_data.py`)

```python
#!/usr/bin/env python3
"""Standalone high-frequency (1s) candle data collector for Pocket Option."""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from strat_trade.adapters.pocket_option_gateway import PocketOptionTradingGateway
from strat_trade.domain.errors import BrokerUnavailableError, InvalidMarketParametersError
from strat_trade.domain.trading.market_data_store import MarketDataStore

DEFAULT_ASSETS = ["EURUSD_otc", "GOLD_otc", "AUDNZD_otc"]
DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_CANDLES_COUNT = 300
DEFAULT_DB_PATH = "data/market_data.db"
```

Key features:
- Initializes `PocketOptionTradingGateway` with SSID from args, environment, or default fallback (`"demo"`).
- Uses `MarketDataStore` for batch insertion and stats tracking.
- Cycles through target assets sequentially:
  ```python
  try:
      candles = await gateway.get_candles(asset, timeframe=1, count=args.count)
      inserted = store.insert_candles(asset, candles)
      logger.info(f"[{asset}] Fetched {len(candles)} S1 candles, saved {inserted} new records.")
  except (BrokerUnavailableError, TimeoutError) as exc:
      logger.warning(f"[{asset}] Transient broker error: {exc}. Will retry next cycle.")
  except Exception as exc:
      logger.error(f"[{asset}] Unexpected error during fetch: {exc}", exc_info=True)
  ```
- Handles cancellation signals (`SIGINT`, `SIGTERM`) smoothly and closes gateway session.

---

## 4. Caveats

- **Broker API Rate Limiting**: Fetching 300 1-second candles per asset every 60s results in ~240 overlapping seconds per cycle, ensuring no gaps during minor network hiccups while staying well within Pocket Option rate limits.
- **SSID Authentication**: In live production environments, a valid `POCKET_OPTION_SSID` must be configured in `.env` or `.ssid`. For testing or mock environments, dummy/demo SSIDs can be used with mock gateways or offline tests.
- **Timestamp Types**: Storing `timestamp` as `REAL` (floating point epoch seconds UTC) allows lossless precision and clean numeric range indexing in SQLite.

---

## 5. Conclusion

The plan for Stage 2 is fully defined:
1. `src/strat_trade/domain/trading/market_data_store.py` encapsulates all SQLite schema creation, WAL configuration, batch upserting with `INSERT OR IGNORE`, and data retrieval (both as `Candle` entities and `pd.DataFrame`).
2. `scripts/collect_s1_data.py` provides a standalone, robust, and interruptible async daemon for continuous S1 collection across target assets.
3. Full compatibility with Stage 1's `BinaryBacktestEngine` time-based evaluation is guaranteed via `store.get_candles_df()`.

---

## 6. Verification Method

Once implemented by the trading systems developer, verify Stage 2 with the following steps:

1. **Unit Tests**:
   ```bash
   .venv/bin/pytest tests/test_market_data_store.py tests/test_collect_s1_data.py -v
   ```
2. **Database Schema & Uniqueness Verification**:
   - Insert overlapping candle batches.
   - Assert `UNIQUE(asset, timestamp)` prevents duplicates while returning exact row counts.
3. **Collector CLI Verification**:
   - Run single iteration test:
     ```bash
     .venv/bin/python scripts/collect_s1_data.py --once --assets EURUSD_otc,GOLD_otc --db-path data/test_market_data.db
     ```
   - Verify `data/test_market_data.db` is populated with `candles_s1` rows.
4. **Code Quality Gates**:
   ```bash
   .venv/bin/ruff check src tests scripts
   .venv/bin/mypy src/strat_trade
   ```
