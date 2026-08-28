# Comprehensive Investigation Report: Strategy Portfolio & Engine Architecture

**Explorer**: Explorer 1 (`.agents/explorer_survey_1`)  
**Mission**: Strategy Engine & Portfolio Survey (Registration, Auto-Matching, Execution, Sniper Alpha Models, Runaway Momentum Guardrails)  
**Project Root**: `/Users/vlados/work/projects/startup/strat_trade_be`  
**Date**: 2026-08-24  

---

## 1. Observation

### 1.1 Strategy Architecture & Registration

1. **Strategy Base Interface**:
   - **File**: `src/strat_trade/domain/strategies/base.py:1-78`
   - **Core Classes**:
     - `SignalResult` (`base.py:12-19`): `action: TradeAction | None`, `confidence: float`, `expiration_bars: int`, `regime: str`, `metadata: dict[str, Any]`.
     - `ParameterDef` (`base.py:21-32`): `name`, `display_name`, `param_type`, `default_value`, `min_value`, `max_value`, `step`, `options`, `description`.
     - `BaseStrategy(ABC)` (`base.py:34-78`):
       - `prepare_dataframe(df_raw: pd.DataFrame) -> pd.DataFrame` (abstract)
       - `evaluate_bar(df: pd.DataFrame, idx: int) -> SignalResult` (abstract)
       - `evaluate_candles(candles: list[Any]) -> SignalResult` (`base.py:50-71`): converts candles to OHLCV DataFrame and calls `prepare_dataframe()` + `evaluate_bar()`.
       - `get_parameter_definitions() -> list[ParameterDef]` (abstract classmethod).

2. **Strategy Registry**:
   - **File**: `src/strat_trade/domain/strategies/registry.py:1-190`
   - **Registry Dictionary**: `_STRATEGIES: dict[str, StrategyMetadata]` (`registry.py:32-129`) contains 8 registered strategies:
     1. `"hybrid_multifactors"` (`HybridMultiFactorsStrategy`)
     2. `"bollinger_atr_reversion"` (`BollingerAtrReversionStrategy`)
     3. `"ema_pullback_trend"` (`EmaPullbackTrendStrategy`)
     4. `"rsi_stochastic_extreme"` (`RsiStochasticExtremeStrategy`)
     5. `"macd_divergence_break"` (`MacdDivergenceBreakStrategy`)
     6. `"volatility_squeeze_breakout"` (`VolatilitySqueezeBreakoutStrategy`)
     7. `"supertrend_adx_momentum"` (`SupertrendAdxMomentumStrategy`)
     8. `"support_resistance_bounce"` (`SupportResistanceBounceStrategy`)
   - **Registry Functions**:
     - `list_available_strategies() -> list[dict[str, Any]]` (`registry.py:132-160`): iterates over `_STRATEGIES` and exports parameters and metadata.
     - `get_strategy_instance(strategy_name: str, params: dict[str, Any] | None = None, **kwargs: Any) -> BaseStrategy` (`registry.py:163-190`): normalizes strategy string (case/whitespace), falls back safely to `support_resistance_bounce` or `rsi_stochastic_extreme`, dynamically inspects `__init__` signatures, and instantiates the strategy.

---

### 1.2 Strategy Auto-Matching & Asset Allocation

1. **Auto-Matcher Engine**:
   - **File**: `src/strat_trade/domain/optimizer/auto_matcher.py:1-523`
   - **Priority Filter**:
     ```python
     PRIORITY_STRATEGIES: frozenset[str] = frozenset(
         {
             "support_resistance_bounce",
             "rsi_stochastic_extreme",
             "ema_pullback_trend",
         }
     )
     ```
     (`auto_matcher.py:21-27`).
   - **Candidate Strategy Filtering**:
     - `candidate_strategies = [s for s in strategies if s["id"] in PRIORITY_STRATEGIES]` (`auto_matcher.py:435-437`). This restricts automated search space strictly to the 3 primary sniper alpha strategies.
   - **Asset Heuristic Profiling & Fallbacks** (`auto_matcher.py:232-378`):
     - Gold / Commodities (`GOLD`, `XAU`): assigned `"support_resistance_bounce"` (Pin-Bar) with `swing_window=20`, `rsi_period=14`, `min_wick_ratio=0.35` (`lines 241-252`).
     - Stocks (`AAPL`, `TSLA`, etc.): assigned `"ema_pullback_trend"` (EMA Ribbon) (`lines 253-271`).
     - Crypto (`BTC`, `ETH`, etc.): assigned `"rsi_stochastic_extreme"` (`lines 272-285`).
     - Forex (`EUR`, `GBP`, `JPY`, etc.): JPY/GBP pairs assigned `"support_resistance_bounce"`, others assigned `"rsi_stochastic_extreme"` (`lines 286-332`).
     - Default unclassified fallback: Primary `"support_resistance_bounce"`, secondary `"rsi_stochastic_extreme"` (`lines 333-366`).
   - **Plan Generation**:
     - `src/strat_trade/use_cases/auto_assign_strategies.py:13-102` (`generate_pre_trading_plan`): executes `find_optimal_strategy_for_asset()` across allowed assets concurrently with semaphore limit (8 workers).

---

### 1.3 Execution Engine (`LiveDemoBotEngine`)

1. **Bot Engine State Machine**:
   - **File**: `src/strat_trade/domain/trading/bot_engine.py:1-704`
   - **Lifecycle**:
     - `start(plan: PreTradingPlan, gateway: Any)` (`bot_engine.py:61-93`): instantiates strategy per asset via `get_strategy_instance(a.strategy_id, **a.parameters)` into `self._strategy_instances[a.asset]`, resets drawdown baseline, and launches `_run_loop()`.
     - `_run_loop()` (`bot_engine.py:199-233`): executes every 4 seconds:
       1. `_check_active_trades()` (`lines 269-385`): polls closed trades, evaluates WIN/LOSS/DRAW, updates PnL and high-watermark drawdown, triggers per-asset cooldown (`cooldown_sec = max(180, cooldown_bars * 60)`), and checks consecutive loss threshold.
       2. `_check_circuit_breakers()` (`lines 234-268`): checks hard Stop-Loss and max peak-to-trough drawdown limits.
       3. Auto-resumes bot if temporary cooldown/pause expired.
       4. `_evaluate_signals_and_trade()` (`lines 387-414`): runs evaluation across assets with semaphore limit (6 workers).
     - `_evaluate_single_asset()` (`bot_engine.py:415-523`):
       - Checks toxic blacklist (`is_toxic_asset`).
       - Checks duplicate active trade guard.
       - Checks per-asset post-settlement cooldown (`self._asset_cooldown_until`).
       - Checks signal-to-signal 30s rate limit.
       - Evaluates live broker payout vs minimum threshold (`min_payout_rate`).
       - Fetches candles and invokes `strat.evaluate_candles(candles)`.
       - Checks multi-pair currency correlation conflicts (`is_correlated_conflict()`).
       - Dispatches `_execute_order()`.
     - `_execute_order()` (`bot_engine.py:524-651`):
       - Acquired `_order_lock` mutex.
       - Double-checks toxic blacklist, post-settlement cooldown, and global 30s portfolio cooldown.
       - Sizes stake (Flat or Percentage of equity).
       - Extracts `IndicatorSnapshot` (`lines 652-704`).
       - Submits order via `gateway.open_trade()`.
       - Saves `LiveTradeRecord` to `TradeStore` (SQLite) and `self.active_trades`.

---

### 1.4 Primary Alpha Strategies Detailed Inspection

| Strategy | File Location | Core Concept | Default Parameters | Expiration | Confluence Filters |
|---|---|---|---|---|---|
| **Support & Resistance Pin-Bar** (`SupportResistanceBounceStrategy`) | `src/strat_trade/domain/strategies/support_resistance_bounce.py:10-141` | Rolling horizontal S/R bounce with rejection pin-bar wick | `swing_window=20`<br>`rsi_period=14`<br>`min_wick_ratio=0.35`<br>`base_expiration_bars=3` | 3 bars (180s) | • Swing low/high touch (`low <= supp * 1.0005` or `high >= res * 0.9995`)<br>• Rejection wick ratio $\ge 35\%$<br>• Candle color confirmation (`close > open` for CALL, `close < open` for PUT)<br>• Position in range $\ge 50\%$<br>• RSI filter bonus ($\le 40$ for CALL, $\ge 60$ for PUT) |
| **RSI + Stoch Extreme Scalp** (`RsiStochasticExtremeStrategy`) | `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py:10-158` | Dual oscillator overbought/oversold exhaustion reversal | `rsi_period=14`<br>`rsi_oversold=25.0`<br>`rsi_overbought=75.0`<br>`stoch_k=14`<br>`stoch_d=3`<br>`stoch_oversold=20.0`<br>`stoch_overbought=80.0`<br>`base_expiration_bars=3` | 3 bars (180s) | • Dual boundary condition: RSI $\le 25$ & Stoch $\%K \le 20$ (CALL); RSI $\ge 75$ & Stoch $\%K \ge 80$ (PUT)<br>• Fresh $\%K / \%D$ crossover bonus |
| **EMA Ribbon Trend Pullback** (`EmaPullbackTrendStrategy`) | `src/strat_trade/domain/strategies/ema_pullback_trend.py:10-224` | Trend following on pullbacks into dynamic EMA 9/21 ribbon | `ema_fast=9`<br>`ema_mid=21`<br>`ema_slow=50`<br>`adx_period=14`<br>`adx_threshold=25.0`<br>`stoch_k=14, stoch_d=3`<br>`rsi_period=14`<br>`rsi_overbought=65.0`<br>`rsi_oversold=35.0`<br>`stoch_overbought=75.0`<br>`stoch_oversold=25.0`<br>`base_expiration_bars=3` | 3 bars (180s) | • Triple EMA trend alignment (`EMA9 > EMA21 > EMA50`)<br>• ADX $\ge 25.0$ and $DI+ > DI-$<br>• Price touches EMA 9 or 21<br>• Stochastic crossover in trend direction<br>• Anti-top/bottom guard: RSI $\le 65$ (CALL) & RSI $\ge 35$ (PUT) |

---

### 1.5 Deactivation Status of Legacy Strategies

1. **`MACD Divergence & Cross` (`MacdDivergenceBreakStrategy`)**:
   - Registered in `registry.py:81-92`.
   - Excluded from `auto_matcher.py:PRIORITY_STRATEGIES`.
   - Excluded from `_heuristic_profile_for_asset()`.
   - Safe to remain in `_STRATEGIES` for standalone backtests without ever being auto-assigned to the live bot.

2. **`Гібридна Мульти-Факторна` (`HybridMultiFactorsStrategy`)**:
   - Registered in `registry.py:33-44`.
   - Excluded from `auto_matcher.py:PRIORITY_STRATEGIES`.
   - Excluded from `_heuristic_profile_for_asset()`.
   - Legacy template references in `index.html` (e.g. default fallback values) can be updated to `'support_resistance_bounce'` or `'rsi_stochastic_extreme'`.

---

### 1.6 Current Absence of Runaway Momentum Guards

1. **In `SupportResistanceBounceStrategy` (`support_resistance_bounce.py:48-105`)**:
   - The strategy only checks the current bar (`idx`) against rolling swing support/resistance and calculates current bar wick ratio.
   - It **does not inspect** the preceding 3-4 bars for consecutive unidirectional momentum bursts.
   - **Vulnerability**: If 3 consecutive large red candles smash into support during a market sell-off, a minor lower wick on the 4th candle will trigger a CALL trade, resulting in a loss when the downward waterfall continues.

2. **In `RsiStochasticExtremeStrategy` (`rsi_stochastic_extreme.py:58-99`)**:
   - The strategy only checks if RSI $\le 25$ and Stoch $\le 20$ (or $\ge 75$ and $\ge 80$).
   - During a runaway trend or news event (e.g. 4-5 consecutive expanding directional candles), oscillators peg at the extreme limits (RSI 10-15, Stoch 0-5) across several bars.
   - **Vulnerability**: The strategy blindly triggers counter-trend CALL/PUT signals on every bar during the waterfall ("catching a falling knife"), creating multiple consecutive losses (5-8 loss cascades).

---

## 2. Logic Chain

1. **Sniper Strategy Edge vs. Indicator Spam**:
   - `MACD Divergence & Cross` and uncalibrated multi-factor models generate frequent low-conviction signals during choppy/transition phases.
   - Restricting live bot assignments to the three vetted models (`support_resistance_bounce`, `rsi_stochastic_extreme`, `ema_pullback_trend`) focuses capital on high-probability price-action rejection, dual-oscillator exhaustion, and strong trend pullbacks.

2. **The Runaway Momentum Failure Mode**:
   - Mean-reversion models assume price returns to a local mean after an extreme excursion.
   - However, during news releases or violent volatility sweeps, price experiences **directional expansion** (runaway momentum) where 3-4 consecutive M1 candles close aggressively in the same direction with expanding bodies and almost non-existent rejection wicks.
   - In this regime, oscillator extremes (RSI $< 20$, Stoch $< 10$) and horizontal support touches do NOT indicate exhaustion; they indicate massive institutional flow breaking through support/resistance.

3. **Detection and Filtering Logic**:
   - To prevent catching falling knives without altering legitimate single-bar rejections, an entry guard must analyze the preceding sequence of 3 to 4 M1 candles:
     $$\text{Bearish Runaway} \iff \forall t \in [idx-k, idx]: (close_t < open_t) \land \left(\frac{|close_t - open_t|}{high_t - low_t} \ge 0.50\right) \land \left(\frac{close_t - low_t}{high_t - low_t} \le 0.25\right)$$
     $$\text{Bullish Runaway} \iff \forall t \in [idx-k, idx]: (close_t > open_t) \land \left(\frac{|close_t - open_t|}{high_t - low_t} \ge 0.50\right) \land \left(\frac{high_t - close_t}{high_t - low_t} \le 0.25\right)$$
   - When a Bearish Runaway sequence is detected: **Suppress CALL signals** (`action = None`, `regime = "runaway_momentum_suppressed"`).
   - When a Bullish Runaway sequence is detected: **Suppress PUT signals** (`action = None`, `regime = "runaway_momentum_suppressed"`).

---

## 3. Proposed Implementation Blueprint

### 3.1 Runaway Momentum Detection Function

A clean, robust helper function can be implemented in `src/strat_trade/domain/strategies/` (or directly within `SupportResistanceBounceStrategy` and `RsiStochasticExtremeStrategy`):

```python
def check_runaway_momentum(
    df: pd.DataFrame,
    idx: int,
    lookback_bars: int = 3,
    min_body_ratio: float = 0.50,
    max_opposing_wick_ratio: float = 0.25,
) -> tuple[bool, bool]:
    """
    Detects whether the market is experiencing a runaway directional momentum burst.
    
    Returns:
        (is_bearish_runaway, is_bullish_runaway)
        - is_bearish_runaway: 3+ consecutive strong red candles (suppress CALL)
        - is_bullish_runaway: 3+ consecutive strong green candles (suppress PUT)
    """
    if idx < lookback_bars:
        return False, False

    bearish_count = 0
    bullish_count = 0

    for k in range(lookback_bars):
        row = df.iloc[idx - k]
        c = float(row["close"])
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        rng = h - l

        if rng <= 1e-9:
            continue

        body = abs(c - o)
        body_ratio = body / rng

        # Check Bearish Candle
        if c < o and body_ratio >= min_body_ratio:
            lower_wick = c - l
            lower_wick_ratio = lower_wick / rng
            if lower_wick_ratio <= max_opposing_wick_ratio:
                bearish_count += 1

        # Check Bullish Candle
        elif c > o and body_ratio >= min_body_ratio:
            upper_wick = h - c
            upper_wick_ratio = upper_wick / rng
            if upper_wick_ratio <= max_opposing_wick_ratio:
                bullish_count += 1

    is_bearish_runaway = (bearish_count >= lookback_bars)
    is_bullish_runaway = (bullish_count >= lookback_bars)

    return is_bearish_runaway, is_bullish_runaway
```

### 3.2 Integration Points

1. **In `SupportResistanceBounceStrategy.evaluate_bar()`**:
   - Evaluate `is_bearish_runaway, is_bullish_runaway = self._check_runaway_momentum(df, idx)`.
   - If support bounce (CALL candidate) and `is_bearish_runaway`: suppress CALL entry, set `regime = "runaway_momentum_suppressed"`.
   - If resistance rejection (PUT candidate) and `is_bullish_runaway`: suppress PUT entry, set `regime = "runaway_momentum_suppressed"`.

2. **In `RsiStochasticExtremeStrategy.evaluate_bar()`**:
   - Evaluate `is_bearish_runaway, is_bullish_runaway = self._check_runaway_momentum(df, idx)`.
   - If oversold exhaustion (CALL candidate) and `is_bearish_runaway`: suppress CALL entry.
   - If overbought exhaustion (PUT candidate) and `is_bullish_runaway`: suppress PUT entry.

---

## 4. Caveats

1. **Preserving Rejection Pin-Bars**:
   - If the current bar (`idx`) itself forms a large rejection pin-bar (e.g. lower wick $> 50\%$ and body is small/green), it should be evaluated whether the runaway sequence should check bars $idx-3 \dots idx-1$ (preceding bars) vs $idx-2 \dots idx$.
   - Checking bars $idx-1, idx-2, idx-3$ for runaway momentum ensures that even if bar $idx$ is a slight bounce, the momentum waterfall from the preceding 3 bars still suppresses dangerous entries, while normal quiet range bounces remain fully active.
2. **Strategy Registry Compatibility**:
   - `MACD Divergence & Cross` and `hybrid_multifactors` must remain in `registry.py` to prevent import errors in historical backtest modules, while remaining strictly deactivated from live bot assignments.
3. **No Code Modification During Survey**:
   - As per read-only explorer constraints, no source code or test files were modified during this survey.

---

## 5. Conclusion

1. **Strategy Engine Health**:
   - The strategy engine architecture (`BaseStrategy`, `registry.py`, `StrategyAutoMatcher`, `LiveDemoBotEngine`) is robust, clean, and fully operational (914 pytest unit/integration tests passing, 0 ruff errors).
2. **Portfolio Restructuring**:
   - `PRIORITY_STRATEGIES` in `auto_matcher.py` is configured with `support_resistance_bounce`, `rsi_stochastic_extreme`, and `ema_pullback_trend`.
   - Legacy strategies (`hybrid_multifactors`, `macd_divergence_break`) are safely excluded from automated live matching.
3. **Runaway Momentum Filter**:
   - The entry guard enhancement for `SupportResistanceBounceStrategy` and `RsiStochasticExtremeStrategy` is fully mapped out.
   - Implementing consecutive candle sequence detection (3-4 bars with expanding bodies $\ge 50\%$ and opposing wicks $\le 25\%$) will prevent counter-trend entries during market waterfalls and eliminate loss streaks.

---

## 6. Verification Method

To independently verify the facts and findings documented in this survey:

1. **Run Full Test Suite**:
   ```bash
   ./.venv/bin/pytest -v
   ```
   *(Confirmed: 914 passed, 2 warnings in 22.67s)*

2. **Run Linter**:
   ```bash
   ./.venv/bin/ruff check .
   ```
   *(Confirmed: All checks passed!)*

3. **Verify File Paths and Classes**:
   - Base Strategy: `src/strat_trade/domain/strategies/base.py`
   - Strategy Registry: `src/strat_trade/domain/strategies/registry.py`
   - Strategy Auto-Matcher: `src/strat_trade/domain/optimizer/auto_matcher.py`
   - Live Bot Engine: `src/strat_trade/domain/trading/bot_engine.py`
   - S&R Pin-Bar Strategy: `src/strat_trade/domain/strategies/support_resistance_bounce.py`
   - RSI+Stoch Extreme Strategy: `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`
   - EMA Ribbon Trend Pullback Strategy: `src/strat_trade/domain/strategies/ema_pullback_trend.py`
