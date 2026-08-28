# Milestone 1 Handoff Report: Strategy Portfolio Restructuring (Sniper Edge)

## 1. Observation
1. **File `src/strat_trade/domain/optimizer/auto_matcher.py`**:
   - Lines 17–24: `PRIORITY_STRATEGIES` previously contained legacy indicator-spam strategies (`supertrend_adx_momentum`, `hybrid_multifactors`, `rsi_stochastic_extreme`, `macd_divergence_break`).
   - Lines 238–352: `_heuristic_profile_for_asset` previously routed Gold/commodities to `hybrid_multifactors`, stocks to `macd_divergence_break`, and unclassified assets to `supertrend_adx_momentum` (primary) and `macd_divergence_break` (secondary).
   - Lines 410–430: `find_optimal_strategy_for_asset` previously evaluated all 8 strategies across candidate variations without prioritizing the Sniper Trio.
2. **File `src/strat_trade/domain/strategies/registry.py`**:
   - Lines 32–129: Central strategy catalog contains 8 strategies (`hybrid_multifactors`, `bollinger_atr_reversion`, `ema_pullback_trend`, `rsi_stochastic_extreme`, `macd_divergence_break`, `volatility_squeeze_breakout`, `supertrend_adx_momentum`, `support_resistance_bounce`).
   - Lines 163–188: `get_strategy_instance()` previously fell back to `supertrend_adx_momentum` (primary) and `macd_divergence_break` (secondary).
3. **Execution Results**:
   - `.venv/bin/pytest`: `662 passed, 2 warnings in 20.24s`
   - `.venv/bin/ruff check src tests`: `All checks passed!` (0 violations)

---

## 2. Logic Chain
1. **Step 1 (Sniper Alpha Allocation)**: Based on Observation 1, Requirement R1 mandates deactivating failing indicator-spam strategies from default active live bot assignments. Updating `PRIORITY_STRATEGIES` in `auto_matcher.py` to `frozenset({"support_resistance_bounce", "rsi_stochastic_extreme", "ema_pullback_trend"})` ensures that the `+15.0` quantum bonus is allocated exclusively to verified sniper strategies.
2. **Step 2 (Heuristic Routing)**: Based on Observation 1, updating `_heuristic_profile_for_asset` routes Gold/commodities and Forex JPY/GBP pairs to `support_resistance_bounce`, stocks to `ema_pullback_trend`, crypto and other Forex pairs to `rsi_stochastic_extreme`, and default unclassified fallbacks to `support_resistance_bounce` (primary) and `rsi_stochastic_extreme` (secondary).
3. **Step 3 (Candidate Filtering)**: Based on Observation 1, filtering `candidate_strategies = [s for s in strategies if s["id"] in PRIORITY_STRATEGIES]` in `find_optimal_strategy_for_asset` guarantees that automated backtesting on candle series evaluates and assigns only the verified sniper strategies.
4. **Step 4 (Registry Fallback Preservation)**: Based on Observation 2, keeping all 8 strategy definitions in `_STRATEGIES` maintains full backwards compatibility with API schema introspection (`list_available_strategies`) and historical backtests, while updating `get_strategy_instance` default fallback to `support_resistance_bounce` (primary) and `rsi_stochastic_extreme` (secondary).
5. **Step 5 (Test Suite Synchronization)**: Synchronizing the 5 test suites (`tests/test_strategy_auto_matcher.py`, `tests/test_strategy_curation_and_asset_filter.py`, `tests/test_phase3_rolling_15_trade_verification.py`, `tests/test_m1_adversarial_challenge.py`, `tests/test_m1_adversarial_empirical_stress.py`) aligns all assertions with the new Sniper fallback contract.
6. **Step 6 (Verification)**: Based on Observation 3, running full test suite `.venv/bin/pytest` yielded 662/662 passing tests with 0 ruff errors.

---

## 3. Caveats
- Legacy strategies (`hybrid_multifactors`, `macd_divergence_break`, `supertrend_adx_momentum`, `volatility_squeeze_breakout`, `bollinger_atr_reversion`) remain registered in `_STRATEGIES` in `registry.py`. They can still be explicitly instantiated or backtested by ID when explicitly requested, but are omitted from automated default matching and priority allocations.
- No other caveats.

---

## 4. Conclusion
Milestone 1 (Strategy Portfolio Restructuring - Sniper Edge) is fully implemented, verified, and clean. All automated strategy matching and fallback routines now strictly prioritize the high-conviction Sniper Trio (`support_resistance_bounce`, `rsi_stochastic_extreme`, `ema_pullback_trend`). All 662 tests pass and 0 ruff violations remain.

---

## 5. Verification Method
To independently verify:
```bash
# 1. Run unit and integration tests across affected test suites
.venv/bin/pytest tests/test_strategy_auto_matcher.py tests/test_strategy_curation_and_asset_filter.py tests/test_phase3_rolling_15_trade_verification.py tests/test_m1_adversarial_challenge.py tests/test_m1_adversarial_empirical_stress.py tests/test_m4_empirical_challenger_2.py -v

# 2. Run full pytest suite (662 tests)
.venv/bin/pytest

# 3. Run ruff linter
.venv/bin/ruff check src tests
```

**Invalidation Conditions**:
- Any test failure in `pytest`.
- Any lint violation in `ruff check src tests`.
- `PRIORITY_STRATEGIES` missing any of `{"support_resistance_bounce", "rsi_stochastic_extreme", "ema_pullback_trend"}` or containing legacy indicator-spam strategies.
- `get_strategy_instance("unknown_name")` returning anything other than an instance of `SupportResistanceBounceStrategy`.
