from __future__ import annotations

import numpy as np
import pandas as pd
import ta

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.strategies.base import BaseStrategy, ParameterDef, SignalResult


class SupertrendAdxMomentumStrategy(BaseStrategy):
    """Supertrend Directional Engine + ADX Trend Strength Strategy.

    Follows clean algorithmic trends using ATR-based trailing stops (Supertrend)
    filtered by ADX directional momentum (ADX >= 25).
    """

    def __init__(
        self,
        *,
        atr_period: int = 10,
        atr_multiplier: float = 3.0,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        base_expiration_bars: int = 3,
        adaptive_expiration_enabled: bool = False,
    ) -> None:
        self.atr_period = int(atr_period)
        self.atr_multiplier = float(atr_multiplier)
        self.adx_period = int(adx_period)
        self.adx_threshold = float(adx_threshold)
        self.base_expiration_bars = int(base_expiration_bars)
        self.adaptive_expiration_enabled = bool(adaptive_expiration_enabled)

    def prepare_dataframe(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        df = df_raw.copy()
        if len(df) < max(self.atr_period, self.adx_period) + 10:
            return df

        # ADX
        adx_ind = ta.trend.ADXIndicator(
            high=df["high"], low=df["low"], close=df["close"], window=self.adx_period
        )
        df["adx"] = adx_ind.adx()
        df["adx_pos"] = adx_ind.adx_pos()
        df["adx_neg"] = adx_ind.adx_neg()

        # ATR & Supertrend
        atr_ind = ta.volatility.AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"], window=self.atr_period
        )
        df["atr"] = atr_ind.average_true_range()

        hl2 = (df["high"] + df["low"]) / 2.0
        up = hl2 - (self.atr_multiplier * df["atr"])
        dn = hl2 + (self.atr_multiplier * df["atr"])

        supertrend = np.zeros(len(df))
        direction = np.zeros(len(df))  # 1 = up, -1 = down

        for i in range(1, len(df)):
            curr_close = df["close"].iloc[i]
            prev_up = up.iloc[i - 1]
            prev_dn = dn.iloc[i - 1]
            prev_dir = direction[i - 1]

            curr_up = up.iloc[i]
            curr_dn = dn.iloc[i]

            if curr_close > prev_dn:
                curr_dir = 1
            elif curr_close < prev_up:
                curr_dir = -1
            else:
                curr_dir = prev_dir

            direction[i] = curr_dir
            supertrend[i] = curr_up if curr_dir == 1 else curr_dn

        df["st_dir"] = direction
        df["st_val"] = supertrend

        return df

    def evaluate_bar(self, df: pd.DataFrame, idx: int) -> SignalResult:
        if idx < 20 or idx >= len(df):
            return SignalResult(None, 0.0, self.base_expiration_bars, "warming_up")

        row = df.iloc[idx]
        prev = df.iloc[idx - 1]

        st_dir = int(row.get("st_dir", 0))
        prev_st_dir = int(prev.get("st_dir", 0))
        adx = float(row.get("adx", 0.0))
        adx_pos = float(row.get("adx_pos", 0.0))
        adx_neg = float(row.get("adx_neg", 0.0))

        action = None
        confidence = 0.0

        if adx >= self.adx_threshold:
            # Bullish: Supertrend flip or continuation with +DI dominance
            if st_dir == 1 and adx_pos > adx_neg:
                action = TradeAction.CALL
                confidence = 0.70
                if prev_st_dir == -1 and st_dir == 1:  # Fresh trend reversal flip
                    confidence += 0.20

            # Bearish: Supertrend flip or continuation with -DI dominance
            elif st_dir == -1 and adx_neg > adx_pos:
                action = TradeAction.PUT
                confidence = 0.70
                if prev_st_dir == 1 and st_dir == -1:  # Fresh trend reversal flip
                    confidence += 0.20

        confidence = min(confidence, 0.95)
        return SignalResult(
            action=action,
            confidence=confidence,
            expiration_bars=self.base_expiration_bars,
            regime="supertrend_momentum",
            metadata={"adx": round(adx, 2), "st_dir": st_dir},
        )

    @classmethod
    def get_parameter_definitions(cls) -> list[ParameterDef]:
        return [
            ParameterDef(
                "atr_period", "Supertrend ATR", "int", 10, 7, 14, 1, description="ATR lookback"
            ),
            ParameterDef(
                "atr_multiplier",
                "Supertrend Multiplier",
                "float",
                3.0,
                2.0,
                4.0,
                0.5,
                description="ATR distance factor",
            ),
            ParameterDef(
                "adx_threshold",
                "ADX Trend Gate",
                "float",
                25.0,
                20.0,
                35.0,
                5.0,
                description="Minimum ADX strength",
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
