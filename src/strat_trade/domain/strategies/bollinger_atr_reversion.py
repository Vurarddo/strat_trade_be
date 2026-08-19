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
        self.base_expiration_bars = int(base_expiration_bars)
        self.adaptive_expiration_enabled = bool(adaptive_expiration_enabled)

    def prepare_dataframe(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        df = df_raw.copy()
        if len(df) < max(self.bb_length, self.rsi_period, self.atr_period) + 10:
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

        return df

    def evaluate_bar(self, df: pd.DataFrame, idx: int) -> SignalResult:
        if idx < 30 or idx >= len(df):
            return SignalResult(None, 0.0, self.base_expiration_bars, "warming_up")

        row = df.iloc[idx]
        prev = df.iloc[idx - 1]

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

        vol_ratio = atr / atr_sma if atr_sma > 0 else 1.0
        if vol_ratio > self.max_atr_ratio:
            return SignalResult(
                None,
                0.0,
                self.base_expiration_bars,
                "volatility_spike_suppressed",
                {"vol_ratio": round(vol_ratio, 2)},
            )

        body = abs(close - open_)
        action = None
        confidence = 0.0

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
                "bb_pband": round(bb_pband, 4),
                "vol_ratio": round(vol_ratio, 2),
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
