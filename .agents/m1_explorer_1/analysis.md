# Technical Analysis: VolatilitySqueezeBreakoutStrategy Logic Correction

## 1. Executive Summary

- **Component**: `VolatilitySqueezeBreakoutStrategy` (`src/strat_trade/domain/strategies/volatility_squeeze_breakout.py`)
- **Milestone / Feature**: Milestone 1 (Strategy Logic Correction & Signal Hygiene), Feature 1
- **Authoritative Requirement**: `ORIGINAL_REQUEST.md` §R1, `PROJECT.md` Feature 1
- **Core Issue**: Line 84 of `volatility_squeeze_breakout.py` allows signals to fire on every uncompressed bar where momentum is non-zero (`not sq_now and abs(mom) > 0`), causing continuous phantom signals on normal bars instead of genuine squeeze releases.
- **Remedy**: Fix line 84 to `squeeze_fired = sq_prev and not sq_now`, verify confidence scoring and directional momentum acceleration, and build comprehensive unit and regression tests in `tests/test_strategy_logic_enhancements.py`.

---

## 2. Root Cause Analysis (RCA)

### 2.1 File Location and Existing Code
File: `src/strat_trade/domain/strategies/volatility_squeeze_breakout.py`
Lines 72-98:
```python
        row = df.iloc[idx]
        prev = df.iloc[idx - 1]

        mom = float(row.get("momentum", 0.0))
        prev_mom = float(prev.get("momentum", 0.0))
        sq_now = bool(row.get("squeeze_on", False))
        sq_prev = bool(prev.get("squeeze_on", False))

        action = None
        confidence = 0.0

        # Breakout Trigger: Squeeze was ON and fired OFF with directional momentum
        squeeze_fired = (sq_prev and not sq_now) or (not sq_now and abs(mom) > 0)

        if squeeze_fired:
            if mom > 0 and mom > prev_mom:
                action = TradeAction.CALL
                confidence = 0.75
                if sq_prev and not sq_now:  # Fresh squeeze fire
                    confidence += 0.15
            elif mom < 0 and mom < prev_mom:
                action = TradeAction.PUT
                confidence = 0.75
                if sq_prev and not sq_now:  # Fresh squeeze fire
                    confidence += 0.15
```

### 2.2 Mechanism of Failure
1. The definition of a **TTM Volatility Squeeze** breakout is the transition from a low-volatility compression phase (Bollinger Bands inside Keltner Channels: `squeeze_on = True`) to volatility expansion (Bollinger Bands outside Keltner Channels: `squeeze_on = False`).
2. Under normal market conditions (uncompressed bars), `sq_now == False` and `sq_prev == False`.
3. In line 84, the clause `(not sq_now and abs(mom) > 0)` evaluates to `True` on virtually every uncompressed bar as long as price changed over the lookback period (`abs(mom) > 0`).
4. As a consequence:
   - When the market is trending up (`mom > 0 and mom > prev_mom`), the strategy generates a `CALL` signal on **every single bar**, despite no squeeze ever having taken place.
   - When the market is trending down (`mom < 0 and mom < prev_mom`), the strategy generates a `PUT` signal on **every single bar**.
   - In choppy, ranging markets without compression, minor momentum fluctuations spam false breakout trades.
5. This completely defeats the purpose of the squeeze filter, flooding the bot engine with spurious trades and leading to catastrophic drawdowns.

---

## 3. Exact Code Fix & Design Specification

### 3.1 Proposed Code in `volatility_squeeze_breakout.py`
In `evaluate_bar`:
```python
    def evaluate_bar(self, df: pd.DataFrame, idx: int) -> SignalResult:
        if idx < 30 or idx >= len(df):
            return SignalResult(None, 0.0, self.base_expiration_bars, "warming_up")

        row = df.iloc[idx]
        prev = df.iloc[idx - 1]

        mom_val = row.get("momentum", 0.0)
        prev_mom_val = prev.get("momentum", 0.0)
        mom = 0.0 if pd.isna(mom_val) else float(mom_val)
        prev_mom = 0.0 if pd.isna(prev_mom_val) else float(prev_mom_val)

        sq_now_val = row.get("squeeze_on", False)
        sq_prev_val = prev.get("squeeze_on", False)
        sq_now = False if pd.isna(sq_now_val) else bool(sq_now_val)
        sq_prev = False if pd.isna(sq_prev_val) else bool(sq_prev_val)

        action = None
        confidence = 0.0

        # Breakout Trigger: Squeeze was ON on previous bar and released (OFF) on current bar
        squeeze_fired = sq_prev and not sq_now

        if squeeze_fired:
            if mom > 0 and mom > prev_mom:
                action = TradeAction.CALL
                confidence = 0.90
            elif mom < 0 and mom < prev_mom:
                action = TradeAction.PUT
                confidence = 0.90

        confidence = min(confidence, 0.95)
        return SignalResult(
            action=action,
            confidence=confidence,
            expiration_bars=self.base_expiration_bars,
            regime="volatility_breakout",
            metadata={"momentum": round(mom, 6), "squeeze_on": sq_now},
        )
```

### 3.2 Key Changes & Simplifications
1. **Strict Transition**: `squeeze_fired = sq_prev and not sq_now`. Only `True` if bar `idx - 1` had `squeeze_on == True` and bar `idx` has `squeeze_on == False`.
2. **Confidence Assignment**: Because `squeeze_fired` already guarantees `sq_prev and not sq_now`, the base breakout confidence is cleanly set to `0.90` (or `0.75 + 0.15`), removing redundant nested conditions.
3. **NaN Safety**: Explicit `pd.isna` checks prevent `TypeError` or unexpected comparison behavior when indicator warmup returns `NaN`.
4. **Metadata**: Retains `"momentum"` (rounded to 6 decimals) and `"squeeze_on"` boolean, preserving 100% backward compatibility with all downstream consumers (`BinaryBacktestEngine`, `LiveDemoBotEngine`, API schemas).

---

## 4. Signal Evaluation Truth Table

| `sq_prev` | `sq_now` | `squeeze_fired` | Momentum Condition | Expected Action | Confidence | Regime | Rationale |
|---|---|---|---|---|---|---|---|
| `False` | `False` | `False` | `mom > 0, mom > prev_mom` | `None` | `0.0` | `volatility_breakout` | Normal uncompressed bar (NO phantom signal) |
| `False` | `False` | `False` | `mom < 0, mom < prev_mom` | `None` | `0.0` | `volatility_breakout` | Normal uncompressed bar (NO phantom signal) |
| `True` | `True` | `False` | Any momentum | `None` | `0.0` | `volatility_breakout` | Squeeze ongoing (market compressed, wait for release) |
| `False` | `True` | `False` | Any momentum | `None` | `0.0` | `volatility_breakout` | Squeeze starting / entering compression |
| `True` | `False` | `True` | `mom > 0 and mom > prev_mom` | `TradeAction.CALL` | `0.90` | `volatility_breakout` | **Valid Bullish Breakout** |
| `True` | `False` | `True` | `mom < 0 and mom < prev_mom` | `TradeAction.PUT` | `0.90` | `volatility_breakout` | **Valid Bearish Breakout** |
| `True` | `False` | `True` | `mom > 0 and mom <= prev_mom` | `None` | `0.0` | `volatility_breakout` | Squeeze fired but momentum decelerating |
| `True` | `False` | `True` | `mom < 0 and mom >= prev_mom` | `None` | `0.0` | `volatility_breakout` | Squeeze fired but momentum decelerating |
| `True` | `False` | `True` | `mom == 0.0` | `None` | `0.0` | `volatility_breakout` | Zero momentum at release |
| Any | Any | N/A | `idx < 30` | `None` | `0.0` | `warming_up` | Warmup period safeguard |
| Any | Any | N/A | `idx >= len(df)` | `None` | `0.0` | `warming_up` | Index boundary guard |

---

## 5. Concrete Test Suite Specification

A dedicated test suite in `tests/test_strategy_logic_enhancements.py` will systematically test and guarantee this behavior.

### 5.1 Test Cases Matrix

```python
# tests/test_strategy_logic_enhancements.py

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, UTC, timedelta

from strat_trade.domain.strategies.volatility_squeeze_breakout import VolatilitySqueezeBreakoutStrategy
from strat_trade.domain.backtest.models import TradeAction


def _create_synthetic_squeeze_df(
    n_bars: int = 100,
    squeeze_start: int = 35,
    squeeze_end: int = 50,
    breakout_direction: str = "bullish",
) -> pd.DataFrame:
    """Creates a controlled synthetic DataFrame with precise Bollinger & Keltner squeeze and release."""
    # ... builds exact candles with narrow range between squeeze_start and squeeze_end,
    # then explosive breakout candle at squeeze_end ...
```

#### Test 1: Squeeze Transition Fires CALL on Bullish Breakout
- **Given**: DataFrame where bars 35 to 49 have `squeeze_on == True`, and bar 50 has `squeeze_on == False` with `momentum[50] > momentum[49] > 0`.
- **When**: `strat.evaluate_bar(df_prepared, 50)`
- **Assert**:
  - `sig.action == TradeAction.CALL`
  - `sig.confidence == 0.90`
  - `sig.regime == "volatility_breakout"`
  - `sig.metadata["squeeze_on"] is False`

#### Test 2: Squeeze Transition Fires PUT on Bearish Breakout
- **Given**: DataFrame where bars 35 to 49 have `squeeze_on == True`, and bar 50 has `squeeze_on == False` with `momentum[50] < momentum[49] < 0`.
- **When**: `strat.evaluate_bar(df_prepared, 50)`
- **Assert**:
  - `sig.action == TradeAction.PUT`
  - `sig.confidence == 0.90`
  - `sig.regime == "volatility_breakout"`

#### Test 3: Normal Uncompressed Bars Do NOT Fire Phantom Signals
- **Given**: DataFrame of 100 bars where `squeeze_on` is `False` across all bars 30-99, with strong positive trend (`close` increasing every bar, `mom > 0`, `mom > prev_mom`).
- **When**: Evaluating all bars from index 30 to 99.
- **Assert**:
  - For all `i` in `30..99`, `strat.evaluate_bar(df, i).action is None`
  - `strat.evaluate_bar(df, i).confidence == 0.0`
  - Zero false signals generated.

#### Test 4: Long Continuous Squeeze Periods Do NOT Fire Until Release
- **Given**: DataFrame where bars 30 to 70 have `squeeze_on == True` on every bar.
- **When**: Evaluating bars 30 to 70.
- **Assert**:
  - Every bar in index 30 to 70 produces `action is None` and `confidence == 0.0`.
  - On bar 71, when `squeeze_on` flips to `False` with accelerating momentum, signal fires immediately.

#### Test 5: Squeeze Release with Decelerating or Zero Momentum Filtered
- **Given**: Squeeze release transition at bar 50 (`sq_prev=True`, `sq_now=False`), but:
  - Subcase A: `mom = 0.005`, `prev_mom = 0.008` (positive but decelerating) -> `action is None`
  - Subcase B: `mom = -0.005`, `prev_mom = -0.008` (negative but decelerating) -> `action is None`
  - Subcase C: `mom = 0.0`, `prev_mom = 0.0` (zero momentum) -> `action is None`
- **Assert**: All subcases evaluate to `action is None` and `confidence == 0.0`.

#### Test 6: Warmup and Out-of-Bounds Guards
- **Given**: Index values `0, 15, 29, len(df), len(df) + 10`.
- **When**: `strat.evaluate_bar(df, idx)`
- **Assert**:
  - `sig.action is None`
  - `sig.confidence == 0.0`
  - `sig.regime == "warming_up"`

---

## 6. Verification and Regression Plan

1. **Unit Test Execution**:
   Run `.venv/bin/pytest tests/test_strategy_logic_enhancements.py -v` and verify 100% pass rate.
2. **Full Regression Test Suite**:
   Run `.venv/bin/pytest` across the entire repository to ensure:
   - `tests/test_new_strategies.py` passes.
   - `tests/test_strategy_optimizer.py` passes.
   - `tests/test_backtest_models_and_engine.py` passes.
   - All 66 existing tests continue to pass without regression.
