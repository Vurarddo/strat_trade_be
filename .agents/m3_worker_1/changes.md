# Summary of Changes — M3 Worker 1 (Dynamic Microstructure Noise Filter & Cooldown)

## 1. Domain Asset Filter (`src/strat_trade/domain/trading/asset_filter.py`)
- **Implemented `qualify_asset_microstructure(candles: pd.DataFrame) -> tuple[bool, str]`**:
  - Requires at least 50 valid OHLC candles (`len(candles) >= 50`).
  - Evaluates `flat_bar_ratio` (proportion of bars where `high == low` or `abs(close - open) <= 1e-9`); rejects if $> 0.15$ (15%).
  - Evaluates `unique_price_ratio` (`unique_close_prices / total_bars`); rejects if $< 0.30$ (30%) to block discrete step-tick exotics and quantized feeds.
  - Evaluates `whipsaw_sign_flip_ratio` (proportion of consecutive 1-bar return sign flips); rejects if $> 0.80$ (80%) to block alternating micro-noise.
  - Evaluates `relative_atr` ($ATR(14) / Close$); rejects if $< 0.00003$ to block dead / zero-volatility assets.
  - Returns `(True, "Asset microstructure qualified (continuous, liquid, valid volatility)")` when all checks pass.
- **Enhanced `filter_allowed_assets`**:
  - Added optional `candle_data: dict[str, pd.DataFrame] | None = None` parameter to enable dynamic microstructure filtering alongside canonical blacklist and whitelist checks.

## 2. Trading Engine (`src/strat_trade/domain/trading/bot_engine.py`)
- **Hard Minimum 3-Minute Settlement Cooldown**:
  - In `_check_active_trades()`: updated post-trade settlement cooldown formula to `cooldown_sec = max(180, cooldown_bars * 60)`, guaranteeing a hard minimum 180s (3-minute) cooldown on any asset after trade completion regardless of user plan overrides.
- **Atomic Order Lock Cooldown Check**:
  - In `_execute_order()`: added atomic `cooldown_until` verification inside `async with self._order_lock:` to prevent race conditions and repeat entries during volatile breakouts.

## 3. Strategy AutoMatcher (`src/strat_trade/domain/optimizer/auto_matcher.py`)
- **Integrated Microstructure Qualification**:
  - In `find_optimal_strategy_for_asset()`: calls `qualify_asset_microstructure(df_raw)` when `len(df_raw) >= 50`. If an asset fails microstructure checks, it logs a diagnostic warning and returns a low-score fallback profile (`quantum_score = 15.0`) with `rationale = f"[MICROSTRUCTURE REJECTED] {qual_reason}"`.

## 4. Test Suite (`tests/test_strategy_curation_and_asset_filter.py`)
- **Added Comprehensive Unit and Integration Tests**:
  - `test_qualify_asset_microstructure_insufficient_or_malformed_data`: Verifies rejection on `< 50` bars, empty DataFrame, None, NaNs, missing columns, and non-positive prices.
  - `test_qualify_asset_microstructure_flat_bar_ratio`: Verifies rejection when flat bar ratio $> 0.15$.
  - `test_qualify_asset_microstructure_unique_price_ratio`: Verifies rejection when unique close ratio $< 0.30$.
  - `test_qualify_asset_microstructure_whipsaw_sign_flip_ratio`: Verifies rejection when whipsaw sign flip ratio $> 0.80$.
  - `test_qualify_asset_microstructure_relative_atr`: Verifies rejection when relative ATR $< 0.00003$.
  - `test_qualify_asset_microstructure_continuous_liquid_assets`: Verifies qualification of continuous liquid assets (`EURUSD`, `GBPUSD`, `USDJPY`, `AUDUSD`, `USDCLP`, `USDBDT`, `USDEGP`, `Gold`).
  - `test_filter_allowed_assets_with_microstructure_candle_data`: Verifies `filter_allowed_assets` strips illiquid / dead assets when `candle_data` is supplied.
  - `test_bot_engine_anti_whipsaw_3min_cooldown_and_atomic_check`: Verifies that `LiveDemoBotEngine` enforces at least 180s settlement cooldown and atomic check in `_execute_order`.

## 5. Verification Results
- `pytest`: 840 passed, 0 failed in 22.65s (100% pass rate).
- `ruff check src tests`: 0 errors.
