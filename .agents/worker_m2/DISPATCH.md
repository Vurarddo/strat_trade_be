## 2026-08-24T13:57:17Z
You are Worker 2 for Milestone 2 of strat_trade_be.
Your working directory: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/worker_m2`.
Project root: `/Users/vlados/work/projects/startup/strat_trade_be`.
Original request file: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md`.
Project file: `/Users/vlados/work/projects/startup/strat_trade_be/PROJECT.md`.
Explorer Survey Reports: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_survey_2/handoff.md`.

Skill files to reference:
- `/Users/vlados/work/projects/startup/strat_trade_be/.agents/skills/risk-manager/SKILL.md`
- `/Users/vlados/work/projects/startup/strat_trade_be/.agents/skills/trading-systems-developer/SKILL.md`

Your Mission for Milestone 2:
1. Implement & Verify Risk Governance in `src/strat_trade/domain/trading/bot_engine.py` and `portfolio_engine.py`:
   - Consecutive-loss circuit breaker (15-min / 900s global pause after 3 consecutive losses across all assets).
   - Atomic streak tracking on `LiveDemoBotEngine`: `consecutive_losses`, `paused_until`, `status = BotStatus.PAUSED`.
   - Reset on any `TradeOutcome.WIN`, on auto-resume when `now >= paused_until`, and on manual `resume()`.
   - Anti-whipsaw cooldown: verify $\ge 180s$ (3 min) post-settlement per-asset cooldown (`_asset_cooldown_until`).
   - Microstructure noise filter: verify `qualify_asset_microstructure` integration in `asset_filter.py`.
2. Enhance UI Telemetry in `src/strat_trade/web/templates/index.html`:
   - In `renderLiveBotStatus(data)`:
     - Add explicit branch for `data.status === 'PAUSED'` / `data.is_paused`:
     - Render an amber/yellow warning badge: `PAUSED (COOLDOWN)` with pulse effect.
     - Render countdown timer calculating remaining seconds from `data.paused_until` (e.g., "Захисна пауза (3 збитки поспіль): MM:SS").
     - Show consecutive loss indicator.
3. Create comprehensive automated tests in `tests/test_risk_governance_circuit_breaker.py`:
   - Test 3 consecutive losses trigger 15-minute global pause across multiple assets.
   - Test that no trades are opened during the active pause window.
   - Test auto-resume when time advances past `paused_until` and consecutive_losses resets to 0.
   - Test WIN resets consecutive_losses to 0.
   - Test per-asset anti-whipsaw cooldown ($\ge 180s$) blocks immediate re-entry on the same asset.
   - Test `GET /api/v1/bot/status` serialization of `consecutive_losses`, `paused_until`, `is_paused`.
4. Run verification commands:
   - `.venv/bin/pytest tests/test_risk_governance_circuit_breaker.py -v`
   - `.venv/bin/pytest`
   - `.venv/bin/ruff check src tests`
5. Write your complete completion report to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/worker_m2/handoff.md`.
6. Send a message to parent upon completion.
