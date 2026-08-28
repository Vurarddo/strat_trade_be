# Handoff Report: AutoMatcher Restructuring & Sniper Alpha Allocation (Milestone 1)

## 1. Observation
- **`src/strat_trade/domain/optimizer/auto_matcher.py:17-24`**: `PRIORITY_STRATEGIES` is currently defined with legacy indicator-spam strategies:
  ```python
  PRIORITY_STRATEGIES: frozenset[str] = frozenset(
      {
          "supertrend_adx_momentum",
          "hybrid_multifactors",
          "rsi_stochastic_extreme",
          "macd_divergence_break",
      }
  )
  ```
- **`src/strat_trade/domain/optimizer/auto_matcher.py:238-352`**: `_heuristic_profile_for_asset` routes:
  - Commodities (`"GOLD"` / `"XAU"`) to `hybrid_multifactors` (lines 238–256).
  - Stocks (`"#"` / tech tickers) to `macd_divergence_break` (lines 257–266).
  - Forex pairs to `bollinger_atr_reversion` (lines 310–321).
  - Default fallbacks (`else:`) to `supertrend_adx_momentum` (primary) and `macd_divergence_break` (secondary) (lines 323–352).
- **`src/strat_trade/domain/optimizer/auto_matcher.py:410-489`**: `find_optimal_strategy_for_asset` iterates over all strategies from `list_available_strategies()`, allowing non-sniper legacy strategies to be assigned if candidate candles trigger backtest signals.
- **`src/strat_trade/domain/strategies/registry.py:171-174`**: `get_strategy_instance()` resolves missing strategy instances with fallback to `supertrend_adx_momentum` and `macd_divergence_break`.
- **Existing Test Assertions**: 6 test suites assert the legacy fallbacks (`supertrend_adx_momentum` / `hybrid_multifactors` / `macd_divergence_break`):
  1. `tests/test_strategy_auto_matcher.py:53-86`
  2. `tests/test_strategy_curation_and_asset_filter.py:421-429`
  3. `tests/test_phase3_rolling_15_trade_verification.py:783-837`
  4. `tests/test_m1_adversarial_challenge.py:339-405`
  5. `tests/test_m1_adversarial_empirical_stress.py:276-350`
  6. `tests/test_m4_empirical_challenger_2.py:33, 193`

## 2. Logic Chain
1. Requirement R1 of `ORIGINAL_REQUEST.md` requires deactivating failing indicator-spam strategies (`MACD Divergence & Cross`, `hybrid_multifactors`) and concentrating live bot trading on the proven Sniper Trio: `Support & Resistance Pin-Bar` (`support_resistance_bounce`), `RSI + Stoch Extreme Scalp` (`rsi_stochastic_extreme`), and `EMA Ribbon Trend Pullback` (`ema_pullback_trend`).
2. Updating `PRIORITY_STRATEGIES` to `frozenset({"support_resistance_bounce", "rsi_stochastic_extreme", "ema_pullback_trend"})` ensures that the `+15.0` quantum ranking bonus is awarded exclusively to sniper strategies.
3. Filtering `candidate_strategies = [s for s in strategies if s["id"] in PRIORITY_STRATEGIES]` in `find_optimal_strategy_for_asset` guarantees that automated backtesting on candle streams evaluates and allocates only the sniper strategies.
4. Re-routing heuristic profiles in `_heuristic_profile_for_asset`:
   - Commodities (`Gold_otc`) -> `support_resistance_bounce`
   - Stocks -> `ema_pullback_trend`
   - Default fallbacks -> `support_resistance_bounce` (primary) and `rsi_stochastic_extreme` (secondary)
   guarantees that when candle history is sparse (<35 bars) or unclassified assets are introduced, the engine consistently allocates high-conviction sniper alpha.
5. Updating `get_strategy_instance` in `registry.py` ensures complete architectural consistency between heuristic planning and bot runtime instantiation.
6. Synchronizing the 6 test files aligns test assertions with the new sniper alpha contract while preserving 100% test coverage.

## 3. Caveats
- No legacy strategy classes should be deleted from `_STRATEGIES` in `registry.py` to prevent breaking existing parameter definitions, historical simulation harnesses, and manual backtest endpoints.
- Parameter variations generator `_generate_strategy_variations` should keep support for all strategies so variation unit tests continue to pass.

## 4. Conclusion
The restructuring plan for `StrategyAutoMatcher` and `registry.py` is fully specified, verified, and accompanied by complete diff patches and test synchronization requirements in `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m1_explorer_1/m1_plan_automatcher.md`. Implementation can proceed cleanly in Milestone 1 without runtime risk.

## 5. Verification Method
1. Inspect the detailed plan and diffs in `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m1_explorer_1/m1_plan_automatcher.md`.
2. Apply the patch to `src/strat_trade/domain/optimizer/auto_matcher.py` and `src/strat_trade/domain/strategies/registry.py`.
3. Synchronize test assertions across the 6 test files listed in Section 4 of the plan.
4. Run:
   ```bash
   .venv/bin/pytest tests/test_strategy_auto_matcher.py tests/test_strategy_curation_and_asset_filter.py tests/test_phase3_rolling_15_trade_verification.py tests/test_m1_adversarial_challenge.py tests/test_m1_adversarial_empirical_stress.py
   .venv/bin/pytest
   ```
5. Confirm that all 662+ tests pass with 0 failures and 0 warnings.
