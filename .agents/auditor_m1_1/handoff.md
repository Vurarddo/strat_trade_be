# Forensic Audit Report: Milestone 1 — Runaway Momentum & Consecutive Candle Filter

**Auditor**: Forensic Integrity Auditor (`.agents/auditor_m1_1`)  
**Target Deliverable**: Milestone 1 (`support_resistance_bounce.py`, `rsi_stochastic_extreme.py`, `tests/test_runaway_momentum_filter.py`)  
**Integrity Mode**: Development (per `ORIGINAL_REQUEST.md`)  
**Verdict**: **CLEAN**

---

## 1. Observation

Direct empirical inspection of the Milestone 1 codebase yielded the following observations:

1. **Source Code & Mathematical Integrity**:
   - `src/strat_trade/domain/strategies/support_resistance_bounce.py`:
     - Top-level function `check_runaway_momentum(df, idx, lookback_bars=3, min_body_ratio=0.50, max_opposing_wick_ratio=0.25) -> tuple[bool, bool]` implements exact mathematical formulas:
       - Range: `rng = high - low` with zero-range / negative-range guard `if rng <= 1e-9: return False`.
       - Bearish candle: `close < open`, `body = open - close`, `body / rng >= min_body_ratio`, `lower_wick = close - low`, `lower_wick / rng <= max_opposing_wick_ratio`.
       - Bullish candle: `close > open`, `body = close - open`, `body / rng >= min_body_ratio`, `upper_wick = high - close`, `upper_wick / rng <= max_opposing_wick_ratio`.
       - Lookback verification: checks both sliding windows (ending at `idx` and ending at `idx - 1`).
     - In `SupportResistanceBounceStrategy.evaluate_bar()`:
       - If CALL setup tests support during `is_bearish_runaway` $\implies$ returns `SignalResult(action=None, confidence=0.0, regime="runaway_momentum_suppressed", metadata={"suppressed_action": "CALL", ...})`.
       - If PUT setup tests resistance during `is_bullish_runaway` $\implies$ returns `SignalResult(action=None, confidence=0.0, regime="runaway_momentum_suppressed", metadata={"suppressed_action": "PUT", ...})`.
     - Calibrated expiration: `base_expiration_bars = 3` (180s on M1).
   - `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`:
     - Implements identical mathematical `check_runaway_momentum` and exposes both `_check_runaway_momentum` and `check_runaway_momentum` instance methods.
     - In `RsiStochasticExtremeStrategy.evaluate_bar()`:
       - Oversold exhaustion + `is_bearish_runaway` $\implies$ returns `SignalResult(action=None, confidence=0.0, regime="runaway_momentum_suppressed", metadata={"suppressed_action": "CALL", ...})`.
       - Overbought exhaustion + `is_bullish_runaway` $\implies$ returns `SignalResult(action=None, confidence=0.0, regime="runaway_momentum_suppressed", metadata={"suppressed_action": "PUT", ...})`.
     - Calibrated expiration: `base_expiration_bars = 3` (180s on M1).

2. **Absence of Prohibited Patterns**:
   - **Hardcoded test results**: PASS. Zero hardcoded results, test name branches, or mocked data injection in strategy code.
   - **Facade implementations**: PASS. Functions perform actual sliding-window mathematical computations over row attributes.
   - **Fabricated verification outputs**: PASS. No pre-populated result artifacts, logs, or spoofed outputs in the repository.
   - **Self-certifying tests**: PASS. Tests construct explicit OHLCV candle scenarios and test mathematical invariants and strategy signal outcomes.
   - **Execution delegation**: PASS. Fully implemented in standard Python + pandas with zero third-party blackbox delegation.

3. **Runtime & Test Verification**:
   - `pytest tests/test_runaway_momentum_filter.py -v`: **14 passed in 0.33s**.
   - Full repository test suite (`pytest`): **928 passed, 2 warnings in 26.91s**.
   - Linter (`ruff check src/ tests/test_runaway_momentum_filter.py`): **0 errors / All checks passed**.

---

## 2. Logic Chain

1. **Reversal Suppression vs Waterfall Cascades**:
   - Counter-trend mean reversion models fail when buying into a free-falling market (multi-candle waterfall).
   - The verified implementation tests both the window ending at `idx` and the preceding window ending at `idx - 1`. This accurately catches both active waterfall candles and the initial tentative bounce bar right after a 3-bar sweep.
   - When runaway momentum is present, the strategy cleanly suppresses the signal with `action=None` and telemetry `regime="runaway_momentum_suppressed"`.
   - In quiet, ranging markets without consecutive large-bodied one-sided candles, pin-bar and dual-oscillator exhaustion signals fire normally (`action=TradeAction.CALL`/`PUT`).

2. **Authentic Testing**:
   - Grep searches for `mock`, `patch`, `MagicMock` in `tests/test_runaway_momentum_filter.py` confirmed 0 instances of mocking.
   - Tests execute real strategy instances through `prepare_dataframe` and `evaluate_bar`, verifying true end-to-end indicator calculation and signal generation.

---

## 3. Caveats

- **Timeframe Specificity**: Candle ratio thresholds ($\ge 50\%$ body, $\le 25\%$ opposing wick) are designed for M1 (60-second) bars. On higher timeframes, these parameters would represent longer temporal holding horizons.
- **Warm-up Lookback**: At `idx < 2`, `check_runaway_momentum` returns `(False, False)` by design to allow indicator warm-up.

---

## 4. Conclusion

**Verdict: CLEAN**

Milestone 1 satisfies all functional, architectural, and integrity requirements set forth in `ORIGINAL_REQUEST.md` and `PROJECT.md`:
1. `check_runaway_momentum` computes authentic OHLCV body and wick ratios without shortcuts or facades.
2. Signal suppression is properly enforced in both `SupportResistanceBounceStrategy` and `RsiStochasticExtremeStrategy`.
3. 3-bar (180s) base expiration is calibrated and verified across primary sniper alpha models.
4. Comprehensive unit test suite (`tests/test_runaway_momentum_filter.py`) passes 100% with 0 mocks.
5. Repository test suite passes 100% (928/928 tests passed).

---

## 5. Verification Method

To independently reproduce the forensic audit findings:

1. **Verify Unit Tests**:
   ```bash
   .venv/bin/pytest tests/test_runaway_momentum_filter.py -v
   ```
   *(Expected: 14 passed)*

2. **Verify Full Test Suite**:
   ```bash
   .venv/bin/pytest
   ```
   *(Expected: 928 passed)*

3. **Verify Static Linting**:
   ```bash
   .venv/bin/ruff check src/ tests/test_runaway_momentum_filter.py
   ```
   *(Expected: All checks passed!)*

4. **Run Empirical Invariant Check**:
   ```bash
   .venv/bin/python -c "
   import pandas as pd
   from strat_trade.domain.strategies.support_resistance_bounce import check_runaway_momentum as sr_crm
   from strat_trade.domain.strategies.rsi_stochastic_extreme import check_runaway_momentum as rsi_crm

   df = pd.DataFrame([
       {'open': 100.0, 'close': 90.0, 'high': 101.0, 'low': 89.0},
       {'open': 90.0, 'close': 80.0, 'high': 91.0, 'low': 79.0},
       {'open': 80.0, 'close': 70.0, 'high': 81.0, 'low': 69.0},
   ])
   assert sr_crm(df, 2, 3) == (True, False)
   assert rsi_crm(df, 2, 3) == (True, False)
   print('AUDIT OK')
   "
   ```
