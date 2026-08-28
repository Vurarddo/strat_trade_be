# Strategy Portfolio Curation & Loss Remediation (R1) Investigation Report

## 1. Observation

### 1.1 Strategy Catalog & Definitions
All strategies inherit from `BaseStrategy` (`src/strat_trade/domain/strategies/base.py:34-78`) and are registered in `src/strat_trade/domain/strategies/registry.py:32-129` under `_STRATEGIES`:

| Strategy ID | Display Name / Category | Implementation File | Key Parameters & Defaults |
| :--- | :--- | :--- | :--- |
| `ema_pullback_trend` | `EMA Ribbon Trend Pullback` (Trend Following) | `src/strat_trade/domain/strategies/ema_pullback_trend.py:10-175` | `ema_fast=9`, `ema_mid=21`, `ema_slow=50`, `adx_period=14`, `adx_threshold=25.0`, `stoch_k=14`, `stoch_d=3`, `base_expiration_bars=3` |
| `support_resistance_bounce` | `Support & Resistance Pin-Bar` (Price Action / S&R) | `src/strat_trade/domain/strategies/support_resistance_bounce.py:10-133` | `swing_window=20`, `rsi_period=14`, `min_wick_ratio=0.35`, `base_expiration_bars=3` |
| `supertrend_adx_momentum` | `SuperTrend + ADX Momentum` (Momentum Trend) | `src/strat_trade/domain/strategies/supertrend_adx_momentum.py:11-162` | `atr_period=10`, `atr_multiplier=3.0`, `adx_period=14`, `adx_threshold=25.0`, `base_expiration_bars=3` |
| `hybrid_multifactors` | `Гібридна Мульти-Факторна` (Hybrid Multi-Factor) | `src/strat_trade/domain/strategies/hybrid_multifactors.py:10-326` | `rsi_period=14`, `rsi_oversold=30.0`, `rsi_overbought=70.0`, `ema_fast=9`, `ema_mid=21`, `ema_slow=50`, `bb_length=20`, `bb_std=2.0`, `atr_period=14`, `adx_period=14`, `adx_trend_threshold=25.0`, `adx_range_threshold=20.0`, `base_expiration_bars=3` |
| `rsi_stochastic_extreme` | `RSI + Stoch Extreme Scalp` (Scalping Reversal) | `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py:10-158` | `rsi_period=14`, `rsi_oversold=25.0`, `rsi_overbought=75.0`, `stoch_k=14`, `stoch_d=3`, `stoch_oversold=20.0`, `stoch_overbought=80.0`, `base_expiration_bars=2` |
| `macd_divergence_break` | `MACD Divergence & Cross` (Reversal Divergence) | `src/strat_trade/domain/strategies/macd_divergence_break.py:10-134` | `macd_fast=12`, `macd_slow=26`, `macd_sign=9`, `lookback_swings=15`, `base_expiration_bars=3` |
| `bollinger_atr_reversion` | `Bollinger + ATR Mean Reversion` (Mean Reversion) | `src/strat_trade/domain/strategies/bollinger_atr_reversion.py:10-287` | `bb_length=20`, `bb_std=2.0`, `rsi_period=14`, `rsi_oversold=30.0`, `rsi_overbought=70.0`, `atr_period=14`, `max_atr_ratio=2.2`, `adx_period=14`, `adx_trend_threshold=25.0`, `min_wick_ratio=0.25`, `base_expiration_bars=3` |
| `volatility_squeeze_breakout` | `TTM Volatility Squeeze Breakout` (Volatility Breakout) | `src/strat_trade/domain/strategies/volatility_squeeze_breakout.py:10-145` | `bb_length=20`, `bb_std=2.0`, `kc_length=20`, `kc_mult=1.5`, `momentum_period=12`, `base_expiration_bars=3` |

### 1.2 Strategy Registration & Instantiation
- `src/strat_trade/domain/strategies/registry.py:32-129`: Registered in module-level `_STRATEGIES: dict[str, StrategyMetadata]`.
- `list_available_strategies()` (`registry.py:132-160`): Converts metadata & parameter definitions into serializable dicts for UI/API.
- `get_strategy_instance(strategy_name, params=None, **kwargs)` (`registry.py:163-185`): Dynamic factory inspecting `cls.__init__` parameters and instantiating strategy.

### 1.3 Auto-Matching, Strategy Scoring & Prioritization
- `StrategyAutoMatcher.find_optimal_strategy_for_asset` (`src/strat_trade/domain/optimizer/auto_matcher.py:290-401`):
  - Iterates over all strategies in `list_available_strategies()`.
  - For each strategy, generates parameter variations via `_generate_strategy_variations` (`auto_matcher.py:23-206`).
  - Runs `BinaryBacktestEngine.run(df_raw)` (`auto_matcher.py:348-355`).
  - Calculates fitness score (`auto_matcher.py:357-369`):
    ```python
    if trades >= 2:
        score = (
            (wr - 50.0) * 3.0
            + min(pf, 4.0) * 15.0
            + min(trades, 10) * 3.0
            - dd * 0.5
            + roi * 0.5
        )
    elif trades == 1:
        score = (wr - 50.0) * 1.5 + (15.0 if wr > 50 else -15.0)
    else:
        score = -50.0
    ```
  - **Heuristic Fallback** (`auto_matcher.py:208-289`): When candle data is insufficient (<35 bars), assigns:
    - Stocks -> `macd_divergence_break`
    - Crypto -> `supertrend_adx_momentum`
    - Forex JPY/GBP -> `support_resistance_bounce`
    - Forex other -> `bollinger_atr_reversion`
    - Default fallback (line 268) -> `ema_pullback_trend`!

### 1.4 Signal Generation in `EmaPullbackTrendStrategy` (`ema_pullback_trend.py`)
- **Indicators calculated** (`ema_pullback_trend.py:40-68`):
  - `ema_f`, `ema_m`, `ema_s` (EMA 9, 21, 50)
  - `adx`, `adx_pos`, `adx_neg` (ADX 14)
  - `stoch_k`, `stoch_d` (Stochastic 14, 3)
  - **NO RSI indicator is computed or present in DataFrame.**
- **Signal Triggers** (`ema_pullback_trend.py:110-135`):
  - Bullish: `if uptrend: if (low <= ema_f * 1.0005 and close >= ema_f) or (low <= ema_m * 1.0005 and close >= ema_m): if sk > sd or (sk > prev_sk and sk < 75): action = TradeAction.CALL`
  - Bearish: `elif downtrend: if (high >= ema_f * 0.9995 and close <= ema_f) or (high >= ema_m * 0.9995 and close <= ema_m): if sk < sd or (sk < prev_sk and sk > 25): action = TradeAction.PUT`
  - **Observation on Overbought/Oversold**: When `sk > sd`, CALL is allowed even if `sk >= 80` (overbought). When `sk < sd`, PUT is allowed even if `sk <= 20` (oversold). There is zero RSI filtering.

### 1.5 Signal Generation in `SupportResistanceBounceStrategy` (`support_resistance_bounce.py`)
- **Indicators calculated** (`support_resistance_bounce.py:32-46`):
  - `sr_resistance`: rolling max of `high.shift(1)` over `swing_window` (default 20).
  - `sr_support`: rolling min of `low.shift(1)` over `swing_window` (default 20).
  - `rsi`: RSI(14).
- **Signal Triggers** (`support_resistance_bounce.py:73-89`):
  - Bullish: `if low <= supp * 1.0005 and close >= supp and (lower_wick / range_) >= self.min_wick_ratio:` -> CALL
  - Bearish: `elif high >= res * 0.9995 and close <= res and (upper_wick / range_) >= self.min_wick_ratio:` -> PUT
  - **Observation on Wick Ratio & Confirmation**:
    - Default `min_wick_ratio` in class is 0.35, but in `auto_matcher.py:190` the variation uses `min_wick_ratio: 0.28`, and in `auto_matcher.py:250` the heuristic profile uses `min_wick_ratio: 0.32`.
    - No explicit candlestick bounce confirmation (e.g. green/bullish close for support bounce, red/bearish close for resistance bounce, or close position within range).

---

## 2. Logic Chain

1. **Premise 1**: In fast 1m binary options markets, `EMA Ribbon Trend Pullback` experiences significant loss rate when buying into overbought rallies ($RSI > 65$, $Stoch > 75$) or selling into oversold dumps ($RSI < 35$, $Stoch < 25$) because the market mean-reverts before 3m expiration completes.
2. **Premise 2**: Currently, `EmaPullbackTrendStrategy` lacks RSI calculations entirely and allows CALL entries whenever `sk > sd` regardless of whether `sk` is 80+, 90+.
3. **Premise 3**: In `SupportResistanceBounceStrategy`, false breakouts occur when price touches a support/resistance level with a small wick (<35%) or without physical bounce confirmation (e.g., a bearish candle closing on support that proceeds to break down).
4. **Premise 4**: In `StrategyAutoMatcher`, `ema_pullback_trend` is currently the ultimate fallback strategy (line 268), and all 8 strategies have equal baseline prioritization, whereas higher-performing systematic strategies (`supertrend_adx_momentum`, `hybrid_multifactors`, `rsi_stochastic_extreme`, `macd_divergence_break`) should be prioritized.

---

## 3. Caveats

1. **Backtesting Dataset Sensitivity**: Strict filters (RSI <= 65 on CALL, wick >= 0.35) reduce total trade count while increasing win rate. Verification scripts must have sufficient bar history (>=150-200 bars) to ensure >=15 trades per evaluation batch.
2. **Backward Compatibility with Strategy Registry**: Modifying `EmaPullbackTrendStrategy.__init__` parameters must maintain default values so existing callers and unit tests in `tests/test_new_strategies.py` and `tests/test_rolling_15_trade_verification.py` pass without breakages.

---

## 4. Conclusion & Proposed Implementation Details

### 4.1 Refactoring `EmaPullbackTrendStrategy` (`src/strat_trade/domain/strategies/ema_pullback_trend.py`)
1. **Add RSI and strict thresholds to `__init__`**:
   ```python
   def __init__(
       self,
       *,
       ema_fast: int = 9,
       ema_mid: int = 21,
       ema_slow: int = 50,
       adx_period: int = 14,
       adx_threshold: float = 25.0,
       stoch_k: int = 14,
       stoch_d: int = 3,
       rsi_period: int = 14,
       rsi_overbought: float = 65.0,
       rsi_oversold: float = 35.0,
       stoch_overbought: float = 75.0,
       stoch_oversold: float = 25.0,
       base_expiration_bars: int = 3,
       adaptive_expiration_enabled: bool = False,
   ) -> None: ...
   ```
2. **Calculate RSI in `prepare_dataframe`**:
   ```python
   df["rsi"] = ta.momentum.RSIIndicator(close=df["close"], window=self.rsi_period).rsi()
   ```
3. **Enforce strict overbought/oversold filtering in `evaluate_bar`**:
   ```python
   rsi = float(row.get("rsi", 50.0))
   
   # Bullish Pullback (CALL)
   if uptrend:
       if (low <= ema_f * 1.0005 and close >= ema_f) or (low <= ema_m * 1.0005 and close >= ema_m):
           # Require RSI <= 65 and Stoch <= 75 to avoid buying into extreme tops
           if (sk > sd or (sk > prev_sk and sk < self.stoch_overbought)) and rsi <= self.rsi_overbought and sk <= self.stoch_overbought:
               action = TradeAction.CALL
               confidence = 0.70
               ...
   
   # Bearish Pullback (PUT)
   elif downtrend:
       if (high >= ema_f * 0.9995 and close <= ema_f) or (high >= ema_m * 0.9995 and close <= ema_m):
           # Require RSI >= 35 and Stoch >= 25 to avoid selling into extreme bottoms
           if (sk < sd or (sk < prev_sk and sk > self.stoch_oversold)) and rsi >= self.rsi_oversold and sk >= self.stoch_oversold:
               action = TradeAction.PUT
               confidence = 0.70
               ...
   ```

### 4.2 Enhancing `SupportResistanceBounceStrategy` (`src/strat_trade/domain/strategies/support_resistance_bounce.py`)
1. **Enforce minimum wick ratio $\ge 0.35$ and directional bounce confirmation**:
   ```python
   # Bounce off Support (CALL):
   # 1. Low tested support level: low <= supp * 1.0005
   # 2. Closed inside/above support: close >= supp
   # 3. Lower rejection wick >= min_wick_ratio (>= 0.35)
   # 4. Bounce confirmation: Bullish close (close > open_) and close in upper 50% of bar
   if (
       low <= supp * 1.0005
       and close >= supp
       and (lower_wick / range_) >= max(0.35, self.min_wick_ratio)
       and close > open_
       and (close - low) / range_ >= 0.50
   ):
       action = TradeAction.CALL
       confidence = 0.75
       if rsi <= 40:
           confidence += 0.15

   # Rejection off Resistance (PUT):
   # 1. High tested resistance level: high >= res * 0.9995
   # 2. Closed inside/below resistance: close <= res
   # 3. Upper rejection wick >= min_wick_ratio (>= 0.35)
   # 4. Bounce confirmation: Bearish close (close < open_) and close in lower 50% of bar
   elif (
       high >= res * 0.9995
       and close <= res
       and (upper_wick / range_) >= max(0.35, self.min_wick_ratio)
       and close < open_
       and (high - close) / range_ >= 0.50
   ):
       action = TradeAction.PUT
       confidence = 0.75
       if rsi >= 60:
           confidence += 0.15
   ```

### 4.3 Updating `StrategyAutoMatcher` & Prioritization (`src/strat_trade/domain/optimizer/auto_matcher.py`)
1. **Update variations**:
   - For `support_resistance_bounce`: set `min_wick_ratio` to `0.35` and `0.40` (replace `0.28`).
   - For `ema_pullback_trend`: ensure variations include `rsi_overbought: 65.0`, `rsi_oversold: 35.0`.
2. **Strategy Prioritization Bonus in `find_optimal_strategy_for_asset`**:
   - Give priority weighting (+15.0 quantum score) to `supertrend_adx_momentum`, `hybrid_multifactors`, `rsi_stochastic_extreme`, `macd_divergence_break`.
3. **Change Fallback Profile in `_heuristic_profile_for_asset`**:
   - Replace default fallback `ema_pullback_trend` with `hybrid_multifactors` or `supertrend_adx_momentum`.

---

## 5. Verification Method

1. **Unit & Logic Verification**:
   - Run full test suite with `.venv/bin/pytest`.
   - Add unit tests in `tests/test_strategy_logic_enhancements.py` testing:
     - `EmaPullbackTrendStrategy` overbought CALL suppression ($RSI > 65$ or $Stoch > 75$).
     - `EmaPullbackTrendStrategy` oversold PUT suppression ($RSI < 35$ or $Stoch < 25$).
     - `SupportResistanceBounceStrategy` wick ratio $< 0.35$ rejection.
     - `SupportResistanceBounceStrategy` lack of bounce confirmation rejection (e.g. bearish candle testing support rejected for CALL).
2. **Regression Verification**:
   - Run `.venv/bin/pytest tests/test_new_strategies.py tests/test_strategy_auto_matcher.py tests/test_rolling_15_trade_verification.py`.
