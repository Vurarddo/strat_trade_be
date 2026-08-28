# Empirical Challenge Report: Milestone 1 (Strategy Portfolio Restructuring — Sniper Edge)

## Challenge Summary

**Overall risk assessment**: LOW (All empirical stress tests, fuzzing vectors, and priority allocation invariants passed).
**Verdict**: **APPROVE**

Milestone 1 successfully refactors `StrategyAutoMatcher` and `registry.py` to prioritize the Sniper Trio (`support_resistance_bounce`, `rsi_stochastic_extreme`, `ema_pullback_trend`), eliminate indicator spam from default live bot heuristics, and maintain backward compatibility for historical backtesting and registry introspection.

---

## Challenges

### [Low] Challenge 1: Unclassified Asset Heuristic Routing Invariance
- **Assumption challenged**: Unclassified assets or symbol noise strings (e.g. `""`, `"RANDOM_TOKEN"`, `123456`) might crash or route to deactivated legacy strategies.
- **Attack scenario**: Fuzz asset strings with non-standard characters, empty strings, pure numbers, and special symbols into `_heuristic_profile_for_asset`.
- **Blast radius**: If unclassified symbols routed to legacy strategies or crashed, automated bot planning would fail on novel assets.
- **Mitigation & Verification**: Tested 6 distinct unclassified symbol shapes (`UNKNOWN_COMMODITY`, `RANDOM_SYMBOL`, `XYZ123`, `""`, `___$$$%%%`, `123456`). All gracefully routed to Sniper Trio strategies (`support_resistance_bounce` or `rsi_stochastic_extreme`) with valid parameters.

### [Low] Challenge 2: Corrupted, Missing, NaN, and Flatline Candle Data
- **Assumption challenged**: Backtest-based matching in `find_optimal_strategy_for_asset` assumes valid, non-zero volatility OHLCV data and might raise `ZeroDivisionError`, `KeyError`, or `ValueError` on corrupted feeds.
- **Attack scenario**: Injected empty lists, empty DataFrames, sub-threshold candle lengths (1, 5, 10, 25, 34 rows), missing `close`/`volume` columns, `np.nan`, `np.inf`, `-np.inf`, zero-volatility flatlines, and inverted candle spans.
- **Blast radius**: Bot engine initialization crashes on malformed broker WebSocket frames.
- **Mitigation & Verification**: Tested via `TestAutoMatcherFuzzAndBoundaryResilience`. All malformed data frames and sub-threshold candle streams are safely caught and fall back cleanly to valid heuristic `StrategyAssignment` profiles without uncaught exceptions.

### [Low] Challenge 3: Parameter Injection and Case Sensitivity in Strategy Registry
- **Assumption challenged**: Calling `get_strategy_instance` with non-string types, mixed casing, unknown kwargs, or invalid names could cause instantiation exceptions or instantiate deactivated strategies by default.
- **Attack scenario**: Injected uppercase names (`SUPPORT_RESISTANCE_BOUNCE`), padded names (`  rsi_stochastic_extreme  `), non-string objects (`None`, `12345`, `dict`, `list`, `object()`), and unrecognized keyword parameters.
- **Blast radius**: Live bot trade execution crash if broker or UI sends uncleaned strategy strings or extra parameters.
- **Mitigation & Verification**: Tested via `TestRegistryInstanceResolutionStress`. Case-insensitive resolution works seamlessly; unknown names and invalid types fall back to `SupportResistanceBounceStrategy`; kwargs filtering strips unknown arguments cleanly without raising `TypeError`.

### [Low] Challenge 4: Concurrency & Asynchronous Safety
- **Assumption challenged**: Multiple concurrent matching operations running on different assets could mutate shared strategy parameter templates or race on engine state.
- **Attack scenario**: Spawned 40 concurrent async tasks executing `find_optimal_strategy_for_asset` simultaneously via `asyncio.gather`.
- **Blast radius**: Corrupted strategy assignments or race conditions during multi-pair pre-trading plan generation.
- **Mitigation & Verification**: Tested via `TestConcurrencyAndAsyncSafety`. All 40 concurrent tasks completed in 0.85s with 100% valid, isolated `StrategyAssignment` results.

---

## Stress Test Results

| Test Class / Area | Scenario | Expected Behavior | Actual Behavior | Result |
|---|---|---|---|---|
| `TestMilestone1SniperTrioInvariants` | Exact composition of `PRIORITY_STRATEGIES` | Strictly 3 sniper strategies | Exact set match (`support_resistance_bounce`, `rsi_stochastic_extreme`, `ema_pullback_trend`) | PASS |
| `TestMilestone1SniperTrioInvariants` | Legacy strategy exclusion | None of the 5 legacy strategies in priority | All 5 excluded | PASS |
| `TestRegistryInstanceResolutionStress` | Case & whitespace variations | Case-insensitive resolution | Correct instance returned | PASS |
| `TestRegistryInstanceResolutionStress` | Unknown strings & non-string types | Fallback to `SupportResistanceBounceStrategy` | Fallback successful, `BaseStrategy` subclass | PASS |
| `TestRegistryInstanceResolutionStress` | Kwargs injection & filtering | Unknown kwargs ignored | Handled cleanly without `TypeError` | PASS |
| `TestHeuristicAssetTaxonomyStress` | Gold / Commodities (`GOLD`, `XAUUSD`) | Maps to `support_resistance_bounce` | Mapped to `support_resistance_bounce` (3 bars) | PASS |
| `TestHeuristicAssetTaxonomyStress` | Stocks (`AAPL`, `TSLA`, `NVDA`, `#...`) | Maps to `ema_pullback_trend` | Mapped to `ema_pullback_trend` (3 bars) | PASS |
| `TestHeuristicAssetTaxonomyStress` | Crypto (`BTC`, `ETH`, `SOL`, `DOGE`) | Maps to `rsi_stochastic_extreme` | Mapped to `rsi_stochastic_extreme` (2 bars) | PASS |
| `TestHeuristicAssetTaxonomyStress` | Forex JPY / GBP (`USDJPY`, `GBPJPY`) | Maps to `support_resistance_bounce` | Mapped to `support_resistance_bounce` (3 bars) | PASS |
| `TestHeuristicAssetTaxonomyStress` | Other Forex & Exotic pairs | Maps to `rsi_stochastic_extreme` | Mapped to `rsi_stochastic_extreme` (3 bars) | PASS |
| `TestAutoMatcherFuzzAndBoundaryResilience` | Empty list & empty DataFrame | Graceful heuristic fallback | Fallback successful | PASS |
| `TestAutoMatcherFuzzAndBoundaryResilience` | Sub-threshold candle counts (<35) | Graceful heuristic fallback | Fallback successful | PASS |
| `TestAutoMatcherFuzzAndBoundaryResilience` | Missing `close` column | Fallback without crash | Fallback successful | PASS |
| `TestAutoMatcherFuzzAndBoundaryResilience` | NaN / Inf / -Inf values | Fallback without crash | Fallback successful | PASS |
| `TestAutoMatcherFuzzAndBoundaryResilience` | Flatline / zero volatility candles | Fallback without zero division | Fallback successful | PASS |
| `TestAutoMatcherFuzzAndBoundaryResilience` | Toxic OTC blacklist assets | Penalized score (10.0) + rationale | Correct score & rationale | PASS |
| `TestAutoMatcherFuzzAndBoundaryResilience` | Continuous oscillating candles | Selected winner in `PRIORITY_STRATEGIES` | Chosen strategy strictly in Sniper Trio | PASS |
| `TestStrategyVariationsGeneration` | Parameter variations across all catalog strategies | Valid parameter dicts | All >= 1 valid variation | PASS |
| `TestConcurrencyAndAsyncSafety` | 40 concurrent async matching tasks | Isolated, correct assignments | All 40 passed concurrently | PASS |

**Total Challenger Test Suite**: 85 tests, 85 passed, 0 failed (0.85s).
**Full Test Suite**: 747 tests, 747 passed, 0 failed (21.63s).
**Linter**: `ruff check src tests` passed with 0 violations.

---

## Unchallenged Areas

- UI control panel adjustments and `#botCfgExpiration` removal (Scoped to Milestone 2).
- Dynamic microstructure qualification `qualify_asset_microstructure` and anti-whipsaw cooldown (Scoped to Milestone 3).
- E2E 600+ real broker trade rolling 15-trade validation (Scoped to Milestone 4).
