# Handoff Report — Strategy Implementations & Signal Logic Survey

**Agent**: `survey_explorer_1`  
**Working Directory**: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_1`  
**Date**: 2026-08-20  
**Handoff Type**: Hard (Task Complete)  

---

## 1. Observation

1. **`VolatilitySqueezeBreakoutStrategy` False Breakout Bug**:
   - Location: `src/strat_trade/domain/strategies/volatility_squeeze_breakout.py:83-97`
   - Verbatim Code:
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
   - Direct finding: On every normal non-squeeze bar where `abs(mom) > 0` and `mom > prev_mom` or `mom < prev_mom`, `squeeze_fired` evaluates to `True`.

2. **`BollingerAtrReversionStrategy` Candle Confirmation & ADX Deficiencies**:
   - Location: `src/strat_trade/domain/strategies/bollinger_atr_reversion.py:40-64, 99-122`
   - Verbatim Code:
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
     ```
   - Direct finding 1: The condition permits entries when `close <= bb_l * 1.0002` (falling knife closing below the lower band) even with 0 wick rejection (`lower_wick > body * 0.8` is only an optional confidence booster).
   - Direct finding 2: `prepare_dataframe` does not compute ADX, and `evaluate_bar` has no check for `adx >= 25.0`, allowing blind counter-trend entries in runaway OTC trends.

3. **Current Test Suite Baseline**:
   - Command: `./.venv/bin/pytest`
   - Result: 66 passed, 4 warnings in 2.53s.

4. **Strategy Registry Catalog**:
   - Location: `src/strat_trade/domain/strategies/registry.py:32-129`
   - Contains 8 registered strategies: `hybrid_multifactors`, `bollinger_atr_reversion`, `ema_pullback_trend`, `rsi_stochastic_extreme`, `macd_divergence_break`, `volatility_squeeze_breakout`, `supertrend_adx_momentum`, `support_resistance_bounce`.

---

## 2. Logic Chain

1. **Premise from Observation 1**: In `VolatilitySqueezeBreakoutStrategy`, the expression `(not sq_now and abs(mom) > 0)` is unconditionally true during all normal market conditions where Bollinger Bands are wider than Keltner Channels.
2. **Inference 1**: Whenever market momentum shifts (`mom > prev_mom` or `mom < prev_mom`), `squeeze_fired` triggers regardless of whether any volatility squeeze ever existed.
3. **Conclusion 1**: Removing `or (not sq_now and abs(mom) > 0)` and restricting `squeeze_fired` strictly to `sq_prev and not sq_now` eliminates bar-by-bar spamming and restores the authentic TTM Squeeze breakout logic.
4. **Premise from Observation 2**: In `BollingerAtrReversionStrategy`, allowing `close <= bb_l * 1.0002` without requiring a wick bounce or close inside the band causes entries during heavy downward candles.
5. **Inference 2**: In binary options, betting on mean reversion requires evidence of buyer price rejection (wick rejection + closing inside or bouncing back above the band).
6. **Premise from Observation 2**: In strong trends, RSI stays oversold/overbought for extended periods, and price hugs the outer Bollinger Band.
7. **Inference 3**: Integrating `ta.trend.ADXIndicator` and suppressing signals when `adx >= 25.0` (or `adx_trend_threshold`) protects capital against runaway OTC momentum regimes.
8. **Conclusion 2**: Upgrading `BollingerAtrReversionStrategy` with mandatory candle confirmation (`close >= bb_l` / `close <= bb_h` and `lower_wick / range_ >= min_wick_ratio`) plus ADX trend suppression directly satisfies Requirement R1.

---

## 3. Caveats

- **Adaptive Expiration**: While `adaptive_expiration_enabled` parameter exists on `BaseStrategy` subclasses, its activation is optional (`False` by default in most backtest configs).
- **Optimization Parameter Ranges**: When adding `adx_trend_threshold` or `min_wick_ratio` to `BollingerAtrReversionStrategy`, their definitions in `get_parameter_definitions()` must include suitable min/max/step values for the grid search optimizer.
- **Correlated Pairs & Bot Guardrails**: Survey was focused on Strategy Implementations and Signal Logic (R1); bot engine execution guardrails (R2) and the automated 15-trade optimization runner (R3) interact with these strategies and require complementary implementation.

---

## 4. Conclusion

1. The exact bug causing continuous non-squeeze bar firing in `VolatilitySqueezeBreakoutStrategy` is the fallback clause `(not sq_now and abs(mom) > 0)` at line 84 of `volatility_squeeze_breakout.py`. Replacing this with `sq_prev and not sq_now` completely cures the bug.
2. The deficiencies in `BollingerAtrReversionStrategy` are:
   - Missing candle confirmation (wick rejection + close inside band) at lines 101–122.
   - Complete lack of ADX indicator calculation and trend suppression (ADX $\ge$ 25).
3. The full survey report is documented in `/Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_1/survey_report.md`.

---

## 5. Verification Method

1. **Inspect Strategy Files**:
   - View `src/strat_trade/domain/strategies/volatility_squeeze_breakout.py:84` to verify the identified squeeze firing bug.
   - View `src/strat_trade/domain/strategies/bollinger_atr_reversion.py:50-64, 100-122` to verify the lack of ADX and missing candle confirmation.
2. **Execute Existing Test Suite**:
   - Run: `./.venv/bin/pytest`
   - Expectation: 66 tests pass.
3. **Inspect Generated Survey Report**:
   - View: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_1/survey_report.md`
