# Stage 2 Exploration Report: S1 Market Data Collector & Gateway Integration

## 1. Observation
- **Original Request Reference**: `ORIGINAL_REQUEST.md` (§ Follow-up — 2026-08-31T15:45:40Z).
  - R1: Database schema in `src/strat_trade/domain/trading/market_data_store.py` connecting to `data/market_data.db`, table `candles_s1` with columns `(asset TEXT, timestamp INTEGER/REAL, open REAL, high REAL, low REAL, close REAL, volume REAL)` and `UNIQUE(asset, timestamp)`.
  - R2: Standalone script `scripts/collect_s1_data.py` instantiating `PocketOptionTradingGateway`, async loop fetching `timeframe=1`, `count=300` for assets `["EURUSD_otc", "GOLD_otc", "AUDNZD_otc"]`, sleeping 60-120s, handling exceptions gracefully.
  - R3: Safe upsert via `INSERT OR IGNORE` (or `INSERT OR REPLACE`) to handle overlapping window polling without duplicate entries.
- **Gateway Implementation**: `src/strat_trade/adapters/pocket_option_gateway.py`:
  - Native periods: `_PO_NATIVE_PERIODS = frozenset({1, 5, 15, 30, 60, 300})` (lines 21-22).
  - Class: `PocketOptionTradingGateway` (lines 254-653).
  - Method: `get_candles(self, asset: str, timeframe: int | str, *, count: int, end_time: datetime | None = None) -> list[Candle]` (lines 368-430).
  - Return type: `list[Candle]` where `Candle` (`src/strat_trade/domain/entities.py`) has `open_time: datetime` (UTC tz-aware), `open: Decimal`, `high: Decimal`, `low: Decimal`, `close: Decimal`, `volume: Decimal | None`.
  - Error classes:
    - `BrokerUnavailableError` (`src/strat_trade/domain/errors.py`: lines 8-14)
    - `InvalidMarketParametersError` (`src/strat_trade/domain/errors.py`: lines 16-22)
    - `TimeoutError` (handled internally and re-raised as `BrokerUnavailableError`)
- **Settings & Auth**:
  - `src/strat_trade/settings.py` (`Settings.pocket_option_ssid`, `pocket_option_ssid_file`, `pocket_option_is_demo`, etc.).
  - `Settings` raises `ValueError` if neither `POCKET_OPTION_SSID` nor `POCKET_OPTION_SSID_FILE` is set.
  - For standalone script, fallback chain: CLI `--ssid` -> `Settings()` -> `os.getenv("POCKET_OPTION_SSID")` -> `.ssid` file -> `"demo"`.
- **Existing Store Patterns**:
  - `src/strat_trade/domain/trading/trade_store.py`: Uses standard library `sqlite3`, `PRAGMA journal_mode=WAL`, `db_path.parent.mkdir(parents=True, exist_ok=True)`.

---

## 2. Logic Chain

### 2.1. Gateway Execution & Lifecycle
1. `PocketOptionTradingGateway` connects lazily upon `_client_connected()`. It uses `PocketOptionAsync` from `BinaryOptionsToolsV2`.
2. Calling `gateway.get_candles(asset, timeframe=1, count=300)` calculates `offset = 1 * 300 + 1 = 301` seconds of historical 1-second candles.
3. If the broker is unreachable or asset sync fails, `BrokerUnavailableError` is raised.
4. If network timeout occurs during candle request, the gateway retries once with connection reset; if it fails again, it raises `BrokerUnavailableError`.
5. Releasing gateway resources is done via `await gateway.aclose()`.

### 2.2. Error Resilience in Collector Loop
To satisfy R2 (script never crashes on network/broker issues), the collector loop must wrap individual asset fetches in a try-except block:
- Catch `(BrokerUnavailableError, InvalidMarketParametersError, TimeoutError, ConnectionError, OSError)`: log as warning with asset context, record metric/counter, continue to next asset.
- Catch general `Exception`: log error with traceback, continue to next asset.
- Only exit when `shutdown_event.is_set()` (via SIGINT/SIGTERM) or after 1 round if `--once` is provided.

### 2.3. Data Transformation & SQLite Storage
1. Each `Candle` from the gateway has:
   - `open_time`: `datetime` with `tzinfo=UTC` -> converted to epoch integer: `int(candle.open_time.timestamp())`.
   - `open`, `high`, `low`, `close`: `Decimal` -> converted to `float`.
   - `volume`: `Decimal | None` -> converted to `float` or `None`.
2. `MarketDataStore.save_candles(asset, candles)` executes:
   ```sql
   INSERT OR IGNORE INTO candles_s1 (asset, timestamp, open, high, low, close, volume)
   VALUES (?, ?, ?, ?, ?, ?, ?)
   ```
3. Because consecutive 60-second polling rounds request 300 seconds of history, 240 seconds overlap. `UNIQUE(asset, timestamp)` and `INSERT OR IGNORE` ensure idempotency and zero duplicates.

### 2.4. Graceful Shutdown Architecture
Using `asyncio.Event()` for cancellation:
- Register signal handlers for `signal.SIGINT` and `signal.SIGTERM` with `shutdown_event.set()`.
- Between rounds, wait with `await asyncio.wait_for(shutdown_event.wait(), timeout=interval)` instead of `asyncio.sleep(interval)` so shutdown is instantaneous when user presses Ctrl+C.
- In `finally:`, execute `await gateway.aclose()`.

---

## 3. Caveats
1. **Pocket Option WebSocket Rate Limits**: Polling too frequently (< 5s) or fetching thousands of bars in parallel across many assets could trigger broker connection throttling. Default interval of 60s with sequential asset requests (with 0.5s pause between assets) is safe.
2. **Settings Validation**: `Settings()` from `strat_trade.settings` enforces non-empty SSID. When running in dummy demo mode (`SSID="demo"`), `Settings(pocket_option_ssid="demo")` must be explicitly passed or resolved by a fallback helper.
3. **Database Concurrency**: Using `PRAGMA journal_mode=WAL` allows concurrent read access (e.g. backtesting engine or web UI) while the collector process writes incoming batches.

---

## 4. Conclusion & Recommended Architecture

### Component 1: `src/strat_trade/domain/trading/market_data_store.py`
```python
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from strat_trade.domain.entities import Candle


class MarketDataStore:
    """Persistent SQLite store for high-frequency market data (S1 candles)."""

    def __init__(self, db_path: str | Path = "data/market_data.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS candles_s1 (
                    asset TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL,
                    UNIQUE(asset, timestamp)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_candles_s1_asset_timestamp ON candles_s1(asset, timestamp)"
            )
            conn.commit()

    def save_candles(self, asset: str, candles: Sequence[Candle]) -> int:
        """Inserts candles using INSERT OR IGNORE, avoiding duplicates.
        Returns the number of newly inserted rows.
        """
        if not candles:
            return 0

        asset_clean = asset.strip()
        records: list[tuple[str, int, float, float, float, float, float | None]] = []
        for c in candles:
            ts = int(c.open_time.timestamp()) if isinstance(c.open_time, datetime) else int(c.open_time)
            vol = float(c.volume) if c.volume is not None else None
            records.append((
                asset_clean,
                ts,
                float(c.open),
                float(c.high),
                float(c.low),
                float(c.close),
                vol,
            ))

        with self._get_connection() as conn:
            initial_count = conn.total_changes
            conn.executemany(
                """
                INSERT OR IGNORE INTO candles_s1 (asset, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
            conn.commit()
            return conn.total_changes - initial_count

    def get_candles(
        self,
        asset: str,
        start_time: int | datetime | None = None,
        end_time: int | datetime | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        """Query candles for an asset within an optional time range."""
        query = "SELECT asset, timestamp, open, high, low, close, volume FROM candles_s1 WHERE asset = ?"
        params: list[Any] = [asset.strip()]

        if start_time is not None:
            ts_start = int(start_time.timestamp()) if isinstance(start_time, datetime) else int(start_time)
            query += " AND timestamp >= ?"
            params.append(ts_start)

        if end_time is not None:
            ts_end = int(end_time.timestamp()) if isinstance(end_time, datetime) else int(end_time)
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
            dt = datetime.fromtimestamp(r["timestamp"], tz=UTC)
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

    def count_candles(self, asset: str | None = None) -> int:
        with self._get_connection() as conn:
            if asset is None:
                row = conn.execute("SELECT COUNT(*) as count FROM candles_s1").fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) as count FROM candles_s1 WHERE asset = ?", [asset.strip()]).fetchone()
            return int(row["count"]) if row else 0

    def get_latest_timestamp(self, asset: str) -> int | None:
        with self._get_connection() as conn:
            row = conn.execute("SELECT MAX(timestamp) as max_ts FROM candles_s1 WHERE asset = ?", [asset.strip()]).fetchone()
            return int(row["max_ts"]) if row and row["max_ts"] is not None else None

    def get_stored_assets(self) -> list[str]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT DISTINCT asset FROM candles_s1 ORDER BY asset").fetchall()
            return [r["asset"] for r in rows]
```

### Component 2: `scripts/collect_s1_data.py`
```python
#!/usr/bin/env python3
"""Standalone S1 Data Collector for Pocket Option AutoTrader Pro.

Fetches 1-second candles for target assets in an async loop and upserts them
into data/market_data.db using MarketDataStore.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Sequence

# Add repo root to pythonpath
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from strat_trade.adapters.pocket_option_gateway import PocketOptionTradingGateway
from strat_trade.domain.errors import BrokerUnavailableError, InvalidMarketParametersError
from strat_trade.domain.trading.market_data_store import MarketDataStore
from strat_trade.settings import Settings

DEFAULT_TARGET_ASSETS = ["EURUSD_otc", "GOLD_otc", "AUDNZD_otc"]
logger = logging.getLogger("collect_s1_data")


def resolve_ssid(cli_ssid: str | None = None, cli_ssid_file: str | None = None) -> str:
    if cli_ssid and cli_ssid.strip():
        return cli_ssid.strip()
    if cli_ssid_file and Path(cli_ssid_file).is_file():
        return Path(cli_ssid_file).read_text(encoding="utf-8").strip()
    try:
        settings = Settings()
        if settings.pocket_option_ssid:
            return settings.pocket_option_ssid
    except Exception:
        pass
    env_ssid = os.getenv("POCKET_OPTION_SSID") or os.getenv("STRAT_TRADE_POCKET_OPTION_SSID")
    if env_ssid and env_ssid.strip():
        return env_ssid.strip()
    ssid_file = os.getenv("POCKET_OPTION_SSID_FILE") or os.getenv("STRAT_TRADE_POCKET_OPTION_SSID_FILE")
    if ssid_file and Path(ssid_file).is_file():
        return Path(ssid_file).read_text(encoding="utf-8").strip()
    if (REPO_ROOT / ".ssid").is_file():
        return (REPO_ROOT / ".ssid").read_text(encoding="utf-8").strip()
    return "demo"


async def collect_cycle(
    gateway: PocketOptionTradingGateway,
    store: MarketDataStore,
    assets: Sequence[str],
    *,
    timeframe: int = 1,
    count: int = 300,
) -> dict[str, int]:
    """Runs a single pass across target assets."""
    results: dict[str, int] = {}
    for asset in assets:
        try:
            logger.info("Fetching %d S%d candles for %s...", count, timeframe, asset)
            candles = await gateway.get_candles(asset, timeframe=timeframe, count=count)
            inserted = store.save_candles(asset, candles)
            results[asset] = inserted
            logger.info(
                "Stored %d candles for %s (%d new inserted, total in DB: %d)",
                len(candles),
                asset,
                inserted,
                store.count_candles(asset),
            )
        except (BrokerUnavailableError, TimeoutError) as exc:
            logger.warning("Broker unavailable or timeout for %s: %s", asset, exc)
        except InvalidMarketParametersError as exc:
            logger.warning("Invalid market parameters for %s: %s", asset, exc)
        except Exception as exc:
            logger.error("Unexpected error fetching candles for %s: %s", asset, exc, exc_info=True)
        # Small throttle between assets
        await asyncio.sleep(0.5)
    return results


async def run_collector_loop(
    gateway: PocketOptionTradingGateway,
    store: MarketDataStore,
    assets: Sequence[str],
    *,
    timeframe: int = 1,
    count: int = 300,
    interval: int = 60,
    once: bool = False,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    event = shutdown_event or asyncio.Event()
    logger.info(
        "Starting S1 data collection loop for assets=%s (interval=%ds, count=%d, once=%s)",
        list(assets),
        interval,
        count,
        once,
    )
    cycle = 0
    while not event.is_set():
        cycle += 1
        logger.info("--- Starting collection cycle #%d ---", cycle)
        await collect_cycle(gateway, store, assets, timeframe=timeframe, count=count)
        if once:
            logger.info("Single-run (--once) complete; exiting loop.")
            break
        logger.info("Cycle #%d finished. Sleeping for %ds...", cycle, interval)
        try:
            await asyncio.wait_for(event.wait(), timeout=interval)
        except TimeoutError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect S1 historical candles from Pocket Option.")
    parser.add_argument("--assets", default=",".join(DEFAULT_TARGET_ASSETS), help="Comma-separated asset symbols.")
    parser.add_argument("--timeframe", type=int, default=1, help="Candle timeframe in seconds (default: 1).")
    parser.add_argument("--count", type=int, default=300, help="Number of candles per request (default: 300).")
    parser.add_argument("--interval", type=int, default=60, help="Sleep interval between cycles (default: 60s).")
    parser.add_argument("--db-path", default="data/market_data.db", help="Path to SQLite DB.")
    parser.add_argument("--ssid", default=None, help="Pocket Option SSID override.")
    parser.add_argument("--ssid-file", default=None, help="File containing Pocket Option SSID.")
    parser.add_argument("--demo", action="store_true", default=True, help="Use demo account mode (default).")
    parser.add_argument("--once", action="store_true", help="Run one collection cycle and exit.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    assets = [a.strip() for a in args.assets.split(",") if a.strip()]
    ssid = resolve_ssid(args.ssid, args.ssid_file)
    store = MarketDataStore(db_path=args.db_path)
    gateway = PocketOptionTradingGateway(ssid=ssid, is_demo=args.demo)

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except (NotImplementedError, RuntimeError):
            pass

    try:
        await run_collector_loop(
            gateway=gateway,
            store=store,
            assets=assets,
            timeframe=args.timeframe,
            count=args.count,
            interval=args.interval,
            once=args.once,
            shutdown_event=shutdown_event,
        )
    finally:
        logger.info("Shutting down gateway connection...")
        await gateway.aclose()
        logger.info("Collector shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 5. Verification Method
- **Unit Tests**:
  - Test `MarketDataStore` initialization, table creation, and indices.
  - Test `MarketDataStore.save_candles` with overlapping candle timestamps; assert row count matches unique items and duplicates are ignored without error.
  - Test `MarketDataStore.get_candles` with start/end time filters and limits.
  - Test `scripts/collect_s1_data.py` `collect_cycle` with mocked `PocketOptionTradingGateway`:
    - Case A: Normal successful batch -> verify all candles inserted.
    - Case B: `BrokerUnavailableError` raised on one asset -> verify script logs warning, continues to other assets, and does not crash.
    - Case C: `TimeoutError` raised -> verify resilience and loop continuation.
    - Case D: `--once` flag -> verify loop executes exactly once and cleanly terminates.
- **Commands**:
  - `.venv/bin/pytest tests/test_market_data_store.py tests/test_collect_s1_data.py -v`
  - `.venv/bin/python scripts/collect_s1_data.py --once --db-path data/test_market_data.db`
  - `sqlite3 data/market_data.db "SELECT asset, count(*), min(timestamp), max(timestamp) FROM candles_s1 GROUP BY asset;"`
