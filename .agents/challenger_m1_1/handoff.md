# Milestone 1 Adversarial Review Report: Runaway Momentum Guard

**Agent**: Challenger 1 (`.agents/challenger_m1_1`)  
**Role**: critic, specialist  
**Milestone**: M1 — Runaway Momentum & Consecutive Candle Filter for Mean Reversion  
**Date**: 2026-08-24  
**Project Root**: `/Users/vlados/work/projects/startup/strat_trade_be`  
**Verdict**: **APPROVE**

---

## 1. Observation

1. **Target Functionality**:
   - `check_runaway_momentum` in `src/strat_trade/domain/strategies/support_resistance_bounce.py` (lines 10–76) and `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py` (lines 10–76).
   - Integration in `SupportResistanceBounceStrategy.evaluate_bar` (lines 181–222) and `RsiStochasticExtremeStrategy.evaluate_bar` (lines 177–220).
   - Parameters: `lookback_bars: int = 3`, `min_body_ratio: float = 0.50`, `max_opposing_wick_ratio: float = 0.25`.

2. **Empirical Adversarial Test Execution**:
   - Created dedicated empirical test suite `tests/test_adversarial_runaway_momentum.py` containing 37 distinct stress cases and a 1,000-iteration randomized Monte Carlo fuzzing harness.
   - Command: `.venv/bin/pytest tests/test_adversarial_runaway_momentum.py -v`
   - Output: `37 passed in 0.56s` (100% pass rate).
   - Full test suite: `.venv/bin/pytest`
   - Output: `965 passed, 2 warnings in 25.57s`.
   - Linter: `.venv/bin/ruff check src tests`
   - Output: `All checks passed!` (0 errors).

---

## 2. Logic Chain

1. **Numerical Stability & Zero-Division Immunity**:
   - *Observation*: Zero-range candles ($H = L = O = C$) and micro-range candles ($H - L \le 10^{-9}$) trigger `if rng <= 1e-9: return False`.
   - *Verification*: Tested $H - L \in [10^{-15}, 10^{-12}, 10^{-10}, 10^{-9}, 10^{-8}, 10^{-7}, 10^{-6}]$. Below $10^{-9}$, functions safely return `False` without raising `ZeroDivisionError` or propagating `NaN`/`inf`. Above $10^{-9}$, ratio calculations compute cleanly.

2. **Threshold Boundary Precision**:
   - *Observation*: Body ratio threshold is $\ge 0.50$ and opposing wick ratio is $\le 0.25$.
   - *Verification*:
     - Bearish body ratio at 0.49 and 0.4999 returns `False`; at 0.50, 0.5001, and 0.51 returns `True`.
     - Bearish lower wick ratio at 0.24, 0.2499, and 0.25 returns `True`; at 0.2501 and 0.26 returns `False`.
     - Bullish body ratio at 0.49 and 0.4999 returns `False`; at 0.50, 0.5001, and 0.51 returns `True`.
     - Bullish upper wick ratio at 0.24, 0.2499, and 0.25 returns `True`; at 0.2501 and 0.26 returns `False`.

3. **Multi-Bar Sequence and Timing Dynamics**:
   - *Observation*: Filter checks both sequences ending at current bar `idx` and sequences ending at preceding bar `idx - 1`.
   - *Verification*:
     - 1-bar and 2-bar runs with `lookback_bars=3` return `False`.
     - 3-bar and 4-bar consecutive waterfalls return `True`.
     - Alternating candle sequences (Red-Green-Red) and broken streaks (Red-Red-Green-Red) correctly return `False`.
     - A 3-bar bearish waterfall followed by a tentative green pin bar at `idx` correctly returns `is_bearish = True`, suppressing the dangerous "falling knife" CALL entry.

4. **Strategy Suppression Protocol Conformance**:
   - *Observation*: Contract in `PROJECT.md` requires `regime = "runaway_momentum_suppressed"`, `confidence = 0.0`, `action = None`, and metadata indicating `suppressed_action`.
   - *Verification*:
     - `SupportResistanceBounceStrategy.evaluate_bar()` under bearish waterfall returns `SignalResult(action=None, confidence=0.0, regime="runaway_momentum_suppressed", metadata={"suppressed_action": "CALL", ...})`.
     - `SupportResistanceBounceStrategy.evaluate_bar()` under bullish burst returns `SignalResult(action=None, confidence=0.0, regime="runaway_momentum_suppressed", metadata={"suppressed_action": "PUT", ...})`.
     - `RsiStochasticExtremeStrategy.evaluate_bar()` under bearish waterfall returns `SignalResult(action=None, confidence=0.0, regime="runaway_momentum_suppressed", metadata={"suppressed_action": "CALL", ...})`.
     - `RsiStochasticExtremeStrategy.evaluate_bar()` under bullish burst returns `SignalResult(action=None, confidence=0.0, regime="runaway_momentum_suppressed", metadata={"suppressed_action": "PUT", ...})`.
     - Quiet ranging markets allow normal entries (`TradeAction.CALL` / `TradeAction.PUT`) with `regime="sr_bounce"` or `regime="extreme_exhaustion"` and high confidence ($\ge 0.70$).

5. **Randomized Monte Carlo Fuzzing**:
   - *Observation*: 1,000 synthetic random OHLCV sequences generated with chaos, extreme price gaps, flash crashes ($10^6$ pts), inverted spreads, zero ranges, and micro-ticks.
   - *Verification*: 0 unhandled exceptions, 0 NaN returns, exactly 100% valid `tuple[bool, bool]` outputs where `(is_bearish and is_bullish)` is never simultaneously True.

---

## 3. Caveats

- **Timeframe Context**: Thresholds ($\ge 50\%$ body ratio and $\le 25\%$ opposing wick ratio over 3 bars) are specifically calibrated for M1 binary options trading.
- **Lookback Limits**: At dataset startup (`idx < 2`), runaway momentum guard defaults to `(False, False)` during indicator warmup.

---

## 4. Conclusion

**Verdict**: **APPROVE**

The implementation of `check_runaway_momentum` in `SupportResistanceBounceStrategy` and `RsiStochasticExtremeStrategy` is mathematically rigorous, numerically stable against edge-case candle geometries and zero-ranges, conforms strictly to the interface contracts in `PROJECT.md`, and completely eliminates false reversal signals during runaway momentum sweeps without impairing legitimate ranging setups.

---

## 5. Verification Method

To independently execute and verify all empirical adversarial stress tests:

```bash
# 1. Run Challenger 1's adversarial stress test suite
.venv/bin/pytest tests/test_adversarial_runaway_momentum.py -v

# 2. Run Worker 1's unit tests
.venv/bin/pytest tests/test_runaway_momentum_filter.py -v

# 3. Run entire repository test suite (965 tests)
.venv/bin/pytest

# 4. Verify code formatting and lint
.venv/bin/ruff check src tests
```
