# Handoff Report: Strategy Registry & Fallback Resolution (M1 Explorer 2)

## 1. Observation

### 1.1 Strategy Registry Definition (`src/strat_trade/domain/strategies/registry.py`)
- `_STRATEGIES` dictionary (lines 32–129) defines exactly 8 strategies:
  1. `hybrid_multifactors` (`HybridMultiFactorsStrategy`)
  2. `bollinger_atr_reversion` (`BollingerAtrReversionStrategy`)
  3. `ema_pullback_trend` (`EmaPullbackTrendStrategy`)
  4. `rsi_stochastic_extreme` (`RsiStochasticExtremeStrategy`)
  5. `macd_divergence_break` (`MacdDivergenceBreakStrategy`)
  6. `volatility_squeeze_breakout` (`VolatilitySqueezeBreakoutStrategy`)
  7. `supertrend_adx_momentum` (`SupertrendAdxMomentumStrategy`)
  8. `support_resistance_bounce` (`SupportResistanceBounceStrategy`)
- `list_available_strategies()` (lines 132–160) iterates `_STRATEGIES.values()` and returns a `list[dict[str, Any]]` containing strategy metadata and parameter definitions derived via `meta.cls.get_parameter_definitions()`.

### 1.2 Current Fallback Logic in `get_strategy_instance()` (lines 163–188)
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

### 1.3 Consumers of `registry.py` Across Codebase
- `src/strat_trade/domain/backtest/engine.py:36-41`: `BinaryBacktestEngine._create_strategy()` invokes `get_strategy_instance(self.config.strategy_name, **params)`.
- `src/strat_trade/domain/backtest/portfolio_engine.py:49-55`: `PortfolioBacktestEngine.__init__()` invokes `get_strategy_instance(config.strategy_name, **params)`.
- `src/strat_trade/domain/trading/bot_engine.py:86`: `LiveDemoBotEngine.start()` dynamically instantiates strategies via `get_strategy_instance(a.strategy_id, **a.parameters)`.
- `src/strat_trade/api/routes/backtest.py:289`: `list_strategies_endpoint()` calls `list_available_strategies()` to expose available strategies to the UI and API clients.
- `src/strat_trade/domain/optimizer/auto_matcher.py:375`: `StrategyAutoMatcher.find_optimal_strategy_for_asset()` calls `list_available_strategies()`.
- `src/strat_trade/use_cases/optimize_strategy.py:38-40`: `_build_default_grid()` accesses `_STRATEGIES`.
- `src/strat_trade/domain/backtest/verification_runner.py:905-907`: `_build_fallback_grid()` accesses `_STRATEGIES`.

### 1.4 Downstream Test Assertions on Fallback
- `tests/test_m1_adversarial_challenge.py:452-462`: `test_registry_fallback_to_supertrend()` asserts `isinstance(inst_unknown, SupertrendAdxMomentumStrategy)`.
- `tests/test_m1_adversarial_empirical_stress.py:202-227`: `test_registry_fallback_arbitrary_and_malformed_names()` asserts `isinstance(strat, SupertrendAdxMomentumStrategy)`.
- `tests/test_phase3_rolling_15_trade_verification.py:829-837`: `test_phase3_strategy_registry_fallback_to_supertrend()` asserts `isinstance(strat, SupertrendAdxMomentumStrategy)`.

### 1.5 Baseline Execution Results
- Command: `.venv/bin/pytest` -> 662 passed in 23.35s.
- Command: `.venv/bin/ruff check .` -> All checks passed (0 errors).

---

## 2. Logic Chain

1. **Strategy Preservation**:
   - In §1.1, `_STRATEGIES` defines 8 strategies. In §1.3, multiple consumers rely on `_STRATEGIES` and `list_available_strategies()`.
   - Modifying or removing any strategy class from `_STRATEGIES` would break `list_available_strategies()`, `GET /api/backtest/strategies`, and manual backtesting of historical strategies.
   - Therefore, all 8 strategy classes (`hybrid_multifactors`, `bollinger_atr_reversion`, `ema_pullback_trend`, `rsi_stochastic_extreme`, `macd_divergence_break`, `volatility_squeeze_breakout`, `supertrend_adx_momentum`, `support_resistance_bounce`) must remain fully defined in `_STRATEGIES`.

2. **Fallback Resolution Transformation**:
   - In §1.2, lines 171–174 fall back to `supertrend_adx_momentum` (primary) and `macd_divergence_break` (secondary).
   - Under R1 of the Sniper Confluence Trading System, `macd_divergence_break` and uncalibrated indicators are deactivated from live execution priority in favor of high-winrate Sniper alpha (`Support & Resistance Pin-Bar` at 57.6% WR, `RSI + Stoch Extreme Scalp` at 71.4% WR, `EMA Ribbon Trend Pullback` at 60.0% WR).
   - Updating `get_strategy_instance()` to resolve unrecognized strategies to `support_resistance_bounce` (primary) and `rsi_stochastic_extreme` (secondary) guarantees that any unmatched or malformed strategy request executes high-conviction sniper price-action logic.

3. **Keyword Filtration & Safety**:
   - In §1.2, `get_strategy_instance()` filters `combined_params` against `inspect.signature(meta.cls.__init__)`.
   - When resolving unknown strategies, foreign parameters (e.g. `atr_period`, `macd_fast`) are discarded, while compatible parameters (e.g. `base_expiration_bars`, `adaptive_expiration_enabled`, `swing_window`) are preserved.
   - This ensures fallback instantiation is atomic, exception-free, and robust against parameter injection.

4. **Test Synchronization Requirement**:
   - In §1.4, three specific test suites directly assert that fallback returns `SupertrendAdxMomentumStrategy`.
   - When the fallback is redirected to `SupportResistanceBounceStrategy`, these three test assertions must be synchronized to assert `SupportResistanceBounceStrategy`.

---

## 3. Caveats
- No caveats. The strategy classes, registry metadata, parameter definitions, dynamic kwargs filtering, and downstream consumers have been fully investigated and verified.

---

## 4. Conclusion
1. `src/strat_trade/domain/strategies/registry.py` must preserve all 8 strategy classes in `_STRATEGIES`.
2. Fallback resolution in `get_strategy_instance()` must be updated to:
   ```python
   meta = _STRATEGIES.get(strategy_name.strip().lower()) if isinstance(strategy_name, str) else None
   if not meta:
       meta = _STRATEGIES.get(
           "support_resistance_bounce",
           _STRATEGIES.get("rsi_stochastic_extreme", next(iter(_STRATEGIES.values()))),
       )
   ```
3. The exact unified diffs and test synchronization plans have been authored in `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m1_explorer_2/m1_plan_registry.md`.

---

## 5. Verification Method

### Test Commands
1. Run registry unit tests:
   ```bash
   .venv/bin/pytest tests/test_new_strategies.py -v
   ```
2. Run fallback & adversarial regression tests:
   ```bash
   .venv/bin/pytest tests/test_m1_adversarial_challenge.py tests/test_m1_adversarial_empirical_stress.py tests/test_phase3_rolling_15_trade_verification.py -v
   ```
3. Run full test suite:
   ```bash
   .venv/bin/pytest
   ```
4. Run linter:
   ```bash
   .venv/bin/ruff check .
   ```

### Invalidation Conditions
- Any test fails with `KeyError` or `TypeError` during strategy instantiation.
- `list_available_strategies()` returns fewer or more than 8 strategy entries.
- Unrecognized or empty strategy name fails to resolve to `SupportResistanceBounceStrategy`.
