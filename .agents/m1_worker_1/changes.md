# Milestone 1: Strategy Portfolio Restructuring (Sniper Edge) — Changes Log

## Summary of Changes
Milestone 1 transitions the automated strategy matching engine from legacy indicator-spam configurations to the high-conviction **Sniper Trio**:
1. **Support & Resistance Pin-Bar** (`support_resistance_bounce`) — 57.6% WR, price-action rejection at key swing levels.
2. **RSI + Stoch Extreme Scalp** (`rsi_stochastic_extreme`) — 71.4% WR, dual-oscillator exhaustion.
3. **EMA Ribbon Trend Pullback** (`ema_pullback_trend`) — 60.0% WR, calibrated overbought/oversold guards.

Legacy strategies (`MACD Divergence & Cross`, `hybrid_multifactors`, `supertrend_adx_momentum`) are cleanly removed from `PRIORITY_STRATEGIES` and default heuristic fallbacks while remaining registered in `_STRATEGIES` (`registry.py`) for backward compatibility and manual/historical backtesting.

---

## 1. Domain Layer Modifications

### 1.1 `src/strat_trade/domain/optimizer/auto_matcher.py`
- **`PRIORITY_STRATEGIES`**: Updated from legacy set to:
  ```python
  PRIORITY_STRATEGIES: frozenset[str] = frozenset(
      {
          "support_resistance_bounce",
          "rsi_stochastic_extreme",
          "ema_pullback_trend",
      }
  )
  ```
- **`_heuristic_profile_for_asset`**:
  - Gold / Commodities (`"GOLD" in sym or "XAU" in sym`): Routes to `support_resistance_bounce` (`swing_window=20, rsi_period=14, min_wick_ratio=0.35, base_expiration_bars=expiration_bars`).
  - Stocks (`"#" in sym or "AAPL" in sym ...`): Routes to `ema_pullback_trend` (`ema_fast=9, ema_mid=21, ema_slow=50, adx_threshold=25.0, rsi_overbought=65.0, rsi_oversold=35.0, stoch_overbought=75.0, stoch_oversold=25.0, base_expiration_bars=expiration_bars`).
  - Crypto (`BTC, ETH, BNB, MATIC, SOL, DOGE, XRP`): Routes to `rsi_stochastic_extreme` (`rsi_period=14, rsi_oversold=25.0, rsi_overbought=75.0, stoch_k=14, stoch_d=3, stoch_oversold=20.0, stoch_overbought=80.0, base_expiration_bars=expiration_bars`).
  - Forex Pairs:
    - JPY / GBP pairs (`"JPY" in sym or "GBP" in sym`): Routes to `support_resistance_bounce` (`swing_window=20, rsi_period=14, min_wick_ratio=0.35, base_expiration_bars=expiration_bars`).
    - Other Forex pairs: Routes to `rsi_stochastic_extreme` (`rsi_period=14, rsi_oversold=25.0, rsi_overbought=75.0, stoch_k=14, stoch_d=3, stoch_oversold=20.0, stoch_overbought=80.0, base_expiration_bars=expiration_bars`).
  - Default Fallbacks (`else:` branch):
    - Primary: `support_resistance_bounce` (`swing_window=20, rsi_period=14, min_wick_ratio=0.35`).
    - Secondary: `rsi_stochastic_extreme` (`rsi_period=14, rsi_oversold=25.0, rsi_overbought=75.0, stoch_k=14, stoch_d=3`).
- **`find_optimal_strategy_for_asset`**:
  - Filtered strategy candidate pool to `candidate_strategies = [s for s in strategies if s["id"] in PRIORITY_STRATEGIES]`, safely falling back to `strategies` if no priority strategies are present.

### 1.2 `src/strat_trade/domain/strategies/registry.py`
- Preserved all 8 strategy metadata entries in `_STRATEGIES` for full backwards compatibility with historical backtesting and API endpoint introspection (`list_available_strategies`).
- Updated `get_strategy_instance` default fallback to `support_resistance_bounce` (primary) and `rsi_stochastic_extreme` (secondary).

---

## 2. Test Suite Synchronization

### 2.1 `tests/test_strategy_auto_matcher.py`
- Updated fallback assertions in `test_strategy_auto_matcher_fallback_hierarchy` to assert primary fallback is `support_resistance_bounce` and secondary is `rsi_stochastic_extreme`.

### 2.2 `tests/test_strategy_curation_and_asset_filter.py`
- Updated `test_auto_matcher_toxic_asset_rejection_and_whitelist_boost` to assert `"Gold_otc"` routes to `support_resistance_bounce` and unclassified symbol `"RANDOM_SYNTHETIC"` routes to `support_resistance_bounce`.

### 2.3 `tests/test_phase3_rolling_15_trade_verification.py`
- Renamed & synchronized `test_phase3_automatcher_unclassified_asset_primary_fallback_sniper_sr` asserting `res.strategy_id == "support_resistance_bounce"`.
- Renamed & synchronized `test_phase3_automatcher_unclassified_asset_secondary_fallback_sniper_rsi_stoch` asserting `res.strategy_id == "rsi_stochastic_extreme"`.
- Synchronized `test_phase3_automatcher_never_defaults_to_hybrid_multifactors` and `test_phase3_strategy_registry_fallback_to_support_resistance_bounce`.

### 2.4 `tests/test_m1_adversarial_challenge.py`
- Updated `test_auto_matcher_unclassified_symbols_primary_fallback` to assert `support_resistance_bounce`.
- Updated `test_auto_matcher_limited_strategy_pools_fallback_hierarchy` to verify fallback order: `support_resistance_bounce` -> `rsi_stochastic_extreme` -> first available.
- Updated `test_registry_fallback_to_support_resistance_bounce` asserting `SupportResistanceBounceStrategy`.

### 2.5 `tests/test_m1_adversarial_empirical_stress.py`
- Updated `test_registry_fallback_arbitrary_and_malformed_names` fuzz test to assert `SupportResistanceBounceStrategy`.
- Updated `test_automatcher_unclassified_asset_primary_and_secondary_fallback` and `test_automatcher_find_optimal_strategy_edge_case_inputs` to assert `support_resistance_bounce`.

### 2.6 `tests/test_m4_empirical_challenger_2.py`
- Verified compatibility with updated `PRIORITY_STRATEGIES`.

---

## 3. Verification Results
- **Pytest**: 662 passed in 20.24s (100% pass rate across entire test suite).
- **Ruff**: 0 errors (`.venv/bin/ruff check src tests` passed cleanly).
