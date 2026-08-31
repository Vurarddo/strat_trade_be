## 2026-08-31T18:33:55Z
You are the E2E Test Writer for Stage 3 of Pocket Option AutoTrader Pro.
Your working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/e2e_test_writer
Original user request: /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md
Project plan: /Users/vlados/work/projects/startup/strat_trade_be/PROJECT.md
Test infrastructure design: /Users/vlados/work/projects/startup/strat_trade_be/TEST_INFRA.md
QA Survey handoff: /Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_survey_3/handoff.md

You have EXCLUSIVE write ownership of:
- `tests/conftest.py`
- `tests/test_collector_api.py`
- `tests/test_collector_concurrency.py`
- `tests/test_collector_ui.py`
- `tests/test_collector_e2e.py`
- `TEST_READY.md` (at project root)

Task:
1. Read ORIGINAL_REQUEST.md, PROJECT.md, and TEST_INFRA.md first.
2. Implement centralized test fixtures in `tests/conftest.py` providing `isolated_market_store`, `mock_trading_gateway`, `async_test_client` (using `httpx.AsyncClient(transport=ASGITransport(app=app))` to prevent asyncio drift), and realistic sample candle data. Ensure existing tests continue to pass!
3. Implement `tests/test_collector_api.py` covering Tier 1 & Tier 2:
   - `GET /api/v1/collector/available-assets` (success, returns symbol/name/payout/is_otc/asset_type)
   - `GET /api/v1/collector/status` (initial IDLE state, running state with stats)
   - `POST /api/v1/collector/start` (valid asset array, sanitization of whitespace/duplicates, empty asset rejection HTTP 422, already running handling)
   - `POST /api/v1/collector/stop` (stops running collector, safe no-op if idle)
4. Implement `tests/test_collector_concurrency.py` covering Tier 3:
   - Shared gateway concurrency: verify collector and other calls do not crash or close gateway
   - Rapid start/stop cycling stress test without orphan tasks or zombie connections
   - Exception resilience: gateway timeout, broker unavailable, and invalid market parameters do not crash the loop
   - FastAPI lifespan shutdown cancels and drains collector task cleanly
5. Implement `tests/test_collector_ui.py` covering Tier 1 & 4 DOM validation:
   - Fetch `GET /` and verify index.html contains `#tabBtnCollector`, `#tabCollector`, `#collectorAssetsContainer`, `#btnStartCollector`, `#btnStopCollector`, `#collectorStatsTable` / `#collectorTableBody`, Select All / Deselect All buttons, search input, and telemetry cards
   - Verify JavaScript function signatures exist for `loadCollectorAvailableAssets`, `startDataCollector`, `stopDataCollector`, `fetchCollectorStatus`, `selectAllCollectorAssets`, `deselectAllCollectorAssets`, etc.
6. Implement `tests/test_collector_e2e.py` covering Tier 4:
   - Complete end-to-end lifecycle flow: fetch assets -> select -> start collection -> simulate cycles with mock gateway -> verify candles in `MarketDataStore` -> verify status endpoint reflects exact counts -> stop collection -> verify no further writes.
7. Run the tests via pytest and write `TEST_READY.md` at `/Users/vlados/work/projects/startup/strat_trade_be/TEST_READY.md` when the test suite is created and ready.

Write your final report to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/e2e_test_writer/handoff.md`. Update progress.md with your liveness heartbeat. Once finished, send a message to parent.
