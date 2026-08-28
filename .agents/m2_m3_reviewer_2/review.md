# M2 & M3 Integration Quality & Adversarial Review Report

**Reviewer**: M2/M3 Reviewer 2 (Roles: Reviewer, Critic)  
**Date**: 2026-08-23  
**Working Directory**: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_m3_reviewer_2`  
**Parent Orchestrator**: `965d505d-f351-4731-b173-775c7711e297`  
**Verdict**: **APPROVE**

---

## 1. Review Summary

**Verdict**: **APPROVE**

This review conducted an exhaustive, independent quality and adversarial evaluation of the Milestone 2 (UI Expiration Simplification & Strategy Auto-Expiration) and Milestone 3 (Dynamic Microstructure Noise Filtering & Anti-Whipsaw Settlement Cooldown) deliverables across the backend trading engine, API layers, domain strategy catalog, and web frontend UI.

All 840 automated tests passed without failure (`840 passed, 2 warnings in 24.56s`), and the static analysis linter completed with zero errors (`.venv/bin/ruff check src tests` -> `All checks passed!`).

Implementation integrity was strictly verified: all statistical filters, lock synchronizations, strategy parameters, and frontend markup changes represent authentic, high-quality production code without shortcuts, facades, or hardcoded mock fixtures.

---

## 2. Scope & Requirement Fulfillment

### Milestone 2: UI Expiration Simplification & Strategy Auto-Expiration (Requirement R2)
1. **Frontend Control Dock Cleanliness**:
   - The manual `<select id="botCfgExpiration">` dropdown was completely removed from `src/strat_trade/web/templates/index.html`. Global grep across template files confirmed 0 occurrences.
   - The layout of the Live Bot configuration dock was re-balanced into an elegant, clean two-column grid pairing `botCfgStopLoss` with `botCfgMinPayout`.
   - The JavaScript function `prepareLiveBotLaunch()` cleanly omitted `expiration_seconds` from its POST payload to `/api/v1/bot/auto-assign`.
2. **Strategy Parameter Standardization & Backend Defaults**:
   - `RsiStochasticExtremeStrategy` in `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py` was updated to default `base_expiration_bars = 3` (180 seconds on M1) in `__init__` and in `ParameterDef`.
   - All sniper strategies (`SupportResistanceBounceStrategy`, `RsiStochasticExtremeStrategy`, `EmaPullbackTrendStrategy`) now uniformly default to 3-bar (180s) expiration duration.
   - `AutoAssignRequest` schema defaults `expiration_seconds` to `180`, ensuring seamless fallback for automated execution.

### Milestone 3: Dynamic Microstructure Filtering & Anti-Whipsaw Cooldown (Requirement R3)
1. **Dynamic Microstructure Qualification (`qualify_asset_microstructure`)**:
   - Implemented in `src/strat_trade/domain/trading/asset_filter.py` with rigorous mathematical metrics:
     - Requires $\ge 50$ candles.
     - `flat_bar_ratio`: rejects if $> 0.15$ (15%).
     - `unique_price_ratio`: rejects if $< 0.30$ (30%).
     - `whipsaw_sign_flip_ratio`: rejects if $> 0.80$ (80%).
     - `relative_atr`: $ATR(14) / Close$, rejects if $< 0.00003$.
   - Handles edge cases (empty data, `< 50` bars, NaNs, non-numeric values, non-positive prices) deterministically.
   - Integrated into `filter_allowed_assets()` and `StrategyAutoMatcher.find_optimal_strategy_for_asset()`.
2. **Anti-Whipsaw Settlement Cooldown**:
   - In `src/strat_trade/domain/trading/bot_engine.py`, trade settlement enforces a hard floor: `cooldown_sec = max(180, cooldown_bars * 60)`, guaranteeing a minimum 3-minute cooldown per asset upon trade close.
   - Atomic synchronization: `_execute_order` re-checks `cooldown_until` inside `async with self._order_lock:`, eliminating race conditions between concurrent worker tasks.

---

## 3. Verified Claims

| # | Claim | Verification Method | Result | Evidence / Details |
|---|-------|---------------------|--------|-------------------|
| 1 | All unit and integration tests pass | `.venv/bin/pytest` | **PASS** | 840 passed, 2 warnings in 24.56s |
| 2 | Codebase conforms to linting rules | `.venv/bin/ruff check src tests` | **PASS** | All checks passed (0 errors, line length <= 100) |
| 3 | `#botCfgExpiration` removed from UI | `grep_search` across `src/strat_trade/web/templates/` | **PASS** | 0 matches found in templates |
| 4 | JS payload omits manual expiration | Code inspection of `index.html` `prepareLiveBotLaunch()` | **PASS** | Payload sends deposit, stake, stop-loss, min payout; omits expiration |
| 5 | `rsi_stochastic_extreme.py` defaults to 3 bars | `view_file` lines 27 & 151 | **PASS** | `base_expiration_bars: int = 3` in `__init__` and `ParameterDef` |
| 6 | Microstructure filter rejects flat/discrete/whipsaw feeds | `pytest tests/test_strategy_curation_and_asset_filter.py` | **PASS** | Flat ratio > 15%, unique price < 30%, whipsaw > 80%, low ATR rejected |
| 7 | Liquid Forex/OTC pairs pass microstructure | `pytest` test `test_qualify_asset_microstructure_continuous_liquid_assets` | **PASS** | EURUSD, GBPUSD, USDJPY, AUDUSD, USDCLP, USDBDT, USDEGP, Gold pass |
| 8 | Engine enforces min 3-min cooldown post settlement | `pytest` test `test_bot_engine_anti_whipsaw_3min_cooldown_and_atomic_check` | **PASS** | Settlement sets cooldown >= 180s even when cooldown_bars=1 |
| 9 | Engine prevents race conditions during cooldown | Code inspection of `_execute_order` lock guard | **PASS** | Checked atomically inside `async with self._order_lock:` |

---

## 4. Adversarial Challenge & Stress Analysis

### 1. Assumption Stress-Testing: Microstructure Filtering
- **Stress Scenario**: A synthetic feed with non-positive close prices or NaN anomalies.
- **Result**: `qualify_asset_microstructure` sanitizes input with `pd.to_numeric(errors="coerce")`, checks `df.isna().any().any()`, and asserts `(df["close"] <= 0).any()`, returning informative rejection diagnostics rather than crashing.
- **Stress Scenario**: Very short candle history (< 50 bars).
- **Result**: Gracefully returns `(False, "Insufficient candle history (N < 50 bars required)")` and allows `StrategyAutoMatcher` to fall back to curated heuristic profiles.

### 2. Concurrency & Re-Entry Race Conditions
- **Attack Scenario**: Multiple async coroutines trigger simultaneous signals for the same asset immediately upon trade settlement.
- **Defense Assessment**:
  1. Primary barrier: `_evaluate_single_asset` checks `self._asset_cooldown_until` before acquiring semaphore.
  2. Secondary barrier: `_execute_order` acquires `self._order_lock` and checks `now < self._asset_cooldown_until.get(asset)`. If valid, the second order is immediately dropped without contacting the broker gateway.

### 3. Strategy Parameter Consistency
- **Check**: Are there strategies with mismatched expiration bars in the active Sniper pool?
- **Finding**: All three priority strategies (`SupportResistanceBounceStrategy`, `RsiStochasticExtremeStrategy`, `EmaPullbackTrendStrategy`) default to `base_expiration_bars = 3` (180s on M1). Single Strategy Backtesting and Portfolio Backtesting panels retain configurable inputs for research purposes while the Live Bot dock uses optimal automated defaults.

---

## 5. Integrity Assessment

- **Hardcoded test results embedded in source code**: **None found**. Calculations use live candle series, rolling indicators, and dynamic price arrays.
- **Dummy or facade implementations**: **None found**. Microstructure evaluation computes actual statistical measures (sample mean of flat bars, unique value cardinality, consecutive return sign products, rolling ATR).
- **Shortcuts bypassing core logic**: **None found**. Cooldowns, locks, and strategy definitions are fully wired into live execution paths.
- **Fabricated verification outputs**: **None found**. Pytest and ruff commands were executed directly in the project virtual environment.

---

## 6. Coverage Gaps & Minor Observations

- **Minor Observation**: In `auto_matcher.py` (lines 420-429), when candle history is $\ge 50$ bars and microstructure qualification fails, `find_optimal_strategy_for_asset` assigns a penalty quantum score (`15.0`) and rationale tag `[MICROSTRUCTURE REJECTED]`. In live demo bot execution, `filter_allowed_assets()` already filters out unqualifying assets if candle data is supplied. This provides multi-layer defense.
- **No blocking issues or regressions identified.**

---

## 7. Final Verdict

**VERDICT**: **APPROVE**  
Milestones M2 and M3 satisfy all functional, architectural, quantitative, and safety requirements specified in `ORIGINAL_REQUEST.md` and `PROJECT.md`. The codebase is ready for Milestone 4 (Rolling 15-Trade Verification & 600+ Trades backtest execution).
