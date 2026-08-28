from __future__ import annotations

import pandas as pd
import ta

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.strategies.base import BaseStrategy, ParameterDef, SignalResult


def check_runaway_momentum(
    df: pd.DataFrame,
    idx: int,
    lookback_bars: int = 3,
    min_body_ratio: float = 0.50,
    max_opposing_wick_ratio: float = 0.25,
) -> tuple[bool, bool]:
    """Detects whether the market is experiencing a runaway directional momentum burst.

    Checks if consecutive M1 candles (either ending at idx or on preceding bars ending at idx-1)
    close aggressively in the trend direction with expanding bodies (>= min_body_ratio)
    and minimal opposing wicks (<= max_opposing_wick_ratio).

    Returns:
        (is_bearish_runaway, is_bullish_runaway)
        - is_bearish_runaway: consecutive strong red candles (suppress CALL reversals)
        - is_bullish_runaway: consecutive strong green candles (suppress PUT reversals)
    """
    if idx < 0 or idx >= len(df) or lookback_bars <= 0:
        return False, False

    def _is_bearish(row: pd.Series) -> bool:
        close_ = float(row["close"])
        open_ = float(row["open"])
        high_ = float(row["high"])
        low_ = float(row["low"])
        rng = high_ - low_
        if rng <= 1e-9 or close_ >= open_:
            return False
        body = open_ - close_
        if (body / rng) < min_body_ratio:
            return False
        lower_wick = close_ - low_
        return (lower_wick / rng) <= max_opposing_wick_ratio

    def _is_bullish(row: pd.Series) -> bool:
        close_ = float(row["close"])
        open_ = float(row["open"])
        high_ = float(row["high"])
        low_ = float(row["low"])
        rng = high_ - low_
        if rng <= 1e-9 or close_ <= open_:
            return False
        body = close_ - open_
        if (body / rng) < min_body_ratio:
            return False
        upper_wick = high_ - close_
        return (upper_wick / rng) <= max_opposing_wick_ratio

    is_bearish = False
    is_bullish = False

    # Check consecutive bars ending at idx
    if idx >= lookback_bars - 1:
        if all(_is_bearish(df.iloc[i]) for i in range(idx - lookback_bars + 1, idx + 1)):
            is_bearish = True
        if all(_is_bullish(df.iloc[i]) for i in range(idx - lookback_bars + 1, idx + 1)):
            is_bullish = True

    # Check consecutive bars ending at idx - 1 (preceding sequence before current rejection bar)
    if idx >= lookback_bars:
        if all(_is_bearish(df.iloc[i]) for i in range(idx - lookback_bars, idx)):
            is_bearish = True
        if all(_is_bullish(df.iloc[i]) for i in range(idx - lookback_bars, idx)):
            is_bullish = True

    return is_bearish, is_bullish


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
        base_expiration_bars: int = 3,
        adaptive_expiration_enabled: bool = False,
        max_adx_trend: float = 30.0,
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
        self.max_adx_trend = float(max_adx_trend)

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
        df["adx"] = ta.trend.ADXIndicator(
            high=df["high"], low=df["low"], close=df["close"], window=14
        ).adx()

        return df

    def _check_runaway_momentum(
        self,
        df: pd.DataFrame,
        idx: int,
        lookback_bars: int = 3,
        min_body_ratio: float = 0.50,
        max_opposing_wick_ratio: float = 0.25,
    ) -> tuple[bool, bool]:
        return check_runaway_momentum(
            df=df,
            idx=idx,
            lookback_bars=lookback_bars,
            min_body_ratio=min_body_ratio,
            max_opposing_wick_ratio=max_opposing_wick_ratio,
        )

    def check_runaway_momentum(
        self,
        df: pd.DataFrame,
        idx: int,
        lookback_bars: int = 3,
        min_body_ratio: float = 0.50,
        max_opposing_wick_ratio: float = 0.25,
    ) -> tuple[bool, bool]:
        return check_runaway_momentum(
            df=df,
            idx=idx,
            lookback_bars=lookback_bars,
            min_body_ratio=min_body_ratio,
            max_opposing_wick_ratio=max_opposing_wick_ratio,
        )

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

        # Strong Trend Guard: Suppress mean-reversion counter-trend trades if ADX >= max_adx_trend
        adx = float(row.get("adx", 20.0))
        if (
            (rsi <= self.rsi_oversold and sk <= self.stoch_oversold)
            or (rsi >= self.rsi_overbought and sk >= self.stoch_overbought)
        ) and (not pd.isna(adx) and adx >= self.max_adx_trend):
            return SignalResult(
                action=None,
                confidence=0.0,
                expiration_bars=self.base_expiration_bars,
                regime="strong_trend_adx_suppressed",
                metadata={
                    "rsi": round(rsi, 2),
                    "stoch_k": round(sk, 2),
                    "adx": round(adx, 2),
                    "max_adx_trend": self.max_adx_trend,
                },
            )

        # Oversold Exhaustion -> CALL
        if rsi <= self.rsi_oversold and sk <= self.stoch_oversold:
            is_bearish_runaway, _ = self._check_runaway_momentum(df, idx)
            if is_bearish_runaway:
                return SignalResult(
                    action=None,
                    confidence=0.0,
                    expiration_bars=self.base_expiration_bars,
                    regime="runaway_momentum_suppressed",
                    metadata={
                        "rsi": round(rsi, 2),
                        "stoch_k": round(sk, 2),
                        "stoch_d": round(sd, 2),
                        "suppressed_action": "CALL",
                    },
                )
            action = TradeAction.CALL
            confidence = 0.70
            if prev_sk <= prev_sd and sk > sd:  # Fresh crossover
                confidence += 0.20
            elif sk > prev_sk:
                confidence += 0.10

        # Overbought Exhaustion -> PUT
        elif rsi >= self.rsi_overbought and sk >= self.stoch_overbought:
            _, is_bullish_runaway = self._check_runaway_momentum(df, idx)
            if is_bullish_runaway:
                return SignalResult(
                    action=None,
                    confidence=0.0,
                    expiration_bars=self.base_expiration_bars,
                    regime="runaway_momentum_suppressed",
                    metadata={
                        "rsi": round(rsi, 2),
                        "stoch_k": round(sk, 2),
                        "stoch_d": round(sd, 2),
                        "suppressed_action": "PUT",
                    },
                )
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
                3,
                1,
                5,
                1,
                description="Expiration bars",
            ),
            ParameterDef(
                "max_adx_trend",
                "Max ADX Trend Guard",
                "float",
                30.0,
                20.0,
                40.0,
                2.0,
                description="Maximum ADX allowed for mean reversion reversal",
            ),
        ]
