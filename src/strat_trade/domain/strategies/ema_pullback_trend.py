from __future__ import annotations

import pandas as pd
import ta

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.strategies.base import BaseStrategy, ParameterDef, SignalResult


class EmaPullbackTrendStrategy(BaseStrategy):
    """Multi-EMA (9, 21, 50) Trend-Following Pullback Strategy with ADX & Stochastic.

    Identifies strong trend regimes (ADX >= 25) and trades continuation impulses
    when price pulls back into the dynamic EMA 9/21 value zone.
    """

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
        min_wick_ratio: float = 0.25,
        base_expiration_bars: int = 3,
        adaptive_expiration_enabled: bool = False,
    ) -> None:
        self.ema_fast = int(ema_fast)
        self.ema_mid = int(ema_mid)
        self.ema_slow = int(ema_slow)
        self.adx_period = int(adx_period)
        self.adx_threshold = float(adx_threshold)
        self.stoch_k = int(stoch_k)
        self.stoch_d = int(stoch_d)
        self.rsi_period = int(rsi_period)
        self.rsi_overbought = float(rsi_overbought)
        self.rsi_oversold = float(rsi_oversold)
        self.stoch_overbought = float(stoch_overbought)
        self.stoch_oversold = float(stoch_oversold)
        self.min_wick_ratio = float(min_wick_ratio)
        self.base_expiration_bars = int(base_expiration_bars)
        self.adaptive_expiration_enabled = bool(adaptive_expiration_enabled)

    def prepare_dataframe(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        df = df_raw.copy()
        if len(df) < max(self.ema_slow, self.adx_period, self.stoch_k, self.rsi_period) + 10:
            return df

        df["ema_f"] = ta.trend.EMAIndicator(close=df["close"], window=self.ema_fast).ema_indicator()
        df["ema_m"] = ta.trend.EMAIndicator(close=df["close"], window=self.ema_mid).ema_indicator()
        df["ema_s"] = ta.trend.EMAIndicator(close=df["close"], window=self.ema_slow).ema_indicator()

        # ADX
        adx_ind = ta.trend.ADXIndicator(
            high=df["high"], low=df["low"], close=df["close"], window=self.adx_period
        )
        df["adx"] = adx_ind.adx()
        df["adx_pos"] = adx_ind.adx_pos()
        df["adx_neg"] = adx_ind.adx_neg()

        # Stochastic
        stoch = ta.momentum.StochasticOscillator(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            window=self.stoch_k,
            smooth_window=self.stoch_d,
        )
        df["stoch_k"] = stoch.stoch()
        df["stoch_d"] = stoch.stoch_signal()

        # RSI
        df["rsi"] = ta.momentum.RSIIndicator(close=df["close"], window=self.rsi_period).rsi()

        return df

    def evaluate_bar(self, df: pd.DataFrame, idx: int) -> SignalResult:
        if idx < 50 or idx >= len(df):
            return SignalResult(None, 0.0, self.base_expiration_bars, "warming_up")

        row = df.iloc[idx]
        prev = df.iloc[idx - 1]

        close = float(row["close"])
        open_ = float(row["open"])
        low = float(row["low"])
        high = float(row["high"])

        ema_f = float(row.get("ema_f", 0.0))
        ema_m = float(row.get("ema_m", 0.0))
        ema_s = float(row.get("ema_s", 0.0))

        adx = float(row.get("adx", 0.0))
        adx_pos = float(row.get("adx_pos", 0.0))
        adx_neg = float(row.get("adx_neg", 0.0))

        sk = float(row.get("stoch_k", 50.0))
        sd = float(row.get("stoch_d", 50.0))
        prev_sk = float(prev.get("stoch_k", 50.0))
        prev_sd = float(prev.get("stoch_d", 50.0))
        rsi = float(row.get("rsi", 50.0))

        action = None
        confidence = 0.0

        rng = high - low
        lower_wick = (min(open_, close) - low) if rng > 1e-9 else 0.0
        upper_wick = (high - max(open_, close)) if rng > 1e-9 else 0.0
        lower_wick_ratio = lower_wick / rng if rng > 1e-9 else 0.0
        upper_wick_ratio = upper_wick / rng if rng > 1e-9 else 0.0

        uptrend = (
            ema_f > ema_m
            and (ema_m > ema_s or close > ema_s)
            and adx >= self.adx_threshold
            and adx_pos > adx_neg
        )
        downtrend = (
            ema_f < ema_m
            and (ema_m < ema_s or close < ema_s)
            and adx >= self.adx_threshold
            and adx_neg > adx_pos
        )

        # Bullish Pullback: Price dips into Value Zone (EMA 9-21-50 pocket) + wick rejection
        # Strictly require RSI <= 65 and Stoch <= 75 to prevent buying overbought tops
        if uptrend:
            value_zone_tested = low <= ema_f * 1.0003 or low <= ema_m * 1.0003
            bounce_confirmed = close >= ema_m * 0.9995 and (
                close >= open_ or lower_wick_ratio >= self.min_wick_ratio
            )

            if value_zone_tested and bounce_confirmed:
                if (
                    (sk > sd or (sk > prev_sk and sk < self.stoch_overbought))
                    and rsi <= self.rsi_overbought
                    and sk <= self.stoch_overbought
                ):
                    action = TradeAction.CALL
                    confidence = 0.70
                    if prev_sk <= prev_sd and sk > sd:  # Fresh Stoch crossover
                        confidence += 0.15
                    if lower_wick_ratio >= self.min_wick_ratio:
                        confidence += 0.10

        # Bearish Pullback: Price rallies into Value Zone + upper wick rejection
        # Strictly require RSI >= 35 and Stoch >= 25 to prevent selling oversold bottoms
        elif downtrend:
            value_zone_tested = high >= ema_f * 0.9997 or high >= ema_m * 0.9997
            bounce_confirmed = close <= ema_m * 1.0005 and (
                close <= open_ or upper_wick_ratio >= self.min_wick_ratio
            )

            if value_zone_tested and bounce_confirmed:
                if (
                    (sk < sd or (sk < prev_sk and sk > self.stoch_oversold))
                    and rsi >= self.rsi_oversold
                    and sk >= self.stoch_oversold
                ):
                    action = TradeAction.PUT
                    confidence = 0.70
                    if prev_sk >= prev_sd and sk < sd:  # Fresh Stoch crossover
                        confidence += 0.15
                    if upper_wick_ratio >= self.min_wick_ratio:
                        confidence += 0.10

        confidence = min(confidence, 0.95)
        return SignalResult(
            action=action,
            confidence=confidence,
            expiration_bars=self.base_expiration_bars,
            regime="trending" if (uptrend or downtrend) else "ranging",
            metadata={
                "adx": round(adx, 2),
                "stoch_k": round(sk, 2),
                "stoch_d": round(sd, 2),
                "rsi": round(rsi, 2),
            },
        )

    @classmethod
    def get_parameter_definitions(cls) -> list[ParameterDef]:
        return [
            ParameterDef(
                "ema_fast", "EMA Fast", "int", 9, 5, 15, 2, description="Fast EMA lookback"
            ),
            ParameterDef(
                "ema_mid", "EMA Mid", "int", 21, 15, 30, 3, description="Medium EMA lookback"
            ),
            ParameterDef(
                "adx_threshold",
                "ADX Trend Gate",
                "float",
                25.0,
                20.0,
                35.0,
                5.0,
                description="Minimum ADX for trend filter",
            ),
            ParameterDef(
                "rsi_overbought",
                "RSI Overbought Filter",
                "float",
                65.0,
                50.0,
                80.0,
                5.0,
                description="Max RSI for CALL entry",
            ),
            ParameterDef(
                "rsi_oversold",
                "RSI Oversold Filter",
                "float",
                35.0,
                20.0,
                50.0,
                5.0,
                description="Min RSI for PUT entry",
            ),
            ParameterDef(
                "base_expiration_bars",
                "Expiration Bars",
                "int",
                3,
                1,
                5,
                1,
                description="Expiration bars",
            ),
        ]
