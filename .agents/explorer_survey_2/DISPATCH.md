## 2026-08-31T18:30:37Z
You are Explorer Survey 2 (Web API & UI Specialist) for Stage 3 of Pocket Option AutoTrader Pro.
Your working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_survey_2
Original user request: /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md

Task:
Read /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md first.
Thoroughly explore the codebase regarding:
1. FastAPI app structure in `src/strat_trade/web/`: app factory, router registrations, existing endpoints (e.g. trading, backtesting, bot status), dependencies, shared state/lifespan context.
2. Web UI and templates: `src/strat_trade/web/templates/index.html` and any static JS/CSS files. How current UI components (bot controls, telemetry cards, chart, tables) are styled and structured (Bootstrap, Tailwind, vanilla CSS/JS, Jinja2 template layout).
3. Frontend requirements for Data Collection panel:
   - Dynamic asset loading from `GET /api/v1/collector/available-assets`
   - Checkbox list with "Select All" / "Deselect All"
   - "Start Collection" and "Stop Collection" buttons
   - Auto-refreshing status table (refresh intervals, polling mechanism, columns: Asset, Status, Total Candles Saved, Last Updated, etc.)
4. Design for `src/strat_trade/web/routes/collector.py`: Request/response schemas (Pydantic models), route signatures, error responses, dependency injection.

Write a comprehensive report to /Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_survey_2/handoff.md with exact UI integration points, template markup structure, JS functions, API schemas, and recommendations for R1 and R2. Update progress.md with your liveness heartbeat. Once finished, send a message to parent.
