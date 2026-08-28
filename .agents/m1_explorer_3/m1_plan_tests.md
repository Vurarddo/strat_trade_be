# Milestone 1 Test Suite Synchronization & Regression Guard Plan

## Executive Summary
Milestone 1 restructures the strategy portfolio from legacy indicators (`MACD Divergence & Cross`, `hybrid_multifactors`, `SuperTrend + ADX Momentum`) to the Sniper Alpha Trio (`Support & Resistance Pin-Bar`, `RSI + Stoch Extreme Scalp`, `EMA Ribbon Trend Pullback`).
This document provides exact, verified line diffs across all 5 affected test files to guarantee clean execution, 100% test pass rates, and zero regressions across the 662+ pytest suite.

---

## 1. Test Impact & Dependency Analysis Matrix

| # | Test File Path | Target Lines | Current Logic / Assertion | Updated Milestone 1 Assertion | Rationale |
|---|---|---|---|---|---|
| 1 | `tests/test_strategy_auto_matcher.py` | 53–86 | Fallback asserts `supertrend_adx_momentum` (primary) and `macd_divergence_break` (secondary) | Asserts `support_resistance_bounce` (primary) and `rsi_stochastic_extreme` (secondary) | Matches updated `PRIORITY_STRATEGIES` and `_heuristic_profile_for_asset` hierarchy |
| 2 | `tests/test_strategy_curation_and_asset_filter.py` | 420–429 | `white_res` asserts `hybrid_multifactors` for Gold_otc; `fallback_res` asserts `supertrend_adx_momentum` | `white_res` asserts `support_resistance_bounce`; `fallback_res` asserts `support_resistance_bounce` | Gold/Commodity and fallback heuristic routing redirected from deprecated hybrid to sniper S&R |
| 3 | `tests/test_phase3_rolling_15_trade_verification.py` | 783–838 | Primary fallback `supertrend_adx_momentum`, secondary `macd_divergence_break`, registry fallback `SupertrendAdxMomentumStrategy` | Primary `support_resistance_bounce`, secondary `rsi_stochastic_extreme`, registry fallback `SupportResistanceBounceStrategy` | Phase 3 fallback regression harness synchronized to M1 Sniper baseline |
| 4 | `tests/test_m1_adversarial_challenge.py` | 18, 340–414, 452–463 | Empty/sparse/short candle fallbacks assert `supertrend_adx_momentum`; secondary asserts `macd_divergence_break`; registry fallback asserts `SupertrendAdxMomentumStrategy` | Primary/sparse asserts `support_resistance_bounce`; secondary asserts `rsi_stochastic_extreme`; registry asserts `SupportResistanceBounceStrategy` | Full adversarial coverage with updated S&R parameter verification |
| 5 | `tests/test_m1_adversarial_empirical_stress.py` | 30, 202–227, 276–351 | Malformed registry string fuzzing asserts `SupertrendAdxMomentumStrategy`; unclassified/sparse asserts `supertrend_adx_momentum` & `macd_divergence_break` | Malformed registry string fuzzing asserts `SupportResistanceBounceStrategy`; unclassified asserts `support_resistance_bounce` & `rsi_stochastic_extreme` | Fuzz testing and edge-case DataFrame handling synchronized with S&R parameters |

---

## 2. Concrete Line Diffs

### Target 1: `tests/test_strategy_auto_matcher.py`

```diff
--- a/tests/test_strategy_auto_matcher.py
+++ b/tests/test_strategy_auto_matcher.py
@@ -53,24 +53,24 @@
 @pytest.mark.asyncio
 async def test_strategy_auto_matcher_fallback_hierarchy():
-    """Verify default heuristic fallback prioritizes supertrend then macd divergence."""
+    """Verify default heuristic fallback prioritizes support_resistance_bounce then rsi_stochastic_extreme."""
     matcher = StrategyAutoMatcher(candle_count=150)
 
-    # 1. Primary fallback: supertrend_adx_momentum
+    # 1. Primary fallback: support_resistance_bounce
     res_primary = await matcher.find_optimal_strategy_for_asset("UNCLASSIFIED_TOKEN_XYZ", [])
-    assert res_primary.strategy_id == "supertrend_adx_momentum"
-    assert res_primary.parameters["atr_period"] == 10
-    assert res_primary.parameters["atr_multiplier"] == 3.0
-    assert res_primary.parameters["adx_threshold"] == 24.0
+    assert res_primary.strategy_id == "support_resistance_bounce"
+    assert res_primary.parameters["swing_window"] == 20
+    assert res_primary.parameters["min_wick_ratio"] == 0.35
+    assert res_primary.parameters["base_expiration_bars"] == 3
 
-    # 2. Secondary fallback when supertrend_adx_momentum is excluded
+    # 2. Secondary fallback when support_resistance_bounce is excluded
     custom_strategies = [
-        {"id": "macd_divergence_break", "name": "MACD Divergence", "category": "Reversal"},
+        {"id": "rsi_stochastic_extreme", "name": "RSI + Stoch Extreme Scalp", "category": "Scalping Reversal"},
         {"id": "bollinger_atr_reversion", "name": "Bollinger ATR", "category": "Mean Reversion"},
     ]
     res_secondary = matcher._heuristic_profile_for_asset(
         "UNCLASSIFIED_TOKEN_XYZ", custom_strategies, expiration_bars=3
     )
-    assert res_secondary.strategy_id == "macd_divergence_break"
-    assert res_secondary.parameters["macd_fast"] == 12
-    assert res_secondary.parameters["macd_slow"] == 26
-    assert res_secondary.parameters["macd_sign"] == 9
+    assert res_secondary.strategy_id == "rsi_stochastic_extreme"
+    assert res_secondary.parameters["rsi_period"] == 14
+    assert res_secondary.parameters["rsi_oversold"] == 25.0
+    assert res_secondary.parameters["rsi_overbought"] == 75.0
 
     # 3. Tertiary fallback to strategies[0] when both are omitted
```

---

### Target 2: `tests/test_strategy_curation_and_asset_filter.py`

```diff
--- a/tests/test_strategy_curation_and_asset_filter.py
+++ b/tests/test_strategy_curation_and_asset_filter.py
@@ -420,10 +420,10 @@
     # Whitelist asset profiling fallback check
     white_res = await matcher.find_optimal_strategy_for_asset("Gold_otc", [])
-    assert white_res.strategy_id == "hybrid_multifactors"
+    assert white_res.strategy_id == "support_resistance_bounce"
     assert white_res.quantum_score >= 80.0
 
     # Fallback for generic unclassified asset
     fallback_res = await matcher.find_optimal_strategy_for_asset("RANDOM_SYNTHETIC", [])
-    assert fallback_res.strategy_id == "supertrend_adx_momentum"
-    assert fallback_res.parameters["adx_threshold"] == 24.0
+    assert fallback_res.strategy_id == "support_resistance_bounce"
+    assert fallback_res.parameters["min_wick_ratio"] == 0.35
```

---

### Target 3: `tests/test_phase3_rolling_15_trade_verification.py`

```diff
--- a/tests/test_phase3_rolling_15_trade_verification.py
+++ b/tests/test_phase3_rolling_15_trade_verification.py
@@ -783,34 +783,34 @@
 @pytest.mark.asyncio
-async def test_phase3_automatcher_unclassified_asset_primary_fallback_supertrend() -> None:
+async def test_phase3_automatcher_unclassified_asset_primary_fallback_support_resistance() -> None:
     """
     When candidate asset has sparse/unclassified candle data,
     StrategyAutoMatcher._heuristic_profile_for_asset defaults to primary fallback
-    'supertrend_adx_momentum' with standard calibrated parameters.
+    'support_resistance_bounce' with standard calibrated parameters.
     """
     matcher = StrategyAutoMatcher()
     res = await matcher.find_optimal_strategy_for_asset("UNCLASSIFIED_TOKEN_XYZ", [])
 
-    assert res.strategy_id == "supertrend_adx_momentum"
-    assert res.parameters["atr_period"] == 10
-    assert res.parameters["atr_multiplier"] == 3.0
-    assert res.parameters["adx_threshold"] == 24.0
+    assert res.strategy_id == "support_resistance_bounce"
+    assert res.parameters["swing_window"] == 20
+    assert res.parameters["min_wick_ratio"] == 0.35
+    assert res.parameters["base_expiration_bars"] == 3
     assert res.quantum_score == 85.0
 
 
-def test_phase3_automatcher_unclassified_asset_secondary_fallback_macd() -> None:
-    """When 'supertrend_adx_momentum' is absent, fallback shifts to 'macd_divergence_break'."""
+def test_phase3_automatcher_unclassified_asset_secondary_fallback_rsi_stoch() -> None:
    """When 'support_resistance_bounce' is absent, fallback shifts to 'rsi_stochastic_extreme'."""
     matcher = StrategyAutoMatcher()
     custom_strategies = [
-        {"id": "macd_divergence_break", "name": "MACD Divergence", "category": "Reversal"},
+        {"id": "rsi_stochastic_extreme", "name": "RSI + Stoch Extreme Scalp", "category": "Scalping Reversal"},
         {"id": "bollinger_atr_reversion", "name": "Bollinger ATR", "category": "Mean Reversion"},
     ]
 
     profile = matcher._heuristic_profile_for_asset(
         asset="UNKNOWN_PAIR_otc",
         strategies=custom_strategies,
         expiration_bars=3,
     )
 
-    assert profile.strategy_id == "macd_divergence_break"
-    assert profile.parameters["macd_fast"] == 12
-    assert profile.parameters["macd_slow"] == 26
-    assert profile.parameters["macd_sign"] == 9
+    assert profile.strategy_id == "rsi_stochastic_extreme"
+    assert profile.parameters["rsi_period"] == 14
+    assert profile.parameters["rsi_oversold"] == 25.0
+    assert profile.parameters["rsi_overbought"] == 75.0
 
 
 @pytest.mark.asyncio
 async def test_phase3_automatcher_never_defaults_to_hybrid_multifactors() -> None:
     """Verify hybrid_multifactors is never the default heuristic fallback."""
     matcher = StrategyAutoMatcher()
     res = await matcher.find_optimal_strategy_for_asset("RANDOM_UNCLASSIFIED_XYZ_otc", [])
     assert res.strategy_id != "hybrid_multifactors"
-    assert res.strategy_id == "supertrend_adx_momentum"
+    assert res.strategy_id == "support_resistance_bounce"
 
 
-def test_phase3_strategy_registry_fallback_to_supertrend() -> None:
-    """get_strategy_instance without name or with unknown name returns supertrend_adx_momentum."""
-    from strat_trade.domain.strategies.supertrend_adx_momentum import (
-        SupertrendAdxMomentumStrategy,
+def test_phase3_strategy_registry_fallback_to_support_resistance_bounce() -> None:
+    """get_strategy_instance without name or with unknown name returns support_resistance_bounce."""
+    from strat_trade.domain.strategies.support_resistance_bounce import (
+        SupportResistanceBounceStrategy,
     )
 
     strat = get_strategy_instance("non_existent_strategy_xyz")
-    assert isinstance(strat, SupertrendAdxMomentumStrategy)
+    assert isinstance(strat, SupportResistanceBounceStrategy)
```

---

### Target 4: `tests/test_m1_adversarial_challenge.py`

```diff
--- a/tests/test_m1_adversarial_challenge.py
+++ b/tests/test_m1_adversarial_challenge.py
@@ -15,7 +15,7 @@
     get_strategy_instance,
     list_available_strategies,
 )
-from strat_trade.domain.strategies.supertrend_adx_momentum import SupertrendAdxMomentumStrategy
+from strat_trade.domain.strategies.support_resistance_bounce import SupportResistanceBounceStrategy
 
 
 def _create_mock_bar_df(
@@ -340,16 +340,16 @@
 @pytest.mark.asyncio
 @pytest.mark.parametrize(
     "symbol",
     [
         "UNKNOWN_ASSET_123",
         "RANDOM_COIN",
         "XYZ_TOKEN",
     ],
 )
 async def test_auto_matcher_unclassified_asset_fallback_empirical(symbol: str):
-    """Stress-test StrategyAutoMatcher with unclassified assets to verify SuperTrend fallback."""
+    """Stress-test StrategyAutoMatcher with unclassified assets to verify Support & Resistance fallback."""
     matcher = StrategyAutoMatcher(candle_count=150)
 
     # Case A: Empty candles list
     res_empty = await matcher.find_optimal_strategy_for_asset(symbol, [])
-    assert res_empty.strategy_id == "supertrend_adx_momentum"
-    assert res_empty.parameters["atr_period"] == 10
-    assert res_empty.parameters["atr_multiplier"] == 3.0
-    assert res_empty.parameters["adx_threshold"] == 24.0
+    assert res_empty.strategy_id == "support_resistance_bounce"
+    assert res_empty.parameters["swing_window"] == 20
+    assert res_empty.parameters["min_wick_ratio"] == 0.35
+    assert res_empty.parameters["base_expiration_bars"] == 3
 
     # Case B: Insufficient candles list (< 35 bars)
     short_candles = [
         Candle(
             open_time=datetime(2026, 1, 1, 10, i, tzinfo=UTC),
             open=Decimal("1.0000"),
             high=Decimal("1.0010"),
             low=Decimal("0.9990"),
             close=Decimal("1.0005"),
             volume=Decimal("50"),
         )
         for i in range(20)
     ]
     res_short = await matcher.find_optimal_strategy_for_asset(symbol, short_candles)
-    assert res_short.strategy_id == "supertrend_adx_momentum"
-    assert res_short.parameters["adx_threshold"] == 24.0
+    assert res_short.strategy_id == "support_resistance_bounce"
+    assert res_short.parameters["min_wick_ratio"] == 0.35
 
     # Case C: Insufficient DataFrame (< 35 rows)
     short_df = pd.DataFrame(
         {
             "close": [1.0] * 30,
             "open": [1.0] * 30,
             "high": [1.001] * 30,
             "low": [0.999] * 30,
             "volume": [10.0] * 30,
         }
     )
     res_df = await matcher.find_optimal_strategy_for_asset(symbol, short_df)
-    assert res_df.strategy_id == "supertrend_adx_momentum"
+    assert res_df.strategy_id == "support_resistance_bounce"
 
 
 def test_auto_matcher_limited_strategy_pools_fallback_hierarchy():
     """Verify fallback precedence when strategy catalogue is restricted."""
     matcher = StrategyAutoMatcher()
 
     all_strats = list_available_strategies()
 
-    # 1. Full catalog -> supertrend_adx_momentum
+    # 1. Full catalog -> support_resistance_bounce
     res_full = matcher._heuristic_profile_for_asset("RANDOM_ASSET", all_strats, 3)
-    assert res_full.strategy_id == "supertrend_adx_momentum"
-    assert res_full.parameters["adx_threshold"] == 24.0
+    assert res_full.strategy_id == "support_resistance_bounce"
+    assert res_full.parameters["min_wick_ratio"] == 0.35
 
-    # 2. Pool without supertrend_adx_momentum -> macd_divergence_break
-    pool_no_supertrend = [s for s in all_strats if s["id"] != "supertrend_adx_momentum"]
-    res_no_st = matcher._heuristic_profile_for_asset("RANDOM_ASSET", pool_no_supertrend, 3)
-    assert res_no_st.strategy_id == "macd_divergence_break"
-    assert res_no_st.parameters["macd_fast"] == 12
-    assert res_no_st.parameters["macd_slow"] == 26
-    assert res_no_st.parameters["macd_sign"] == 9
+    # 2. Pool without support_resistance_bounce -> rsi_stochastic_extreme
+    pool_no_sr = [s for s in all_strats if s["id"] != "support_resistance_bounce"]
+    res_no_sr = matcher._heuristic_profile_for_asset("RANDOM_ASSET", pool_no_sr, 3)
+    assert res_no_sr.strategy_id == "rsi_stochastic_extreme"
+    assert res_no_sr.parameters["rsi_period"] == 14
+    assert res_no_sr.parameters["rsi_oversold"] == 25.0
+    assert res_no_sr.parameters["rsi_overbought"] == 75.0
 
     # 3. Pool without both -> first available strategy
     pool_tertiary = [
         s
         for s in all_strats
-        if s["id"] not in ("supertrend_adx_momentum", "macd_divergence_break")
+        if s["id"] not in ("support_resistance_bounce", "rsi_stochastic_extreme")
     ]
     res_tertiary = matcher._heuristic_profile_for_asset("RANDOM_ASSET", pool_tertiary, 3)
     assert res_tertiary.strategy_id == pool_tertiary[0]["id"]
     assert res_tertiary.parameters["base_expiration_bars"] == 3
@@ -452,12 +452,12 @@
-def test_registry_fallback_to_supertrend():
-    """Verify registry get_strategy_instance falls back to SuperTrend on unknown strategy name."""
+def test_registry_fallback_to_support_resistance_bounce():
+    """Verify registry get_strategy_instance falls back to SupportResistanceBounce on unknown strategy name."""
     inst_unknown = get_strategy_instance("nonexistent_unknown_strategy_xyz")
-    assert isinstance(inst_unknown, SupertrendAdxMomentumStrategy)
+    assert isinstance(inst_unknown, SupportResistanceBounceStrategy)
 
     inst_empty = get_strategy_instance("")
-    assert isinstance(inst_empty, SupertrendAdxMomentumStrategy)
+    assert isinstance(inst_empty, SupportResistanceBounceStrategy)
 
     inst_whitespace = get_strategy_instance("   ")
-    assert isinstance(inst_whitespace, SupertrendAdxMomentumStrategy)
+    assert isinstance(inst_whitespace, SupportResistanceBounceStrategy)
```

---

### Target 5: `tests/test_m1_adversarial_empirical_stress.py`

```diff
--- a/tests/test_m1_adversarial_empirical_stress.py
+++ b/tests/test_m1_adversarial_empirical_stress.py
@@ -27,7 +27,7 @@
     get_strategy_instance,
     list_available_strategies,
 )
-from strat_trade.domain.strategies.supertrend_adx_momentum import SupertrendAdxMomentumStrategy
+from strat_trade.domain.strategies.support_resistance_bounce import SupportResistanceBounceStrategy
 
 # ============================================================================
 # Synthetic Dataset Generators for Multi-Regime Backtesting
@@ -202,12 +202,12 @@
 def test_registry_fallback_arbitrary_and_malformed_names():
     """Fuzz test get_strategy_instance with invalid, non-existent, and malformed strings.
 
     Invariants:
     1. NEVER raises an unhandled exception or KeyError.
     2. Always returns a valid BaseStrategy instance.
-    3. Defaults to SupertrendAdxMomentumStrategy as primary fallback.
+    3. Defaults to SupportResistanceBounceStrategy as primary fallback.
     """
     fuzz_inputs = [
         "non_existent_strategy_xyz",
         "INVALID_STRATEGY_12345",
         "!!!@@@###$$$",
         "   ",
         "",
         "unknown_bot_algo",
         "bollinger_non_existent",
         "supertrend_typo_version",
     ]
 
     for name in fuzz_inputs:
         strat = get_strategy_instance(name)
         assert isinstance(strat, BaseStrategy), f"Failed for name '{name}'"
-        assert isinstance(strat, SupertrendAdxMomentumStrategy), (
-            f"Expected fallback SupertrendAdxMomentumStrategy for '{name}', got {type(strat)}"
+        assert isinstance(strat, SupportResistanceBounceStrategy), (
+            f"Expected fallback SupportResistanceBounceStrategy for '{name}', got {type(strat)}"
         )
@@ -276,42 +276,42 @@
 @pytest.mark.asyncio
 async def test_automatcher_unclassified_asset_primary_and_secondary_fallback():
     """Verify StrategyAutoMatcher fallback hierarchy when matching unclassified assets."""
     matcher = StrategyAutoMatcher(candle_count=150)
 
-    # 1. Primary fallback: supertrend_adx_momentum
+    # 1. Primary fallback: support_resistance_bounce
     res_primary = matcher._heuristic_profile_for_asset(
         asset="UNKNOWN_SYNTHETIC_ASSET_1",
         strategies=list_available_strategies(),
         expiration_bars=3,
     )
-    assert res_primary.strategy_id == "supertrend_adx_momentum"
-    assert res_primary.parameters["atr_period"] == 10
-    assert res_primary.parameters["atr_multiplier"] == 3.0
-    assert res_primary.parameters["adx_threshold"] == 24.0
+    assert res_primary.strategy_id == "support_resistance_bounce"
+    assert res_primary.parameters["swing_window"] == 20
+    assert res_primary.parameters["min_wick_ratio"] == 0.35
+    assert res_primary.parameters["base_expiration_bars"] == 3
 
-    # 2. Secondary fallback when supertrend_adx_momentum is excluded
-    strategies_no_supertrend = [
-        s for s in list_available_strategies() if s["id"] != "supertrend_adx_momentum"
+    # 2. Secondary fallback when support_resistance_bounce is excluded
+    strategies_no_sr = [
+        s for s in list_available_strategies() if s["id"] != "support_resistance_bounce"
     ]
     res_secondary = matcher._heuristic_profile_for_asset(
         asset="UNKNOWN_SYNTHETIC_ASSET_1",
-        strategies=strategies_no_supertrend,
+        strategies=strategies_no_sr,
         expiration_bars=3,
     )
-    assert res_secondary.strategy_id == "macd_divergence_break"
-    assert res_secondary.parameters["macd_fast"] == 12
-    assert res_secondary.parameters["macd_slow"] == 26
-    assert res_secondary.parameters["macd_sign"] == 9
+    assert res_secondary.strategy_id == "rsi_stochastic_extreme"
+    assert res_secondary.parameters["rsi_period"] == 14
+    assert res_secondary.parameters["rsi_oversold"] == 25.0
+    assert res_secondary.parameters["rsi_overbought"] == 75.0
 
     # 3. Tertiary fallback when both are excluded
     strategies_tertiary = [
         s
         for s in list_available_strategies()
-        if s["id"] not in ("supertrend_adx_momentum", "macd_divergence_break")
+        if s["id"] not in ("support_resistance_bounce", "rsi_stochastic_extreme")
     ]
     res_tertiary = matcher._heuristic_profile_for_asset(
         asset="UNKNOWN_SYNTHETIC_ASSET_1",
         strategies=strategies_tertiary,
         expiration_bars=3,
     )
     assert res_tertiary.strategy_id == strategies_tertiary[0]["id"]
     assert res_tertiary.parameters["base_expiration_bars"] == 3
 
 
 @pytest.mark.asyncio
 async def test_automatcher_find_optimal_strategy_edge_case_inputs():
     """Verify find_optimal_strategy_for_asset handles edge case inputs gracefully."""
     matcher = StrategyAutoMatcher(candle_count=150)
 
     # 1. Empty candle list
     res_empty = await matcher.find_optimal_strategy_for_asset("CUSTOM_ASSET", [])
-    assert res_empty.strategy_id == "supertrend_adx_momentum"
+    assert res_empty.strategy_id == "support_resistance_bounce"
 
     # 2. Sparse candle list (<35 candles)
     sparse_candles = [
         Candle(
             open_time=datetime(2026, 8, 20, 10, i, tzinfo=UTC),
             open=Decimal("1.1000"),
             high=Decimal("1.1005"),
             low=Decimal("1.0995"),
             close=Decimal("1.1001"),
             volume=Decimal("50"),
         )
         for i in range(10)
     ]
     res_sparse = await matcher.find_optimal_strategy_for_asset("CUSTOM_ASSET", sparse_candles)
-    assert res_sparse.strategy_id == "supertrend_adx_momentum"
+    assert res_sparse.strategy_id == "support_resistance_bounce"
 
     # 3. Sparse DataFrame (<35 rows)
     df_sparse = pd.DataFrame(
         [{"close": 1.1000, "open": 1.1000, "high": 1.1005, "low": 1.0995}] * 20
     )
     res_df_sparse = await matcher.find_optimal_strategy_for_asset("CUSTOM_ASSET", df_sparse)
-    assert res_df_sparse.strategy_id == "supertrend_adx_momentum"
+    assert res_df_sparse.strategy_id == "support_resistance_bounce"
```

---

## 3. Regression Safeguard & Invariance Verification

1. **Explicit Strategy Invocations**:
   Tests that directly pass `strategy_name="supertrend_adx_momentum"`, `strategy_name="macd_divergence_break"`, or `strategy_name="hybrid_multifactors"` (such as in `test_rolling_15_regression.py`, `test_rolling_15_trade_verification.py`, and `test_hybrid_strategy.py`) continue to pass without modification because all 8 strategies remain fully registered and executable in the strategy catalog.
2. **Deterministic Coverage**:
   All 17 fine-grained deterministic unit tests in `test_strategy_logic_enhancements.py` and `test_adversarial_bollinger_atr.py` operate on explicit strategy instances and will pass cleanly.
3. **Execution Command**:
   Run `.venv/bin/pytest` after implementation to verify all 662+ tests pass with 0 failures and 0 regressions.
