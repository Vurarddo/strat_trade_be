# Milestone 1 Completion Report: Runaway Momentum & Consecutive Candle Filter

**Agent**: Worker 1 (`.agents/worker_m1`)  
**Role**: implementer, qa, specialist  
**Milestone**: M1 — Runaway Momentum & Consecutive Candle Filter for Mean Reversion Strategies  
**Date**: 2026-08-24  
**Project Root**: `/Users/vlados/work/projects/startup/strat_trade_be`  

---

## 1. Observation

1. **Vulnerability in Mean-Reversion Models**:
   - `SupportResistanceBounceStrategy` (`src/strat_trade/domain/strategies/support_resistance_bounce.py`) and `RsiStochasticExtremeStrategy` (`src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`) previously evaluated single-bar conditions (rejection wicks or overbought/oversold oscillator levels) without inspecting the preceding directional momentum sequence.
   - During aggressive trend expansions (e.g. news events, liquidity cascades, or multi-candle market waterfalls), 3-4 consecutive M1 candles expand with $>50\%$ body ratio and minimal opposing rejection wicks ($<25\%$).
   - Entering counter-trend trades during such cascades resulted in repeated consecutive losses ("catching falling knives").

2. **Implemented Logic**:
   - **`check_runaway_momentum`**:
     Implemented in `support_resistance_bounce.py` and `rsi_stochastic_extreme.py`, and exposed via `_check_runaway_momentum` and `check_runaway_momentum` methods.
     Detects whether a sequence of consecutive M1 candles (either ending at `idx` or on preceding bars ending at `idx-1`):
     - For Bearish Runaway: `close < open`, $\text{body\_ratio} = \frac{\text{open} - \text{close}}{\text{high} - \text{low}} \ge 0.50$, $\text{lower\_wick\_ratio} = \frac{\text{close} - \text{low}}{\text{high} - \text{low}} \le 0.25$.
     - For Bullish Runaway: `close > open`, $\text{body\_ratio} = \frac{\text{close} - \text{open}}{\text{high} - \text{low}} \ge 0.50$, $\text{upper\_wick\_ratio} = \frac{\text{high} - \text{close}}{\text{high} - \text{low}} \le 0.25$.
   - **Signal Suppression**:
     - In `SupportResistanceBounceStrategy.evaluate_bar()`:
       - Support bounce (CALL candidate) + bearish runaway momentum detected $\implies$ `action = None`, `confidence = 0.0`, `regime = "runaway_momentum_suppressed"`.
       - Resistance rejection (PUT candidate) + bullish runaway momentum detected $\implies$ `action = None`, `confidence = 0.0`, `regime = "runaway_momentum_suppressed"`.
     - In `RsiStochasticExtremeStrategy.evaluate_bar()`:
       - Oversold exhaustion (CALL candidate) + bearish runaway momentum detected $\implies$ `action = None`, `confidence = 0.0`, `regime = "runaway_momentum_suppressed"`.
       - Overbought exhaustion (PUT candidate) + bullish runaway momentum detected $\implies$ `action = None`, `confidence = 0.0`, `regime = "runaway_momentum_suppressed"`.

3. **Calibrated Parameters & Expiration Verification**:
   - `SupportResistanceBounceStrategy`: `swing_window = 20`, `min_wick_ratio = 0.35`, `base_expiration_bars = 3` (180s on M1).
   - `RsiStochasticExtremeStrategy`: `rsi_period = 14`, `rsi_oversold = 25.0`, `rsi_overbought = 75.0`, `stoch_oversold = 20.0`, `stoch_overbought = 80.0`, `base_expiration_bars = 3` (180s on M1).
   - `EmaPullbackTrendStrategy`: `ema_fast = 9`, `ema_mid = 21`, `ema_slow = 50`, `adx_threshold = 25.0`, `rsi_overbought = 65.0`, `rsi_oversold = 35.0`, `base_expiration_bars = 3` (180s on M1).

4. **Testing & Code Quality Results**:
   - `tests/test_runaway_momentum_filter.py`: 14 comprehensive unit tests created and passing 100%.
   - Full repository test run (`.venv/bin/pytest`): **928 passed, 0 failed** in 21.35s.
   - Code linter (`.venv/bin/ruff check src tests`): **0 errors / all checks passed**.

---

## 2. Logic Chain

1. **Distinguishing Reversals from Cascades**:
   - A legitimate mean-reversion bounce occurs when price reaches support/resistance after quiet, balanced, or choppy price action, displaying a clear rejection pin-bar.
   - When price breaks out violently with 3-4 consecutive full-bodied candles without lower/upper wicks, market microstructure reflects one-sided order flow.
   - Evaluating both sequences ending at `idx` (current bar) and sequences ending at `idx - 1` (preceding bars before the pin bar) ensures that:
     a) Reversal signals on the first tentative bounce candle after a 3-bar waterfall are suppressed.
     b) Reversal signals while price is still in free-fall are suppressed.
     c) Normal pin-bar rejections in balanced/ranging markets fire uninterrupted.

2. **Zero Regressions on Existing Strategies & Suites**:
   - The filter operates as an early guardrail inside `evaluate_bar()` without altering dataframe preparation schemas or existing parameter definitions.
   - All 914 existing tests plus 14 new tests (total 928 tests) pass without regression.

---

## 3. Caveats

- **Timeframe Assumption**: Runaway momentum candle thresholds ($\ge 50\%$ body ratio and $\le 25\%$ opposing wick ratio) are calibrated for M1 candles (60s bars). When applying higher timeframes (e.g. M5 or M15), consecutive candle counts reflect larger absolute price excursions.
- **Lookback Boundary**: At the very beginning of a dataset (`idx < 2`), runaway momentum returns `(False, False)` by design to allow indicator warm-up.

---

## 4. Conclusion

Milestone 1 requirements are fully implemented, verified, and tested:
1. `check_runaway_momentum` implemented with exact mathematical parameters ($\ge 50\%$ body ratio, $\le 25\%$ opposing wick ratio, 3-4 consecutive bars).
2. Counter-trend reversals in `SupportResistanceBounceStrategy` and `RsiStochasticExtremeStrategy` are cleanly suppressed during runaway momentum sweeps with `regime = "runaway_momentum_suppressed"`.
3. Parameter calibrations and 3-bar (180s) expirations across all primary alpha strategies are verified.
4. Comprehensive unit test suite added in `tests/test_runaway_momentum_filter.py`.
5. 100% test pass rate across all 928 unit and integration tests with 0 ruff lint errors.

---

## 5. Verification Method

To independently verify the implementation:

1. **Run Unit Tests for Runaway Momentum Filter**:
   ```bash
   .venv/bin/pytest tests/test_runaway_momentum_filter.py -v
   ```
   *(Result: 14 passed in 0.30s)*

2. **Run Full Test Suite**:
   ```bash
   .venv/bin/pytest
   ```
   *(Result: 928 passed, 2 warnings in 21.35s)*

3. **Run Linting**:
   ```bash
   .venv/bin/ruff check src tests
   ```
   *(Result: All checks passed!)*

4. **Inspect Code Files**:
   - `src/strat_trade/domain/strategies/support_resistance_bounce.py`
   - `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`
   - `tests/test_runaway_momentum_filter.py`
