# E2E Test Infra: Stage 3 S1 Data Collector & Web UI Management

## Test Philosophy
- Opaque-box, requirement-driven, and contract-verifying.
- Derived directly from `ORIGINAL_REQUEST.md`.
- Verifies both API layer, background execution mechanics, data store integrity, and UI markup/client bindings.
- Methodology: Category-Partition + Boundary Value Analysis + Pairwise Concurrency + Real-World Workload Testing.

## Feature Inventory & Test Mapping
| # | Feature | Source | Tier 1 (Feature) | Tier 2 (Boundary) | Tier 3 (Cross-Feature) | Tier 4 (E2E) |
|---|---------|--------|:----------------:|:-----------------:|:----------------------:|:------------:|
| 1 | Available Assets API | ORIGINAL_REQUEST §R1 | TC-1.1 | TC-2.1 | TC-3.1 | TC-4.1 |
| 2 | Collector Status API | ORIGINAL_REQUEST §R1 | TC-1.2, TC-1.4 | TC-2.4 | TC-3.2 | TC-4.1 |
| 3 | Start Collector API | ORIGINAL_REQUEST §R1 | TC-1.3 | TC-2.1, TC-2.2, TC-2.3 | TC-3.3 | TC-4.1 |
| 4 | Stop Collector API | ORIGINAL_REQUEST §R1 | TC-1.5 | TC-2.4 | TC-3.3, TC-3.4 | TC-4.1 |
| 5 | Shared Gateway & Background Loop | ORIGINAL_REQUEST §R3 | TC-1.3, TC-1.5 | TC-2.5, TC-2.6, TC-2.7 | TC-3.1, TC-3.4 | TC-4.1 |
| 6 | Web UI Dashboard & Controls | ORIGINAL_REQUEST §R2 | TC-1.6 | TC-2.2 | TC-3.1 | TC-4.2 |

## Test Architecture
- Test Runner: `pytest` with `pytest-asyncio` and `httpx.AsyncClient(transport=ASGITransport(app=app))`
- Centralized Fixtures: `tests/conftest.py`
  - `isolated_market_store`: Clean temporary SQLite database in WAL mode per test.
  - `mock_trading_gateway`: AsyncMock conforming to `TradingGateway` & `CandleFeed`.
  - `async_test_client`: Asynchronous ASGI HTTP client bound to FastAPI test instance.
- Test Layout:
  - `tests/test_collector_api.py`: Tiers 1 & 2 (REST API feature coverage, payload validation, status inspection).
  - `tests/test_collector_concurrency.py`: Tier 3 (Shared gateway concurrency, cancellation resilience, rapid cycling, lifespan shutdown).
  - `tests/test_collector_ui.py`: Tier 1 & 4 (HTML DOM layout, UI element IDs, JS client handler signatures).
  - `tests/test_collector_e2e.py`: Tier 4 (Complete lifecycle: fetch assets -> select -> start -> collect candles -> check stats -> stop -> verify db).

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Expected Outcome |
|---|----------|--------------------|------------------|
| 1 | Full Operator Lifecycle | Available assets -> Select Top 5 -> Start -> 2 Cycles -> Stop -> Verify DB | Accurate row counts in DB, valid timestamps, clean task shutdown |
| 2 | Live Bot & Collector Concurrency | Collector running while LiveDemoBot performs trade execution | Shared gateway handles both without lockups or WebSocket collisions |
| 3 | UI Contract & DOM Synchronization | HTML template rendering and JS function signatures | Complete DOM parity with API schema |

## Coverage Thresholds
- Tier 1: >= 6 feature contract test cases
- Tier 2: >= 7 boundary & error resilience test cases
- Tier 3: >= 4 concurrency & gateway lifecycle test cases
- Tier 4: >= 2 comprehensive E2E application scenarios
- Total Target: >= 19 test cases
