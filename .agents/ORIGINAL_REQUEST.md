# Original User Request

## 2026-08-31T18:29:45Z

This project implements Stage 3 of the quantitative improvements for Pocket Option AutoTrader Pro: building a Web UI and FastAPI backend endpoints to manage, start, and stop the S1 data collection process dynamically.

Working directory: `/Users/vlados/work/projects/startup/strat_trade_be`
Integrity mode: development

## Requirements

### R1. Backend API for Collector Management
Create or update endpoints in the FastAPI app (e.g., `src/strat_trade/web/routes/collector.py`) to manage the background data collection process.
- `GET /api/v1/collector/available-assets`: Fetches the live list of assets from the broker using `PocketOptionTradingGateway.get_assets()`.
- `GET /api/v1/collector/status`: Returns whether the collector is running, the list of currently tracked assets, and stats from `MarketDataStore.get_asset_stats()`.
- `POST /api/v1/collector/start`: Accepts a JSON list of assets (`{"assets": ["EURUSD_otc", ...]}`) and launches the collector loop as an `asyncio` background task within the FastAPI event loop.
- `POST /api/v1/collector/stop`: Gracefully cancels the running collector background task.

### R2. Frontend UI Dashboard
Update `src/strat_trade/web/templates/index.html` (and associated JS) to include a "Data Collection" management panel.
- The UI must dynamically load the available broker assets and render them as a list of checkboxes.
- It must include "Select All" and "Deselect All" functional buttons for the checkboxes.
- It must provide "Start Collection" and "Stop Collection" buttons connected to the API.
- It should display a status table showing currently collecting assets and their total saved candle counts, auto-refreshing periodically.

### R3. Thread-safe Background Execution
Refactor the collector logic so it can run cleanly inside FastAPI.
- It must share the global `PocketOptionTradingGateway` connection to avoid duplicate websocket connections.
- The `asyncio` loop must process the selected assets (handling broker limits by adding small sleeps between asset fetches) and respect `asyncio.CancelledError` for clean shutdown when the Stop endpoint is called.

## Acceptance Criteria

### API & Background Task
- [ ] `POST /api/v1/collector/start` successfully spawns the background task and begins populating the database.
- [ ] `POST /api/v1/collector/stop` successfully halts the task without crashing the FastAPI server or leaving zombie connections.

### Frontend
- [ ] The web UI displays all available assets with functional checkboxes and Select All / Deselect All logic.
- [ ] The UI accurately reflects the running state and live database counts for the selected assets.
- [ ] Playwright or Pytest integration tests verify the endpoints can start and stop the collector.
