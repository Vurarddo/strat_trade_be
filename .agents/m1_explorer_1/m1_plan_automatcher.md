# Milestone 1 Plan: StrategyAutoMatcher Restructuring & Sniper Alpha Allocation

## 1. Executive Summary
This document defines the restructuring plan for `src/strat_trade/domain/optimizer/auto_matcher.py` and `src/strat_trade/domain/strategies/registry.py` under Milestone 1 (M1). The objective is to transition the automated strategy matching engine from legacy indicator-spam configurations to the high-conviction **Sniper Trio**:
1. **Support & Resistance Pin-Bar** (`support_resistance_bounce`) — 57.6% WR in live broker tests, price-action rejection at key swings.
2. **RSI + Stoch Extreme Scalp** (`rsi_stochastic_extreme`) — 71.4% WR in live broker tests, dual-oscillator exhaustion.
3. **EMA Ribbon Trend Pullback** (`ema_pullback_trend`) — 60.0% WR with calibrated overbought/oversold guards.

Legacy strategies (`MACD Divergence & Cross`, `hybrid_multifactors`, `supertrend_adx_momentum`) are cleanly removed from `PRIORITY_STRATEGIES` and default heuristic fallbacks while remaining registered in `_STRATEGIES` (`registry.py`) for backward compatibility and manual/historical backtesting.

---

## 2. Target Component Changes

### 2.1. `PRIORITY_STRATEGIES` Update (`auto_matcher.py`)
- **Target File**: `src/strat_trade/domain/optimizer/auto_matcher.py:17-24`
- **Change**: Replace legacy set `{supertrend_adx_momentum, hybrid_multifactors, rsi_stochastic_extreme, macd_divergence_break}` with `frozenset({"support_resistance_bounce", "rsi_stochastic_extreme", "ema_pullback_trend"})`.
- **Impact**: Only verified Sniper strategies receive the `+15.0` quantum bonus score during automated evaluation.

### 2.2. Restructuring Heuristic Profiles (`_heuristic_profile_for_asset`)
- **Target File**: `src/strat_trade/domain/optimizer/auto_matcher.py:229-365`
- **Asset Routing Specification**:
  - **Commodities & Gold** (`"GOLD" in sym or "XAU" in sym`): Route to `support_resistance_bounce` with `swing_window=20, rsi_period=14, min_wick_ratio=0.35, base_expiration_bars=expiration_bars`.
  - **Stocks / Equities** (`"#" in sym or "AAPL" in sym or "TSLA" in sym or "NVDA" in sym or "INTC" in sym`): Route to `ema_pullback_trend` with `ema_fast=9, ema_mid=21, ema_slow=50, adx_threshold=25.0, rsi_period=14, rsi_overbought=65.0, rsi_oversold=35.0, stoch_overbought=75.0, stoch_oversold=25.0, base_expiration_bars=expiration_bars`.
  - **Crypto Assets** (`BTC, ETH, BNB, MATIC, SOL, DOGE, XRP`): Route to `rsi_stochastic_extreme` with `rsi_period=14, rsi_oversold=25.0, rsi_overbought=75.0, stoch_k=14, stoch_d=3, stoch_oversold=20.0, stoch_overbought=80.0, base_expiration_bars=expiration_bars`.
  - **Forex Pairs** (`EUR, GBP, AUD, NZD, CAD, CHF, JPY, ARS, CNH, CNY, JOD, CLP, BDT, EGP`):
    - JPY or GBP pairs (`"JPY" in sym or "GBP" in sym`): Route to `support_resistance_bounce` (`swing_window=20, rsi_period=14, min_wick_ratio=0.35, base_expiration_bars=expiration_bars`).
    - Other Forex pairs: Route to `rsi_stochastic_extreme` (`rsi_period=14, rsi_oversold=25.0, rsi_overbought=75.0, stoch_k=14, stoch_d=3, stoch_oversold=20.0, stoch_overbought=80.0, base_expiration_bars=expiration_bars`).
  - **Curated Fallbacks (`else:` branch)**:
    - **Primary Fallback**: `support_resistance_bounce` (`swing_window=20, rsi_period=14, min_wick_ratio=0.35, base_expiration_bars=expiration_bars`).
    - **Secondary Fallback**: `rsi_stochastic_extreme` (`rsi_period=14, rsi_oversold=25.0, rsi_overbought=75.0, stoch_k=14, stoch_d=3, stoch_oversold=20.0, stoch_overbought=80.0, base_expiration_bars=expiration_bars`).
    - **Tertiary Fallback**: `strategies[0]` with `base_expiration_bars=expiration_bars`.

### 2.3. Restricting Optimal Allocation to Sniper Alpha Pool (`find_optimal_strategy_for_asset`)
- **Target File**: `src/strat_trade/domain/optimizer/auto_matcher.py:410-415`
- **Specification**: Filter candidate strategies being backtested to `candidate_strategies = [s for s in strategies if s["id"] in PRIORITY_STRATEGIES]`. If a custom pool without priority strategies is passed in testing, fallback to evaluating `strategies`.
- **Impact**: Guarantees that automated candle backtesting only assigns strategies from the verified Sniper Trio (`support_resistance_bounce`, `rsi_stochastic_extreme`, `ema_pullback_trend`).

### 2.4. Synchronizing Central Strategy Registry Fallback (`registry.py`)
- **Target File**: `src/strat_trade/domain/strategies/registry.py:163-176`
- **Specification**: Update `get_strategy_instance` default fallback resolution from `supertrend_adx_momentum` / `macd_divergence_break` to `support_resistance_bounce` (primary) and `rsi_stochastic_extreme` (secondary).

---

## 3. Concrete Implementation Diff Patch

```diff
--- a/src/strat_trade/domain/optimizer/auto_matcher.py
+++ b/src/strat_trade/domain/optimizer/auto_matcher.py
@@ -17,10 +17,9 @@
 PRIORITY_STRATEGIES: frozenset[str] = frozenset(
     {
-        "supertrend_adx_momentum",
-        "hybrid_multifactors",
+        "support_resistance_bounce",
         "rsi_stochastic_extreme",
-        "macd_divergence_break",
+        "ema_pullback_trend",
     }
 )
 
@@ -238,29 +237,34 @@
         if "GOLD" in sym or "XAU" in sym:
-            # Gold / Commodities -> Hybrid Multi-Factor
-            st = next((s for s in strategies if s["id"] == "hybrid_multifactors"), strategies[0])
+            # Gold / Commodities -> Support & Resistance Pin-Bar
+            st = next(
+                (s for s in strategies if s["id"] == "support_resistance_bounce"), strategies[0]
+            )
             params = {
+                "swing_window": 20,
                 "rsi_period": 14,
-                "rsi_oversold": 30.0,
-                "rsi_overbought": 70.0,
-                "ema_fast": 9,
-                "ema_mid": 21,
-                "ema_slow": 50,
-                "bb_length": 20,
-                "bb_std": 2.0,
-                "atr_period": 14,
-                "adx_period": 14,
-                "adx_trend_threshold": 25.0,
-                "adx_range_threshold": 20.0,
+                "min_wick_ratio": 0.35,
                 "base_expiration_bars": expiration_bars,
             }
-            rationale = f"Гібридний мульти-факторний аналіз для золота {asset}"
+            rationale = f"Фрактальні рівні підтримки/опору та Pin-Bar для золота {asset}"
         elif "#" in sym or "AAPL" in sym or "TSLA" in sym or "NVDA" in sym or "INTC" in sym:
-            # Stocks -> MACD Divergence or Volatility Squeeze Breakout
-            st = next((s for s in strategies if s["id"] == "macd_divergence_break"), strategies[0])
+            # Stocks -> EMA Ribbon Trend Pullback
+            st = next((s for s in strategies if s["id"] == "ema_pullback_trend"), strategies[0])
             params = {
-                "macd_fast": 12,
-                "macd_slow": 26,
-                "macd_sign": 9,
+                "ema_fast": 9,
+                "ema_mid": 21,
+                "ema_slow": 50,
+                "adx_period": 14,
+                "adx_threshold": 25.0,
+                "stoch_k": 14,
+                "stoch_d": 3,
+                "rsi_period": 14,
+                "rsi_overbought": 65.0,
+                "rsi_oversold": 35.0,
+                "stoch_overbought": 75.0,
+                "stoch_oversold": 25.0,
                 "base_expiration_bars": expiration_bars,
             }
-            rationale = f"Оптимально для імпульсних рухів акцій {asset}"
+            rationale = f"EMA Ribbon трендовий відкат для імпульсних рухів акцій {asset}"
         elif any(c in sym for c in ("BTC", "ETH", "BNB", "MATIC", "SOL", "DOGE", "XRP")):
-            # Crypto -> SuperTrend ADX Momentum
+            # Crypto -> RSI + Stoch Extreme Scalp
             st = next(
-                (s for s in strategies if s["id"] == "supertrend_adx_momentum"), strategies[0]
+                (s for s in strategies if s["id"] == "rsi_stochastic_extreme"), strategies[0]
             )
             params = {
-                "atr_period": 10,
-                "atr_multiplier": 3.0,
-                "adx_threshold": 24.0,
+                "rsi_period": 14,
+                "rsi_oversold": 25.0,
+                "rsi_overbought": 75.0,
+                "stoch_k": 14,
+                "stoch_d": 3,
+                "stoch_oversold": 20.0,
+                "stoch_overbought": 80.0,
                 "base_expiration_bars": expiration_bars,
             }
-            rationale = f"Оптимально для крипто-волатильності {asset}"
+            rationale = f"Подвійне виснаження осциляторів для крипто-активу {asset}"
         elif any(
@@ -298,22 +302,23 @@
-            # Forex -> Bollinger ATR Reversion or Support/Resistance Bounce
+            # Forex -> S&R Bounce (JPY/GBP) or RSI + Stoch Extreme Scalp
             if "JPY" in sym or "GBP" in sym:
                 st = next(
                     (s for s in strategies if s["id"] == "support_resistance_bounce"), strategies[0]
                 )
                 params = {
                     "swing_window": 20,
+                    "rsi_period": 14,
                     "min_wick_ratio": 0.35,
                     "base_expiration_bars": expiration_bars,
                 }
                 rationale = f"Фрактальні рівні відбою для валютного спреду {asset}"
             else:
                 st = next(
-                    (s for s in strategies if s["id"] == "bollinger_atr_reversion"), strategies[0]
+                    (s for s in strategies if s["id"] == "rsi_stochastic_extreme"), strategies[0]
                 )
                 params = {
-                    "bb_length": 20,
-                    "bb_std": 1.9,
-                    "rsi_period": 12,
-                    "rsi_oversold": 30.0,
-                    "rsi_overbought": 70.0,
+                    "rsi_period": 14,
+                    "rsi_oversold": 25.0,
+                    "rsi_overbought": 75.0,
+                    "stoch_k": 14,
+                    "stoch_d": 3,
+                    "stoch_oversold": 20.0,
+                    "stoch_overbought": 80.0,
                     "base_expiration_bars": expiration_bars,
                 }
-                rationale = f"Смуги Боллінджера для канальної торгівлі {asset}"
+                rationale = f"Подвійне виснаження осциляторів для валютної пари {asset}"
         else:
-            # Curated fallback: Primary SuperTrend ADX, Secondary MACD Break
+            # Curated sniper fallback: Primary S&R Bounce, Secondary RSI + Stoch Extreme
             st = next(
-                (s for s in strategies if s["id"] == "supertrend_adx_momentum"),
+                (s for s in strategies if s["id"] == "support_resistance_bounce"),
                 next(
-                    (s for s in strategies if s["id"] == "macd_divergence_break"),
+                    (s for s in strategies if s["id"] == "rsi_stochastic_extreme"),
                     strategies[0],
                 ),
             )
-            if st["id"] == "supertrend_adx_momentum":
+            if st["id"] == "support_resistance_bounce":
                 params = {
-                    "atr_period": 10,
-                    "atr_multiplier": 3.0,
-                    "adx_threshold": 24.0,
+                    "swing_window": 20,
+                    "rsi_period": 14,
+                    "min_wick_ratio": 0.35,
                     "base_expiration_bars": expiration_bars,
                 }
-                rationale = f"Пріоритетний SuperTrend ADX імпульсний профіль для активу {asset}"
-            elif st["id"] == "macd_divergence_break":
+                rationale = f"Пріоритетний Sniper S&R Pin-Bar профіль для активу {asset}"
+            elif st["id"] == "rsi_stochastic_extreme":
                 params = {
-                    "macd_fast": 12,
-                    "macd_slow": 26,
-                    "macd_sign": 9,
+                    "rsi_period": 14,
+                    "rsi_oversold": 25.0,
+                    "rsi_overbought": 75.0,
+                    "stoch_k": 14,
+                    "stoch_d": 3,
+                    "stoch_oversold": 20.0,
+                    "stoch_overbought": 80.0,
                     "base_expiration_bars": expiration_bars,
                 }
-                rationale = f"Вторинний MACD дивергенційний профіль для активу {asset}"
+                rationale = f"Вторинний Sniper RSI + Stoch Extreme профіль для активу {asset}"
             else:
@@ -410,3 +415,7 @@
+        candidate_strategies = [s for s in strategies if s["id"] in PRIORITY_STRATEGIES]
+        if not candidate_strategies:
+            candidate_strategies = strategies
+
-        for strat_meta in strategies:
+        for strat_meta in candidate_strategies:
             strat_id = strat_meta["id"]
```

```diff
--- a/src/strat_trade/domain/strategies/registry.py
+++ b/src/strat_trade/domain/strategies/registry.py
@@ -171,4 +171,4 @@
         # Fallback to default top performers
         meta = _STRATEGIES.get(
-            "supertrend_adx_momentum",
-            _STRATEGIES.get("macd_divergence_break", next(iter(_STRATEGIES.values()))),
+            "support_resistance_bounce",
+            _STRATEGIES.get("rsi_stochastic_extreme", next(iter(_STRATEGIES.values()))),
         )
```

---

## 4. Test Suite Synchronization Plan

When the changes to `auto_matcher.py` and `registry.py` are applied, the following 6 test files must have their legacy assertions synchronized:

### 4.1. `tests/test_strategy_auto_matcher.py`
- In `test_strategy_auto_matcher_fallback_hierarchy`:
  - Update primary fallback expectation for `"UNCLASSIFIED_TOKEN_XYZ"` from `supertrend_adx_momentum` to `support_resistance_bounce` (`swing_window == 20`, `min_wick_ratio == 0.35`).
  - Update secondary fallback expectation from `macd_divergence_break` to `rsi_stochastic_extreme` (`rsi_period == 14`, `stoch_k == 14`).
  - Keep tertiary fallback to `bollinger_atr_reversion` when both are omitted.

### 4.2. `tests/test_strategy_curation_and_asset_filter.py`
- In `test_auto_matcher_toxic_asset_rejection_and_whitelist_boost`:
  - Update `white_res` (`"Gold_otc"`) from `hybrid_multifactors` to `support_resistance_bounce`.
  - Update `fallback_res` (`"RANDOM_SYNTHETIC"`) from `supertrend_adx_momentum` to `support_resistance_bounce`.

### 4.3. `tests/test_phase3_rolling_15_trade_verification.py`
- Rename & update `test_phase3_automatcher_unclassified_asset_primary_fallback_supertrend` -> `test_phase3_automatcher_unclassified_asset_primary_fallback_sniper_sr` asserting `res.strategy_id == "support_resistance_bounce"`.
- Rename & update `test_phase3_automatcher_unclassified_asset_secondary_fallback_macd` -> `test_phase3_automatcher_unclassified_asset_secondary_fallback_sniper_rsi_stoch` asserting `res.strategy_id == "rsi_stochastic_extreme"`.
- In `test_phase3_automatcher_never_defaults_to_hybrid_multifactors`: assert `res.strategy_id == "support_resistance_bounce"`.
- In `test_phase3_strategy_registry_fallback_to_supertrend`: update to assert fallback instance is `SupportResistanceBounceStrategy`.

### 4.4. `tests/test_m1_adversarial_challenge.py`
- In `test_auto_matcher_unclassified_symbols_primary_fallback`: assert `res.strategy_id == "support_resistance_bounce"`.
- In `test_auto_matcher_limited_strategy_pools_fallback_hierarchy`:
  - Full catalog fallback -> `support_resistance_bounce`
  - Pool without `support_resistance_bounce` -> `rsi_stochastic_extreme`
  - Pool without both -> first available strategy.

### 4.5. `tests/test_m1_adversarial_empirical_stress.py`
- In `test_automatcher_unclassified_asset_primary_and_secondary_fallback`:
  - Primary fallback -> `support_resistance_bounce`
  - Secondary fallback -> `rsi_stochastic_extreme`
  - Tertiary fallback -> first strategy in pool.
- In `test_automatcher_find_optimal_strategy_edge_case_inputs`:
  - Empty candles, sparse candles, sparse DataFrame -> all return `support_resistance_bounce`.

### 4.6. `tests/test_m4_empirical_challenger_2.py`
- Automatically validates that whitelist asset assignments belong to `PRIORITY_STRATEGIES` (`support_resistance_bounce`, `rsi_stochastic_extreme`, `ema_pullback_trend`).

---

## 5. Risk Assessment & Verification Strategy

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Legacy strategy tests breaking due to removed registry entries | Low | High | Do NOT delete strategy classes from `_STRATEGIES` in `registry.py`. Only update priority sets and fallback resolvers. |
| Fallback parameter mismatch during backtest or bot execution | Low | Medium | Standardize parameter dictionaries across all heuristic branches to exactly match strategy `ParameterDef` defaults. |
| Test suite regressions across other milestones | Low | High | Run full `.venv/bin/pytest` test suite (662+ items) and verify 100% pass with 0 errors. |

---

## 6. Execution Command for Verification
```bash
.venv/bin/pytest tests/test_strategy_auto_matcher.py tests/test_strategy_curation_and_asset_filter.py tests/test_phase3_rolling_15_trade_verification.py tests/test_m1_adversarial_challenge.py tests/test_m1_adversarial_empirical_stress.py -v
.venv/bin/pytest
```
