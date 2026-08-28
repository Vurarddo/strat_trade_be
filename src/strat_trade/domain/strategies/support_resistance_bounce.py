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

        # Bounce off Support: Low tests support + long lower wick + bullish confirmation
        # and RSI oversold/moderate
        if (
            low <= supp * 1.0005
            and close >= supp
            and (lower_wick / range_) >= max(0.35, self.min_wick_ratio)
            and close > open_
            and ((close - low) / range_) >= 0.50
            and rsi <= 50.0
        ):
            is_bearish_runaway, _ = self._check_runaway_momentum(df, idx)
            if is_bearish_runaway:
                return SignalResult(
                    action=None,
                    confidence=0.0,
                    expiration_bars=self.base_expiration_bars,
                    regime="runaway_momentum_suppressed",
                    metadata={
                        "support": round(supp, 5),
                        "resistance": round(res, 5),
                        "rsi": round(rsi, 2),
                        "suppressed_action": "CALL",
                    },
                )
            action = TradeAction.CALL
            confidence = 0.75
            if rsi <= 35.0:  # Strong Oversold confirmation
                confidence += 0.15

        # Rejection off Resistance: High tests resistance + long upper wick
        # and bearish confirmation + RSI overbought/moderate
        elif (
            high >= res * 0.9995
            and close <= res
            and (upper_wick / range_) >= max(0.35, self.min_wick_ratio)
            and close < open_
            and ((high - close) / range_) >= 0.50
            and rsi >= 50.0
        ):
            _, is_bullish_runaway = self._check_runaway_momentum(df, idx)
            if is_bullish_runaway:
                return SignalResult(
                    action=None,
                    confidence=0.0,
                    expiration_bars=self.base_expiration_bars,
                    regime="runaway_momentum_suppressed",
                    metadata={
                        "support": round(supp, 5),
                        "resistance": round(res, 5),
                        "rsi": round(rsi, 2),
                        "suppressed_action": "PUT",
                    },
                )
            action = TradeAction.PUT
            confidence = 0.75
            if rsi >= 65.0:  # Strong Overbought confirmation
                confidence += 0.15

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
