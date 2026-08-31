# Stage 3 Test Suite Readiness: S1 Data Collector & Web UI Management

**Status**: READY FOR MILESTONE VERIFICATION  
**Author**: E2E Test Writer  
**Date**: 2026-08-31  
**Project**: Pocket Option AutoTrader Pro (`strat_trade_be`)  

---

## 1. Test Suite Summary

The comprehensive automated test suite for **Stage 3: S1 Data Collector & Web UI Management** has been fully created and integrated into the project's test framework. It delivers centralized test fixtures and tiered test coverage across REST API endpoints, background concurrency & lifecycle resilience, DOM/JS contract parity, and end-to-end data ingestion flows.

| Test File | Tier | Coverage Scope | Test Cases |
| :--- | :---: | :--- | :---: |
| `tests/conftest.py` | Infra | Centralized fixtures: `isolated_market_store`, `mock_trading_gateway`, `async_test_client` (ASGI transport), sample candle series | 4 Fixtures |
| `tests/test_collector_api.py` | Tier 1 & 2 | Available assets endpoint, status endpoint, start/stop endpoints, input sanitization, 422 boundary validation, idempotence | 7 Methods |
| `tests/test_collector_concurrency.py` | Tier 3 | Shared gateway concurrency (bot + collector), rapid 20-cycle start/stop stress test, multi-asset fault isolation, SQLite WAL concurrent read/write | 4 Methods |
| `tests/test_collector_ui.py` | Tier 1 & 4 | Web UI DOM layout, tab navigation, asset checkbox matrix, action buttons, telemetry cards, JS client handler signatures | 3 Methods |
| `tests/test_collector_e2e.py` | Tier 4 | Complete operator workflow (Discover -> Select -> Start -> Cycles -> DB Verification -> Status -> Stop -> Immutability), coexistence | 2 Methods |
| **Total Stage 3 Suite** | **Tier 1–4** | **Exhaustive functional, adversarial, concurrency, and E2E coverage** | **20 Tests** |

---

## 2. Test Architecture & Fixtures (`tests/conftest.py`)

1. **`isolated_market_store`**:
   - Spawns an isolated `MarketDataStore` against a dedicated SQLite database in `tmp_path` configured with `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000`.
   - Guaranteed zero state bleeding across tests.
2. **`mock_trading_gateway`**:
   - `AsyncMock` conforming to `TradingGateway` and `CandleFeed` ports.
   - Provides realistic `get_assets()` listings (currencies, OTC, commodities, cryptocurrencies).
   - Generates monotonic synthetic candle series with UTC timestamps via `get_candles()` and `get_recent_candles()`.
   - Mocks `aclose()` without side effects.
3. **`async_test_client`**:
   - Pure asynchronous test client bound via `httpx.ASGITransport(app=main_app)`.
   - Injects mock gateway and isolated store directly into `main_app.state`.
   - Eliminates asyncio loop drift between FastAPI background tasks and test assertions.

---

## 3. Tiered Test Matrix

### Tier 1: Feature Contracts (REST API & UI)
- **TC-1.1**: `test_get_available_assets_success` — Verifies `GET /api/v1/collector/available-assets` returns symbols, names, payout rates, and OTC flags.
- **TC-1.2**: `test_get_collector_status_initial_idle` — Verifies `GET /api/v1/collector/status` starts in `IDLE` state with empty active asset list.
- **TC-1.3**: `test_post_collector_start_valid_assets` — Verifies `POST /api/v1/collector/start` transitions collector to `RUNNING` with configured assets.
- **TC-1.4**: `test_get_collector_status_with_database_candle_stats` — Verifies live status telemetry aggregates candle counts and timestamps from `MarketDataStore`.
- **TC-1.5**: `test_post_collector_stop_running_task` — Verifies `POST /api/v1/collector/stop` halts background loop and transitions state to `STOPPED`.
- **TC-1.6**: `test_ui_html_contains_collector_tab_navigation` & `test_ui_html_contains_collector_controls_and_containers` — Validates `#tabBtnCollector`, `#tabCollector`, `#collectorAssetsContainer`, Select All / Deselect All, and Start/Stop buttons in `index.html`.

### Tier 2: Boundary Values & Error Resilience
- **TC-2.1**: `test_post_collector_start_empty_assets_rejected` & `test_post_collector_start_invalid_parameter_bounds` — Rejects empty asset arrays and invalid numerical parameters with HTTP 422.
- **TC-2.2**: `test_post_collector_start_sanitization` — Sanitizes whitespace, trims strings, eliminates empty elements, and deduplicates asset arrays.
- **TC-2.3**: `test_post_collector_start_already_running_handling` — Handles concurrent start calls safely (HTTP 409 Conflict or idempotent RUNNING).
- **TC-2.4**: `test_post_collector_stop_idle_is_safe_noop` — Stopping an already idle/stopped collector is a safe, idempotent no-op.
- **TC-2.5–2.7**: `test_multi_asset_fault_isolation_resilience` — Gateway timeouts (`TimeoutError`), broker drops (`BrokerUnavailableError`), and parameter errors (`InvalidMarketParametersError`) on individual assets do not crash the loop or abort healthy assets.

### Tier 3: Concurrency & Lifecycle
- **TC-3.1**: `test_shared_gateway_concurrency_bot_and_collector` — Shared `PocketOptionTradingGateway` handles concurrent API/bot requests while collector runs; stopping collector does not close the shared gateway (`aclose` not invoked).
- **TC-3.2**: `test_concurrent_sqlite_wal_reads_and_writes` — Heavy concurrent background writers and reader tasks execute without `sqlite3.OperationalError: database is locked`.
- **TC-3.3**: `test_rapid_start_stop_cycling_stress` — 20 rapid start/stop cycles execute cleanly without orphan background tasks or memory leaks.

### Tier 4: End-to-End Application Flows
- **TC-4.1**: `test_collector_full_operator_lifecycle_e2e` — Full user lifecycle: Discover assets -> Select top 2 -> Start -> Execute cycles -> Verify monotonic candles in SQLite -> Check telemetry -> Stop -> Verify write immutability.
- **TC-4.2**: `test_ui_javascript_collector_api_bindings` — Validates JavaScript client functions (`loadCollectorAvailableAssets`, `startDataCollector`, `stopDataCollector`, `fetchCollectorStatus`) and endpoint paths.

---

## 4. Verification Commands

```bash
# 1. Run targeted Stage 3 Collector test suite
.venv/bin/pytest tests/test_collector_api.py tests/test_collector_concurrency.py tests/test_collector_ui.py tests/test_collector_e2e.py -v

# 2. Run full regression test suite (1233+ tests)
.venv/bin/pytest tests/ -v

# 3. Static analysis and code style verification
.venv/bin/ruff check tests/conftest.py tests/test_collector_*.py
.venv/bin/ruff format --check tests/conftest.py tests/test_collector_*.py
```
