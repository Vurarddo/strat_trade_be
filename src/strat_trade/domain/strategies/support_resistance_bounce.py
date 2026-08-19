from __future__ import annotations

import pandas as pd
import ta

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.strategies.base import BaseStrategy, ParameterDef, SignalResult


class SupportResistanceBounceStrategy(BaseStrategy):
    """Dynamic Support & Resistance Bounce Strategy with Rejection Pin-Bars.

    Identifies rolling horizontal support/resistance levels and trades reversals
    when price tests levels with pin-bar/hammer rejection wicks.
    """

    def __init__(
        self,
        *,
        swing_window: int = 20,
        rsi_period: int = 14,
        min_wick_ratio: float = 0.35,
        base_expiration_bars: int = 3,
        adaptive_expiration_enabled: bool = False,
    ) -> None:
        self.swing_window = int(swing_window)
        self.rsi_period = int(rsi_period)
        self.min_wick_ratio = float(min_wick_ratio)
        self.base_expiration_bars = int(base_expiration_bars)
        self.adaptive_expiration_enabled = bool(adaptive_expiration_enabled)

    def prepare_dataframe(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        df = df_raw.copy()
        if len(df) < max(self.swing_window, self.rsi_period) + 10:
            return df

        # Rolling Resistance (highest high) and Support (lowest low) over previous window
        df["sr_resistance"] = (
            df["high"].shift(1).rolling(window=self.swing_window, min_periods=5).max()
        )
        df["sr_support"] = df["low"].shift(1).rolling(window=self.swing_window, min_periods=5).min()

        # RSI for divergence/exhaustion confirmation
        df["rsi"] = ta.momentum.RSIIndicator(close=df["close"], window=self.rsi_period).rsi()

        return df

    def evaluate_bar(self, df: pd.DataFrame, idx: int) -> SignalResult:
        if idx < self.swing_window + 5 or idx >= len(df):
            return SignalResult(None, 0.0, self.base_expiration_bars, "warming_up")

        row = df.iloc[idx]

        close = float(row["close"])
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        supp = float(row.get("sr_support", low))
        res = float(row.get("sr_resistance", high))
        rsi = float(row.get("rsi", 50.0))

        range_ = high - low
        if range_ <= 0:
            return SignalResult(None, 0.0, self.base_expiration_bars, "flat_bar")

        lower_wick = min(open_, close) - low
        upper_wick = high - max(open_, close)

        action = None
        confidence = 0.0

        # Bounce off Support: Low tests support level + long lower rejection wick
        if low <= supp * 1.0005 and close >= supp and (lower_wick / range_) >= self.min_wick_ratio:
            action = TradeAction.CALL
            confidence = 0.70
            if rsi <= 40:  # Oversold confirmation
                confidence += 0.15
            if close > open_:  # Bullish close
                confidence += 0.10

        # Rejection off Resistance: High tests resistance level + long upper rejection wick
        elif high >= res * 0.9995 and close <= res and (upper_wick / range_) >= self.min_wick_ratio:
            action = TradeAction.PUT
            confidence = 0.70
            if rsi >= 60:  # Overbought confirmation
                confidence += 0.15
            if close < open_:  # Bearish close
                confidence += 0.10

        confidence = min(confidence, 0.95)
        return SignalResult(
            action=action,
            confidence=confidence,
            expiration_bars=self.base_expiration_bars,
            regime="sr_bounce",
            metadata={"support": round(supp, 5), "resistance": round(res, 5), "rsi": round(rsi, 2)},
        )

    @classmethod
    def get_parameter_definitions(cls) -> list[ParameterDef]:
        return [
            ParameterDef(
                "swing_window",
                "S/R Lookback",
                "int",
                20,
                10,
                40,
                5,
                description="Swing high/low lookback",
            ),
            ParameterDef(
                "min_wick_ratio",
                "Min Rejection Wick",
                "float",
                0.35,
                0.20,
                0.50,
                0.05,
                description="Minimum wick-to-range ratio",
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
