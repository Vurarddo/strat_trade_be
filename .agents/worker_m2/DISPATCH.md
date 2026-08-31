## 2026-08-31T18:33:55Z
Task:
1. Read ORIGINAL_REQUEST.md, PROJECT.md, and Explorer Survey 2 handoff (`.agents/explorer_survey_2/handoff.md`) first.
2. Update `src/strat_trade/web/templates/index.html`:
   - Add tab button `#tabBtnCollector` with icon and status badge in navigation header.
   - Add tab container `#tabCollector` with:
     - Live status header ribbon (pulsing status indicator, RUNNING/IDLE badge, title/subtitle, manual refresh button, Start Collection button, Stop Collection button).
     - Telemetry ribbon (Total candles in DB, active collecting assets count, cycles completed, last cycle time & uptime).
     - Left column: Asset selector dock with `#collectorAssetsContainer`, `#collectorAssetSelectedBadge`, "Select All", "Deselect All", quick filters ("Top-5 Payout", "All OTC", "Forex"), search input with clear button, and collapsible advanced parameters (timeframe, count, interval, throttle).
     - Right column: Auto-refreshing status table (`#collectorTableBody`) with refresh interval dropdown (3s, 5s, 10s, off), displaying Asset, Type (OTC/Spot), Status (Collecting/Idle), Total Candles Saved, First Candle UTC, Last Candle UTC.
   - Update JavaScript logic:
     - Update `switchTab(tabId)` to support `'collector'`.
     - Implement `loadCollectorAvailableAssets()`, `renderCollectorAssetCheckboxes()`, `updateCollectorSelectedCount()`.
     - Implement `selectAllCollectorAssets()`, `deselectAllCollectorAssets()`, `selectCollectorTopNAssets()`, `selectCollectorOtcAssets()`, `selectCollectorForexAssets()`, `filterCollectorAssetsList()`, `clearCollectorAssetSearch()`.
     - Implement `startDataCollector()`, `stopDataCollector()`, `fetchCollectorStatus()`, `renderCollectorStatus()`, `startCollectorPolling()`, `updateCollectorRefreshTimer()`.
3. Verify HTML structure, Tailwind styling, and Lucide icons.
4. Run `ruff check` and any relevant tests.
