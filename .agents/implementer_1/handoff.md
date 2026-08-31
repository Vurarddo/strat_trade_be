> [!WARNING] **Skepticism Disclaimer**
> High confidence in the core logic refactoring since all 1,149 pytest test suites passed with 0 failures and 0 ruff errors; however, live broker trade execution and WebSocket timestamp jitter remain unverified in a real live network session.

## 1. What I changed
- **`src/strat_trade/domain/backtest/models.py`**:
  - Added optional `expiration_seconds: int | None = None` to `BacktestConfig` dataclass.
- **`src/strat_trade/domain/backtest/engine.py` (`BinaryBacktestEngine`)**:
  - Derived `target_exit_time = entry_time + pd.Timedelta(seconds=exp_seconds)`.
  - Implemented forward search in the dataframe using `df["timestamp"].searchsorted(target_exit_time, side="left")` with forward sequential fallback to locate the exact first row with `timestamp >= target_exit_time`.
  - Handled sub-minute/tick/irregular timestamps gracefully and recorded actual `expiration_seconds` on `BacktestTrade`.
  - In `_create_strategy`, mapped `expiration_seconds` to `base_expiration_bars` when `expiration_seconds` is explicitly specified.
- **`src/strat_trade/domain/optimizer/auto_matcher.py` (`StrategyAutoMatcher`)**:
  - Updated `find_optimal_strategy_for_asset` to return `None` immediately if an asset is toxic (`is_toxic_asset`) or fails microstructure qualification (`qualify_asset_microstructure`).
  - Passed `expiration_seconds` explicitly when instantiating `BacktestConfig` during grid search variation evaluation.
  - Updated return type annotation to `StrategyAssignment | None`.
- **`src/strat_trade/use_cases/auto_assign_strategies.py` (`generate_pre_trading_plan`)**:
  - Updated `_process_asset` return type to `StrategyAssignment | None`.
  - Filtered out `None` values from gathered assignments so rejected assets do not appear in `PreTradingPlan`.
- **`tests/` and new test suite**:
  - Created `tests/test_stage1_time_based_backtest_and_auto_assign.py` testing M1, S5 sub-minute, irregular gapped data, toxic asset rejection returning `None`, microstructure rejection returning `None`, and `generate_pre_trading_plan` filtering.
  - Updated existing regression tests in `tests/test_bot_and_audit_api.py`, `tests/test_m1_challenger_2_boundary_confluence.py`, `tests/test_m1_empirical_challenger_stress.py`, `tests/test_m2_empirical_challenger_adversarial.py`, `tests/test_m2_m3_adversarial_empirical_challenge.py`, `tests/test_m4_empirical_challenger_2.py`, `tests/test_phase3_rolling_15_trade_verification.py`, `tests/test_strategy_auto_matcher.py`, and `tests/test_strategy_curation_and_asset_filter.py` to assert `None` on toxic / microstructure-rejected assets and use realistic non-flat mock feeds.

## 2. Why
- Replaced fragile integer bar offset indexing (`exit_idx = i + exp_bars`) with exact time-based timestamp matching (`timestamp >= target_exit_time`), ensuring compatibility with sub-minute data, tick data, and irregular timestamp feeds.
- Prevented toxic or illiquid/dead OTC assets from receiving fallback heuristic strategy assignments, ensuring they are cleanly rejected and excluded from `PreTradingPlan`.

## 3. Verification Record
- **Deep Verification (ran actual tests):**
  - Ran full test suite `./.venv/bin/pytest`: 1,149 passed, 0 failed in 46.79s.
  - Ran linter `./.venv/bin/ruff check src tests`: 0 errors.
  - Executed targeted tests in `tests/test_stage1_time_based_backtest_and_auto_assign.py`: 7 passed, 0 failed.
- **Shallow Verification (manual run only):**
  - Inspected git diff across all modified files in `src/` and `tests/` to verify minimal, surgical changes.
- **Unverified aspects:**
  - Live pocket option broker execution over real WebSockets (tested via mocks and unit/integration suites).
  - High-frequency tick data streams with sub-second out-of-order arrival (backtester assumes monotonically increasing timestamp data).

## 4. Known Issues
- `Minor Robustness Risk` — If input dataframe has non-monotonic or backwards-jumping timestamps, `searchsorted` could find an index before `i`; engine contains a fallback forward search loop from `i + 1`, but datasets with corrupt unordered timestamps should be cleaned before backtesting.

## 5. Untested Edge Cases & Next Step
- Edge case: Dataframe where timestamp series has mixed timezone offsets or missing timestamps in the middle of active trade expiration.
- Next step for reviewer: Verify live pre-trading plan generation via FastAPI bot endpoint with real market feeds.
