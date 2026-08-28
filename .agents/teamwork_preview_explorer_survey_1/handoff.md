# Handoff Report: Auto-Matcher Strategy Hierarchy & Hybrid Multi-Factors Refinements (Phase 3 R1)

## 1. Observation

### 1.1 StrategyAutoMatcher & Fallback Hierarchy
- **File**: `src/strat_trade/domain/optimizer/auto_matcher.py`
- **Lines 17–24**:
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
- **Lines 47–76 (`_generate_strategy_variations`)**:
  `hybrid_multifactors` fast variation `v_fast` sets `"adx_trend_threshold": 20.0` (line 57), which violates the new minimum $ADX \ge 22.0$ constraint.
- **Lines 228–340 (`_heuristic_profile_for_asset`)**:
  - Line 237–255: Gold / Commodities (`GOLD`, `XAU`) explicitly map to `hybrid_multifactors`.
  - Line 256–265: Stocks (`#`, `AAPL`, `TSLA`, `NVDA`, `INTC`) explicitly map to `macd_divergence_break`.
  - Line 266–277: Crypto (`BTC`, `ETH`, `BNB`, `MATIC`, `SOL`, `DOGE`, `XRP`) explicitly map to `supertrend_adx_momentum`.
  - Line 278–320: Forex pairs map to `support_resistance_bounce` (for JPY/GBP) or `bollinger_atr_reversion`.
  - Line 322–340 (Default heuristic fallback for unclassified assets or missing candles):
    ```python
    else:
        # Default curated fallback: Hybrid Multi-Factor Strategy
        st = next((s for s in strategies if s["id"] == "hybrid_multifactors"), strategies[0])
        params = {
            "rsi_period": 14,
            "rsi_oversold": 30.0,
            "rsi_overbought": 70.0,
            "ema_fast": 9,
            "ema_mid": 21,
            "ema_slow": 50,
            "bb_length": 20,
            "bb_std": 2.0,
            "atr_period": 14,
            "adx_period": 14,
            "adx_trend_threshold": 25.0,
            "adx_range_threshold": 20.0,
            "base_expiration_bars": expiration_bars,
        }
        rationale = f"Гібридний мульти-факторний профіль для активу {asset}"
    ```
- **Lines 362–481 (`find_optimal_strategy_for_asset`)**:
  - Evaluates all available strategy variations against historical candles.
  - If candles are empty or `< 35`, calls `_heuristic_profile_for_asset` (line 375, line 392).
  - If backtest produces 0 trades across all strategies, falls back to `_heuristic_profile_for_asset` (line 479).

### 1.2 Strategy Registry Fallback
- **File**: `src/strat_trade/domain/strategies/registry.py`
- **Lines 163–173 (`get_strategy_instance`)**:
  ```python
  def get_strategy_instance(
      strategy_name: str, params: dict[str, Any] | None = None, **kwargs: Any
  ) -> BaseStrategy:
      import inspect

      meta = _STRATEGIES.get(strategy_name.strip().lower())
      if not meta:
          # Fallback to default
          meta = _STRATEGIES["hybrid_multifactors"]
  ```
  `get_strategy_instance` defaults to `hybrid_multifactors` when an unrecognized `strategy_name` is provided.

### 1.3 HybridMultiFactors Current Implementation
- **File**: `src/strat_trade/domain/strategies/hybrid_multifactors.py`
- **Lines 20–52 (`__init__`)**:
  Parameters: `rsi_period=14`, `rsi_overbought=70.0`, `rsi_oversold=30.0`, `ema_fast=9`, `ema_mid=21`, `ema_slow=50`, `bb_length=20`, `bb_std=2.0`, `atr_period=14`, `adx_period=14`, `adx_trend_threshold=25.0`, `adx_range_threshold=20.0`, `base_expiration_bars=3`, `adaptive_expiration_enabled=False`.
  *Missing*: explicit `adx_min_threshold` parameter (or hard filter $ADX < 22.0$).
- **Lines 53–109 (`prepare_dataframe`)**:
  Computes `ema_fast`, `ema_mid`, `ema_slow`, `rsi`, `stoch_k`, `stoch_d`, `bb_high`, `bb_mid`, `bb_low`, `bb_pband`, `bb_wband`, `atr`, `atr_sma`, `adx`, `adx_pos`, `adx_neg`.
- **Lines 111–273 (`evaluate_bar`)**:
  - Line 135: `adx = float(row["adx"]) if pd.notna(row["adx"]) else 15.0`. Note: `adx_pos` and `adx_neg` are computed in `prepare_dataframe` but not extracted or checked in `evaluate_bar`.
  - Line 151–157: Regime classified into `trending` ($ADX \ge 25$), `ranging` ($ADX \le 20$), or `transitional` ($20 < ADX < 25$).
  - Lines 163–205 (Model A): Pullback / momentum evaluated for `regime in ("trending", "transitional")`.
  - Lines 206–233 (Model B): Mean reversion evaluated unconditionally, even if $ADX < 20.0$ (choppy consolidation) or during runaway trends.
  - Lines 235–241: Decisions trigger on `signals_call >= 1` or `signals_put >= 1`, allowing single, weak, non-concordant indicators to place orders.
  - *Zero gating exists for $ADX < 22.0$*; trades are generated during low-momentum and choppy transitional regimes.

### 1.4 Top Performer Implementations
- **`SupertrendAdxMomentumStrategy`** (`src/strat_trade/domain/strategies/supertrend_adx_momentum.py:11–162`):
  - Uses ATR-based SuperTrend directional flipping and continuation.
  - Gated by $ADX \ge 25.0$ and directional dominance ($+DI > -DI$ for CALL, $-DI > +DI$ for PUT).
  - Demonstrates 59.1% WR and +$579 live PnL.
- **`MacdDivergenceBreakStrategy`** (`src/strat_trade/domain/strategies/macd_divergence_break.py:10–134`):
  - Swing price extreme divergence against MACD histogram momentum with signal line confirmation.
  - Default parameters: `macd_fast=12`, `macd_slow=26`, `macd_sign=9`, `lookback_swings=15`.

### 1.5 Existing Tests Covering StrategyAutoMatcher & Hybrid Strategy
- `tests/test_strategy_auto_matcher.py` (50 lines): Tests `StrategyAutoMatcher.find_optimal_strategy_for_asset` on synthetic EURUSD candles.
- `tests/test_hybrid_strategy.py` (66 lines): Tests indicator preparation and `evaluate_bar` regime validity.
- `tests/test_strategy_curation_and_asset_filter.py` (lines 357–376):
  ```python
  # Fallback for generic unclassified asset
  fallback_res = await matcher.find_optimal_strategy_for_asset("RANDOM_SYNTHETIC", [])
  assert fallback_res.strategy_id == "hybrid_multifactors"
  assert fallback_res.parameters["rsi_period"] == 14
  ```
  Explicitly asserts old Phase 2 fallback behavior to `hybrid_multifactors`.
- `tests/test_new_strategies.py` (lines 43–94): Parameterized backtest across all 8 registered strategies.
- `tests/test_m4_empirical_challenger_2.py`: Auto-matcher stress testing, whitelisting boost, and toxic asset rejection.

---

## 2. Logic Chain

1. **Premise 1 (R1 Fallback Hierarchy)**:
   In `ORIGINAL_REQUEST.md §R1`, `hybrid_multifactors` must be removed as the default heuristic fallback in `StrategyAutoMatcher` and replaced with `supertrend_adx_momentum` as primary fallback, and `macd_divergence_break` as secondary fallback.
2. **Premise 2 (AutoMatcher Fallback Selection)**:
   In `StrategyAutoMatcher._heuristic_profile_for_asset` (`auto_matcher.py:322-340`), unmatched assets currently assign `hybrid_multifactors`. Replacing this `else` branch with:
   - Primary: `next((s for s in strategies if s["id"] == "supertrend_adx_momentum"), ...)`
   - Secondary: `next((s for s in strategies if s["id"] == "macd_divergence_break"), ...)`
   - Fallback: `strategies[0]`
   guarantees that unclassified or candle-deprived assets receive proven top performers (`supertrend_adx_momentum` / `macd_divergence_break`) rather than uncalibrated multi-factors.
3. **Premise 3 (Priority Pool Optimization)**:
   In `auto_matcher.py:17-24`, `PRIORITY_STRATEGIES` should maintain the top verified strategies (`supertrend_adx_momentum`, `macd_divergence_break`, `rsi_stochastic_extreme`).
4. **Premise 4 (Hybrid Strategy Gating & Concordance)**:
   In `HybridMultiFactorsStrategy` (`hybrid_multifactors.py`):
   - When $ADX < 22.0$, market directional momentum is insufficient, leading to whipsaws and false breakout/reversion traps.
   - Enforcing a hard check `if adx < 22.0: return SignalResult(None, 0.0, ..., regime="adx_sub_threshold_choppy", ...)` eliminates trades during flat/choppy transitional markets.
   - When $ADX \ge 22.0$, signals must require simultaneous confirmation from all 3 core indicators:
     - **CALL**: $ADX \ge 22.0$ AND $+DI > -DI$ (`adx_pos > adx_neg`), EMA bullish structure ($EMA_{fast} \ge EMA_{mid}$ and $Close \ge EMA_{fast} \times 0.9990$), RSI in bullish momentum corridor ($45.0 \le RSI \le 68.0$), Stoch confirmation ($Stoch_K > Stoch_D$).
     - **PUT**: $ADX \ge 22.0$ AND $-DI > +DI$ (`adx_neg > adx_pos`), EMA bearish structure ($EMA_{fast} \le EMA_{mid}$ and $Close \le EMA_{fast} \times 1.0010$), RSI in bearish momentum corridor ($32.0 \le RSI \le 55.0$), Stoch confirmation ($Stoch_K < Stoch_D$).
     - If any core filter conflicts (e.g. $+DI > -DI$ but RSI overbought $>68$ or EMA is downward), `action = None`.
5. **Premise 5 (Registry Consistency)**:
   In `registry.py:171`, `get_strategy_instance` default fallback when `meta` is missing should default to `supertrend_adx_momentum` with secondary fallback to `macd_divergence_break` instead of `hybrid_multifactors`.
6. **Premise 6 (Test Consistency)**:
   `tests/test_strategy_curation_and_asset_filter.py:373` must be updated to expect `supertrend_adx_momentum` instead of `hybrid_multifactors`. New unit tests must be added in `tests/test_hybrid_strategy.py` and `tests/test_strategy_auto_matcher.py` to verify $ADX < 22.0$ gating, strict concordance, and fallback precedence.

---

## 3. Caveats

1. **Asset-Specific Heuristic Branches**:
   In `auto_matcher.py:237-255`, gold/commodities (`GOLD`, `XAU`) currently route to `hybrid_multifactors`. With the updated `HybridMultiFactorsStrategy` ($ADX \ge 22.0$ gating and strict concordance), gold execution will be filtered. Alternatively, commodities could be routed to `supertrend_adx_momentum` or retained with the gated hybrid strategy.
2. **Backtest Warmup Periods**:
   `HybridMultiFactorsStrategy` requires 50 warmup bars (due to EMA(50) and ADX(14)). Backtests with $< 50$ candles will correctly return `warming_up`.
3. **Adaptive Expiration Interaction**:
   `adaptive_expiration_enabled` scales expiration bars by $\pm 1$ bar based on volatility ratio. It operates downstream of signal confirmation and does not bypass the $ADX \ge 22.0$ gate.

---

## 4. Conclusion & Required Changes

### Summary Table of Required Code Changes for R1

| Target File | Line Numbers | Current State | Required Modification | Rationale |
|---|---|---|---|---|
| `src/strat_trade/domain/optimizer/auto_matcher.py` | 322–340 | Defaults unclassified asset heuristic to `hybrid_multifactors` | Replace with primary fallback `supertrend_adx_momentum` (parameters: `atr_period=10`, `atr_multiplier=3.0`, `adx_threshold=24.0`) and secondary fallback `macd_divergence_break` (`macd_fast=12`, `macd_slow=26`, `macd_sign=9`) | Enforces top-performing strategy hierarchy for candle-deprived/unclassified assets |
| `src/strat_trade/domain/optimizer/auto_matcher.py` | 57 | `v_fast` sets `adx_trend_threshold: 20.0` | Set `adx_trend_threshold: 22.0` (or `adx_min_threshold: 22.0`) | Complies with $ADX \ge 22.0$ minimum requirement |
| `src/strat_trade/domain/strategies/registry.py` | 171 | Default fallback is `_STRATEGIES["hybrid_multifactors"]` | Set fallback to `_STRATEGIES.get("supertrend_adx_momentum", _STRATEGIES.get("macd_divergence_break", ...))` | Aligns registry fallback with top performers |
| `src/strat_trade/domain/strategies/hybrid_multifactors.py` | 20–52 | `__init__` lacks `adx_min_threshold` | Add `adx_min_threshold: float = 22.0` (and `self.adx_min_threshold = float(adx_min_threshold)`) | Exposes configurable $ADX \ge 22.0$ gate |
| `src/strat_trade/domain/strategies/hybrid_multifactors.py` | 135–157 | Extracts only `adx`; no hard gate for $ADX < 22.0$ | Extract `adx_pos`, `adx_neg`; add hard check `if adx < self.adx_min_threshold: return SignalResult(None, 0.0, ..., "adx_sub_threshold_choppy", ...)` | Suppresses whipsaws during choppy, low-momentum regimes |
| `src/strat_trade/domain/strategies/hybrid_multifactors.py` | 163–241 | Loose scoring model (Model A + Model B sum) allowing single weak signals | Enforce strict 3-way confirmation (ADX directional strength $+DI/-DI$, EMA trend alignment, RSI momentum zone $45..68$ for CALL, $32..55$ for PUT). Eliminate loose unconfirmed Model B counter-trend entries. | Ensures zero trades are placed without full multi-indicator concordance |
| `src/strat_trade/domain/strategies/hybrid_multifactors.py` | 276–325 | `get_parameter_definitions` lacks `adx_min_threshold` | Expose `adx_min_threshold` in parameter definitions | Allows optimizer and UI parameter tuning |
| `tests/test_strategy_curation_and_asset_filter.py` | 371–375 | Asserts `fallback_res.strategy_id == "hybrid_multifactors"` | Update assertion to `fallback_res.strategy_id == "supertrend_adx_momentum"` and `fallback_res.parameters["adx_threshold"] == 24.0` | Reflects Phase 3 default fallback |
| `tests/test_hybrid_strategy.py` | New tests | Only tests basic column existence and regime type | Add tests for: $ADX < 22.0$ suppression, Bullish agreement CALL, Bearish agreement PUT, RSI conflict suppression, EMA conflict suppression | Verifies strict concordance and ADX gating |
| `tests/test_strategy_auto_matcher.py` | New tests | Basic single asset profiling test | Add test verifying fallback hierarchy (`supertrend_adx_momentum` -> `macd_divergence_break`) | Verifies auto-matcher hierarchy |

---

## 5. Verification Method

### 5.1 Independent Test Verification Commands
1. **Run full pytest suite**:
   ```bash
   .venv/bin/pytest -v
   ```
2. **Run specific strategy and auto-matcher test suites**:
   ```bash
   .venv/bin/pytest tests/test_hybrid_strategy.py tests/test_strategy_auto_matcher.py tests/test_strategy_curation_and_asset_filter.py tests/test_new_strategies.py -v
   ```
3. **Verify lint and code formatting**:
   ```bash
   .venv/bin/ruff check .
   ```

### 5.2 Specific Invalidation Conditions
- If `fallback_res = await matcher.find_optimal_strategy_for_asset("RANDOM_SYNTHETIC", [])` returns `strategy_id == "hybrid_multifactors"`, R1 is NOT satisfied.
- If `HybridMultiFactorsStrategy.evaluate_bar` generates `TradeAction.CALL` or `TradeAction.PUT` when $ADX = 18.5$, R1 is NOT satisfied.
- If `HybridMultiFactorsStrategy.evaluate_bar` generates `TradeAction.CALL` when $RSI > 70.0$ (overbought) or when $EMA_{fast} < EMA_{mid}$, R1 is NOT satisfied.
