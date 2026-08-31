# Stage 1 Quantitative Improvements — Reviewer 4 Audit & Handoff Report

## Executive Summary
In Round 4, adversarial review identified and resolved the root cause of intermittent test failures caused by `PreTradingPlan` default `bar_edge_guard_seconds=3.0` during wall-clock execution in mock unit tests. A comprehensive sweep was performed across all test files to ensure all unit tests testing asynchronous order dispatch and evaluation isolate edge guards cleanly (`bar_edge_guard_seconds=0.0`).

All 1,182 unit, integration, and adversarial stress tests in the repository pass with 100% success rate, and 0 ruff errors/warnings.

---

## 1. What Was Found & Fixed

### 1.1 Minute-Boundary Flake in `tests/test_phase4_sniper_rolling_15_verification.py`
- **Location:** `tests/test_phase4_sniper_rolling_15_verification.py:1060` (`test_sniper_e2e_live_demo_bot_engine_sniper_execution`) and line 685 (`test_sniper_anti_whipsaw_cooldown_guard`).
- **Input:** Test invoking `bot._execute_order` with `PreTradingPlan` using default `bar_edge_guard_seconds=3.0`.
- **Expected:** Order executes and increments `active_trades` to 1.
- **Actual:** During seconds `[0..2]` or `[58..59]` of any minute (when test suite executes for ~50s), `is_bar_edge_blocked` blocked the order, resulting in `len(bot.active_trades) == 0`.
- **Root Cause:** In mock bot tests without mocked timestamps, wall-clock time lands on bar edges and gets rejected by the bar-edge guard unless `bar_edge_guard_seconds=0.0`.
- **Fix:** Explicitly set `bar_edge_guard_seconds=0.0` in `PreTradingPlan` in both tests.

### 1.2 Comprehensive Sweep of All Test Suites for Bar-Edge Flakiness
Identified and sanitized all remaining `PreTradingPlan` instantiations across test suites:
- `tests/test_m4_empirical_challenger.py` (lines 419, 508)
- `tests/test_m4_empirical_challenger_2.py` (lines 366, 469)
- `tests/test_m2_adversarial_stress.py` (`_make_test_plan`, default `bar_edge_guard_seconds=0.0`)
- `tests/test_m2_challenger_2_empirical_verification.py` (`_make_plan`, default `bar_edge_guard_seconds=0.0`)
- `tests/test_m2_empirical_challenger_adversarial.py` (lines 342, 429)
- `tests/test_m2_m3_adversarial_empirical_challenge.py` (lines 372, 426, 495, 581, 727)
- `tests/test_m2_toxic_blacklist_fuzz.py` (line 429)
- `tests/test_phase3_rolling_15_trade_verification.py` (line 733)
- `tests/test_strategy_curation_and_asset_filter.py` (lines 461, 801)
- `tests/test_empirical_stress_challenger.py` (line 597)
- `tests/test_forensic_auditor_stress.py` (lines 122, 167)
- `tests/test_august_24_streak_elimination.py` (`_make_sniper_plan`)
- `tests/test_challenger_m3_streak_volatility_stress.py` (`_make_adversarial_plan`)
- `tests/test_adversarial_guardrails.py` (`_make_pre_trading_plan`)
- `tests/test_session_schedule_filter.py` (`_make_plan`)
- `tests/test_broker_truth_settlement.py` (`_plan` defaults)

---

## 2. Verification of Stage 1 Core Requirements

### Requirement 1: Time-Based Backtester Execution
- `BinaryBacktestEngine` calculates `target_exit_time = entry_time + pd.Timedelta(seconds=exp_seconds)`.
- Uses `df["timestamp"].searchsorted(target_exit_time, side="left")` with forward linear search fallback.
- Supports `expiration_seconds` directly and handles sub-minute/tick/nanosecond timestamps seamlessly.
- Tested and verified in `tests/test_stage1_time_based_backtest_and_auto_assign.py` and `tests/test_adversarial_stage1_reviewer_round*.py`.

### Requirement 2: Auto-Assign Logic Cleanup
- `StrategyAutoMatcher.find_optimal_strategy_for_asset` returns `None` when `is_toxic_asset` or `qualify_asset_microstructure` fails.
- `generate_pre_trading_plan` filters `raw_assignments` to discard `None` values, ensuring rejected assets do not appear in `PreTradingPlan`.

---

## 3. Test & Linter Execution Results

1. **Full Pytest Suite:**
   ```bash
   ./.venv/bin/pytest
   ```
   **Result:** `1182 passed, 2 warnings in 47.48s` (100% pass rate)

2. **Ruff Check:**
   ```bash
   ./.venv/bin/ruff check src tests
   ```
   **Result:** `All checks passed!` (0 errors)

3. **Ruff Format:**
   ```bash
   ./.venv/bin/ruff format --check src tests
   ```
   **Result:** `144 files already formatted` (0 formatting issues)