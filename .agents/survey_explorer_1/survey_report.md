# Comprehensive Strategy & Signal Logic Survey Report

**Author**: `survey_explorer_1`  
**Date**: 2026-08-20  
**Target Project**: `strat_trade_be` (Pocket Option AutoTrader Pro Backend)  
**Status**: Read-Only Survey Complete  

---

## 1. Executive Summary

This survey explores the quantitative strategy architecture, indicator calculation pipelines, and signal generation mechanisms within `strat_trade_be`. The analysis focused on:
1. **`VolatilitySqueezeBreakoutStrategy`**: Pinpointing the false breakout bug causing continuous bar-by-bar signal spamming outside squeeze periods.
2. **`BollingerAtrReversionStrategy`**: Identifying structural deficiencies in candle confirmation (wick rejection + candle close inside band) and the total absence of ADX-based trend suppression against runaway OTC momentum regimes.
3. **Full Strategy Ecosystem & Indicator Mechanics**: Mapping all 8 strategies, their parameter schemas, backtest execution mechanics, and integration into the live/demo `LiveDemoBotEngine`.

---

## 2. Strategy Architecture & Registry Mapping

### 2.1 Base Strategy Interface (`src/strat_trade/domain/strategies/base.py`)

All strategies inherit from `BaseStrategy` and communicate decisions via `SignalResult` and `ParameterDef`:

```python
@dataclass
class SignalResult:
    action: TradeAction | None  # TradeAction.CALL, TradeAction.PUT, or None
    confidence: float          # 0.0 to 1.0
    expiration_bars: int       # Trade expiration duration in bars (e.g. 1 to 5)
    regime: str                # Diagnostic regime string (e.g. "volatility_breakout", "mean_reversion")
    metadata: dict[str, Any]   # Indicator values, debug telemetry, reasons
```

#### Core Abstract Methods
- `prepare_dataframe(self, df_raw: pd.DataFrame) -> pd.DataFrame`: Vectorized indicator computation over OHLCV data.
- `evaluate_bar(self, df: pd.DataFrame, idx: int) -> SignalResult`: State-free or rolling evaluation of candle at index `idx`.
- `evaluate_candles(self, candles: list[Any]) -> SignalResult`: Convenience bridge converting domain `Candle` entities to DataFrame and evaluating `idx = len(df) - 1`.
- `get_parameter_definitions(cls) -> list[ParameterDef]`: Metadata declarations for dynamic parameter reflection and grid-search optimization.

---

### 2.2 Strategy Registry Catalog (`src/strat_trade/domain/strategies/registry.py`)

The system registers 8 discrete quantitative strategies:

| Strategy ID | Class Name | Category | Primary Indicators | Core Rationale |
|---|---|---|---|---|
| `hybrid_multifactors` | `HybridMultiFactorsStrategy` | Hybrid Multi-Factor | EMA(9,21,50), RSI(14), Stoch(14,3), BB(20,2), ATR, ADX(14) | Multi-indicator consensus filter with trend and oscillation agreement |
| `bollinger_atr_reversion` | `BollingerAtrReversionStrategy` | Mean Reversion | Bollinger Bands(20,2), RSI(14), ATR(14) | Boundary rejection in ranging markets with volatility surge protection |
| `ema_pullback_trend` | `EmaPullbackTrendStrategy` | Trend Following | EMA(9,21,50), ADX(14), Stoch(14,3) | Trend pullback to EMA 9/21 zone during strong momentum (ADX $\ge$ 25) |
| `rsi_stochastic_extreme` | `RsiStochasticExtremeStrategy` | Scalping Reversal | RSI(14), Stochastic(14,3,3) | Micro liquidity exhaustion when both oscillators reach extreme boundaries |
| `macd_divergence_break` | `MacdDivergenceBreakStrategy` | Reversal Divergence | MACD(12,26,9), Swing High/Low | Regular swing divergence detection with histogram zero-line momentum |
| `volatility_squeeze_breakout` | `VolatilitySqueezeBreakoutStrategy` | Volatility Breakout | Bollinger Bands(20,2), Keltner Channels(20,1.5), Momentum(12) | TTM Squeeze release when compressed Bollinger Bands expand outside Keltner |
| `supertrend_adx_momentum` | `SupertrendAdxMomentumStrategy` | Momentum Trend | Supertrend(10,3.0), ADX(14) | Supertrend directional flips and continuations gated by ADX $\ge$ 25 |
| `support_resistance_bounce` | `SupportResistanceBounceStrategy` | Price Action / S&R | Rolling 20-bar High/Low, RSI(14), Pin-bar wick ratio | Price bouncing off dynamic support/resistance with pin-bar wick rejection |

---

## 3. Deep Dive: `VolatilitySqueezeBreakoutStrategy`

**File Path**: `src/strat_trade/domain/strategies/volatility_squeeze_breakout.py`

### 3.1 Indicator Calculation Mechanics
- **Bollinger Bands**: Computed using `ta.volatility.BollingerBands(close=df["close"], window=self.bb_length, window_dev=self.bb_std)`:
  - Upper: `bb_high`
  - Lower: `bb_low`
- **Keltner Channels**: Computed using `ta.volatility.KeltnerChannel(high=df["high"], low=df["low"], close=df["close"], window=self.kc_length, window_atr=self.kc_length, multiplier=self.kc_mult)`:
  - Upper: `kc_high`
  - Lower: `kc_low`
- **Squeeze State**:
  ```python
  df["squeeze_on"] = (df["bb_low"] > df["kc_low"]) & (df["bb_high"] < df["kc_high"])
  ```
  `squeeze_on` is `True` when volatility is compressed (BB is completely inside KC), and `False` when volatility expands (BB reaches outside KC).
- **Momentum Oscillator**:
  ```python
  df["momentum"] = df["close"] - df["close"].shift(self.momentum_period)
  ```

---

### 3.2 Root Cause Analysis: False Breakout & Continuous Bar Spamming Bug

#### Verbatim Code (`volatility_squeeze_breakout.py:83-97`):
```python
# Breakout Trigger: Squeeze was ON and fired OFF with directional momentum
squeeze_fired = (sq_prev and not sq_now) or (not sq_now and abs(mom) > 0)

if squeeze_fired:
    if mom > 0 and mom > prev_mom:
        action = TradeAction.CALL
        confidence = 0.75
        if sq_prev and not sq_now:  # Fresh squeeze fire
            confidence += 0.15
    elif mom < 0 and mom < prev_mom:
        action = TradeAction.PUT
        confidence = 0.75
        if sq_prev and not sq_now:  # Fresh squeeze fire
            confidence += 0.15
```

#### Defect Mechanism:
1. The logical condition for `squeeze_fired` has a catastrophic second clause:
   $$\text{squeeze\_fired} = (\text{sq\_prev} \land \neg\text{sq\_now}) \lor (\neg\text{sq\_now} \land |\text{mom}| > 0)$$
2. In normal, uncompressed markets, `squeeze_on` is `False` (`not sq_now` is `True`).
3. Since prices are constantly fluctuating, `abs(mom) > 0` is almost universally `True`.
4. Therefore, `squeeze_fired` evaluates to `True` on **every single normal bar** in the dataset.
5. On every bar where `mom > prev_mom`, the strategy issues a `CALL` signal with `confidence = 0.75`; when `mom < prev_mom`, it issues a `PUT` signal.
6. This completely violates the foundational principle of the TTM Squeeze breakout strategy, which is designed to fire **only upon transitioning from compression to expansion**.

#### Solution & Specification:
1. **Strict Transition Condition**:
   ```python
   squeeze_fired = sq_prev and not sq_now
   ```
2. **Directional Breakout Confirmation**:
   When `squeeze_fired` is `True`:
   - `CALL`: `mom > 0` (and optionally `mom > prev_mom` or `close > kc_high`)
   - `PUT`: `mom < 0` (and optionally `mom < prev_mom` or `close < kc_low`)
   - Confidence: Base `0.75` to `0.85` on legitimate fresh breakout.
3. **Prevent Multi-Bar Retriggers**: Ensure signals only trigger on the exact transition bar (bar $t$ where $t-1$ was squeezed and $t$ is released).

---

## 4. Deep Dive: `BollingerAtrReversionStrategy`

**File Path**: `src/strat_trade/domain/strategies/bollinger_atr_reversion.py`

### 4.1 Current Implementation & Mechanics
- **Indicators Prepared**:
  - `bb_high`, `bb_mid`, `bb_low`, `bb_pband` via `ta.volatility.BollingerBands(close, window=20, window_dev=2.0)`
  - `rsi` via `ta.momentum.RSIIndicator(close, window=14)`
  - `atr` and `atr_sma` (30-bar rolling mean of ATR)
- **Volatility Spike Filter**:
  - `vol_ratio = atr / atr_sma`
  - If `vol_ratio > max_atr_ratio` (default 2.2), signals are suppressed (`regime="volatility_spike_suppressed"`).

---

### 4.2 Defect 1: Missing Candle Confirmation (Blind Knife-Catching)

#### Verbatim Code (`bollinger_atr_reversion.py:99-122`):
```python
# Bullish Reversal: Price pierced lower band + RSI oversold + lower wick rejection
lower_wick = min(open_, close) - low
if (low <= bb_l or close <= bb_l * 1.0002 or bb_pband <= 0.05) and (
    rsi <= self.rsi_oversold or prev["rsi"] <= self.rsi_oversold
):
    action = TradeAction.CALL
    confidence = 0.65
    if lower_wick > body * 0.8:
        confidence += 0.15
    if close > open_:  # bullish candle
        confidence += 0.10

# Bearish Reversal: Price pierced upper band + RSI overbought + upper wick rejection
upper_wick = high - max(open_, close)
if (high >= bb_h or close >= bb_h * 0.9998 or bb_pband >= 0.95) and (
    rsi >= self.rsi_overbought or prev["rsi"] >= self.rsi_overbought
):
    action = TradeAction.PUT
    confidence = 0.65
    if upper_wick > body * 0.8:
        confidence += 0.15
    if close < open_:  # bearish candle
        confidence += 0.10
```

#### Defect Mechanism:
1. The condition `close <= bb_l * 1.0002` triggers when a strong bearish momentum candle crashes *through* and closes *outside* the lower Bollinger Band.
2. The wick check (`lower_wick > body * 0.8`) is solely an optional confidence bonus (+0.15), not an entry condition.
3. As a result, the strategy enters `CALL` while the candle is closed below the band with zero lower wick (a marubozu or falling knife candle).
4. In binary options, betting against an active breakout before price shows any sign of rejection guarantees high loss rates.

#### Specification for Proper Candle Confirmation:
1. **Bullish Reversal (CALL)**:
   - **Boundary Touch**: `low <= bb_l` (or `low <= bb_l * 1.0005` / `bb_pband <= 0.05`)
   - **Band Re-entry / Inside Close**: `close >= bb_l` (candle closed inside or back above the lower band)
   - **Lower Wick Rejection Gate**: Lower wick must demonstrate buying pressure:
     $$\text{lower\_wick} = \min(\text{open}, \text{close}) - \text{low} \ge \text{body} \times \text{min\_wick\_ratio} \quad (\text{or } \text{lower\_wick} / (\text{high} - \text{low}) \ge 0.25)$$
   - **Oscillator Filter**: `rsi <= rsi_oversold` (or `prev_rsi <= rsi_oversold` with rising RSI).
2. **Bearish Reversal (PUT)**:
   - **Boundary Touch**: `high >= bb_h` (or `high >= bb_h * 0.9995` / `bb_pband >= 0.95`)
   - **Band Re-entry / Inside Close**: `close <= bb_h` (candle closed inside or back below the upper band)
   - **Upper Wick Rejection Gate**: Upper wick must demonstrate selling pressure:
     $$\text{upper\_wick} = \text{high} - \max(\text{open}, \text{close}) \ge \text{body} \times \text{min\_wick\_ratio} \quad (\text{or } \text{upper\_wick} / (\text{high} - \text{low}) \ge 0.25)$$
   - **Oscillator Filter**: `rsi >= rsi_overbought` (or `prev_rsi >= rsi_overbought` with falling RSI).

---

### 4.3 Defect 2: Missing ADX-Based Trend Suppression (Runaway Trends)

#### Defect Mechanism:
1. `prepare_dataframe` does **not calculate ADX** at all.
2. In strong trending markets (e.g. OTC runaway trends), price constantly walks the upper or lower Bollinger band for 10–30 bars.
3. During such trends, RSI remains pinned in overbought/oversold territory.
4. Without an ADX filter, the mean-reversion strategy repeatedly takes losing counter-trend trades.

#### Specification for ADX Trend Suppression:
1. **Indicator Addition**:
   - In `prepare_dataframe`:
     ```python
     adx_ind = ta.trend.ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=self.adx_period)
     df["adx"] = adx_ind.adx()
     ```
2. **Parameter Configuration**:
   - `adx_period: int = 14`
   - `adx_trend_threshold: float = 25.0` (or `adx_max: float = 25.0`)
3. **Filter Gate in `evaluate_bar`**:
   - If `adx >= self.adx_trend_threshold`, suppress the mean-reversion signal:
     ```python
     if adx >= self.adx_trend_threshold:
         return SignalResult(
             action=None,
             confidence=0.0,
             expiration_bars=self.base_expiration_bars,
             regime="trend_suppressed_adx",
             metadata={"adx": round(adx, 2), "rsi": round(rsi, 2)},
         )
     ```
4. **ParameterDef and Registry Update**: Expose `adx_trend_threshold` in `get_parameter_definitions()` so it can be optimized.

---

## 5. Execution Pipeline & Guardrail Interconnections

### 5.1 Backtest Engines
- **Single Asset**: `BinaryBacktestEngine` (`src/strat_trade/domain/backtest/engine.py`)
  - Evaluates bars sequentially $i \in [50, N-1]$.
  - Respects expiration bars $exit\_idx = i + exp\_bars$.
  - Computes Win Rate, PnL with payout rates, Profit Factor, and Max Drawdown.
- **Portfolio**: `PortfolioBinaryBacktestEngine` (`src/strat_trade/domain/backtest/portfolio_engine.py`)
  - Chronological multi-asset signal execution against shared balance.
  - Concurrency caps (`max_concurrent_trades`).

### 5.2 Bot Engine Safeguards (`src/strat_trade/domain/trading/bot_engine.py`)
- **Current Safeguards**:
  - Session Stop-Loss: `loss >= self.plan.stop_loss_amount` -> halts bot (`BotStatus.HALTED_BY_STOP_LOSS`).
  - Active trade limit: `len(self.active_trades) >= self.plan.max_concurrent_trades`.
  - Same asset deduplication: skips if trade on `asset` is already active.
  - Per-asset timer: hardcoded `(now - last_sig).total_seconds() < 30`.
- **Gaps Identified for R2**:
  - Missing Bar-Based Cooldown ($N$ bars before re-entering same pair).
  - Missing Correlated Currency Pair Protection (e.g. AUD/USD and AUD/NZD entering CALL simultaneously).
  - Missing Consecutive-Loss Circuit Breaker ($K$ consecutive losses pausing trading).

---

## 6. Comprehensive File, Class, and Signature Catalog

| Module / File Path | Class / Function | Key Signatures & Methods | Core Dependencies |
|---|---|---|---|
| `src/strat_trade/domain/strategies/base.py` | `BaseStrategy`<br>`SignalResult`<br>`ParameterDef` | `prepare_dataframe(df_raw)`<br>`evaluate_bar(df, idx)`<br>`evaluate_candles(candles)`<br>`get_parameter_definitions()` | `pandas`, `dataclasses`, `TradeAction` |
| `src/strat_trade/domain/strategies/volatility_squeeze_breakout.py` | `VolatilitySqueezeBreakoutStrategy` | `__init__(bb_length, bb_std, kc_length, kc_mult, momentum_period, ...)`<br>`prepare_dataframe()`<br>`evaluate_bar()` | `ta.volatility.BollingerBands`, `ta.volatility.KeltnerChannel`, `pandas` |
| `src/strat_trade/domain/strategies/bollinger_atr_reversion.py` | `BollingerAtrReversionStrategy` | `__init__(bb_length, bb_std, rsi_period, rsi_oversold, rsi_overbought, atr_period, max_atr_ratio, ...)`<br>`prepare_dataframe()`<br>`evaluate_bar()` | `ta.volatility.BollingerBands`, `ta.momentum.RSIIndicator`, `ta.volatility.AverageTrueRange`, `ta.trend.ADXIndicator` |
| `src/strat_trade/domain/strategies/registry.py` | `_STRATEGIES`<br>`list_available_strategies()`<br>`get_strategy_instance()` | `get_strategy_instance(strategy_name, params, **kwargs)` | All strategy classes, `inspect` |
| `src/strat_trade/domain/backtest/engine.py` | `BinaryBacktestEngine` | `__init__(config: BacktestConfig)`<br>`run(df_raw) -> BacktestSummary` | `BacktestConfig`, `BacktestSummary`, `Decimal` |
| `src/strat_trade/domain/backtest/portfolio_engine.py` | `PortfolioBacktestEngine` | `__init__(config: PortfolioBacktestConfig)`<br>`run(asset_dfs) -> PortfolioBacktestSummary` | `PortfolioBacktestConfig`, `Decimal` |
| `src/strat_trade/domain/optimizer/grid_search.py` | `StrategyOptimizerEngine` | `__init__(...)`<br>`run(df_raw, parameter_grid) -> OptimizationReport` | `itertools`, `BinaryBacktestEngine` |
| `src/strat_trade/domain/trading/bot_engine.py` | `LiveDemoBotEngine` | `start(plan, gateway)`<br>`stop()`<br>`_evaluate_signals_and_trade()`<br>`_check_active_trades()` | `TradeStore`, `PocketOptionGateway` |

---

## 7. Edge Cases & Validation Guidelines

1. **Warmup Period Constraints**:
   - `prepare_dataframe` returns early if `len(df) < max_lookback + 10`.
   - `evaluate_bar` requires `idx >= 30` or `idx >= 50` to ensure rolling windows and moving averages are fully populated without `NaN`.
2. **Candle Data Gaps**:
   - `data_loader.py` and `evaluate_candles()` handle missing timestamps by cleaning and sorting.
3. **Volatility Spikes**:
   - When ATR spikes above `max_atr_ratio` times its 30-bar SMA, mean reversion must remain suppressed.
4. **Zero-Range Bars / Flat Prices**:
   - When `high == low` (zero volume or frozen feed), `lower_wick / range_` must guard against division by zero.
5. **Exact Squeeze Fire Boundary**:
   - A squeeze release occurs on the first bar where `squeeze_on` flips from `True` to `False`. The signal must only trigger on that specific transition bar.
