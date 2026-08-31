# Project: strat_trade_be (Stage 3: S1 Data Collector & Web UI Management)

## Architecture
Stage 3 of Pocket Option AutoTrader Pro introduces dynamic, asynchronous S1 market data collection managed via FastAPI REST endpoints and a Web UI management dashboard.

Core Architecture Components:
- **Async Collector Engine (`src/strat_trade/use_cases/manage_collector.py`)**: Singleton async service managing the background collection loop, running as a managed `asyncio.Task` inside the FastAPI event loop. Shares the single application-level `PocketOptionTradingGateway` instance from FastAPI lifespan without creating duplicate WebSocket connections. Provides graceful start/stop with `asyncio.CancelledError` handling and per-asset transient error isolation.
- **Market Data Store (`src/strat_trade/domain/trading/market_data_store.py`)**: Local SQLite database in WAL mode (`data/market_data.db`) storing 1-second candles with indexed `candles_s1(asset, timestamp)`, duplicate suppression via `INSERT OR IGNORE`, and real-time statistics queries via `get_asset_stats()`.
- **Collector REST API (`src/strat_trade/api/routes/collector.py` & `src/strat_trade/web/routes/collector.py`)**: Endpoints for available broker assets, collector state & database statistics, start collection with custom parameters, and stop collection.
- **Web UI Management Dashboard (`src/strat_trade/web/templates/index.html`)**: Interactive panel with dynamic asset loading, checkbox matrix with Select All / Deselect All / category quick filters, real-time search, Start/Stop buttons, telemetry cards, and auto-refreshing live status table.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Collector Engine Core | Async background task with start/stop lifecycle, cancellation handling, and shared gateway | M1 | ORIGINAL_REQUEST §R1, §R3 |
| 2 | Available Assets API | `GET /api/v1/collector/available-assets` returning live broker assets or fallback list | M1 | ORIGINAL_REQUEST §R1 |
| 3 | Collector Status API | `GET /api/v1/collector/status` returning running state, tracked assets, and DB stats | M1 | ORIGINAL_REQUEST §R1 |
| 4 | Start Collector API | `POST /api/v1/collector/start` accepting asset list and launching background task | M1 | ORIGINAL_REQUEST §R1 |
| 5 | Stop Collector API | `POST /api/v1/collector/stop` gracefully halting background task | M1 | ORIGINAL_REQUEST §R1 |
| 6 | Lifespan Integration | Clean collector shutdown on FastAPI server teardown | M1 | ORIGINAL_REQUEST §R3 |
| 7 | Data Collection UI Tab | Navigation tab and header badge in Web SPA | M2 | ORIGINAL_REQUEST §R2 |
| 8 | Asset Checkbox Matrix | Dynamic asset loading, multi-select checkboxes, and count badge | M2 | ORIGINAL_REQUEST §R2 |
| 9 | Selection Controls | "Select All", "Deselect All", and quick filter buttons | M2 | ORIGINAL_REQUEST §R2 |
| 10 | Start/Stop UI Controls | Responsive Start Collection and Stop Collection buttons with loading state | M2 | ORIGINAL_REQUEST §R2 |
| 11 | Telemetry & Live Status Table | Metric cards and auto-refreshing table with candle counts and timestamps | M2 | ORIGINAL_REQUEST §R2 |
| 12 | Comprehensive E2E Testing | Tier 1-4 automated tests (FastAPI integration, DOM verification, concurrency, lifecycle) | M3 / E2E | ORIGINAL_REQUEST §Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Track | Requirement-driven test suite (Tiers 1-4: API contracts, boundary cases, concurrency, UI DOM) -> publishes TEST_READY.md | none | DONE |
| 1 | M1: Backend API & Collector Engine | `AsyncCollectorEngine`, FastAPI routes (`/available-assets`, `/status`, `/start`, `/stop`), schemas, lifespan integration | none | DONE |
| 2 | M2: Web UI Dashboard & Telemetry | Update `index.html` with Data Collection panel, checkbox matrix, Select/Deselect All, Start/Stop buttons, auto-refreshing table | M1 | DONE |
| 3 | M3: Final Milestone (100% E2E Pass & Audit) | Pass 100% of E2E test suite, adversarial hardening, and Forensic Integrity Audit verification | M1, M2, E2E | DONE |

## Interface Contracts
### Collector API ↔ Frontend / Client
- `GET /api/v1/collector/available-assets`
  - Response: `list[CollectorAssetResponse]` (`symbol: str`, `name: str`, `payout: int`, `is_otc: bool`, `asset_type: str`)
- `GET /api/v1/collector/status`
  - Response: `CollectorStatusResponse` (`status: Literal["IDLE", "RUNNING", "STOPPED"]`, `is_running: bool`, `started_at: datetime | None`, `active_assets: list[str]`, `timeframe_seconds: int`, `candles_count: int`, `interval_seconds: float`, `throttle_delay: float`, `cycles_completed: int`, `total_candles_saved: int`, `last_cycle_at: datetime | None`, `asset_stats: list[CollectorAssetStatResponse]`, `total_database_candles: int`)
- `POST /api/v1/collector/start`
  - Request: `StartCollectorRequest` (`assets: list[str]`, `timeframe_seconds: int = 1`, `candles_count: int = 300`, `interval_seconds: float = 60.0`, `throttle_delay: float = 0.5`)
  - Response: `CollectorStatusResponse` (HTTP 200)
- `POST /api/v1/collector/stop`
  - Response: `CollectorStatusResponse` (HTTP 200)

### AsyncCollectorEngine ↔ Gateway & Store
- Method: `start(gateway: TradingGateway, assets: Sequence[str], timeframe: int = 1, count: int = 300, interval: float = 60.0, throttle: float = 0.5) -> CollectorStatusResponse`
- Method: `stop() -> CollectorStatusResponse`
- Method: `get_status() -> CollectorStatusResponse`
- Concurrency: Internal `asyncio.Lock()` serializing state transitions; background `asyncio.Task` consuming shared `TradingGatewayDep`.

## Code Layout
- `src/strat_trade/use_cases/manage_collector.py`: Asynchronous collector service engine.
- `src/strat_trade/api/routes/collector.py`: FastAPI route handlers and Pydantic schemas.
- `src/strat_trade/web/routes/collector.py`: Web routing re-export / proxy.
- `src/strat_trade/main.py`: Lifespan registration and router inclusion.
- `src/strat_trade/web/templates/index.html`: Web UI dashboard template with S1 collection panel.
- `tests/conftest.py`: Centralized test fixtures (`mock_trading_gateway`, `isolated_market_store`, `async_test_client`).
- `tests/test_collector_api.py`: REST endpoint contracts and boundary tests.
- `tests/test_collector_concurrency.py`: Background task concurrency, cancellation, and shared gateway tests.
- `tests/test_collector_ui.py`: HTML DOM and JavaScript client contract verification tests.
- `tests/test_collector_e2e.py`: End-to-end start/collect/status/stop integration tests.
- `tests/test_stage3_challenger_1_backend_stress.py`: Backend concurrency & SQLite WAL stress test suite.
- `tests/test_stage3_challenger_2_ui_contract_stress.py`: Web UI contract & DOM state machine stress test suite.
