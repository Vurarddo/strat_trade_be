from __future__ import annotations

import pandas as pd
import ta

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.strategies.base import BaseStrategy, ParameterDef, SignalResult


class MacdDivergenceBreakStrategy(BaseStrategy):
    """MACD Regular Divergence and Momentum Cross Strategy (12, 26, 9).

    Detects divergence between price swing extremes and MACD histogram momentum,
    providing high-probability reversal signals.
    """

    def __init__(
        self,
        *,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_sign: int = 9,
        lookback_swings: int = 15,
        base_expiration_bars: int = 3,
        adaptive_expiration_enabled: bool = False,
    ) -> None:
        self.macd_fast = int(macd_fast)
        self.macd_slow = int(macd_slow)
        self.macd_sign = int(macd_sign)
        self.lookback_swings = int(lookback_swings)
        self.base_expiration_bars = int(base_expiration_bars)
        self.adaptive_expiration_enabled = bool(adaptive_expiration_enabled)

    def prepare_dataframe(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        df = df_raw.copy()
        if len(df) < max(self.macd_slow, self.lookback_swings) + 10:
            return df

        macd = ta.trend.MACD(
            close=df["close"],
            window_fast=self.macd_fast,
            window_slow=self.macd_slow,
            window_sign=self.macd_sign,
        )
        df["macd_line"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_diff"] = macd.macd_diff()  # Histogram

        return df

    def evaluate_bar(self, df: pd.DataFrame, idx: int) -> SignalResult:
        if idx < self.lookback_swings + self.macd_slow or idx >= len(df):
            return SignalResult(None, 0.0, self.base_expiration_bars, "warming_up")

        row = df.iloc[idx]
        prev = df.iloc[idx - 1]

        diff = float(row.get("macd_diff", 0.0))
        prev_diff = float(prev.get("macd_diff", 0.0))
        macd_l = float(row.get("macd_line", 0.0))
        macd_s = float(row.get("macd_signal", 0.0))

        close = float(row["close"])

        # Check local window for swing divergence
        window = df.iloc[idx - self.lookback_swings : idx]
        min_price = float(window["low"].min())
        max_price = float(window["high"].max())
        min_diff = float(window["macd_diff"].min())
        max_diff = float(window["macd_diff"].max())

        action = None
        confidence = 0.0

        # Bullish Divergence: Price near swing low, MACD histogram higher low
        if close <= min_price * 1.0008 and diff > min_diff and prev_diff <= 0 and diff > prev_diff:
            action = TradeAction.CALL
            confidence = 0.70
            if macd_l > macd_s and prev.get("macd_line", 0.0) <= prev.get("macd_signal", 0.0):
                confidence += 0.20
            elif diff > 0:
                confidence += 0.10

        # Bearish Divergence: Price near swing high, MACD histogram lower high
        elif (
            close >= max_price * 0.9992 and diff < max_diff and prev_diff >= 0 and diff < prev_diff
        ):
            action = TradeAction.PUT
            confidence = 0.70
            if macd_l < macd_s and prev.get("macd_line", 0.0) >= prev.get("macd_signal", 0.0):
                confidence += 0.20
            elif diff < 0:
                confidence += 0.10

        confidence = min(confidence, 0.95)
        return SignalResult(
            action=action,
            confidence=confidence,
            expiration_bars=self.base_expiration_bars,
            regime="divergence_reversal",
            metadata={"macd_diff": round(diff, 6), "macd_line": round(macd_l, 6)},
        )

    @classmethod
    def get_parameter_definitions(cls) -> list[ParameterDef]:
        return [
            ParameterDef(
                "macd_fast", "MACD Fast", "int", 12, 8, 16, 2, description="Fast EMA period"
            ),
            ParameterDef(
                "macd_slow", "MACD Slow", "int", 26, 20, 32, 2, description="Slow EMA period"
            ),
            ParameterDef(
                "macd_sign",
                "MACD Signal",
                "int",
                9,
                5,
                13,
                2,
                description="Signal smoothing period",
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
