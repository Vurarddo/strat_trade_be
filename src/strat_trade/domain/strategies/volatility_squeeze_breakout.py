from __future__ import annotations

import pandas as pd
import ta

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.strategies.base import BaseStrategy, ParameterDef, SignalResult


class VolatilitySqueezeBreakoutStrategy(BaseStrategy):
    """Bollinger Bands & Keltner Channel Volatility Squeeze Breakout (TTM Squeeze).

    Detects consolidation phases where Bollinger Bands narrow inside Keltner Channels,
    then fires a strong momentum trade upon channel breakout.
    """

    def __init__(
        self,
        *,
        bb_length: int = 20,
        bb_std: float = 2.0,
        kc_length: int = 20,
        kc_mult: float = 1.5,
        momentum_period: int = 12,
        base_expiration_bars: int = 3,
        adaptive_expiration_enabled: bool = False,
    ) -> None:
        self.bb_length = int(bb_length)
        self.bb_std = float(bb_std)
        self.kc_length = int(kc_length)
        self.kc_mult = float(kc_mult)
        self.momentum_period = int(momentum_period)
        self.base_expiration_bars = int(base_expiration_bars)
        self.adaptive_expiration_enabled = bool(adaptive_expiration_enabled)

    def prepare_dataframe(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        df = df_raw.copy()
        if len(df) < max(self.bb_length, self.kc_length, self.momentum_period) + 10:
            return df

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(
            close=df["close"], window=self.bb_length, window_dev=self.bb_std
        )
        df["bb_high"] = bb.bollinger_hband()
        df["bb_low"] = bb.bollinger_lband()

        # Keltner Channels
        kc = ta.volatility.KeltnerChannel(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            window=self.kc_length,
            window_atr=self.kc_length,
            multiplier=self.kc_mult,
        )
        df["kc_high"] = kc.keltner_channel_hband()
        df["kc_low"] = kc.keltner_channel_lband()

        # Squeeze indicator: BB inside KC = squeeze on (1), outside = squeeze off (0)
        df["squeeze_on"] = (df["bb_low"] > df["kc_low"]) & (df["bb_high"] < df["kc_high"])

        # Momentum oscillator: linear regression of price relative to mid
        df["momentum"] = df["close"] - df["close"].shift(self.momentum_period)

        return df

    def evaluate_bar(self, df: pd.DataFrame, idx: int) -> SignalResult:
        if idx < 30 or idx >= len(df):
            return SignalResult(None, 0.0, self.base_expiration_bars, "warming_up")

        row = df.iloc[idx]
        prev = df.iloc[idx - 1]

        mom_val = row.get("momentum", 0.0)
        prev_mom_val = prev.get("momentum", 0.0)
        mom = 0.0 if pd.isna(mom_val) else float(mom_val)
        prev_mom = 0.0 if pd.isna(prev_mom_val) else float(prev_mom_val)

        sq_now_val = row.get("squeeze_on", False)
        sq_prev_val = prev.get("squeeze_on", False)
        sq_now = False if pd.isna(sq_now_val) else bool(sq_now_val)
        sq_prev = False if pd.isna(sq_prev_val) else bool(sq_prev_val)

        action = None
        confidence = 0.0

        # Breakout Trigger: Squeeze was ON on previous bar and released (OFF) on current bar
        squeeze_fired = sq_prev and not sq_now

        if squeeze_fired:
            if mom > 0 and mom > prev_mom:
                action = TradeAction.CALL
                confidence = 0.90
            elif mom < 0 and mom < prev_mom:
                action = TradeAction.PUT
                confidence = 0.90

        confidence = min(confidence, 0.95)
        return SignalResult(
            action=action,
            confidence=confidence,
            expiration_bars=self.base_expiration_bars,
            regime="volatility_breakout",
            metadata={"momentum": round(mom, 6), "squeeze_on": sq_now},
        )

    @classmethod
    def get_parameter_definitions(cls) -> list[ParameterDef]:
        return [
            ParameterDef(
                "bb_length", "Bollinger Length", "int", 20, 14, 26, 2, description="BB lookback"
            ),
            ParameterDef(
                "kc_mult",
                "Keltner Multiplier",
                "float",
                1.5,
                1.0,
                2.0,
                0.25,
                description="KC multiplier",
            ),
            ParameterDef(
                "momentum_period",
                "Momentum Period",
                "int",
                12,
                6,
                18,
                2,
                description="Momentum lookback",
            ),
            ParameterDef(
                "base_expiration_bars",
                "Expiration Bars",
                "int",
                3,
                1,
                5,
                1,
                description="Expiration duration",
            ),
        ]
