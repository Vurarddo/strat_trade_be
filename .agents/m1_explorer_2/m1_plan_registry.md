# M1 Implementation Plan: Strategy Registry & Fallback Resolution

## Executive Summary
This document provides the exhaustive analysis and concrete implementation plan for `src/strat_trade/domain/strategies/registry.py` and its ecosystem under Milestone 1 (M1) of the Sniper Confluence Trading System transformation.

The primary objectives are:
1. **Preserve all 8 strategy classes** in `_STRATEGIES` to guarantee full backward compatibility with existing backtest logs, parameter optimization grids, and API endpoints.
2. **Update default fallback resolution** in `get_strategy_instance()` to route unrecognized/malformed strategy identifiers to `support_resistance_bounce` (primary fallback) and `rsi_stochastic_extreme` (secondary fallback), replacing the legacy `supertrend_adx_momentum` / `macd_divergence_break` fallback chain.
3. **Validate argument inspection & keyword filtering** to ensure that fallback instantiation never raises `TypeError` regardless of what unexpected parameters are provided in configs or payloads.
4. **Identify all downstream tests and modules** requiring synchronization with the new fallback behavior.

---

## 1. Registry Architecture & Strategy Inventory

### 1.1 Registered Strategies (`_STRATEGIES`)
The central registry dictionary `_STRATEGIES: dict[str, StrategyMetadata]` in `src/strat_trade/domain/strategies/registry.py` must retain all 8 strategy definitions:

| # | Strategy Identifier | Strategy Class | Category | Recommended Timeframes | Recommended Assets | Role in System |
|---|---------------------|----------------|----------|------------------------|--------------------|----------------|
| 1 | `hybrid_multifactors` | `HybridMultiFactorsStrategy` | Hybrid Multi-Factor | `[60, 180, 300]` | `EURUSD_otc`, `GBPUSD_otc`, `USDJPY_otc` | Legacy multi-factor indicator combo (deactivated from live bot priority) |
| 2 | `bollinger_atr_reversion` | `BollingerAtrReversionStrategy` | Mean Reversion | `[60, 180]` | `EURUSD_otc`, `GBPUSD_otc`, `AUDUSD_otc` | OTC flat channel reversal |
| 3 | `ema_pullback_trend` | `EmaPullbackTrendStrategy` | Trend Following | `[60, 300]` | `EURUSD`, `GBPUSD`, `USDJPY_otc` | **Sniper Priority Trio** (Trend continuation on EMA 9/21 pullback) |
| 4 | `rsi_stochastic_extreme` | `RsiStochasticExtremeStrategy` | Scalping Reversal | `[60]` | `EURUSD_otc`, `USDJPY_otc`, `BTCUSD_otc` | **Sniper Priority Trio** & **Secondary Fallback** (Dual oscillator exhaustion) |
| 5 | `macd_divergence_break` | `MacdDivergenceBreakStrategy` | Reversal Divergence | `[60, 180, 300]` | `EURUSD_otc`, `GBPUSD_otc` | Legacy reversal divergence (deactivated from live bot priority) |
| 6 | `volatility_squeeze_breakout` | `VolatilitySqueezeBreakoutStrategy` | Volatility Breakout | `[60, 180]` | `EURUSD_otc`, `GBPUSD_otc`, `USDJPY_otc` | TTM Bollinger/Keltner squeeze breakout |
| 7 | `supertrend_adx_momentum` | `SupertrendAdxMomentumStrategy` | Momentum Trend | `[60, 300]` | `EURUSD`, `GBPUSD`, `EURUSD_otc` | Legacy trend momentum |
| 8 | `support_resistance_bounce` | `SupportResistanceBounceStrategy` | Price Action / S&R | `[60, 180]` | `EURUSD_otc`, `GBPUSD_otc`, `AUDUSD_otc` | **Sniper Priority Trio** & **Primary Fallback** (Pin-bar rejection at swing S&R) |

### 1.2 Preservation Rationale
- **API Continuity**: `GET /api/backtest/strategies` calls `list_available_strategies()` to expose available strategy metadata, descriptions, and parameter definitions to the UI and external API clients. Keeping all 8 strategies preserves schema validation and UI drop-down options for manual backtests.
- **Historical Backtesting**: Historical trade analysis and verification suites (`verification_runner.py`, `portfolio_engine.py`) can backtest any strategy ID without raising `KeyError`.
- **Decoupled Activation**: Active strategy curation and deactivation are handled by `StrategyAutoMatcher.PRIORITY_STRATEGIES` in `auto_matcher.py`, keeping domain catalog registration clean, cohesive, and decoupled.

---

## 2. Fallback Resolution in `get_strategy_instance()`

### 2.1 Current Implementation vs Proposed Implementation

#### Current (`registry.py:163-188`)
```python
def get_strategy_instance(
    strategy_name: str, params: dict[str, Any] | None = None, **kwargs: Any
) -> BaseStrategy:
    import inspect

    meta = _STRATEGIES.get(strategy_name.strip().lower())
    if not meta:
        # Fallback to default top performers
        meta = _STRATEGIES.get(
            "supertrend_adx_momentum",
            _STRATEGIES.get("macd_divergence_break", next(iter(_STRATEGIES.values()))),
        )

    combined_params = dict(params or {})
    combined_params.update(kwargs)

    sig = inspect.signature(meta.cls.__init__)
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    if has_var_kw:
        filtered = combined_params
    else:
        valid_names = set(sig.parameters.keys()) - {"self"}
        filtered = {k: v for k, v in combined_params.items() if k in valid_names}

    return meta.cls(**filtered)
```

#### Proposed Updated Implementation
```python
def get_strategy_instance(
    strategy_name: str, params: dict[str, Any] | None = None, **kwargs: Any
) -> BaseStrategy:
    import inspect

    meta = _STRATEGIES.get(strategy_name.strip().lower()) if isinstance(strategy_name, str) else None
    if not meta:
        # Fallback to default top sniper performers
        meta = _STRATEGIES.get(
            "support_resistance_bounce",
            _STRATEGIES.get("rsi_stochastic_extreme", next(iter(_STRATEGIES.values()))),
        )

    combined_params = dict(params or {})
    combined_params.update(kwargs)

    sig = inspect.signature(meta.cls.__init__)
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    if has_var_kw:
        filtered = combined_params
    else:
        valid_names = set(sig.parameters.keys()) - {"self"}
        filtered = {k: v for k, v in combined_params.items() if k in valid_names}

    return meta.cls(**filtered)
```

### 2.2 Fallback Precedence Chain
1. **Direct Match**: If `strategy_name.strip().lower()` exists in `_STRATEGIES`, return the corresponding strategy metadata.
2. **Primary Fallback**: `"support_resistance_bounce"` (`SupportResistanceBounceStrategy`) — Proven 57.6% win rate on real broker feeds with fractal swing rejection pin-bars.
3. **Secondary Fallback**: `"rsi_stochastic_extreme"` (`RsiStochasticExtremeStrategy`) — Proven 71.4% win rate on real broker feeds with dual-oscillator exhaustion.
4. **Tertiary Guard**: `next(iter(_STRATEGIES.values()))` — Failsafe fallback ensuring that even in mock test environments or dynamic dictionaries, `meta` is never `None`.

### 2.3 Parameter Signature Inspection & Kwargs Filtration
When an unrecognized strategy name is requested with parameters intended for another strategy (e.g. `atr_period=10`, `macd_fast=12`, `bogus_key="foo"`), the signature inspection ensures:
- `sig = inspect.signature(meta.cls.__init__)`
- `valid_names = set(sig.parameters.keys()) - {"self"}`
- `filtered = {k: v for k, v in combined_params.items() if k in valid_names}`

For `SupportResistanceBounceStrategy`, `valid_names` are:
`{"swing_window", "rsi_period", "min_wick_ratio", "base_expiration_bars", "adaptive_expiration_enabled"}`.
Any incompatible parameters (`atr_period`, `macd_fast`, `bogus_key`) are safely discarded without error, guaranteeing robust and crash-free fallback instantiation.

---

## 3. Backward Compatibility & Consumer Audit

### 3.1 Direct Consumers of `registry.py`

| File | Function / Class | Usage | Compatibility Impact |
|---|---|---|---|
| `src/strat_trade/domain/backtest/engine.py` | `BinaryBacktestEngine._create_strategy()` | Calls `get_strategy_instance(self.config.strategy_name, **params)` | Fully compatible. Unknown strategy names now safely resolve to `SupportResistanceBounceStrategy`. |
| `src/strat_trade/domain/backtest/portfolio_engine.py` | `PortfolioBacktestEngine.__init__()` | Calls `get_strategy_instance(config.strategy_name, **params)` | Fully compatible. |
| `src/strat_trade/domain/trading/bot_engine.py` | `LiveDemoBotEngine.start()` | Calls `get_strategy_instance(a.strategy_id, **a.parameters)` | Fully compatible. Live bot will safely initialize fallback sniper strategy if an invalid ID is passed. |
| `src/strat_trade/domain/optimizer/auto_matcher.py` | `StrategyAutoMatcher.find_optimal_strategy_for_asset()` | Calls `list_available_strategies()` | Fully compatible. Evaluates all 8 strategies. |
| `src/strat_trade/api/routes/backtest.py` | `list_strategies_endpoint()` | Calls `list_available_strategies()` | Fully compatible. Returns all 8 strategies with metadata and parameter definitions. |
| `src/strat_trade/use_cases/optimize_strategy.py` | `_build_default_grid()` | Accesses `_STRATEGIES` | Fully compatible. |
| `src/strat_trade/domain/backtest/verification_runner.py` | `_build_fallback_grid()` | Accesses `_STRATEGIES` | Fully compatible. |

---

## 4. Test Suite Synchronization Plan

When the fallback in `registry.py` is updated from `supertrend_adx_momentum` / `macd_divergence_break` to `support_resistance_bounce` / `rsi_stochastic_extreme`, the following unit tests must be synchronized:

### 4.1 `tests/test_m1_adversarial_challenge.py` (lines 452–463)
- **Current**: Asserts `isinstance(inst, SupertrendAdxMomentumStrategy)` for unknown/empty/whitespace strings.
- **Update**: Assert `isinstance(inst, SupportResistanceBounceStrategy)`.

### 4.2 `tests/test_m1_adversarial_empirical_stress.py` (lines 202–228)
- **Current**: Fuzz test asserts `isinstance(strat, SupertrendAdxMomentumStrategy)` for invalid/malformed strings.
- **Update**: Assert `isinstance(strat, SupportResistanceBounceStrategy)`.

### 4.3 `tests/test_phase3_rolling_15_trade_verification.py` (lines 829–838)
- **Current**: `test_phase3_strategy_registry_fallback_to_supertrend()` asserts `isinstance(strat, SupertrendAdxMomentumStrategy)`.
- **Update**: Rename to `test_phase3_strategy_registry_fallback_to_support_resistance_bounce()` and assert `isinstance(strat, SupportResistanceBounceStrategy)`.

---

## 5. Concrete Diff Instructions

### 5.1 Diff for `src/strat_trade/domain/strategies/registry.py`

```diff
--- a/src/strat_trade/domain/strategies/registry.py
+++ b/src/strat_trade/domain/strategies/registry.py
@@ -165,13 +165,13 @@ def get_strategy_instance(
 ) -> BaseStrategy:
     import inspect
 
-    meta = _STRATEGIES.get(strategy_name.strip().lower())
+    meta = _STRATEGIES.get(strategy_name.strip().lower()) if isinstance(strategy_name, str) else None
     if not meta:
-        # Fallback to default top performers
+        # Fallback to default top sniper performers
         meta = _STRATEGIES.get(
-            "supertrend_adx_momentum",
-            _STRATEGIES.get("macd_divergence_break", next(iter(_STRATEGIES.values()))),
+            "support_resistance_bounce",
+            _STRATEGIES.get("rsi_stochastic_extreme", next(iter(_STRATEGIES.values()))),
         )
 
     combined_params = dict(params or {})
```

### 5.2 Diff for `tests/test_m1_adversarial_challenge.py`

```diff
--- a/tests/test_m1_adversarial_challenge.py
+++ b/tests/test_m1_adversarial_challenge.py
@@ -15,7 +15,7 @@ from strat_trade.domain.strategies.registry import (
     get_strategy_instance,
     list_available_strategies,
 )
-from strat_trade.domain.strategies.supertrend_adx_momentum import SupertrendAdxMomentumStrategy
+from strat_trade.domain.strategies.support_resistance_bounce import SupportResistanceBounceStrategy
 
 
 # =====================================================================
@@ -449,16 +449,16 @@ def test_adx_concordance_regime_filtering_stress():
 # =====================================================================
 
 
-def test_registry_fallback_to_supertrend():
-    """Verify registry get_strategy_instance falls back to SuperTrend on unknown strategy name."""
+def test_registry_fallback_to_support_resistance_bounce():
+    """Verify registry get_strategy_instance falls back to Support & Resistance Bounce on unknown strategy name."""
     inst_unknown = get_strategy_instance("nonexistent_unknown_strategy_xyz")
-    assert isinstance(inst_unknown, SupertrendAdxMomentumStrategy)
+    assert isinstance(inst_unknown, SupportResistanceBounceStrategy)
 
     inst_empty = get_strategy_instance("")
-    assert isinstance(inst_empty, SupertrendAdxMomentumStrategy)
+    assert isinstance(inst_empty, SupportResistanceBounceStrategy)
 
     inst_whitespace = get_strategy_instance("   ")
-    assert isinstance(inst_whitespace, SupertrendAdxMomentumStrategy)
+    assert isinstance(inst_whitespace, SupportResistanceBounceStrategy)
 
 
 # =====================================================================
```

### 5.3 Diff for `tests/test_m1_adversarial_empirical_stress.py`

```diff
--- a/tests/test_m1_adversarial_empirical_stress.py
+++ b/tests/test_m1_adversarial_empirical_stress.py
@@ -28,7 +28,7 @@ from strat_trade.domain.strategies.registry import (
 )
 from strat_trade.domain.strategies.rsi_stochastic_extreme import RsiStochasticExtremeStrategy
 from strat_trade.domain.strategies.supertrend_adx_momentum import SupertrendAdxMomentumStrategy
-from strat_trade.domain.strategies.support_resistance_bounce import SupportResistanceBounceStrategy
+from strat_trade.domain.strategies.support_resistance_bounce import SupportResistanceBounceStrategy
 from strat_trade.domain.trading.asset_filter import (
     canonical_asset_key,
     is_toxic_asset,
@@ -205,7 +205,7 @@ def test_registry_fallback_arbitrary_and_malformed_names():
     Invariants:
     1. NEVER raises an unhandled exception or KeyError.
     2. Always returns a valid BaseStrategy instance.
-    3. Defaults to SupertrendAdxMomentumStrategy as primary fallback.
+    3. Defaults to SupportResistanceBounceStrategy as primary fallback.
     """
     fuzz_inputs = [
         "non_existent_strategy_xyz",
@@ -221,8 +221,8 @@ def test_registry_fallback_arbitrary_and_malformed_names():
     for name in fuzz_inputs:
         strat = get_strategy_instance(name)
         assert isinstance(strat, BaseStrategy), f"Failed for name '{name}'"
-        assert isinstance(strat, SupertrendAdxMomentumStrategy), (
-            f"Expected fallback SupertrendAdxMomentumStrategy for '{name}', got {type(strat)}"
+        assert isinstance(strat, SupportResistanceBounceStrategy), (
+            f"Expected fallback SupportResistanceBounceStrategy for '{name}', got {type(strat)}"
         )
```

### 5.4 Diff for `tests/test_phase3_rolling_15_trade_verification.py`

```diff
--- a/tests/test_phase3_rolling_15_trade_verification.py
+++ b/tests/test_phase3_rolling_15_trade_verification.py
@@ -826,14 +826,14 @@ async def test_phase3_auto_matcher_unmatched_asset_fallback() -> None:
     assert res.strategy_id == "supertrend_adx_momentum"
 
 
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
 
 
 # =========================================================================
```

---

## 6. Verification and Acceptance Criteria

1. **All 8 Strategies Preserved**:
   - `len(list_available_strategies()) == 8`
   - IDs: `{"hybrid_multifactors", "bollinger_atr_reversion", "ema_pullback_trend", "rsi_stochastic_extreme", "macd_divergence_break", "volatility_squeeze_breakout", "supertrend_adx_momentum", "support_resistance_bounce"}`.
2. **Fallback Resolution**:
   - `get_strategy_instance("unknown_strategy")` returns an instance of `SupportResistanceBounceStrategy`.
   - `get_strategy_instance("")` returns an instance of `SupportResistanceBounceStrategy`.
   - `get_strategy_instance("   ")` returns an instance of `SupportResistanceBounceStrategy`.
   - If `support_resistance_bounce` is simulated as missing, secondary fallback is `RsiStochasticExtremeStrategy`.
3. **Kwargs Filtering**:
   - Passing unknown kwargs e.g. `get_strategy_instance("support_resistance_bounce", bogus_param=123)` safely initializes without `TypeError`.
4. **Test Suite**:
   - 100% test pass on `pytest` across all test files (662+ items).
   - 0 ruff errors on `ruff check .`.
