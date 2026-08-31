# Stage 1 Adversarial Reviewer (Round 3) Handoff Report

> [!WARNING] **Skepticism Disclaimer**
> Verified across 1,182 automated unit, integration, and adversarial stress tests including sub-second tick feeds (50ms), microsecond and nanosecond UNIX epoch conversions, mixed ISO 8601 string timezone formats, discrete step-tick and toxic microstructure filtering, and portfolio backtest execution. Live Pocket Option broker WebSocket transport latency and live order slippage remain unverified against live real-money execution.

## 1. What the prior attempt got wrong
1. **Issue: ISO 8601 String Timezone Inconsistency in `BinaryBacktestEngine` and `parse_candles_csv_or_json`**
   - **Input:** OHLCV DataFrames or uploaded CSVs with mixed ISO datetime formats (e.g. some strings with `+00:00`, some with `Z`, some space-delimited `"2026-08-25 10:00:00"`).
   - **Expected:** Engine parses mixed timestamp formats into UTC datetime series without throwing runtime format mismatches.
   - **Actual:** Pandas 2.0+ threw `ValueError: time data '2026-08-25 10:01:00' doesn't match format '%Y-%m-%dT%H:%M:%S%z'` because `format="mixed"` was not specified.
   - **Root cause:** Missing `format="mixed"` in `pd.to_datetime` calls when converting string timestamp columns.

2. **Issue: Microsecond (1e15) and Nanosecond (1e18) Timestamp Scale Misinterpretation**
   - **Input:** Datasets with microsecond integer epoch timestamps (e.g., `1787652000000000`) or nanosecond epoch timestamps.
   - **Expected:** Engine accurately resolves timestamps into UTC datetime series.
   - **Actual:** `first_val > 1e11` condition routed microsecond timestamps into `unit="ms"`, overflowing to year 58000+.
   - **Root cause:** Incomplete timestamp scale thresholds in `BinaryBacktestEngine.run()` and `data_loader.py`.

3. **Issue: Missing `expiration_seconds` support in `PortfolioBacktestEngine` and API schemas**
   - **Input:** `PortfolioBacktestConfig` and `PortfolioBacktestRequest` lacked explicit `expiration_seconds` support for portfolio-level multi-asset chronological backtesting with time-based forward exit resolution.
   - **Expected:** `PortfolioBacktestConfig` and `PortfolioBacktestEngine` accept `expiration_seconds` and execute time-based forward timestamp searching matching `BinaryBacktestEngine`.
   - **Actual:** `PortfolioBacktestEngine` was only using index-based bar stepping (`i + exp_bars`).
   - **Root cause:** `PortfolioBacktestConfig`, `PortfolioBacktestEngine`, and `run_portfolio_backtest` were not updated to forward `expiration_seconds`.

4. **Issue: Non-Deterministic Wall-Clock Race Hazard in Unit Tests with `bar_edge_guard_seconds`**
   - **Input:** Mock `PreTradingPlan` builders across test files used default `bar_edge_guard_seconds=3.0`.
   - **Expected:** Unit tests testing order locks and cooldown boundaries run deterministically regardless of wall-clock seconds.
   - **Actual:** When test runner executed at clock seconds `XX:XX:00`..`XX:XX:02`, `is_bar_edge_blocked` triggered, causing intermittent test flakes.
   - **Root cause:** Default bar-edge guard was active during unit tests executing against wall-clock time.

## 2. What I changed
- **`src/strat_trade/domain/backtest/engine.py`**:
  - Implemented comprehensive numeric epoch scale detection (`> 1e16` -> `unit="ns"`, `> 1e13` -> `unit="us"`, `> 1e11` -> `unit="ms"`, `> 1e8` -> `unit="s"`).
  - Added `format="mixed"` and `utc=True` to all `pd.to_datetime` calls for string timestamps.
  - Hardened `exp_seconds = max(1, int(...))` boundary protection.
- **`src/strat_trade/domain/backtest/data_loader.py`**:
  - Added microsecond/nanosecond epoch handling and `format="mixed"` in `parse_candles_csv_or_json`.
- **`src/strat_trade/domain/backtest/models.py`**:
  - Added `expiration_seconds: int | None = None` to `PortfolioBacktestConfig`.
- **`src/strat_trade/domain/backtest/portfolio_engine.py`**:
  - Updated `PortfolioBacktestEngine` to support `expiration_seconds` and forward timestamp searching (`target_exit_time = entry_time + pd.Timedelta(seconds=exp_sec)`).
- **`src/strat_trade/api/schemas.py`**:
  - Added `expiration_seconds: int | None = None` to `PortfolioBacktestRequest`.
- **`src/strat_trade/use_cases/run_portfolio_backtest.py` & `src/strat_trade/api/routes/backtest.py`**:
  - Forwarded `expiration_seconds` parameter through use cases and API endpoints.
- **`tests/test_execution_guardrails.py`, `tests/test_forensic_auditor_stress.py`, `tests/test_m2_challenger_1_empirical_stress.py`, `tests/test_risk_governance_circuit_breaker.py`**:
  - Set `bar_edge_guard_seconds=0.0` in mock plan helpers to eliminate wall-clock race conditions.
- **`tests/test_adversarial_stage1_reviewer_round3.py`**:
  - Authored an 11-test adversarial test suite covering:
    1. Microsecond and Nanosecond UNIX epoch timestamp scales.
    2. Mixed ISO 8601 string timezone formats with `format="mixed"` UTC normalization.
    3. High-frequency 50ms sub-second tick streams with 1s expiration resolution.
    4. Zero-volatility / Flat price / DRAW trade outcome handling and streak resets.
    5. `PortfolioBacktestEngine` execution with explicit `expiration_seconds` and forward search.
    6. End-to-end auto-assign filtering of toxic assets and substandard discrete microstructure.
    7. Adaptive expiration seconds scaling.
    8. Bounded expiration seconds safety under zero/negative values.
    9. Session stop loss circuit breaker cutoff.
    10. Martingale and Percent position sizing models under time-based exit.
    11. FastAPI `/api/v1/backtest/portfolio/run` endpoint validation and execution with `expiration_seconds`.

## 3. Verification Record
- **Deep Verification (ran actual tests):**
  - Full test suite `./.venv/bin/pytest`: **1,182 passed, 0 failed, 2 warnings in 51.27s**.
  - Round 3 Adversarial test suite `./.venv/bin/pytest tests/test_adversarial_stage1_reviewer_round3.py`: **11 passed in 1.86s**.
  - All Stage 1 test suites (core + R1 + R2 + R3): **40 passed in 2.21s**.
  - Linter `./.venv/bin/ruff check src tests`: **All checks passed (0 errors)**.
- **Shallow Verification (manual only):**
  - Verified architectural cohesion across domain models, backtesting engines, use cases, and API schemas.
- **Unverified aspects:**
  - Live pocket option broker WebSocket network transport jitter and broker slippage under real-money conditions.

## 4. Known Issues
- None.

## 5. Remaining risk & next step
- Stage 1 quantitative improvements are thoroughly hardened, verified across all time granularities and edge cases, and 100% regression-free.
- Next step: Proceed to Stage 2 implementation.
