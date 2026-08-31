# Handoff Report — Explorer Survey 1 (Gateway & Collector Specialist)

## Executive Summary
This report provides a comprehensive architectural and code-level investigation of the **Pocket Option AutoTrader Pro** codebase to support Stage 3: building FastAPI endpoints and a Web UI dashboard for dynamic, thread-safe S1 market data collection.

---

## 1. Observation

### 1.1 PocketOptionTradingGateway Implementation & Shared Lifecycle
- **File Location**: `src/strat_trade/adapters/pocket_option_gateway.py` (lines 1–653)
- **Implemented Ports**: `TradingGateway` (`strat_trade.ports.trading_gateway`), `CandleFeed` (`strat_trade.ports.candles`)
- **Underlying Engine**: `BinaryOptionsToolsV2.pocketoption.PocketOptionAsync`
- **Constructor Signature**:
  ```python
  class PocketOptionTradingGateway:
      def __init__(
          self,
          *,
          ssid: str,
          is_demo: bool = True,
          region: str | None = None,
          use_raw_auth_frame: bool = True,
          sdk_debug: bool = False,
          balance_currency: str = "USD",
      ) -> None:
  ```
- **Connection & Concurrency Locks**:
  - `self._lock = asyncio.Lock()`: Serializes connection establishment (`_client_connected`) and reconnection/shutdown (`_reset_client`, `aclose`).
  - `self._candles_lock = asyncio.Lock()`: Strictly serializes all candle request/response exchanges across concurrent callers to prevent WebSocket framing collisions on Pocket Option's multiplexed channel (`lines 280, 386`).
  - `_PO_NATIVE_PERIODS: frozenset[int] = frozenset({1, 5, 15, 30, 60, 300})`: S1 collection utilizes native period `1` (`lines 21, 376–381`).
- **Asset Discovery (`get_assets`) Method**:
  ```python
  async def get_assets(self) -> list[dict[str, Any]]:
  ```
  - Located at lines 431–511.
  - Queries `await client.active_assets()`.
  - Normalizes asset categories into `"currency"`, `"cryptocurrency"`, `"stock"`, `"commodity"`, and `"index"`.
  - Standard return format per asset:
    ```python
    {
        "symbol": sym,        # e.g., "EURUSD_otc"
        "name": name,          # e.g., "EUR/USD OTC"
        "payout": payout_int,  # e.g., 92
        "is_otc": is_otc_bool, # e.g., True
        "asset_type": raw_type # "currency" | "cryptocurrency" | "stock" | "commodity" | "index"
    }
    ```
- **FastAPI Shared Lifecycle & DI Architecture**:
  - `src/strat_trade/main.py:24–40`:
    ```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = Settings()
        gateway = PocketOptionTradingGateway(...)
        app.state.settings = settings
        app.state.trading_gateway = gateway
        yield
        await gateway.aclose()
    ```
  - `src/strat_trade/api/deps.py:19–34`:
    ```python
    def get_trading_gateway(request: Request) -> TradingGateway:
        gateway = getattr(request.app.state, "trading_gateway", None)
        if gateway is None:
            raise RuntimeError("Trading gateway is not configured on the application.")
        return gateway

    TradingGatewayDep = Annotated[TradingGateway, Depends(get_trading_gateway)]
    ```

---

### 1.2 MarketDataStore Implementation & Schema
- **File Location**: `src/strat_trade/domain/trading/market_data_store.py` (lines 1–324)
- **Database Engine**: Local SQLite with Write-Ahead Logging (`PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA busy_timeout=5000`).
- **Default Database Path**: `data/market_data.db`
- **Schema & Indexes**:
  ```sql
  CREATE TABLE IF NOT EXISTS candles_s1 (
      asset TEXT NOT NULL,
      timestamp REAL NOT NULL,
      open REAL NOT NULL,
      high REAL NOT NULL,
      low REAL NOT NULL,
      close REAL NOT NULL,
      volume REAL NOT NULL DEFAULT 0.0,
      UNIQUE(asset, timestamp)
  );
  CREATE INDEX IF NOT EXISTS idx_candles_s1_asset_timestamp ON candles_s1(asset, timestamp);
  ```
- **Key Methods & Query Contracts**:
  - `insert_candles(asset: str, candles: Sequence[Candle | dict[str, Any]]) -> int` (lines 69–134):
    - Executes `INSERT OR IGNORE INTO candles_s1 ...` using `executemany`.
    - Automatically deduplicates and suppresses overlapping timestamps.
    - Returns count of newly inserted rows (`conn.total_changes - initial_changes`).
  - `get_asset_stats(asset: str) -> dict[str, Any]` (lines 256–287):
    - Executes `SELECT COUNT(*) as count, MIN(timestamp) as min_ts, MAX(timestamp) as max_ts FROM candles_s1 WHERE asset = ?`.
    - Returns:
      ```python
      {
          "asset": asset.strip(),
          "count": int(row["count"]),
          "first_timestamp": float | None,
          "last_timestamp": float | None,
          "first_time": datetime | None,  # UTC datetime
          "last_time": datetime | None,   # UTC datetime
      }
      ```
  - `get_stored_assets() -> list[str]` (lines 250–254): `SELECT DISTINCT asset FROM candles_s1 ORDER BY asset`.
  - `count_candles(asset: str | None = None) -> int` (lines 289–300).
  - `get_total_candle_count() -> int` (lines 301–304).
  - `get_candles_df(asset: str, start_time=None, end_time=None, limit=None) -> pd.DataFrame` (lines 193–249).

---

### 1.3 Existing Data Collection Scripts & Modules
- **File Location**: `scripts/collect_s1_data.py` (lines 1–374)
- **Collection Mechanics**:
  - `collect_cycle(gateway, store, assets, timeframe=1, count=300, throttle_delay=0.5, shutdown_event=None)` (lines 93–169):
    - Iterates sequentially over `assets`.
    - Fetches 300 1-second candles per asset via `await gateway.get_candles(clean_asset, timeframe=1, count=300)`.
    - Inserts candles into `MarketDataStore` via `store.insert_candles`.
    - Catches `BrokerUnavailableError`, `TimeoutError`, `InvalidMarketParametersError`, `ConnectionError`, `OSError`, and generic `Exception` per asset to isolate individual asset faults.
    - Applies `await asyncio.sleep(throttle_delay)` between consecutive asset calls (default `0.5s`) to respect broker rate limits.
  - `run_collector_loop(...)` (lines 171–235):
    - Infinite while loop conditioned on `not shutdown_event.is_set()`.
    - Suspends execution between cycles using `await asyncio.wait_for(event.wait(), timeout=interval)` (default 60.0s), which enables immediate wakeup on cancellation/shutdown without waiting out the 60-second timer.

---

### 1.4 Live Demo Bot Concurrency & Background Task Reference Model
- **File Location**: `src/strat_trade/domain/trading/bot_engine.py` (lines 1–800) and `src/strat_trade/use_cases/manage_live_bot.py` (lines 1–64)
- **Pattern**:
  - Encapsulated singleton engine `LiveDemoBotEngine` with `asyncio.Lock()`, status enum (`IDLE`, `RUNNING`, `PAUSED`, `STOPPED`), and a single background `asyncio.Task`.
  - `start()` spawns `self._task = asyncio.create_task(self._run_loop())`.
  - `stop()` sets status, cancels `self._task`, and awaits it with `try: await self._task except asyncio.CancelledError: pass`.
  - The shared `TradingGateway` is passed in from `TradingGatewayDep` (`app.state.trading_gateway`), avoiding duplicate connections.

---

## 2. Logic Chain

### 2.1 Gateway Sharing & Connection Safety (R1 & R3)
1. Pocket Option WebSocket connections are stateful and expensive to establish (`PocketOptionAsync.wait_for_assets` timeout up to 120s).
2. Creating a separate gateway for the background collector creates duplicate WebSocket sessions, triggering broker disconnects, rate limits, or session invalidation on demo/live tokens.
3. Therefore, the collector management service MUST consume the shared `PocketOptionTradingGateway` instance instantiated in FastAPI `lifespan` via `request.app.state.trading_gateway` (or `TradingGatewayDep`).
4. Because `PocketOptionTradingGateway.get_candles` already features `self._candles_lock`, multiple concurrent calls from the API, Live Bot, and Collector are safely serialized at the gateway level.

### 2.2 Background Task Execution & Shutdown Safety (R1 & R3)
1. Running an `asyncio` task directly in FastAPI requires managing its lifecycle to prevent "fire-and-forget" zombie tasks that continue running after stop requests or server shutdowns.
2. Creating a `MarketDataCollector` (or `CollectorEngine`) class with internal `asyncio.Lock()`, `asyncio.Event()`, and `asyncio.Task` provides complete encapsulation.
3. `POST /api/v1/collector/start` initializes the task and returns immediate status.
4. `POST /api/v1/collector/stop` signals `shutdown_event.set()`, cancels the `_task`, awaits task resolution, and cleans up state without closing the shared gateway.
5. In `src/strat_trade/main.py:lifespan()`, registering an explicit shutdown step `await collector_engine.stop()` before `await gateway.aclose()` guarantees clean teardown during server restarts or SIGINT/SIGTERM signals.

### 2.3 Store Integration & Real-time Stats Aggregation (R1)
1. `MarketDataStore` already exposes `get_asset_stats(asset)`, `get_stored_assets()`, `count_candles(asset)`, and `get_total_candle_count()`.
2. `GET /api/v1/collector/status` can query `get_asset_stats` for all currently tracked assets and all stored assets to return exact row counts, first timestamp, and latest timestamp.
3. Because SQLite is operating in WAL mode with `busy_timeout=5000`, reading stats during active background batch writes is fast, non-blocking, and thread-safe.

---

## 3. Recommended Architectural Design & Endpoint Specifications

### 3.1 Domain Collector Engine (`src/strat_trade/domain/trading/collector_engine.py` or `src/strat_trade/use_cases/manage_collector.py`)
```python
from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from strat_trade.adapters.pocket_option_gateway import PocketOptionTradingGateway
from strat_trade.domain.errors import (
    BrokerUnavailableError,
    InvalidMarketParametersError,
)
from strat_trade.domain.trading.market_data_store import MarketDataStore

logger = logging.getLogger(__name__)

class CollectorStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"

class MarketDataCollector:
    def __init__(self, store: MarketDataStore | None = None) -> None:
        self._store = store or MarketDataStore()
        self._gateway: PocketOptionTradingGateway | None = None
        self._status = CollectorStatus.IDLE
        self._target_assets: list[str] = []
        self._started_at: datetime | None = None
        self._cycles_completed: int = 0
        self._last_cycle_at: datetime | None = None
        self._last_cycle_results: dict[str, int] = {}
        self._total_session_inserted: int = 0
        self._task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._interval_seconds: float = 60.0
        self._candles_count: int = 300
        self._throttle_delay: float = 0.5

    @property
    def status(self) -> CollectorStatus:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._status == CollectorStatus.RUNNING

    async def start(
        self,
        assets: Sequence[str],
        gateway: PocketOptionTradingGateway,
        *,
        interval_seconds: float = 60.0,
        candles_count: int = 300,
        throttle_delay: float = 0.5,
    ) -> None:
        async with self._lock:
            if self._status == CollectorStatus.RUNNING:
                logger.info("Collector already running; updating assets/config.")
                self._target_assets = [a.strip() for a in assets if a.strip()]
                return

            self._gateway = gateway
            self._target_assets = [a.strip() for a in assets if a.strip()]
            self._interval_seconds = interval_seconds
            self._candles_count = candles_count
            self._throttle_delay = throttle_delay
            self._started_at = datetime.now(UTC)
            self._cycles_completed = 0
            self._total_session_inserted = 0
            self._last_cycle_results.clear()
            self._shutdown_event.clear()
            self._status = CollectorStatus.RUNNING
            self._task = asyncio.create_task(self._run_loop())
            logger.info("MarketDataCollector started for assets: %s", self._target_assets)

    async def stop(self) -> None:
        async with self._lock:
            if self._status != CollectorStatus.RUNNING:
                return

            self._status = CollectorStatus.STOPPED
            self._shutdown_event.set()
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None
            logger.info("MarketDataCollector stopped by user request.")

    async def _run_loop(self) -> None:
        while not self._shutdown_event.is_set():
            self._cycles_completed += 1
            cycle_results = {}
            for asset in list(self._target_assets):
                if self._shutdown_event.is_set():
                    break
                try:
                    if self._gateway is not None:
                        candles = await self._gateway.get_candles(
                            asset=asset,
                            timeframe=1,
                            count=self._candles_count,
                        )
                        inserted = self._store.insert_candles(asset, candles)
                        cycle_results[asset] = inserted
                        self._total_session_inserted += inserted
                except (BrokerUnavailableError, TimeoutError, InvalidMarketParametersError, ConnectionError, OSError) as exc:
                    logger.warning("Collector transient error on %s: %s", asset, exc)
                except Exception as exc:
                    logger.error("Collector unexpected error on %s: %s", asset, exc, exc_info=True)

                if self._throttle_delay > 0 and not self._shutdown_event.is_set():
                    await asyncio.sleep(self._throttle_delay)

            self._last_cycle_at = datetime.now(UTC)
            self._last_cycle_results = cycle_results

            if self._shutdown_event.is_set():
                break

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=max(0.1, self._interval_seconds),
                )
            except TimeoutError:
                pass
```

### 3.2 FastAPI Schemas (`src/strat_trade/api/schemas.py`)
```python
class StartCollectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assets: list[str] = Field(..., min_length=1, description="List of broker asset symbols to collect")
    interval_seconds: float = Field(60.0, ge=1.0, le=3600.0, description="Interval in seconds between cycles")
    candles_count: int = Field(300, ge=10, le=5000, description="Candle count requested per batch")
    throttle_delay: float = Field(0.5, ge=0.0, le=10.0, description="Delay between asset requests in seconds")

class CollectorAssetStatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset: str
    count: int
    first_timestamp: float | None = None
    last_timestamp: float | None = None
    first_time: str | None = None
    last_time: str | None = None
    session_inserted: int = 0

class CollectorStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_running: bool
    status: str
    started_at: str | None = None
    tracked_assets: list[str]
    cycles_completed: int
    total_stored_candles: int
    total_session_inserted: int
    last_cycle_at: str | None = None
    asset_stats: list[CollectorAssetStatResponse]
```

### 3.3 FastAPI Route Handlers (`src/strat_trade/api/routes/collector.py`)
- `GET /api/v1/collector/available-assets` -> returns `list[AssetItemResponse]` via `await feed.get_assets()`, fallback to curated assets.
- `GET /api/v1/collector/status` -> returns `CollectorStatusResponse` with live stats from `store.get_asset_stats()`.
- `POST /api/v1/collector/start` -> accepts `StartCollectorRequest`, starts loop using `TradingGatewayDep`, returns updated `CollectorStatusResponse`.
- `POST /api/v1/collector/stop` -> halts collector background task, returns updated `CollectorStatusResponse`.

---

## 4. Caveats
1. **Curated Fallback Asset List**: If the broker connection is currently unauthenticated or offline (e.g. invalid SSID or network issues), `get_assets()` returns `[]`. The `available-assets` endpoint should fall back to `_CURATED_ASSETS` (defined in `src/strat_trade/api/routes/candles.py:13–196`) so the Web UI still renders checkboxes for the operator.
2. **Rate Limiting on Large Asset Selections**: If an operator selects 50+ assets with a `0.5s` throttle, one cycle takes >25 seconds. The collector design naturally handles this sequentially, but `interval_seconds` should represent the sleep duration *between* completed cycles.
3. **Database File Location**: In multi-process deployment (e.g., Uvicorn workers > 1), SQLite WAL handles concurrency, but background tasks should run in a single worker or dedicated process. Pocket Option AutoTrader Pro runs as a single FastAPI instance.

---

## 5. Conclusion
1. `PocketOptionTradingGateway` is well-equipped with `get_assets()`, `get_candles(asset, timeframe=1, count=300)`, internal reconnect resilience, and a candle request mutex lock (`_candles_lock`).
2. `MarketDataStore` already provides high-speed WAL SQLite ingestion with duplicate suppression (`INSERT OR IGNORE`) and detailed summary queries (`get_asset_stats`).
3. The data collection pipeline from `scripts/collect_s1_data.py` can be encapsulated into a singleton `MarketDataCollector` service and exposed via clean REST endpoints in `src/strat_trade/api/routes/collector.py`.
4. Graceful background lifecycle handling requires using `asyncio.Task`, `asyncio.Event`, cancellation exception handling, and FastAPI `lifespan` hook registration.

---

## 6. Verification Method

### Test Suite Execution
```bash
.venv/bin/pytest tests/test_collect_s1_data.py tests/test_market_data_store.py tests/test_s1_data_collection_integration.py tests/test_m2_challenger_2_collector_stress.py -v
```

### Direct Verification Criteria for Stage 3 Implementers
1. `GET /api/v1/collector/available-assets` returns HTTP 200 with JSON list containing asset objects (`symbol`, `name`, `payout`, `is_otc`, `asset_type`).
2. `POST /api/v1/collector/start` with `{"assets": ["EURUSD_otc"]}` returns HTTP 200 with `is_running: true`.
3. `GET /api/v1/collector/status` returns HTTP 200 reflecting growing candle counts in `asset_stats`.
4. `POST /api/v1/collector/stop` returns HTTP 200 with `is_running: false` and halts the background loop within <1.0s.
