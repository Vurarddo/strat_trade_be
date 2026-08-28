# Milestone 1 Quality & Adversarial Review Report

## Review Summary

**Target Milestone**: M1 — Strategy Portfolio Restructuring (Sniper Edge)  
**Reviewed Artifacts**:
- `src/strat_trade/domain/optimizer/auto_matcher.py`
- `src/strat_trade/domain/strategies/registry.py`
- Relevant test suites (`tests/test_strategy_auto_matcher.py`, `tests/test_strategy_curation_and_asset_filter.py`, `tests/test_phase3_rolling_15_trade_verification.py`, `tests/test_m1_adversarial_challenge.py`, `tests/test_m1_adversarial_empirical_stress.py`)

**Verdict**: **APPROVE**

---

## 1. Quality & Conformance Findings

### [Minor] Finding 1: `BacktestConfig` Float vs Decimal Typing in `auto_matcher.py`
- **What**: In `auto_matcher.py` (lines 438, 440, 441, 442), `BacktestConfig` constructor is passed `float` values for `initial_deposit=1000.0`, `stake_amount=10.0`, `payout_rate=payout_rate`, and `min_payout_rate=0.80`, whereas `BacktestConfig` dataclass fields are annotated as `Decimal`.
- **Where**: `src/strat_trade/domain/optimizer/auto_matcher.py:438-442`
- **Why**: While Python standard dataclasses accept floats at runtime without raising an exception during object instantiation, static type checkers (`mypy`) flag these as type incompatibilities.
- **Suggestion**: In future cleanup, wrap values with `Decimal(str(...))` for strict static typing compliance.

---

## 2. Integrity Violation Assessment (Adversarial Check)

| Integrity Dimension | Status | Evidence / Observation |
|---|---|---|
| Hardcoded Test Results | **CLEAN** | No hardcoded win rates, spoofed return values, or bypassed calculations in `auto_matcher.py` or `registry.py`. |
| Dummy / Facade Implementations | **CLEAN** | `StrategyAutoMatcher` executes genuine `BinaryBacktestEngine` simulations across strategy variations on input candle data. |
| Task Bypassing / Shortcuts | **CLEAN** | Core Sniper alpha allocation (`support_resistance_bounce`, `rsi_stochastic_extreme`, `ema_pullback_trend`) is systematically implemented in priority sets, heuristic profilers, candidate selectors, and registry factories. |
| Fabricated Verifications / Logs | **CLEAN** | Full pytest suite was executed live, verifying all 662 tests pass independently. |

---

## 3. Verified Claims

1. **Deactivation of Failing Strategies from Priority Allocation**:
   - Verified `PRIORITY_STRATEGIES = frozenset({"support_resistance_bounce", "rsi_stochastic_extreme", "ema_pullback_trend"})` in `src/strat_trade/domain/optimizer/auto_matcher.py:17-23`.
   - Legacy strategies (`hybrid_multifactors`, `macd_divergence_break`, `supertrend_adx_momentum`) are excluded from priority sets.
2. **Heuristic Asset Routing**:
   - Verified `_heuristic_profile_for_asset()` in `src/strat_trade/domain/optimizer/auto_matcher.py:228-376`:
     - Gold/XAU -> `support_resistance_bounce`
     - Equities/Stocks -> `ema_pullback_trend`
     - Crypto -> `rsi_stochastic_extreme`
     - Forex JPY/GBP -> `support_resistance_bounce`
     - Other Forex -> `rsi_stochastic_extreme`
     - Unclassified Fallback -> Primary `support_resistance_bounce`, Secondary `rsi_stochastic_extreme`, Tertiary `strategies[0]`.
3. **Candidate Strategy Evaluation**:
   - Verified `candidate_strategies = [s for s in strategies if s["id"] in PRIORITY_STRATEGIES]` in `auto_matcher.py:422-425`.
4. **Registry Fallback Robustness**:
   - Verified `get_strategy_instance()` in `src/strat_trade/domain/strategies/registry.py:163-191` normalizes names (`.strip().lower()`), falls back gracefully to `support_resistance_bounce` for unknown/empty/whitespace inputs, and safely filters parameters via `inspect.signature` to prevent `TypeError`.
   - Verified `list_available_strategies()` preserves all 8 strategy catalog definitions for API backward compatibility.
5. **Automated Verification**:
   - `.venv/bin/pytest`: 662 passed, 0 failed (23.35s).
   - `.venv/bin/ruff check src tests`: 0 errors.

---

## 4. Adversarial Attack Surface & Stress-Test Results

| Challenge / Stress Test | Scenario / Input | Expected Behavior | Actual Behavior | Result |
|---|---|---|---|---|
| Fuzz / Malformed Strategy Names | `get_strategy_instance("!@#$ non_existent")` | Fallback to `SupportResistanceBounceStrategy` without crash | Returns `SupportResistanceBounceStrategy` instance | **PASS** |
| Unexpected Parameters | `get_strategy_instance("rsi_stochastic_extreme", bogus_arg=999)` | Filter unknown kwargs via signature inspection | Safely instantiates without `TypeError` | **PASS** |
| Empty / Short Candle History | `find_optimal_strategy_for_asset("ASSET", [])` or `< 35` candles | Route to heuristic profile fallback | Returns valid `StrategyAssignment` | **PASS** |
| Toxic Blacklisted Assets | `find_optimal_strategy_for_asset("USD/IDR OTC", candles)` | Identify toxic asset, assign low quantum score (10.0) | Returns toxic flagged assignment | **PASS** |
| Zero Trades Backtest Output | Asset with zero trades generated across all variations | Fallback to heuristic assignment | Returns heuristic `StrategyAssignment` | **PASS** |
| Restricted Strategy Pool | Catalog missing `support_resistance_bounce` | Fallback to `rsi_stochastic_extreme`, then `strategies[0]` | Follows exact 3-tier fallback hierarchy | **PASS** |

---

## 5. Coverage & Dependency Assessment

- **Call Sites Explored**:
  - `generate_pre_trading_plan` in `src/strat_trade/use_cases/auto_assign_strategies.py` (M1 compatible)
  - `LiveDemoBotEngine` in `src/strat_trade/domain/trading/bot_engine.py` (M1 compatible)
  - Full test suite across unit, adversarial, and regression layers (all 662 tests pass)
- **Coverage Gaps**: None. All dependencies and invocation pathways in M1 scope are validated.

---

## 6. Final Recommendation

**APPROVE**. Milestone 1 implementation is sound, robust against edge cases, and satisfies all requirements specified in `ORIGINAL_REQUEST.md` and `PROJECT.md`.
