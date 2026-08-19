from __future__ import annotations

import pandas as pd
import ta

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.strategies.base import BaseStrategy, ParameterDef, SignalResult


class RsiStochasticExtremeStrategy(BaseStrategy):
    """Double Oscillator Extreme Exhaustion Scalping Strategy (RSI + Stochastic).

    Triggers counter-trend scalp reversals when both RSI and Stochastic reach
    extreme boundaries simultaneously, indicating micro liquidity exhaustion.
    """

    def __init__(
        self,
        *,
        rsi_period: int = 14,
        rsi_oversold: float = 25.0,
        rsi_overbought: float = 75.0,
        stoch_k: int = 14,
        stoch_d: int = 3,
        stoch_oversold: float = 20.0,
        stoch_overbought: float = 80.0,
        base_expiration_bars: int = 2,
        adaptive_expiration_enabled: bool = False,
    ) -> None:
        self.rsi_period = int(rsi_period)
        self.rsi_oversold = float(rsi_oversold)
        self.rsi_overbought = float(rsi_overbought)
        self.stoch_k = int(stoch_k)
        self.stoch_d = int(stoch_d)
        self.stoch_oversold = float(stoch_oversold)
        self.stoch_overbought = float(stoch_overbought)
        self.base_expiration_bars = int(base_expiration_bars)
        self.adaptive_expiration_enabled = bool(adaptive_expiration_enabled)

    def prepare_dataframe(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        df = df_raw.copy()
        if len(df) < max(self.rsi_period, self.stoch_k) + 10:
            return df

        df["rsi"] = ta.momentum.RSIIndicator(close=df["close"], window=self.rsi_period).rsi()
        stoch = ta.momentum.StochasticOscillator(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            window=self.stoch_k,
            smooth_window=self.stoch_d,
        )
        df["stoch_k"] = stoch.stoch()
        df["stoch_d"] = stoch.stoch_signal()

        return df

    def evaluate_bar(self, df: pd.DataFrame, idx: int) -> SignalResult:
        if idx < 20 or idx >= len(df):
            return SignalResult(None, 0.0, self.base_expiration_bars, "warming_up")

        row = df.iloc[idx]
        prev = df.iloc[idx - 1]

        rsi = float(row.get("rsi", 50.0))
        sk = float(row.get("stoch_k", 50.0))
        sd = float(row.get("stoch_d", 50.0))
        prev_sk = float(prev.get("stoch_k", 50.0))
        prev_sd = float(prev.get("stoch_d", 50.0))

        action = None
        confidence = 0.0

        # Oversold Exhaustion -> CALL
        if rsi <= self.rsi_oversold and sk <= self.stoch_oversold:
            action = TradeAction.CALL
            confidence = 0.70
            if prev_sk <= prev_sd and sk > sd:  # Fresh crossover
                confidence += 0.20
            elif sk > prev_sk:
                confidence += 0.10

        # Overbought Exhaustion -> PUT
        elif rsi >= self.rsi_overbought and sk >= self.stoch_overbought:
            action = TradeAction.PUT
            confidence = 0.70
            if prev_sk >= prev_sd and sk < sd:  # Fresh crossover
                confidence += 0.20
            elif sk < prev_sk:
                confidence += 0.10

        confidence = min(confidence, 0.95)
        return SignalResult(
            action=action,
            confidence=confidence,
            expiration_bars=self.base_expiration_bars,
            regime="extreme_exhaustion",
            metadata={"rsi": round(rsi, 2), "stoch_k": round(sk, 2), "stoch_d": round(sd, 2)},
        )

    @classmethod
    def get_parameter_definitions(cls) -> list[ParameterDef]:
        return [
            ParameterDef(
                "rsi_period", "RSI Period", "int", 14, 7, 21, 1, description="RSI lookback"
            ),
            ParameterDef(
                "rsi_oversold",
                "RSI Oversold",
                "float",
                25.0,
                15.0,
                30.0,
                5.0,
                description="RSI oversold boundary",
            ),
            ParameterDef(
                "rsi_overbought",
                "RSI Overbought",
                "float",
                75.0,
                70.0,
                85.0,
                5.0,
                description="RSI overbought boundary",
            ),
            ParameterDef(
                "stoch_oversold",
                "Stoch Oversold",
                "float",
                20.0,
                10.0,
                30.0,
                5.0,
                description="Stochastic oversold level",
            ),
            ParameterDef(
                "stoch_overbought",
                "Stoch Overbought",
                "float",
                80.0,
                70.0,
                90.0,
                5.0,
                description="Stochastic overbought level",
            ),
            ParameterDef(
                "base_expiration_bars",
                "Expiration Bars",
                "int",
                2,
                1,
                4,
                1,
                description="Expiration bars",
            ),
        ]
