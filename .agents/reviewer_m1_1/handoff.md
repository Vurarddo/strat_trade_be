# Milestone 1 Independent & Adversarial Review Report

**Agent**: Reviewer 1 (`.agents/reviewer_m1_1`)  
**Roles**: Reviewer, Adversarial Critic  
**Milestone**: M1 — Strategy Confluence & Runaway Momentum Guards  
**Verdict**: **APPROVE**  
**Date**: 2026-08-24  
**Project Root**: `/Users/vlados/work/projects/startup/strat_trade_be`  

---

## 1. Observation

### 1.1 Implementation Code Inspection
1. **`src/strat_trade/domain/strategies/support_resistance_bounce.py`**:
   - **`check_runaway_momentum`** (lines 10–76):
     - Implements directional runaway momentum detection across `lookback_bars` (default 3).
     - Bearish condition (lines 31–43): `close < open`, `range = high - low > 1e-9`, `body / range >= min_body_ratio` (0.50), and `lower_wick / range <= max_opposing_wick_ratio` (0.25).
     - Bullish condition (lines 45–57): `close > open`, `range = high - low > 1e-9`, `body / range >= min_body_ratio` (0.50), and `upper_wick / range <= max_opposing_wick_ratio` (0.25).
     - Dual-window lookback evaluation (lines 62–74): evaluates consecutive bars ending at `idx` (`range(idx - lookback + 1, idx + 1)`) AND preceding bars ending at `idx - 1` (`range(idx - lookback, idx)`).
     - Out-of-bounds guards (line 28): returns `(False, False)` if `idx < 0`, `idx >= len(df)`, or `lookback_bars <= 0`.
   - **Strategy integration** (lines 118–147, 181–221):
     - Exposes instance methods `_check_runaway_momentum` and `check_runaway_momentum`.
     - In `evaluate_bar()`:
       - On Support bounce (CALL candidate): checks `is_bearish_runaway`; if True, returns `SignalResult(action=None, confidence=0.0, expiration_bars=3, regime="runaway_momentum_suppressed", metadata={"suppressed_action": "CALL", ...})`.
       - On Resistance rejection (PUT candidate): checks `is_bullish_runaway`; if True, returns `SignalResult(action=None, confidence=0.0, expiration_bars=3, regime="runaway_momentum_suppressed", metadata={"suppressed_action": "PUT", ...})`.
   - **Default Parameter Defs & Expiration** (lines 89–98, 237–269):
     - `swing_window = 20`, `min_wick_ratio = 0.35`, `base_expiration_bars = 3` (180s on M1).

2. **`src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`**:
   - **`check_runaway_momentum`** (lines 10–76): identical robust mathematical definition exported and bound to class methods.
   - **Strategy integration** (lines 175–214):
     - Oversold exhaustion (CALL candidate): suppresses entry if `is_bearish_runaway` is True (`regime="runaway_momentum_suppressed"`, `metadata={"suppressed_action": "CALL", ...}`).
     - Overbought exhaustion (PUT candidate): suppresses entry if `is_bullish_runaway` is True (`regime="runaway_momentum_suppressed"`, `metadata={"suppressed_action": "PUT", ...}`).
   - **Default Parameter Defs & Expiration** (lines 89–106, 231–286):
     - `rsi_period = 14`, `rsi_oversold = 25.0`, `rsi_overbought = 75.0`, `stoch_oversold = 20.0`, `stoch_overbought = 80.0`, `base_expiration_bars = 3` (180s on M1).

3. **`src/strat_trade/domain/strategies/ema_pullback_trend.py`**:
   - `base_expiration_bars = 3` (lines 47, 164, 214–222).
   - Parameters: `ema_fast = 9`, `ema_mid = 21`, `ema_slow = 50`, `adx_threshold = 25.0`, `rsi_overbought = 65.0`, `rsi_oversold = 35.0`.

4. **`src/strat_trade/domain/optimizer/auto_matcher.py`**:
   - `PRIORITY_STRATEGIES = frozenset({"support_resistance_bounce", "rsi_stochastic_extreme", "ema_pullback_trend"})` (lines 21–27).
   - Evaluator boosts priority sniper alpha strategies with a +15.0 quantum bonus (line 486).

### 1.2 Test Execution Results
- **Dedicated Runaway Momentum Test Suite**:
  - Command: `.venv/bin/pytest tests/test_runaway_momentum_filter.py -v`
  - Output: `14 passed in 0.27s` (100% pass).
- **Full Repository Test Suite**:
  - Command: `.venv/bin/pytest`
  - Output: `928 passed, 2 warnings in 25.61s` (100% pass, 0 failures, 0 regressions).
- **Code Linter**:
  - Command: `.venv/bin/ruff check src tests`
  - Output: `All checks passed!` (0 lint errors).

---

## 2. Logic Chain

1. **Mathematical Precision of Runaway Momentum Guard**:
   - A runaway cascade is defined by strong trend-directed candle bodies and absence of opposing rejection wicks.
   - For bearish runaway:
     $$\text{Body Ratio} = \frac{\text{Open} - \text{Close}}{\text{High} - \text{Low}} \ge 0.50$$
     $$\text{Opposing (Lower) Wick Ratio} = \frac{\text{Close} - \text{Low}}{\text{High} - \text{Low}} \le 0.25$$
   - For bullish runaway:
     $$\text{Body Ratio} = \frac{\text{Close} - \text{Open}}{\text{High} - \text{Low}} \ge 0.50$$
     $$\text{Opposing (Upper) Wick Ratio} = \frac{\text{High} - \text{Close}}{\text{High} - \text{Low}} \le 0.25$$
   - The implementation directly calculates these ratios on floating-point values and guards against zero-range candles (`rng <= 1e-9`), avoiding `ZeroDivisionError`.

2. **Necessity and Correctness of Dual-Window Lookback**:
   - In `SupportResistanceBounceStrategy`, a pin bar at `idx` is a rejection candle (e.g. green with a large lower wick). The 3-bar waterfall occurred on preceding bars (`idx-3, idx-2, idx-1`). Checking `range(idx - lookback, idx)` accurately detects the waterfall and suppresses the premature counter-trend CALL.
   - In `RsiStochasticExtremeStrategy`, the current bar at `idx` may be the 3rd or 4th consecutive waterfall bar triggering extreme oversold status. Checking `range(idx - lookback + 1, idx + 1)` catches the active cascade and suppresses the falling-knife CALL.
   - Checking both windows ensures total coverage for both mid-cascade and immediate post-cascade rejection attempts without false positives during calm ranging market bounces.

3. **Signal Suppression & Regime Attribution**:
   - Counter-trend reversal candidates in both strategies correctly set `action = None`, `confidence = 0.0`, `expiration_bars = 3`, and `regime = "runaway_momentum_suppressed"`.
   - Rich metadata (`suppressed_action`, `support`, `resistance`, `rsi`, `stoch_k`, `stoch_d`) is preserved for forensic telemetry and UI logging.

4. **Integrity Check**:
   - No hardcoded test responses, fake mock facades, or test bypasses were found in `support_resistance_bounce.py`, `rsi_stochastic_extreme.py`, or `test_runaway_momentum_filter.py`.
   - Real indicator math and bar-by-bar evaluation are fully operational.

---

## 3. Adversarial Stress-Testing & Edge-Case Mining

| # | Stress Scenario | Attack / Edge Input | Expected Behavior | Actual Behavior | Result |
|---|-----------------|---------------------|-------------------|-----------------|--------|
| 1 | Out-of-Bounds Indices | `idx = -1`, `idx = len(df)`, `idx = 100` | Return `(False, False)` without exception | Returned `(False, False)` | **PASS** |
| 2 | Warm-up Indices | `idx = 0`, `idx = 1` with `lookback = 3` | Return `(False, False)` | Returned `(False, False)` | **PASS** |
| 3 | Zero-Range Candle | `open = high = low = close = 100.0` (`rng = 0.0`) | Guard `rng <= 1e-9`, return `False` | Returned `(False, False)` without zero-division | **PASS** |
| 4 | Micro-Tick Spread | `rng = 1e-12` (< 1e-9 threshold) | Treated as flat bar, return `False` | Returned `(False, False)` | **PASS** |
| 5 | Perfect Doji | `open == close`, `high > low` | `body = 0.0`, return `False` | Returned `(False, False)` | **PASS** |
| 6 | Exact Boundary (50% body, 25% wick) | `range = 10.0, body = 5.0, wick = 2.5` | `body/rng >= 0.50` and `wick/rng <= 0.25` $\implies$ True | Identified as runaway `True` | **PASS** |
| 7 | Sub-Boundary Body (49% body) | `range = 10.0, body = 4.9, wick = 2.5` | `body/rng < 0.50` $\implies$ False | Rejected from runaway `False` | **PASS** |
| 8 | Excess Opposing Wick (26% wick) | `range = 10.0, body = 5.0, wick = 2.6` | `wick/rng > 0.25` $\implies$ False | Rejected from runaway `False` | **PASS** |
| 9 | Calm Ranging Market (No Runaway) | Alternating small candles with >30% wicks | `check_runaway_momentum == (False, False)` | S&R Bounce fires CALL/PUT normally ($\text{confidence} \ge 0.75$) | **PASS** |

---

## 4. Caveats

- **Lookback Resolution**: `lookback_bars = 3` is tuned for M1 (60s) bars. On higher timeframes (M5/M15), 3 bars represent a 15–45 minute move.
- **Warm-up Period**: Datasets with fewer than `lookback_bars` bars return `(False, False)` by design to allow indicator initialization.
- No other caveats found.

---

## 5. Conclusion

**Verdict**: **APPROVE**

Milestone 1 satisfies all requirements outlined in `PROJECT.md` and `ORIGINAL_REQUEST.md`:
1. `check_runaway_momentum` is mathematically exact, robust to edge cases, and correctly implemented across both `SupportResistanceBounceStrategy` and `RsiStochasticExtremeStrategy`.
2. Asymmetric counter-trend signal suppression properly silences dangerous falling-knife CALL and overbought-surge PUT entries while tagging `regime = "runaway_momentum_suppressed"`.
3. All primary sniper alpha strategies (`Support & Resistance Pin-Bar`, `RSI + Stoch Extreme Scalp`, `EMA Ribbon Trend Pullback`) have calibrated default parameters and 3-bar (180s) expirations.
4. Test suite coverage is exemplary: 14 dedicated unit tests in `tests/test_runaway_momentum_filter.py` pass cleanly, and the full repository test suite passes with 928/928 tests and 0 ruff lint errors.

---

## 6. Verification Method

To reproduce and independently verify the results:

1. **Run Unit Tests for Runaway Momentum Filter**:
   ```bash
   .venv/bin/pytest tests/test_runaway_momentum_filter.py -v
   ```
2. **Run Full Project Test Suite**:
   ```bash
   .venv/bin/pytest
   ```
3. **Run Code Quality Linter**:
   ```bash
   .venv/bin/ruff check src tests
   ```
4. **Inspect Source Files**:
   - `src/strat_trade/domain/strategies/support_resistance_bounce.py`
   - `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`
   - `src/strat_trade/domain/strategies/ema_pullback_trend.py`
   - `src/strat_trade/domain/optimizer/auto_matcher.py`
   - `tests/test_runaway_momentum_filter.py`
