from __future__ import annotations

import pandas as pd
import ta

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.strategies.base import BaseStrategy, ParameterDef, SignalResult


class BollingerAtrReversionStrategy(BaseStrategy):
    """Bollinger Bands (20, 2.0) + ATR Volatility Filter Mean-Reversion Strategy.

    Exploits price boundary rejections in ranging/consolidation markets with
    candlestick wick confirmation and abnormal volatility spike protection.
    """

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

        # Volatility spike suppression
        vol_ratio = atr / atr_sma if atr_sma > 0 else 1.0
        if vol_ratio > self.max_atr_ratio:
            return SignalResult(
                None,
                0.0,
                self.base_expiration_bars,
                "volatility_spike_suppressed",
                {"vol_ratio": round(vol_ratio, 2)},
            )

        # ADX trend suppression (suppress mean-reversion during strong directional trend)
        if adx >= self.adx_trend_threshold:
            return SignalResult(
                action=None,
                confidence=0.0,
                expiration_bars=self.base_expiration_bars,
                regime="trend_suppressed_adx",
                metadata={
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
