# Changes Summary — Requirement R2 (UI Expiration & Strategy Auto-Expiration)

**Agent**: M2 Worker 1  
**Date**: 2026-08-23  
**Status**: Implemented & Verified (840 tests passing, 0 lint errors)  

---

## 1. Files Modified

### A. `src/strat_trade/web/templates/index.html`
- **Removed `#botCfgExpiration` select dropdown**: Cleanly eliminated the manual expiration dropdown from the Live Demo Bot configuration dock.
- **Rebalanced dock layout**: Combined `botCfgStopLoss` and `botCfgMinPayout` into a clean, balanced 2-column responsive grid (`grid grid-cols-2 gap-3`).
- **Updated JavaScript payload builder**: Removed `expiration_seconds: parseInt(document.getElementById('botCfgExpiration').value)` from `prepareLiveBotLaunch()`, letting the backend use strategy-calibrated expiration defaults automatically.

### B. `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`
- **Updated `__init__`**: Changed default `base_expiration_bars` from `2` to `3` (180 seconds on M1 timeframe).
- **Updated `get_parameter_definitions()`**: Changed default value of `base_expiration_bars` parameter definition from `2` to `3`, and increased `max_value` to `5` (aligned with all other sniper strategies).

### C. `src/strat_trade/domain/trading/bot_engine.py`
- **Added `now` parameter propagation to `_execute_order`**: Propagated the evaluation simulation timestamp `now` to `_execute_order()` to ensure atomic cooldown checks operate consistently across time-mocked stress tests and live operations.

### D. `tests/test_strategy_curation_and_asset_filter.py`
- Added tests verifying:
  - `RsiStochasticExtremeStrategy` default `base_expiration_bars == 3` in instance and parameter definitions.
  - `AutoAssignRequest` automatic defaulting of `expiration_seconds = 180` when omitted from client payload.
  - `generate_pre_trading_plan` auto-assignment of 180s (3 bars) strategy parameters across assets.

### E. `tests/test_bot_and_audit_api.py`
- Added `test_bot_auto_assign_without_expiration_payload()` verifying the `/api/v1/bot/auto-assign` REST API endpoint successfully handles payloads without `expiration_seconds` and returns strategy-calibrated 180s / 3-bar plans.

---

## 2. Verification Summary
- **Unit & Integration Tests**: `.venv/bin/pytest` -> 840 passed, 0 failures.
- **Linter & Style**: `.venv/bin/ruff check src tests` -> All checks passed (0 errors).
