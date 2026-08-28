# Comprehensive Survey Report: R1 Strategy Portfolio Restructuring (Sniper Edge)

**Document Version**: 1.0.0  
**Date**: 2026-08-23  
**Target Subsystem**: Strategy Registry, StrategyAutoMatcher, LiveDemoBotEngine, Primary Alpha Strategies, and Confluence Pipelines  
**Integrity Mode**: Development / High Conviction  

---

## 1. Executive Summary

This investigation surveys the architecture, current implementation, data flows, and test footprint required to restructure the trading strategy portfolio of **Pocket Option AutoTrader Pro** into a high-conviction **Sniper Confluence System** (Requirement **R1**).

### Core Discoveries:
1. **Deactivation Targets**:
   - `MACD Divergence & Cross` (`macd_divergence_break`) and `Гібридна Мульти-Факторна` (`hybrid_multifactors`) are currently active in `StrategyAutoMatcher.PRIORITY_STRATEGIES` (`auto_matcher.py:17-24`), receive `+15.0` quantum bonus points in automated strategy profiling, and serve as default/heuristic fallbacks for stocks and commodities (`auto_matcher.py:238-266`, `auto_matcher.py:323-352`).
   - They can be cleanly deactivated from default live demo bot assignment and automated priority matching by modifying `PRIORITY_STRATEGIES`, `_heuristic_profile_for_asset`, and `get_strategy_instance` fallbacks while preserving their metadata classes in `_STRATEGIES` (`registry.py:32-129`) to prevent breaking existing backtest routes and legacy references.
2. **Primary Alpha Trio**:
   - **`Support & Resistance Pin-Bar`** (`support_resistance_bounce.py:10-141`): Rolling swing fractal levels + rejection wick threshold ($\ge 35\%$) + candlestick body direction + RSI overbought/oversold confirmation. Proven 57.6% WR in live broker tests.
   - **`RSI + Stoch Extreme Scalp`** (`rsi_stochastic_extreme.py:10-158`): Dual-oscillator exhaustion ($\text{RSI} \le 25 / \ge 75$ and $\text{Stoch\_K} \le 20 / \ge 80$) + fresh signal line crossover confirmation. Top performer with 71.4% WR in real broker executions.
   - **`EMA Ribbon Trend Pullback`** (`ema_pullback_trend.py:10-224`): Multi-EMA (9, 21, 50) alignment + directional ADX gate ($\text{ADX} \ge 25$, $+\text{DI} > -\text{DI}$) + dynamic value zone test + strict anti-overbought/oversold guards ($\text{RSI} \le 65 / \ge 35$, $\text{Stoch} \le 75 / \ge 25$). 60.0% WR.
3. **Engine & Allocation Pipeline**:
   - In `LiveDemoBotEngine` (`bot_engine.py:29-687`), strategies are dynamically instantiated from `PreTradingPlan.assignments` via `get_strategy_instance(a.strategy_id, **a.parameters)`.
   - `generate_pre_trading_plan` (`auto_assign_strategies.py:13-102`) delegates multi-asset profiling to `StrategyAutoMatcher.find_optimal_strategy_for_asset`, which scores strategies based on win rate, profit factor, trade volume, and priority bonuses.
4. **Test Suite Baseline**:
   - Full test suite has **662 passing tests** across 43 test modules in 23.7s (`.venv/bin/pytest`).
   - Specific fallback tests in `test_strategy_auto_matcher.py` and `test_m1_adversarial_challenge.py` currently assert fallback to `supertrend_adx_momentum` / `macd_divergence_break` and will require surgical updates when the primary fallback transitions to the Sniper Alpha Trio.

---

## 2. Architecture & Data Flow Breakdown

```
                            ┌────────────────────────────────────────┐
                            │    Asset List / Broker Candle Stream   │
                            └───────────────────┬────────────────────┘
                                                │
                                                ▼
                            ┌────────────────────────────────────────┐
                            │      Asset Filter / Toxic Blacklist    │
                            │  (asset_filter.py: filter_allowed_assets)
                            └───────────────────┬────────────────────┘
                                                │ Whitelisted & Clean Assets
                                                ▼
                            ┌────────────────────────────────────────┐
                            │          StrategyAutoMatcher           │
                            │ (auto_matcher.py: find_optimal_strat)  │
                            │                                        │
                            │  PRIORITY_STRATEGIES (+15 score):      │
                            │   1. support_resistance_bounce         │
                            │   2. rsi_stochastic_extreme            │
                            │   3. ema_pullback_trend                │
                            └───────────────────┬────────────────────┘
                                                │
                                                ▼
                            ┌────────────────────────────────────────┐
                            │             PreTradingPlan             │
                            │ (auto_assign_strategies.py: Plan Model)│
                            │  - Per-asset strategy assignment       │
                            │  - Strategy-calibrated exp duration    │
                            └───────────────────┬────────────────────┘
                                                │
                                                ▼
                            ┌────────────────────────────────────────┐
                            │          LiveDemoBotEngine             │
                            │   (bot_engine.py: Trading Loop)        │
                            │  - Concurrency Lock & Guardrails       │
                            │  - Currency Correlation Filter         │
                            │  - Post-Settlement Cooldown (3-5 min)  │
                            │  - Signal Evaluation (evaluate_candles)│
                            │  - Order Execution via PO Gateway      │
                            └────────────────────────────────────────┘
```

---

## 3. Component Deep Dives

### 3.1 Strategy Registry (`src/strat_trade/domain/strategies/registry.py`)

- **Role**: Central strategy metadata catalog and factory constructor.
- **Current State**:
  - `_STRATEGIES` dictionary contains 8 registered strategies:
    1. `hybrid_multifactors` (`HybridMultiFactorsStrategy`)
    2. `bollinger_atr_reversion` (`BollingerAtrReversionStrategy`)
    3. `ema_pullback_trend` (`EmaPullbackTrendStrategy`)
    4. `rsi_stochastic_extreme` (`RsiStochasticExtremeStrategy`)
    5. `macd_divergence_break` (`MacdDivergenceBreakStrategy`)
    6. `volatility_squeeze_breakout` (`VolatilitySqueezeBreakoutStrategy`)
    7. `supertrend_adx_momentum` (`SupertrendAdxMomentumStrategy`)
    8. `support_resistance_bounce` (`SupportResistanceBounceStrategy`)
  - Lines 168–175: Fallback resolution in `get_strategy_instance()`:
    ```python
    meta = _STRATEGIES.get(strategy_name.strip().lower())
    if not meta:
        meta = _STRATEGIES.get(
            "supertrend_adx_momentum",
            _STRATEGIES.get("macd_divergence_break", next(iter(_STRATEGIES.values()))),
        )
    ```
- **R1 Recommendation**:
  - Keep all 8 classes in `_STRATEGIES` so `list_available_strategies()` and existing tests/backtests referencing them remain functional.
  - Update the fallback in `get_strategy_instance()` to resolve to `support_resistance_bounce` (primary) and `rsi_stochastic_extreme` (secondary) instead of `supertrend_adx_momentum` / `macd_divergence_break`.

---

### 3.2 Strategy Auto-Matcher (`src/strat_trade/domain/optimizer/auto_matcher.py`)

- **Role**: Evaluates candidate strategies on historical asset candles, generates parameter variations, and selects the optimal assignment with quantum scoring.
- **Current Location of Deactivated Strategies**:
  1. `PRIORITY_STRATEGIES` (`auto_matcher.py:17-24`):
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
     `hybrid_multifactors` and `macd_divergence_break` currently receive `+15.0` quantum bonus score points during evaluation (`auto_matcher.py:456-458`).
  2. Heuristic Profile Mappings (`auto_matcher.py:229-364`):
     - Gold / Commodities (`GOLD`, `XAU`) -> assigns `hybrid_multifactors` (`auto_matcher.py:238-256`).
     - Stocks (`AAPL`, `TSLA`, `NVDA`, `#`) -> assigns `macd_divergence_break` (`auto_matcher.py:257-266`).
     - Default unclassified fallback -> assigns `supertrend_adx_momentum` (primary) and `macd_divergence_break` (secondary) (`auto_matcher.py:323-352`).
- **R1 Restructuring Recommendations**:
  1. Update `PRIORITY_STRATEGIES` to strictly contain the 3 Sniper Alpha Strategies:
     ```python
     PRIORITY_STRATEGIES: frozenset[str] = frozenset(
         {
             "support_resistance_bounce",
             "rsi_stochastic_extreme",
             "ema_pullback_trend",
         }
     )
     ```
  2. Update `_heuristic_profile_for_asset`:
     - Gold / Commodities -> assign `support_resistance_bounce` or `ema_pullback_trend` (e.g. `support_resistance_bounce` with `swing_window=20`, `min_wick_ratio=0.35`).
     - Stocks -> assign `ema_pullback_trend` (trend following) with `ema_fast=9`, `ema_mid=21`, `adx_threshold=25.0`.
     - Crypto -> assign `rsi_stochastic_extreme` or `support_resistance_bounce`.
     - Forex (JPY/GBP) -> assign `support_resistance_bounce`.
     - Forex (Standard) -> assign `support_resistance_bounce` or `rsi_stochastic_extreme`.
     - Default fallback -> assign `support_resistance_bounce` (primary) and `rsi_stochastic_extreme` (secondary).
  3. In `find_optimal_strategy_for_asset`:
     - Restrict live strategy evaluation pool to active Sniper strategies (`SUPPORTED_ACTIVE_STRATEGIES` or filter out `{"hybrid_multifactors", "macd_divergence_break"}`), ensuring live demo bot mode never automatically assigns legacy indicator-spam strategies.

---

### 3.3 The 3 Primary Alpha Strategies: Deep Investigation

#### Strategy 1: Support & Resistance Pin-Bar (`SupportResistanceBounceStrategy`)
- **File**: `src/strat_trade/domain/strategies/support_resistance_bounce.py`
- **ID**: `support_resistance_bounce`
- **Category**: Price Action / S&R
- **Core Indicators**:
  - $Resistance_t = \max_{i \in [t-\text{swing\_window}, t-1]} High_i$
  - $Support_t = \min_{i \in [t-\text{swing\_window}, t-1]} Low_i$
  - $RSI(14)$
- **Signal Triggers**:
  - **CALL (Support Rejection Pin-Bar)**:
    1. $Low \le Support \times 1.0005$ and $Close \ge Support$ (Level retest)
    2. Lower wick ratio: $\frac{\min(Open, Close) - Low}{High - Low} \ge \max(0.35, \text{min\_wick\_ratio})$
    3. Bullish candle body: $Close > Open$
    4. Close position: $\frac{Close - Low}{High - Low} \ge 0.50$ (Closing in top 50% of bar)
    5. Confidence: Base $0.75$; $+0.15$ if $RSI \le 40$ (oversold confluence) $\implies 0.90$.
  - **PUT (Resistance Rejection Pin-Bar)**:
    1. $High \ge Resistance \times 0.9995$ and $Close \le Resistance$
    2. Upper wick ratio: $\frac{High - \max(Open, Close)}{High - Low} \ge \max(0.35, \text{min\_wick\_ratio})$
    3. Bearish candle body: $Close < Open$
    4. Close position: $\frac{High - Close}{High - Low} \ge 0.50$ (Closing in bottom 50% of bar)
    5. Confidence: Base $0.75$; $+0.15$ if $RSI \ge 60$ (overbought confluence) $\implies 0.90$.
- **Optimal Expiration**: 3 bars / 180 seconds on M1 (`base_expiration_bars = 3`).

#### Strategy 2: RSI + Stoch Extreme Scalp (`RsiStochasticExtremeStrategy`)
- **File**: `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`
- **ID**: `rsi_stochastic_extreme`
- **Category**: Scalping Reversal
- **Core Indicators**:
  - $RSI(14)$ (Oversold $\le 25.0$, Overbought $\ge 75.0$)
  - $Stochastic(14, 3)$ (%K, %D; Oversold $\le 20.0$, Overbought $\ge 80.0$)
- **Signal Triggers**:
  - **CALL (Oversold Dual Exhaustion)**:
    1. $RSI \le 25.0$ AND $Stoch\_K \le 20.0$
    2. Confidence: Base $0.70$; $+0.20$ if fresh crossover ($Prev\_K \le Prev\_D$ and $Curr\_K > Curr\_D$) or $+0.10$ if $Curr\_K > Prev\_K$. Total $0.90$.
  - **PUT (Overbought Dual Exhaustion)**:
    1. $RSI \ge 75.0$ AND $Stoch\_K \ge 80.0$
    2. Confidence: Base $0.70$; $+0.20$ if fresh crossover ($Prev\_K \ge Prev\_D$ and $Curr\_K < Curr\_D$) or $+0.10$ if $Curr\_K < Prev\_K$. Total $0.90$.
- **Optimal Expiration**: 2–3 bars / 120s–180s on M1 (`base_expiration_bars = 2` or `3`).

#### Strategy 3: EMA Ribbon Trend Pullback (`EmaPullbackTrendStrategy`)
- **File**: `src/strat_trade/domain/strategies/ema_pullback_trend.py`
- **ID**: `ema_pullback_trend`
- **Category**: Trend Following
- **Core Indicators**:
  - $EMA(9), EMA(21), EMA(50)$
  - $ADX(14)$ (Gate $\ge 25.0$), $+DI, -DI$
  - $Stochastic(14, 3)$, $RSI(14)$
- **Signal Triggers**:
  - **Uptrend Regime**: $EMA_9 > EMA_{21}$, $(EMA_{21} > EMA_{50} \text{ or } Close > EMA_{50})$, $ADX \ge 25.0$, $+DI > -DI$.
  - **CALL (Bullish Pullback)**:
    1. Pullback touches EMA 9 or EMA 21: $(Low \le EMA_9 \times 1.0005 \text{ and } Close \ge EMA_9)$ or $(Low \le EMA_{21} \times 1.0005 \text{ and } Close \ge EMA_{21})$
    2. Stochastic momentum hook: $(Stoch\_K > Stoch\_D \text{ or } Stoch\_K > Prev\_K)$
    3. Overbought Guard: $RSI \le 65.0$ AND $Stoch\_K \le 75.0$ (Strictly avoids buying the top)
    4. Confidence: Base $0.70$; $+0.15$ for fresh crossover, $+0.10$ for bullish bar ($Close > Open$).
  - **Downtrend Regime**: $EMA_9 < EMA_{21}$, $(EMA_{21} < EMA_{50} \text{ or } Close < EMA_{50})$, $ADX \ge 25.0$, $-DI > +DI$.
  - **PUT (Bearish Pullback)**:
    1. Pullback touches EMA 9 or EMA 21: $(High \ge EMA_9 \times 0.9995 \text{ and } Close \le EMA_9)$ or $(High \ge EMA_{21} \times 0.9995 \text{ and } Close \le EMA_{21})$
    2. Stochastic momentum hook: $(Stoch\_K < Stoch\_D \text{ or } Stoch\_K < Prev\_K)$
    3. Oversold Guard: $RSI \ge 35.0$ AND $Stoch\_K \ge 25.0$ (Strictly avoids shorting the bottom)
    4. Confidence: Base $0.70$; $+0.15$ for fresh crossover, $+0.10$ for bearish bar ($Close < Open$).
- **Optimal Expiration**: 3 bars / 180 seconds on M1 (`base_expiration_bars = 3`).

---

### 3.4 Multi-Factor Confluence & Higher-Timeframe Alignment Architecture

To achieve the **Sniper Mode** goal of 10–25 ultra-high-conviction trades/day rather than hundreds of noisy micro-trades, three structural layers of filtration operate in concert:

| Layer | Implementation Component | Guardrail Enforced |
| :--- | :--- | :--- |
| **Layer 1: Structural Confluence** | Strategy `evaluate_bar()` | 3-factor concordance: Macro Regime (EMA/ADX) + Value Retest (S&R/Ribbon) + Micro Exhaustion (Dual Oscillator w/ Overbought-Oversold Guards). Minimum confidence $\ge 0.70$. |
| **Layer 2: Asset Integrity & Regime** | `asset_filter.py`, `is_toxic_asset` | Blocks 10+ discrete step-tick toxic OTC pairs (e.g. `USD/IDR OTC`, `USD/VND OTC`, `BNB OTC`, `EUR/CHF OTC`). Focuses capital on continuous continuous-flow pairs (`EUR/USD OTC`, `USD/CLP OTC`, `USD/BDT OTC`, `USD/EGP OTC`, `Gold OTC`). |
| **Layer 3: Execution Guardrails** | `bot_engine.py: LiveDemoBotEngine` | - **Per-Asset Post-Settlement Cooldown**: 3 bars (180s) prevents repeat whipsaw entries.<br>- **Global Portfolio Cooldown**: 30s delay between executions across all assets.<br>- **Currency Correlation Filter**: Blocks contradictory or double-risk trades across correlated pairs.<br>- **Live Broker Payout Filter**: Rejects assets with broker payout $< 80\%$. |

---

## 4. Comprehensive Inventory of Affected Files & Dependencies

### 4.1 Domain & Strategy Files
- `src/strat_trade/domain/strategies/registry.py`: Strategy registry, metadata, and instance factory.
- `src/strat_trade/domain/optimizer/auto_matcher.py`: Strategy candidate variation generator, quantum ranking, priority list, heuristic fallback router.
- `src/strat_trade/domain/trading/bot_engine.py`: Live demo bot execution engine, cooldown tracker, broker order dispatcher.
- `src/strat_trade/domain/trading/entities.py`: Data classes (`StrategyAssignment`, `PreTradingPlan`, `LiveTradeRecord`, `BotSessionSummary`).
- `src/strat_trade/domain/trading/asset_filter.py`: Toxic blacklist and high-winrate whitelist definitions.
- `src/strat_trade/domain/strategies/support_resistance_bounce.py`: SR Pin-Bar strategy implementation.
- `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`: RSI + Stoch Extreme Scalp implementation.
- `src/strat_trade/domain/strategies/ema_pullback_trend.py`: EMA Ribbon Pullback implementation.
- `src/strat_trade/domain/strategies/macd_divergence_break.py`: Legacy MACD Divergence strategy.
- `src/strat_trade/domain/strategies/hybrid_multifactors.py`: Legacy Hybrid Multi-Factor strategy.
- `src/strat_trade/domain/backtest/engine.py` & `portfolio_engine.py`: Vectorized backtest engines.
- `src/strat_trade/domain/backtest/verification_runner.py`: Rolling 15-trade validation runner.

### 4.2 Use Cases & API Routes
- `src/strat_trade/use_cases/auto_assign_strategies.py`: `generate_pre_trading_plan` use case.
- `src/strat_trade/use_cases/manage_live_bot.py`: Live bot lifecycle controller.
- `src/strat_trade/api/routes/bot.py`: REST endpoints (`/bot/auto-assign`, `/bot/start`, `/bot/stop`, `/bot/pause`, `/bot/resume`, `/bot/status`, `/bot/trades`).
- `src/strat_trade/api/schemas.py`: Pydantic request/response schemas.

### 4.3 Test Suite Footprint
The following test modules directly cover strategy selection, auto-matching, and execution:
1. `tests/test_strategy_auto_matcher.py`: Fallback hierarchy and auto-matcher scoring tests.
2. `tests/test_strategy_curation_and_asset_filter.py`: Whitelist prioritization, toxic asset blocking, S&R pin-bar wicks, and EMA pullback guards.
3. `tests/test_m1_adversarial_challenge.py`: Edge cases in fallback routing and ADX boundary behaviors.
4. `tests/test_m2_adversarial_stress.py` & `test_m2_toxic_blacklist_fuzz.py`: Toxic asset stress testing.
5. `tests/test_new_strategies.py`: Registry catalog and execution tests across all strategies.
6. `tests/test_hybrid_strategy.py`: Indicator calculations and concordance for hybrid strategy.
7. `tests/test_strategy_logic_enhancements.py`: Volatility squeeze and S/R logic tests.
8. `tests/test_rolling_15_trade_verification.py` & `test_phase3_rolling_15_trade_verification.py`: Rolling batch validation.

---

## 5. Architectural Recommendations for Implementation

1. **`PRIORITY_STRATEGIES` Update in `auto_matcher.py`**:
   - Replace `{"supertrend_adx_momentum", "hybrid_multifactors", "rsi_stochastic_extreme", "macd_divergence_break"}` with `{"support_resistance_bounce", "rsi_stochastic_extreme", "ema_pullback_trend"}`.
2. **Heuristic Profiling Refinement in `auto_matcher.py`**:
   - Re-route commodities (`Gold_otc`) to `support_resistance_bounce` or `ema_pullback_trend`.
   - Re-route stocks to `ema_pullback_trend`.
   - Default unclassified fallback: Primary `support_resistance_bounce`, Secondary `rsi_stochastic_extreme`, Tertiary `ema_pullback_trend`.
3. **Registry Fallback Alignment in `registry.py`**:
   - Set `get_strategy_instance` default fallback to `support_resistance_bounce` / `rsi_stochastic_extreme`.
4. **Test Adjustments**:
   - Synchronize test assertions in `tests/test_strategy_auto_matcher.py` and `tests/test_m1_adversarial_challenge.py` to match the updated primary fallback hierarchy (`support_resistance_bounce` -> `rsi_stochastic_extreme` -> `ema_pullback_trend`).
5. **Zero Breaking Changes**:
   - Do NOT delete the `MacdDivergenceBreakStrategy` or `HybridMultiFactorsStrategy` classes or their registration in `_STRATEGIES`. They remain accessible via explicit strategy request for historical backtesting and existing endpoint schemas.
