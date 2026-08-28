# Technical Analysis & Implementation Plan: BollingerAtrReversionStrategy Enhancement

**Author**: m1_explorer_2  
**Milestone**: Milestone 1: Strategy Logic Correction & Signal Hygiene (R1)  
**Target File**: `src/strat_trade/domain/strategies/bollinger_atr_reversion.py`  
**Related Files**:
- `src/strat_trade/domain/strategies/base.py`
- `src/strat_trade/domain/strategies/registry.py`
- `src/strat_trade/domain/optimizer/auto_matcher.py`
- `tests/test_new_strategies.py`
- `tests/test_bollinger_atr_reversion.py` (new test suite)

---

## 1. Executive Summary & Problem Statement

In Pocket Option OTC binary options trading, mean-reversion strategies targeting Bollinger Band extremes face significant failure modes during strong directional regimes ("runaway trends") and knife-catching scenarios where price cascades beyond bands without any rejection momentum.

The current implementation of `BollingerAtrReversionStrategy` in `src/strat_trade/domain/strategies/bollinger_atr_reversion.py` has two major design deficiencies:
1. **Total Absence of Trend Strength Filtering (ADX)**: The strategy does not compute ADX or directional indices. During runaway trending moves ($ADX \ge 25.0$), it continuously attempts counter-trend mean-reversion entries against strong multi-bar momentum.
2. **Defective Candle & Rejection Confirmation**:
   - For CALL signals, the logic accepts `close <= bb_l * 1.0002` without requiring that the bar actually closed *inside* the band (`close >= bb_l`) and without requiring a bullish candle (`close > open_`). It also permits zero lower-wick rejection.
   - For PUT signals, the logic accepts `close >= bb_h * 0.9998` without requiring that the bar closed *inside* the band (`close <= bb_h`) and without requiring a bearish candle (`close < open_`). It also permits zero upper-wick rejection.
   - Wick rejection was merely a soft confidence booster (`if lower_wick > body * 0.8: confidence += 0.15`) rather than a mandatory entry gate.

---

## 2. Mathematical & Algorithmic Formulation

### 2.1 ADX Indicator Calculation & Trend Suppression
- **Indicator**: Welles Wilder's Average Directional Index ($ADX$) calculated with lookback period $N = \text{adx\_period}$ (default $14$):
  $$\text{ADX} = \text{ADXIndicator}(\text{high}, \text{low}, \text{close}, \text{window}=14).\text{adx}()$$
- **Regime Gate**:
  - If $ADX \ge \text{adx\_trend\_threshold}$ (default $25.0$):
    $$\text{SignalResult}(\text{action}=\text{None}, \text{confidence}=0.0, \text{regime}="\text{trend\_suppressed\_adx}", \text{metadata}=\{\dots\})$$
  - If $ADX < \text{adx\_trend\_threshold}$: Market is in range/consolidation; evaluate boundary rejection.

### 2.2 Candlestick Wick Rejection & Close Inside Band Formulation
For each bar at index $i$:
$$\text{candle\_range} = \text{high} - \text{low}$$
With division-by-zero protection:
$$\text{If } \text{candle\_range} \le 0: \quad \text{lower\_wick\_ratio} = 0.0, \quad \text{upper\_wick\_ratio} = 0.0$$
$$\text{Else}: \quad \text{lower\_wick} = \min(\text{open}, \text{close}) - \text{low}, \quad \text{lower\_wick\_ratio} = \frac{\text{lower\_wick}}{\text{candle\_range}}$$
$$\phantom{\text{Else}:} \quad \text{upper\_wick} = \text{high} - \max(\text{open}, \text{close}), \quad \text{upper\_wick\_ratio} = \frac{\text{upper\_wick}}{\text{candle\_range}}$$

#### Bullish Reversal Gate (CALL)
All 5 conditions must be strictly satisfied simultaneously:
1. **Band Piercing / Touch**: $\text{low} \le \text{bb\_low}$ (the shadow reached or breached the lower band).
2. **Closed Inside Band**: $\text{close} \ge \text{bb\_low}$ (price rebounded and closed at or above the lower band).
3. **Bullish Candle Body**: $\text{close} > \text{open}$ (green bar confirming upward momentum rejection).
4. **Lower Wick Rejection**: $\text{lower\_wick\_ratio} \ge \text{min\_wick\_ratio}$ (default $\ge 0.25$, i.e. $\ge 25\%$ of full candle range).
5. **RSI Oversold**: $\text{rsi} \le \text{rsi\_oversold}$ (default $\le 30.0$).

#### Bearish Reversal Gate (PUT)
All 5 conditions must be strictly satisfied simultaneously:
1. **Band Piercing / Touch**: $\text{high} \ge \text{bb\_high}$ (the shadow reached or breached the upper band).
2. **Closed Inside Band**: $\text{close} \le \text{bb\_high}$ (price rejected and closed at or below the upper band).
3. **Bearish Candle Body**: $\text{close} < \text{open}$ (red bar confirming downward momentum rejection).
4. **Upper Wick Rejection**: $\text{upper\_wick\_ratio} \ge \text{min\_wick\_ratio}$ (default $\ge 0.25$, i.e. $\ge 25\%$ of full candle range).
5. **RSI Overbought**: $\text{rsi} \ge \text{rsi\_overbought}$ (default $\ge 70.0$).

### 2.3 Confidence Function
- Base confidence on valid signal: $0.70$
- Bonus for strong rejection wick ($\text{wick\_ratio} \ge 0.40$): $+0.15$
- Bonus for deep oscillator exhaustion ($\text{RSI} \le \text{rsi\_oversold} - 5.0$ or $\text{RSI} \ge \text{rsi\_overbought} + 5.0$): $+0.10$
- Confidence ceiling: $\min(\text{confidence}, 0.95)$

---

## 3. Detailed Code Blueprint

### 3.1 `__init__` Parameter Signature & State Assignment
```python
    def __init__(
        self,
        *,
        bb_length: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        atr_period: int = 14,
        max_atr_ratio: float = 2.2,
        adx_period: int = 14,
        adx_trend_threshold: float = 25.0,
        min_wick_ratio: float = 0.25,
        base_expiration_bars: int = 3,
        adaptive_expiration_enabled: bool = False,
    ) -> None:
        self.bb_length = int(bb_length)
        self.bb_std = float(bb_std)
        self.rsi_period = int(rsi_period)
        self.rsi_oversold = float(rsi_oversold)
        self.rsi_overbought = float(rsi_overbought)
        self.atr_period = int(atr_period)
        self.max_atr_ratio = float(max_atr_ratio)
        self.adx_period = int(adx_period)
        self.adx_trend_threshold = float(adx_trend_threshold)
        self.min_wick_ratio = float(min_wick_ratio)
        self.base_expiration_bars = int(base_expiration_bars)
        self.adaptive_expiration_enabled = bool(adaptive_expiration_enabled)
```

### 3.2 `prepare_dataframe` Indicator Computation
```python
    def prepare_dataframe(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        df = df_raw.copy()
        if len(df) < max(self.bb_length, self.rsi_period, self.atr_period, self.adx_period) + 10:
            return df

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(
            close=df["close"], window=self.bb_length, window_dev=self.bb_std
        )
        df["bb_high"] = bb.bollinger_hband()
        df["bb_mid"] = bb.bollinger_mavg()
        df["bb_low"] = bb.bollinger_lband()
        df["bb_pband"] = bb.bollinger_pband()

        # RSI
        df["rsi"] = ta.momentum.RSIIndicator(close=df["close"], window=self.rsi_period).rsi()

        # ATR & ATR moving average
        atr_ind = ta.volatility.AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"], window=self.atr_period
        )
        df["atr"] = atr_ind.average_true_range()
        df["atr_sma"] = df["atr"].rolling(window=30, min_periods=10).mean()

        # ADX (Average Directional Index)
        adx_ind = ta.trend.ADXIndicator(
            high=df["high"], low=df["low"], close=df["close"], window=self.adx_period
        )
        df["adx"] = adx_ind.adx()

        return df
```

### 3.3 `evaluate_bar` Signal & Guardrails Evaluation
```python
    def evaluate_bar(self, df: pd.DataFrame, idx: int) -> SignalResult:
        min_warmup = max(30, self.bb_length, self.rsi_period, self.atr_period, self.adx_period)
        if idx < min_warmup or idx >= len(df):
            return SignalResult(None, 0.0, self.base_expiration_bars, "warming_up")

        row = df.iloc[idx]

        close = float(row["close"])
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])

        bb_h = float(row.get("bb_high", 0.0))
        bb_l = float(row.get("bb_low", 0.0))
        bb_pband = float(row.get("bb_pband", 0.5))
        rsi = float(row.get("rsi", 50.0))
        atr = float(row.get("atr", 0.0))
        atr_sma = float(row.get("atr_sma", atr or 1.0))
        adx_val = row.get("adx", 0.0)
        adx = float(adx_val) if pd.notna(adx_val) else 0.0

        # 1. Volatility spike suppression
        vol_ratio = atr / atr_sma if atr_sma > 0 else 1.0
        if vol_ratio > self.max_atr_ratio:
            return SignalResult(
                None,
                0.0,
                self.base_expiration_bars,
                "volatility_spike_suppressed",
                {"vol_ratio": round(vol_ratio, 2)},
            )

        # 2. ADX trend suppression (suppress mean-reversion during strong directional trend)
        if adx >= self.adx_trend_threshold:
            return SignalResult(
                None,
                0.0,
                self.base_expiration_bars,
                "trend_suppressed_adx",
                {
                    "adx": round(adx, 2),
                    "rsi": round(rsi, 2),
                    "vol_ratio": round(vol_ratio, 2),
                },
            )

        candle_range = high - low
        action = None
        confidence = 0.0
        wick_ratio = 0.0

        # Wick calculations with zero-range protection
        lower_wick = (min(open_, close) - low) if candle_range > 0 else 0.0
        lower_wick_ratio = (lower_wick / candle_range) if candle_range > 0 else 0.0

        upper_wick = (high - max(open_, close)) if candle_range > 0 else 0.0
        upper_wick_ratio = (upper_wick / candle_range) if candle_range > 0 else 0.0

        # Bullish Reversal (CALL):
        # 1. Pierced or touched lower band: low <= bb_l
        # 2. Closed inside/above lower band: close >= bb_l
        # 3. Bullish candle: close > open_
        # 4. Lower wick rejection: lower_wick / (high - low) >= min_wick_ratio
        # 5. RSI oversold: rsi <= rsi_oversold
        if (
            low <= bb_l
            and close >= bb_l
            and close > open_
            and lower_wick_ratio >= self.min_wick_ratio
            and rsi <= self.rsi_oversold
        ):
            action = TradeAction.CALL
            wick_ratio = lower_wick_ratio
            confidence = 0.70
            if lower_wick_ratio >= 0.40:
                confidence += 0.15
            if rsi <= (self.rsi_oversold - 5.0):
                confidence += 0.10

        # Bearish Reversal (PUT):
        # 1. Pierced or touched upper band: high >= bb_h
        # 2. Closed inside/below upper band: close <= bb_h
        # 3. Bearish candle: close < open_
        # 4. Upper wick rejection: upper_wick / (high - low) >= min_wick_ratio
        # 5. RSI overbought: rsi >= rsi_overbought
        elif (
            high >= bb_h
            and close <= bb_h
            and close < open_
            and upper_wick_ratio >= self.min_wick_ratio
            and rsi >= self.rsi_overbought
        ):
            action = TradeAction.PUT
            wick_ratio = upper_wick_ratio
            confidence = 0.70
            if upper_wick_ratio >= 0.40:
                confidence += 0.15
            if rsi >= (self.rsi_overbought + 5.0):
                confidence += 0.10

        confidence = min(confidence, 0.95)
        exp_bars = self.base_expiration_bars
        if self.adaptive_expiration_enabled and action is not None:
            if vol_ratio < 0.8:
                exp_bars += 1
            elif vol_ratio > 1.3:
                exp_bars = max(1, exp_bars - 1)

        return SignalResult(
            action=action,
            confidence=confidence,
            expiration_bars=exp_bars,
            regime="mean_reversion",
            metadata={
                "rsi": round(rsi, 2),
                "adx": round(adx, 2),
                "bb_pband": round(bb_pband, 4),
                "vol_ratio": round(vol_ratio, 2),
                "wick_ratio": round(wick_ratio, 3),
            },
        )
```

### 3.4 `get_parameter_definitions` Metadata Updates
```python
    @classmethod
    def get_parameter_definitions(cls) -> list[ParameterDef]:
        return [
            ParameterDef(
                "bb_length",
                "Bollinger Length",
                "int",
                20,
                10,
                30,
                5,
                description="BB lookback period",
            ),
            ParameterDef(
                "bb_std",
                "Bollinger StdDev",
                "float",
                2.0,
                1.5,
                2.5,
                0.5,
                description="BB standard deviations",
            ),
            ParameterDef(
                "rsi_period", "RSI Period", "int", 14, 7, 21, 1, description="RSI lookback period"
            ),
            ParameterDef(
                "rsi_oversold",
                "RSI Oversold",
                "float",
                30.0,
                20.0,
                35.0,
                5.0,
                description="RSI oversold boundary",
            ),
            ParameterDef(
                "rsi_overbought",
                "RSI Overbought",
                "float",
                70.0,
                65.0,
                80.0,
                5.0,
                description="RSI overbought boundary",
            ),
            ParameterDef(
                "adx_period",
                "ADX Period",
                "int",
                14,
                7,
                21,
                1,
                description="ADX lookback period",
            ),
            ParameterDef(
                "adx_trend_threshold",
                "ADX Trend Threshold",
                "float",
                25.0,
                20.0,
                35.0,
                5.0,
                description="Maximum ADX threshold for range regime",
            ),
            ParameterDef(
                "min_wick_ratio",
                "Min Wick Ratio",
                "float",
                0.25,
                0.10,
                0.50,
                0.05,
                description="Minimum rejection wick ratio",
            ),
            ParameterDef(
                "base_expiration_bars",
                "Expiration Bars",
                "int",
                3,
                1,
                5,
                1,
                description="Trade duration in bars",
            ),
        ]
```

---

## 4. Unified Diff Patch

```patch
--- a/src/strat_trade/domain/strategies/bollinger_atr_reversion.py
+++ b/src/strat_trade/domain/strategies/bollinger_atr_reversion.py
@@ -25,6 +25,9 @@ class BollingerAtrReversionStrategy(BaseStrategy):
         rsi_overbought: float = 70.0,
         atr_period: int = 14,
         max_atr_ratio: float = 2.2,
+        adx_period: int = 14,
+        adx_trend_threshold: float = 25.0,
+        min_wick_ratio: float = 0.25,
         base_expiration_bars: int = 3,
         adaptive_expiration_enabled: bool = False,
     ) -> None:
@@ -35,12 +38,15 @@ class BollingerAtrReversionStrategy(BaseStrategy):
         self.rsi_overbought = float(rsi_overbought)
         self.atr_period = int(atr_period)
         self.max_atr_ratio = float(max_atr_ratio)
+        self.adx_period = int(adx_period)
+        self.adx_trend_threshold = float(adx_trend_threshold)
+        self.min_wick_ratio = float(min_wick_ratio)
         self.base_expiration_bars = int(base_expiration_bars)
         self.adaptive_expiration_enabled = bool(adaptive_expiration_enabled)
 
     def prepare_dataframe(self, df_raw: pd.DataFrame) -> pd.DataFrame:
         df = df_raw.copy()
-        if len(df) < max(self.bb_length, self.rsi_period, self.atr_period) + 10:
+        if len(df) < max(self.bb_length, self.rsi_period, self.atr_period, self.adx_period) + 10:
             return df
 
         # Bollinger Bands
@@ -60,14 +66,19 @@ class BollingerAtrReversionStrategy(BaseStrategy):
         df["atr"] = atr_ind.average_true_range()
         df["atr_sma"] = df["atr"].rolling(window=30, min_periods=10).mean()
 
+        # ADX (Average Directional Index)
+        adx_ind = ta.trend.ADXIndicator(
+            high=df["high"], low=df["low"], close=df["close"], window=self.adx_period
+        )
+        df["adx"] = adx_ind.adx()
+
         return df
 
     def evaluate_bar(self, df: pd.DataFrame, idx: int) -> SignalResult:
-        if idx < 30 or idx >= len(df):
+        min_warmup = max(30, self.bb_length, self.rsi_period, self.atr_period, self.adx_period)
+        if idx < min_warmup or idx >= len(df):
             return SignalResult(None, 0.0, self.base_expiration_bars, "warming_up")
 
         row = df.iloc[idx]
-        prev = df.iloc[idx - 1]
 
         close = float(row["close"])
         open_ = float(row["open"])
@@ -79,48 +90,69 @@ class BollingerAtrReversionStrategy(BaseStrategy):
         rsi = float(row.get("rsi", 50.0))
         atr = float(row.get("atr", 0.0))
         atr_sma = float(row.get("atr_sma", atr or 1.0))
+        adx_val = row.get("adx", 0.0)
+        adx = float(adx_val) if pd.notna(adx_val) else 0.0
 
         vol_ratio = atr / atr_sma if atr_sma > 0 else 1.0
         if vol_ratio > self.max_atr_ratio:
             return SignalResult(
                 None,
                 0.0,
                 self.base_expiration_bars,
                 "volatility_spike_suppressed",
                 {"vol_ratio": round(vol_ratio, 2)},
             )
 
-        body = abs(close - open_)
+        # ADX trend suppression
+        if adx >= self.adx_trend_threshold:
+            return SignalResult(
+                None,
+                0.0,
+                self.base_expiration_bars,
+                "trend_suppressed_adx",
+                {
+                    "adx": round(adx, 2),
+                    "rsi": round(rsi, 2),
+                    "vol_ratio": round(vol_ratio, 2),
+                },
+            )
+
+        candle_range = high - low
         action = None
         confidence = 0.0
+        wick_ratio = 0.0
+
+        lower_wick = (min(open_, close) - low) if candle_range > 0 else 0.0
+        lower_wick_ratio = (lower_wick / candle_range) if candle_range > 0 else 0.0
+
+        upper_wick = (high - max(open_, close)) if candle_range > 0 else 0.0
+        upper_wick_ratio = (upper_wick / candle_range) if candle_range > 0 else 0.0
 
-        # Bullish Reversal: Price pierced lower band + RSI oversold + lower wick rejection
-        lower_wick = min(open_, close) - low
-        if (low <= bb_l or close <= bb_l * 1.0002 or bb_pband <= 0.05) and (
-            rsi <= self.rsi_oversold or prev["rsi"] <= self.rsi_oversold
+        # Bullish Reversal (CALL)
+        if (
+            low <= bb_l
+            and close >= bb_l
+            and close > open_
+            and lower_wick_ratio >= self.min_wick_ratio
+            and rsi <= self.rsi_oversold
         ):
             action = TradeAction.CALL
-            confidence = 0.65
-            if lower_wick > body * 0.8:
+            wick_ratio = lower_wick_ratio
+            confidence = 0.70
+            if lower_wick_ratio >= 0.40:
                 confidence += 0.15
-            if close > open_:  # bullish candle
+            if rsi <= (self.rsi_oversold - 5.0):
                 confidence += 0.10
 
-        # Bearish Reversal: Price pierced upper band + RSI overbought + upper wick rejection
-        upper_wick = high - max(open_, close)
-        if (high >= bb_h or close >= bb_h * 0.9998 or bb_pband >= 0.95) and (
-            rsi >= self.rsi_overbought or prev["rsi"] >= self.rsi_overbought
+        # Bearish Reversal (PUT)
+        elif (
+            high >= bb_h
+            and close <= bb_h
+            and close < open_
+            and upper_wick_ratio >= self.min_wick_ratio
+            and rsi >= self.rsi_overbought
         ):
             action = TradeAction.PUT
-            confidence = 0.65
-            if upper_wick > body * 0.8:
+            wick_ratio = upper_wick_ratio
+            confidence = 0.70
+            if upper_wick_ratio >= 0.40:
                 confidence += 0.15
-            if close < open_:  # bearish candle
+            if rsi >= (self.rsi_overbought + 5.0):
                 confidence += 0.10
 
         confidence = min(confidence, 0.95)
@@ -136,7 +168,9 @@ class BollingerAtrReversionStrategy(BaseStrategy):
             expiration_bars=exp_bars,
             regime="mean_reversion",
             metadata={
                 "rsi": round(rsi, 2),
+                "adx": round(adx, 2),
                 "bb_pband": round(bb_pband, 4),
                 "vol_ratio": round(vol_ratio, 2),
+                "wick_ratio": round(wick_ratio, 3),
             },
         )
 
@@ -188,6 +222,30 @@ class BollingerAtrReversionStrategy(BaseStrategy):
                 5.0,
                 description="RSI overbought boundary",
             ),
+            ParameterDef(
+                "adx_period",
+                "ADX Period",
+                "int",
+                14,
+                7,
+                21,
+                1,
+                description="ADX lookback period",
+            ),
+            ParameterDef(
+                "adx_trend_threshold",
+                "ADX Trend Threshold",
+                "float",
+                25.0,
+                20.0,
+                35.0,
+                5.0,
+                description="Maximum ADX threshold for range regime",
+            ),
+            ParameterDef(
+                "min_wick_ratio",
+                "Min Wick Ratio",
+                "float",
+                0.25,
+                0.10,
+                0.50,
+                0.05,
+                description="Minimum rejection wick ratio",
+            ),
             ParameterDef(
                 "base_expiration_bars",
                 "Expiration Bars",
```

---

## 5. Verification & Test Plan

A dedicated test suite `tests/test_bollinger_atr_reversion.py` will verify each criterion:

1. **Indicator Generation**:
   - Verify `df['adx']` column is present after `prepare_dataframe(df)`.
   - Verify minimum warmup logic handles dataframes shorter than lookback.
2. **ADX Trend Suppression**:
   - Construct candle data where Bollinger Band, wick, and RSI conditions are completely met for CALL, but $ADX = 30.0 \ge 25.0$.
   - Assert `sig.action is None` and `sig.regime == "trend_suppressed_adx"`.
3. **CALL Signal Confirmation**:
   - Positive test: $\text{low} = 1.0800 \le \text{bb\_l} (1.0810)$, $\text{close} = 1.0830 \ge \text{bb\_l}$, $\text{open} = 1.0815 < \text{close}$, $\text{high} = 1.0835$, $\text{lower\_wick} = 0.0015$, $\text{range} = 0.0035 \implies \text{ratio} = 0.428 \ge 0.25$, $RSI = 24.0 \le 30.0$, $ADX = 18.0 < 25.0$.
   - Assert `sig.action == TradeAction.CALL` and `sig.regime == "mean_reversion"`.
   - Negative test (closed below band): $\text{close} = 1.0805 < \text{bb\_l} (1.0810) \implies \text{action is None}$.
   - Negative test (bearish candle): $\text{close} = 1.0812 < \text{open} (1.0820) \implies \text{action is None}$.
   - Negative test (short wick): $\text{lower\_wick\_ratio} = 0.10 < 0.25 \implies \text{action is None}$.
4. **PUT Signal Confirmation**:
   - Positive test: $\text{high} = 1.0900 \ge \text{bb\_h} (1.0890)$, $\text{close} = 1.0870 \le \text{bb\_h}$, $\text{open} = 1.0885 > \text{close}$, $\text{low} = 1.0865$, $\text{upper\_wick} = 0.0015$, $\text{range} = 0.0035 \implies \text{ratio} = 0.428 \ge 0.25$, $RSI = 76.0 \ge 70.0$, $ADX = 17.5 < 25.0$.
   - Assert `sig.action == TradeAction.PUT` and `sig.regime == "mean_reversion"`.
   - Negative test (closed above band): $\text{close} = 1.0895 > \text{bb\_h} (1.0890) \implies \text{action is None}$.
   - Negative test (bullish candle): $\text{close} = 1.0888 > \text{open} (1.0880) \implies \text{action is None}$.
   - Negative test (short upper wick): $\text{upper\_wick\_ratio} = 0.08 < 0.25 \implies \text{action is None}$.
5. **Division-by-Zero Safety**:
   - Flat candle ($\text{high} = \text{low} = \text{open} = \text{close} = 1.0850$).
   - Assert no exception is raised and `sig.action is None`.
6. **Parameter Definitions**:
   - Verify `BollingerAtrReversionStrategy.get_parameter_definitions()` contains all 9 parameters.
   - Verify instantiation via `get_strategy_instance("bollinger_atr_reversion", {"adx_trend_threshold": 22.0})`.
