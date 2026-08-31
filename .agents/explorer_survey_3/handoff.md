# QA & Test Engineering Survey: Stage 3 S1 Data Collector & Web UI Management

**Author**: Explorer Survey 3 (Testing & Quality Assurance Specialist)  
**Date**: 2026-08-31  
**Project**: Pocket Option AutoTrader Pro (Stage 3)  
**Target Scope**: FastAPI S1 Collector Endpoints, Thread-safe Background Execution, Web UI Management Panel, Test Suite Architecture, and Tier 1–4 Test Plan.

---

## 1. Observation

### 1.1 Test Suite & Pytest Configuration
- **Configuration File**: `pyproject.toml` (lines 36–39):
  ```toml
  [tool.pytest.ini_options]
  asyncio_mode = "auto"
  asyncio_default_fixture_loop_scope = "function"
  ```
- **Test Framework**: `pytest 9.1.1` with `pytest-asyncio 1.4.0` and `anyio 4.14.2` running under Python 3.12.13.
- **Fixture Discovery**: Currently, **no root `tests/conftest.py` exists**. Each test file (e.g. `tests/test_candles_api.py`, `tests/test_bot_and_audit_api.py`, `tests/test_collect_s1_data.py`) independently re-declares ad-hoc mock classes (`FakeTradingGateway`, `FakeCandleFeed`, `DummySettings`).
- **Installed Dependencies**:
  - `httpx 0.28.1`, `fastapi 0.141.1`, `starlette 1.6.0`, `pydantic 2.13.4`, `pandas 3.0.5`, `numpy 2.2.6`.
  - `playwright` is **not installed** in `.venv` or declared in `pyproject.toml` optional dependencies.

### 1.2 Existing Endpoint & Gateway Test Patterns
- **Synchronous TestClient vs AsyncClient**:
  - Existing API tests (e.g. `tests/test_bot_and_audit_api.py:57`, `tests/test_candles_api.py:73`) use `from fastapi.testclient import TestClient`.
  - Warning observed: `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated`.
  - When testing async endpoints that spawn background coroutines (`asyncio.create_task`), `TestClient` runs requests via an internal synchronous event loop / portal, which can cause synchronization drift when testing asynchronous task cancellation or background progress.
  - Using `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")` within `@pytest.mark.asyncio` guarantees that tests, endpoints, and background tasks run on the same event loop.
- **Mock Gateways**:
  - Standardized gateway interface is defined in `src/strat_trade/ports/trading_gateway.py` and `src/strat_trade/ports/candles.py`.
  - Concrete adapter `PocketOptionTradingGateway` (`src/strat_trade/adapters/pocket_option_gateway.py:431`) exposes `async def get_assets(self) -> list[dict[str, Any]]` and `async def get_candles(self, asset: str, timeframe: int | str, *, count: int, ...) -> list[Candle]`.
  - `unittest.mock.AsyncMock` is successfully used in `tests/test_collect_s1_data.py` and `tests/test_m2_challenger_2_collector_stress.py` to mock `get_candles` and `get_assets`.
- **Market Data Store Isolation**:
  - `MarketDataStore` (`src/strat_trade/domain/trading/market_data_store.py`) initializes SQLite with `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, and `PRAGMA busy_timeout=5000`.
  - Tests isolate databases by instantiating `MarketDataStore(db_path=tmp_path / "test_market_data.db")`, guaranteeing clean database isolation per test.

### 1.3 Background Task & Cancellation Execution Patterns
- **Bot Engine Precedent**:
  - `LiveDemoBotEngine` (`src/strat_trade/domain/trading/bot_engine.py:112-209`) manages an internal background task:
    - Task creation: `self._task = asyncio.create_task(self._run_loop())` protected by `asyncio.Lock()`.
    - Task cancellation in `stop()`:
      ```python
      if self._task and not self._task.done():
          self._task.cancel()
          try:
              await self._task
          except asyncio.CancelledError:
              pass
          self._task = None
      ```
- **S1 Collector Script Precedent**:
  - `scripts/collect_s1_data.py:93-234`:
    - Uses `collect_cycle(gateway, store, assets, ...)` with per-asset fault isolation catching `(BrokerUnavailableError, TimeoutError)`, `InvalidMarketParametersError`, `(ConnectionError, OSError)`, and generic `Exception`.
    - Polling loop uses `await asyncio.wait_for(event.wait(), timeout=interval)` so cancellation/shutdown immediately terminates sleep without waiting for the full interval.
    - Connection teardown: `await gateway.aclose()` in a `finally` block.
  - `tests/test_m2_challenger_2_collector_stress.py` has 13 empirical tests verifying cancellation, multi-asset fault isolation, and corrupted response resilience.

### 1.4 Web UI Dashboard Architecture
- **Template Rendering**: `src/strat_trade/web/templates/index.html` (186 KB) is served by `src/strat_trade/api/routes/web.py` via `GET /` and `GET /dashboard`.
- **Navigation Structure**: Pure HTML5/Tailwind SPA with tab switching function `switchTab(tabId)` managing:
  - `liveBot` (`#tabLiveBot`)
  - `audit` (`#tabAudit`)
  - `portfolio` (`#tabPortfolio`)
  - `single` (`#tabSingle`)
  - `optimizer` (`#tabOptimizer`)
  - `apiTester` (`#tabApiTester`)
- **Stage 3 Requirement**: Add "Data Collection" management panel (`#tabCollector` and `#tabBtnCollector`) with asset checkbox selection, Select/Deselect All buttons, Start/Stop buttons, and an auto-refreshing status table.

---

## 2. Logic Chain

### 2.1 Test Architecture & Fixture Centralization
1. **Observation**: Currently, mock classes and test apps are redundantly declared in multiple test files without a shared `conftest.py`.
2. **Inference**: Creating a centralized `tests/conftest.py` with modular, reusable fixtures (`mock_trading_gateway`, `isolated_market_store`, `test_fastapi_app`, `async_api_client`) standardizes test authoring, prevents duplicate boilerplate, and ensures clean test isolation.
3. **Async Testing Standard**: Using `httpx.AsyncClient` with `ASGITransport(app=app)` ensures all FastAPI endpoints, dependency injections (`CandleFeedDep`, `TradingGatewayDep`), and background tasks run within the same pytest asyncio event loop.

### 2.2 Background Task Lifecycle & Concurrency Strategy
1. **Observation**: R1 and R3 require launching the collector as an `asyncio` background task inside FastAPI, sharing the global `PocketOptionTradingGateway` instance.
2. **Inference**:
   - A dedicated `CollectorManager` (or `CollectorEngine`) class with `asyncio.Lock()` is necessary to serialize state transitions (`IDLE` -> `RUNNING` -> `STOPPING` -> `STOPPED`).
   - Starting the collector when already running must be idempotent or return an explicit HTTP 409 conflict.
   - Calling `POST /api/v1/collector/stop` must set a stop `asyncio.Event()`, cancel the background task, and await completion cleanly.
   - The loop must yield execution between asset queries using `await asyncio.sleep(throttle_delay)` to avoid broker rate-limiting, and use `asyncio.wait_for(shutdown_event.wait(), timeout=interval)` for responsive stopping.
3. **Verification**: Tests must verify that cancelling the background task does **not** close the shared `PocketOptionTradingGateway` (which must remain alive for the rest of FastAPI and the Live Bot).

### 2.3 UI Testing Strategy: Fast DOM/API Testing vs Playwright
1. **Observation**: The repo does not have Playwright installed or configured in CI. The UI is a single-page HTML/JS dashboard without a complex build pipeline (Tailwind + Lucide CDN).
2. **Inference**:
   - **Track 1 (Primary - Pytest DOM & API Contract Suite)**: Fast, deterministic, and dependency-free. Uses `AsyncClient` to fetch `/` and parse the rendered DOM, asserting all UI component IDs, button click handlers, checkbox list templates, and JavaScript API fetch signatures.
   - **Track 2 (Optional - Playwright E2E Harness)**: Structured with `@pytest.mark.playwright` and `pytest.importorskip("playwright")` so that when Playwright is installed, browser automation tests can run without breaking standard pytest runs.

---

## 3. Caveats & Assumptions

1. **Broker Gateway Sharing**:
   - The background collector uses the shared `app.state.trading_gateway`. Background candle fetching must not interfere with concurrent trade execution or balance fetching on the Live Demo Bot.
2. **Environment Dependencies**:
   - Playwright is not in `.venv`. The primary automated test suite will execute via Pytest + `httpx.AsyncClient` + HTML DOM parsing. An optional Playwright test module will be provided with conditional skipping.
3. **SQLite Concurrency**:
   - `MarketDataStore` uses SQLite with WAL mode. Although WAL mode allows concurrent readers while writing, high-frequency writes during continuous S1 collection require short transactions to prevent `sqlite3.OperationalError: database is locked`.

---

## 4. Conclusion & Acceptance Criteria Test Plan

### Tiered Acceptance Test Matrix

```
+---------------------------------------------------------------------------------------------------+
| Tier 1: Feature Coverage (Unit & REST API Endpoint Contracts)                                    |
+---------------------------------------------------------------------------------------------------+
| Tier 2: Boundary & Error Handling (Fault Injection, Validation, Edge Cases)                       |
+---------------------------------------------------------------------------------------------------+
| Tier 3: Cross-Feature Concurrency & Gateway Sharing (Bot + Collector + Backtester)               |
+---------------------------------------------------------------------------------------------------+
| Tier 4: End-to-End Integration Scenarios (Start -> Collect -> Status -> Stop -> UI Sync)        |
+---------------------------------------------------------------------------------------------------+
```

### Detailed Test Specifications

#### Tier 1: Feature Coverage (Unit & API Contracts)

| Test ID | Test Name | Target Component | Input / Action | Expected Outcome |
| :--- | :--- | :--- | :--- | :--- |
| **TC-1.1** | `test_get_available_assets_success` | `GET /api/v1/collector/available-assets` | Mock gateway returning 10 assets (currencies, OTC, commodities) | HTTP 200; returns JSON array with symbols, names, payout rates, and `is_otc` booleans. |
| **TC-1.2** | `test_get_collector_status_idle` | `GET /api/v1/collector/status` | Initial server state before starting | HTTP 200; `status: "IDLE"`, `is_running: false`, `active_assets: []`, `total_candles: 0`. |
| **TC-1.3** | `test_post_collector_start_valid_assets` | `POST /api/v1/collector/start` | `{"assets": ["EURUSD_otc", "GOLD_otc"]}` | HTTP 200; `status: "RUNNING"`, `is_running: true`, `active_assets: ["EURUSD_otc", "GOLD_otc"]`. Background task spawned. |
| **TC-1.4** | `test_get_collector_status_running_with_stats` | `GET /api/v1/collector/status` | Collector running after 1 cycle inserting 300 candles per asset | HTTP 200; `status: "RUNNING"`, `asset_stats` contains count $\ge 300$, min/max timestamps per asset. |
| **TC-1.5** | `test_post_collector_stop_running_task` | `POST /api/v1/collector/stop` | Collector currently running | HTTP 200; background task cancelled cleanly; status transitions to `"STOPPED"`; `is_running: false`. |
| **TC-1.6** | `test_ui_html_contains_collector_tab_and_controls` | `GET /` (`index.html`) | Fetch root web dashboard HTML | HTTP 200; HTML contains `#tabBtnCollector`, `#tabCollector`, `#collectorAssetsContainer`, `#btnCollectorSelectAll`, `#btnCollectorDeselectAll`, `#btnCollectorStart`, `#btnCollectorStop`, and `#collectorStatsTable`. |

#### Tier 2: Boundary & Error Handling (Fault Injection & Edge Cases)

| Test ID | Test Name | Target Component | Input / Action | Expected Outcome |
| :--- | :--- | :--- | :--- | :--- |
| **TC-2.1** | `test_start_collector_empty_assets_rejected` | `POST /api/v1/collector/start` | `{"assets": []}` | HTTP 422 Unprocessable Entity (or HTTP 400 Bad Request) with explicit error detail. |
| **TC-2.2** | `test_start_collector_whitespace_and_duplicate_assets` | `POST /api/v1/collector/start` | `{"assets": [" EURUSD_otc ", "EURUSD_otc", ""]}` | Sanitizes input: strips whitespace, removes empty strings, deduplicates to single `"EURUSD_otc"`. |
| **TC-2.3** | `test_start_collector_already_running` | `POST /api/v1/collector/start` | Second `POST /start` while first is running | Returns HTTP 409 Conflict (or idempotent 200 with status `"RUNNING"` and warning message). |
| **TC-2.4** | `test_stop_collector_already_idle_or_stopped` | `POST /api/v1/collector/stop` | `POST /stop` when no task is active | Safe no-op; HTTP 200; `status: "IDLE"` or `"STOPPED"`, no exceptions raised. |
| **TC-2.5** | `test_collector_loop_broker_timeout_resilience` | Background Collector Loop | Gateway raises `TimeoutError` on asset 1, returns 10 candles on asset 2 | Loop does not crash; error logged; asset 2 candles saved; loop continues next cycle. |
| **TC-2.6** | `test_collector_loop_broker_unavailable_resilience` | Background Collector Loop | Gateway raises `BrokerUnavailableError` | Error caught and logged; FastAPI server remains responsive; next cycle attempts reconnect. |
| **TC-2.7** | `test_collector_loop_invalid_market_parameters` | Background Collector Loop | Gateway raises `InvalidMarketParametersError` for malformed asset | Malformed asset skipped; valid assets in same cycle processed successfully. |

#### Tier 3: Cross-Feature Concurrency & State Isolation

| Test ID | Test Name | Target Component | Input / Action | Expected Outcome |
| :--- | :--- | :--- | :--- | :--- |
| **TC-3.1** | `test_shared_gateway_concurrency_bot_and_collector` | Gateway / FastAPI state | Run LiveDemoBot trade execution and S1 Collector cycle simultaneously | Both complete without websocket frame corruption or gateway lockup. Gateway remains open after collector stops. |
| **TC-3.2** | `test_concurrent_collector_writes_and_backtest_reads` | `MarketDataStore` | Collector batch inserting 1000 candles while Backtest Engine executes `get_candles_df` | SQLite WAL pragma handles concurrent read/write without `database is locked` error. |
| **TC-3.3** | `test_rapid_start_stop_cycling_stress` | `CollectorManager` / API | Rapidly dispatch 20 `POST /start` and `POST /stop` requests with 10ms intervals | Zero zombie background tasks; state strictly matches the final call; no unhandled task exceptions. |
| **TC-3.4** | `test_fastapi_lifespan_shutdown_cancels_collector` | FastAPI Lifespan | Trigger FastAPI app shutdown while collector is active | Collector background task is cleanly cancelled and drained before gateway teardown completes. |

#### Tier 4: End-to-End (E2E) Integration Scenarios

| Test ID | Test Name | Target Component | Flow / Steps | Expected Outcome |
| :--- | :--- | :--- | :--- | :--- |
| **TC-4.1** | `test_e2e_collector_full_lifecycle` | End-to-End Backend | 1. `GET /api/v1/collector/available-assets`<br>2. Select `["EURUSD_otc", "GOLD_otc"]`<br>3. `POST /api/v1/collector/start`<br>4. Await 2 collection cycles<br>5. `GET /api/v1/collector/status` -> verify candle counts > 0<br>6. Query `MarketDataStore.get_candles()` -> verify continuous monotonic timestamps<br>7. `POST /api/v1/collector/stop`<br>8. Verify `status == "STOPPED"` and no further writes occur | Complete data collection lifecycle executes smoothly with 100% data integrity and zero memory leaks. |
| **TC-4.2** | `test_e2e_web_ui_dom_and_api_contract` | Web UI & Endpoints | 1. Parse `index.html` DOM<br>2. Verify elements and JS handlers (`loadAvailableCollectorAssets`, `startCollector`, `stopCollector`, `refreshCollectorStatus`, `selectAllAssets`, `deselectAllAssets`)<br>3. Test endpoint contracts match JS payload schemas | Web UI structure and JS client bindings perfectly match FastAPI collector endpoint schemas. |

---

## 5. Verification Method

### 5.1 Proposed Reusable Test Fixtures (`tests/conftest.py`)
```python
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock
from pathlib import Path
from fastapi import FastAPI
from strat_trade.main import app as main_app
from strat_trade.domain.trading.market_data_store import MarketDataStore
from strat_trade.domain.entities import Candle
from decimal import Decimal
from datetime import datetime, UTC, timedelta

@pytest.fixture
def isolated_market_store(tmp_path: Path) -> MarketDataStore:
    db_file = tmp_path / "test_market_data.db"
    return MarketDataStore(db_path=db_file)

@pytest.fixture
def mock_trading_gateway() -> AsyncMock:
    gateway = AsyncMock()
    gateway.get_assets.return_value = [
        {"symbol": "EURUSD_otc", "name": "EUR/USD OTC", "payout": 92, "is_otc": True, "asset_type": "currency"},
        {"symbol": "GOLD_otc", "name": "Gold OTC", "payout": 88, "is_otc": True, "asset_type": "commodity"},
        {"symbol": "BTCUSD", "name": "Bitcoin", "payout": 75, "is_otc": False, "asset_type": "cryptocurrency"},
    ]
    
    def _dummy_candles(asset: str, timeframe: int = 1, count: int = 300, **kwargs):
        base_ts = 1700000000.0
        return [
            Candle(
                open_time=datetime.fromtimestamp(base_ts + i, tz=UTC),
                open=Decimal("1.0850"),
                high=Decimal("1.0860"),
                low=Decimal("1.0840"),
                close=Decimal("1.0855"),
                volume=Decimal("10.0"),
            )
            for i in range(count)
        ]
    
    gateway.get_candles.side_effect = _dummy_candles
    return gateway

@pytest.fixture
async def async_test_client(mock_trading_gateway: AsyncMock, isolated_market_store: MarketDataStore):
    # Inject isolated dependencies into app state
    main_app.state.trading_gateway = mock_trading_gateway
    main_app.state.market_data_store = isolated_market_store
    transport = ASGITransport(app=main_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
```

### 5.2 Commands to Run the Test Suite

```bash
# 1. Run full unit and integration regression test suite
.venv/bin/pytest tests/ -v

# 2. Run targeted Stage 3 Collector & API tests
.venv/bin/pytest tests/test_collector_api.py tests/test_collect_s1_data.py tests/test_market_data_store.py -v

# 3. Check code formatting, style, and static analysis
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/
```
