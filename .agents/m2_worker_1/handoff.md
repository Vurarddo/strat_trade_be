# Handoff Report — Requirement R2: UI Expiration Simplification & Strategy Auto-Expiration

**Agent**: M2 Worker 1  
**Working Directory**: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_worker_1`  
**Parent Orchestrator**: `965d505d-f351-4731-b173-775c7711e297`  
**Date**: 2026-08-23  
**Status**: Complete — Hard Handoff  

---

## 1. Observation

1. **Frontend Dock UI (`src/strat_trade/web/templates/index.html`)**:
   - The Live Bot configuration dock previously exposed a manual `<select id="botCfgExpiration">` (lines 228–234) allowing users to select 60s, 180s, or 300s.
   - The JavaScript function `prepareLiveBotLaunch()` explicitly parsed `expiration_seconds: parseInt(document.getElementById('botCfgExpiration').value)` and transmitted it in POST `/api/v1/bot/auto-assign`.
2. **Strategy Expiration Calibration (`src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`)**:
   - In `RsiStochasticExtremeStrategy`, `base_expiration_bars` defaulted to `2` (120s) instead of the calibrated `3` (180s) optimal sniper exhaustion window.
   - All other sniper strategies (`SupportResistanceBounceStrategy`, `EmaPullbackTrendStrategy`, `BollingerAtrReversionStrategy`, `SuperTrendAdxMomentumStrategy`) already defaulted to `base_expiration_bars = 3` (180s on M1).
3. **Backend Defaults (`src/strat_trade/api/schemas.py`)**:
   - `AutoAssignRequest` already defines `expiration_seconds: int = Field(180, ge=5, le=86400)`. When omitted by the frontend client, it defaults to 180s (3 bars on M1).
4. **Test Suite Verification**:
   - Executing `.venv/bin/pytest` yielded `840 passed, 2 warnings in 22.65s`.
   - Executing `.venv/bin/ruff check src tests` yielded `All checks passed!`.

---

## 2. Logic Chain

1. **UI Simplification**:
   - Removing `#botCfgExpiration` prevents user error and ensures all trades use mathematically optimal expiration windows determined by strategy calibration.
   - Combining `botCfgStopLoss` with `botCfgMinPayout` maintains a balanced two-column glassmorphism layout without empty visual voids.
2. **Payload Decoupling**:
   - Removing `expiration_seconds` from `prepareLiveBotLaunch()` in `index.html` allows `AutoAssignRequest` to default to `180` seconds and strategy definitions to govern expiration bars directly.
3. **Strategy Alignment**:
   - Updating `base_expiration_bars` in `rsi_stochastic_extreme.py` to `3` in `__init__` and in `ParameterDef` ensures uniform 180s expiration across the core strategy catalog.
4. **Execution Coherence**:
   - Ensuring `_execute_order` receives the simulated `now` timestamp preserves atomic cooldown integrity across real-time execution and historical/unit tests.

---

## 3. Caveats

- **Backtest UI Panels**: The manual expiration inputs in the Portfolio Backtesting (`#pCfgExpBars`) and Single Strategy Backtesting (`#cfgExpBars`) panels were preserved intentionally, as backtesting requires exploratory parameter tuning across different bar horizons. Only the Live Bot configuration dock was simplified as specified in Requirement R2.
- **No further caveats.**

---

## 4. Conclusion

Requirement R2 is completely implemented and verified:
- `#botCfgExpiration` select dropdown element was removed cleanly from `src/strat_trade/web/templates/index.html`.
- `expiration_seconds` property was removed from `prepareLiveBotLaunch()` in `index.html`.
- `RsiStochasticExtremeStrategy` was calibrated to default `base_expiration_bars = 3` (180s).
- Comprehensive tests added in `tests/test_strategy_curation_and_asset_filter.py` and `tests/test_bot_and_audit_api.py`.
- 100% test pass rate (840 tests passing) and 0 lint/ruff errors.

---

## 5. Verification Method

To independently verify this implementation:
```bash
# 1. Run all unit and integration tests
.venv/bin/pytest -v

# 2. Run specific R2 expiration & auto-assign test suite
.venv/bin/pytest tests/test_strategy_curation_and_asset_filter.py tests/test_bot_and_audit_api.py -k "expiration or auto_assign" -v

# 3. Verify static analysis and formatting
.venv/bin/ruff check src tests

# 4. Verify no remaining references to botCfgExpiration in templates
grep -rn "botCfgExpiration" src/strat_trade/web/templates/
# (Expected output: empty / 0 matches)
```
