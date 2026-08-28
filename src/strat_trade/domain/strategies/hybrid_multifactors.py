from __future__ import annotations

import pandas as pd
import ta

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.strategies.base import BaseStrategy, ParameterDef, SignalResult


class HybridMultiFactorsStrategy(BaseStrategy):
    """
    Hybrid quantitative multi-factor strategy combining:
    - Trend Filters: EMA(9), EMA(21), EMA(50)
    - Momentum Oscillators: RSI(14), Stochastic (14, 3, 3)
    - Volatility & Mean Reversion: Bollinger Bands (20, 2.0), ATR(14)
    - Market Regime Detection: ADX(14) (Trending >= 25 vs Range <= 20 vs Squeeze)
    - Adaptive Expiration: dynamic duration scaling based on ATR & volatility expansion
    """

    def __init__(
        self,
        *,
        rsi_period: int = 14,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        ema_fast: int = 9,
        ema_mid: int = 21,
        ema_slow: int = 50,
        bb_length: int = 20,
        bb_std: float = 2.0,
        atr_period: int = 14,
        adx_period: int = 14,
        adx_trend_threshold: float = 25.0,
        adx_range_threshold: float = 20.0,
        adx_min_threshold: float = 22.0,
        base_expiration_bars: int = 3,
        adaptive_expiration_enabled: bool = False,
    ) -> None:
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.ema_fast = ema_fast
        self.ema_mid = ema_mid
        self.ema_slow = ema_slow
        self.bb_length = bb_length
        self.bb_std = bb_std
        self.atr_period = atr_period
        self.adx_period = adx_period
        self.adx_trend_threshold = adx_trend_threshold
        self.adx_range_threshold = adx_range_threshold
        self.adx_min_threshold = float(adx_min_threshold)
        self.base_expiration_bars = max(1, base_expiration_bars)
        self.adaptive_expiration_enabled = adaptive_expiration_enabled

    def prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate technical indicators in a vectorized manner."""
        work = df.copy()
        if "close" not in work.columns or len(work) < max(self.ema_slow, self.bb_length, 30):
            return work

        close = work["close"]
        high = work["high"]
        low = work["low"]

        # 1. EMAs
        work["ema_fast"] = ta.trend.ema_indicator(close, window=self.ema_fast, fillna=False)
        work["ema_mid"] = ta.trend.ema_indicator(close, window=self.ema_mid, fillna=False)
        work["ema_slow"] = ta.trend.ema_indicator(close, window=self.ema_slow, fillna=False)

        # 2. RSI
        work["rsi"] = ta.momentum.rsi(close, window=self.rsi_period, fillna=False)

        # 3. Stochastic Oscillator
        stoch = ta.momentum.StochasticOscillator(
            high=high,
            low=low,
            close=close,
            window=14,
            smooth_window=3,
            fillna=False,
        )
        work["stoch_k"] = stoch.stoch()
        work["stoch_d"] = stoch.stoch_signal()

        # 4. Bollinger Bands
        bb = ta.volatility.BollingerBands(
            close=close,
            window=self.bb_length,
            window_dev=self.bb_std,
            fillna=False,
        )
        work["bb_high"] = bb.bollinger_hband()
        work["bb_mid"] = bb.bollinger_mavg()
        work["bb_low"] = bb.bollinger_lband()
        work["bb_pband"] = bb.bollinger_pband()
        work["bb_wband"] = bb.bollinger_wband()

        # 5. ATR and ADX
        work["atr"] = ta.volatility.average_true_range(
            high=high, low=low, close=close, window=self.atr_period, fillna=False
        )
        work["atr_sma"] = work["atr"].rolling(window=20, min_periods=5).mean()

        adx_ind = ta.trend.ADXIndicator(
            high=high, low=low, close=close, window=self.adx_period, fillna=False
        )
        work["adx"] = adx_ind.adx()
        work["adx_pos"] = adx_ind.adx_pos()
        work["adx_neg"] = adx_ind.adx_neg()

        return work

    def evaluate_bar(self, df: pd.DataFrame, idx: int) -> SignalResult:
        """
        Evaluate candle at index `idx` (closed bar) to generate a binary options signal.
        """
        if idx < 50:
            return SignalResult(None, 0.0, self.base_expiration_bars, "warming_up", {})

        row = df.iloc[idx]
        close = float(row["close"])

        ema_f = float(row["ema_fast"]) if pd.notna(row["ema_fast"]) else None
        ema_m = float(row["ema_mid"]) if pd.notna(row["ema_mid"]) else None
        ema_s = float(row["ema_slow"]) if pd.notna(row["ema_slow"]) else None
        rsi = float(row["rsi"]) if pd.notna(row["rsi"]) else None
        stoch_k = float(row["stoch_k"]) if pd.notna(row["stoch_k"]) else None
        stoch_d = float(row["stoch_d"]) if pd.notna(row["stoch_d"]) else None
        bb_h = float(row["bb_high"]) if pd.notna(row["bb_high"]) else None
        bb_l = float(row["bb_low"]) if pd.notna(row["bb_low"]) else None
        bb_m = float(row["bb_mid"]) if pd.notna(row["bb_mid"]) else None
        adx = float(row["adx"]) if pd.notna(row["adx"]) else 15.0
        adx_pos = float(row["adx_pos"]) if "adx_pos" in row and pd.notna(row["adx_pos"]) else 0.0
        adx_neg = float(row["adx_neg"]) if "adx_neg" in row and pd.notna(row["adx_neg"]) else 0.0
        atr = float(row["atr"]) if pd.notna(row["atr"]) else 0.0001
        atr_sma = float(row["atr_sma"]) if pd.notna(row["atr_sma"]) else atr

        if None in (ema_f, ema_m, ema_s, rsi, stoch_k, stoch_d, bb_h, bb_l, bb_m):
            return SignalResult(None, 0.0, self.base_expiration_bars, "incomplete_indicators", {})

        # Volatility Squeeze / Explosion Check
        vol_ratio = atr / atr_sma if atr_sma > 0 else 1.0
        if vol_ratio > 2.5:
            # Extreme volatility spike (news / abnormal wick) — suppress trading
            return SignalResult(
                None, 0.0, self.base_expiration_bars, "volatility_spike_suppressed", {}
            )

        metadata = {
            "adx": round(adx, 2),
            "adx_pos": round(adx_pos, 2),
            "adx_neg": round(adx_neg, 2),
            "rsi": round(rsi, 2),
            "stoch_k": round(stoch_k, 2),
            "stoch_d": round(stoch_d, 2),
            "bb_pband": round(float(row.get("bb_pband", 0.5)), 4),
            "vol_ratio": round(vol_ratio, 2),
        }

        # Hard ADX gating check (suppress choppy low-momentum regimes)
        if adx < self.adx_min_threshold:
            metadata["regime"] = "adx_sub_threshold_choppy"
            return SignalResult(
                action=None,
                confidence=0.0,
                expiration_bars=self.base_expiration_bars,
                regime="adx_sub_threshold_choppy",
                metadata=metadata,
            )

        # Market Regime
        if adx >= self.adx_trend_threshold:
            regime = "trending"
        elif adx <= self.adx_range_threshold:
            regime = "ranging"
        else:
            regime = "transitional"
        metadata["regime"] = regime

        # --- Strict 3-Way Concordance ---
        # CALL Conditions:
        # 1. Directional ADX: adx >= adx_min_threshold and adx_pos > adx_neg
        # 2. Bullish EMA Alignment: ema_fast >= ema_mid and close >= ema_fast * 0.9990
        # 3. RSI Bullish Corridor: 45.0 <= rsi <= 68.0
        # 4. Stochastic Confirmation: stoch_k > stoch_d
        call_valid = (
            adx >= self.adx_min_threshold
            and adx_pos > adx_neg
            and ema_f >= ema_m
            and close >= ema_f * 0.9990
            and 45.0 <= rsi <= 68.0
            and stoch_k > stoch_d
        )

        # PUT Conditions:
        # 1. Directional ADX: adx >= adx_min_threshold and adx_neg > adx_pos
        # 2. Bearish EMA Alignment: ema_fast <= ema_mid and close <= ema_fast * 1.0010
        # 3. RSI Bearish Corridor: 32.0 <= rsi <= 55.0
        # 4. Stochastic Confirmation: stoch_k < stoch_d
        put_valid = (
            adx >= self.adx_min_threshold
            and adx_neg > adx_pos
            and ema_f <= ema_m
            and close <= ema_f * 1.0010
            and 32.0 <= rsi <= 55.0
            and stoch_k < stoch_d
        )

        action: TradeAction | None = None
        confidence = 0.0

        if call_valid and not put_valid:
            action = TradeAction.CALL
            confidence = min(
                0.70
                + (0.15 if adx >= self.adx_trend_threshold else 0.05)
                + (0.10 if (stoch_k - stoch_d) > 2.0 else 0.0),
                0.95,
            )
        elif put_valid and not call_valid:
            action = TradeAction.PUT
            confidence = min(
                0.70
                + (0.15 if adx >= self.adx_trend_threshold else 0.05)
                + (0.10 if (stoch_d - stoch_k) > 2.0 else 0.0),
                0.95,
            )
        else:
            action = None
            confidence = 0.0

        # Expiration Calculation:
        exp_bars = self.base_expiration_bars
        if self.adaptive_expiration_enabled and action is not None:
            if regime == "ranging":
                # In ranges, mean reversion often happens in 2-3 bars
                exp_bars = min(self.base_expiration_bars, 3)
            elif regime == "trending":
                # In trends, give 3-4 bars to absorb micro retracements
                exp_bars = max(self.base_expiration_bars, 3)
            if vol_ratio < 0.8:
                # Low volatility: extend duration by 1 bar
                exp_bars += 1

        return SignalResult(
            action=action,
            confidence=confidence,
            expiration_bars=exp_bars,
            regime=regime,
            metadata=metadata,
        )

    @classmethod
    def get_parameter_definitions(cls) -> list[ParameterDef]:
        return [
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
                description="RSI lower threshold",
            ),
            ParameterDef(
                "rsi_overbought",
                "RSI Overbought",
                "float",
                70.0,
                65.0,
                80.0,
                5.0,
                description="RSI upper threshold",
            ),
            ParameterDef("ema_fast", "EMA Fast", "int", 9, 5, 15, 2, description="Fast EMA period"),
            ParameterDef(
                "ema_mid", "EMA Mid", "int", 21, 15, 30, 3, description="Medium EMA period"
            ),
            ParameterDef(
                "adx_trend_threshold",
                "ADX Trend Threshold",
                "float",
                25.0,
                20.0,
                35.0,
                5.0,
                description="ADX level for trend regime",
            ),
            ParameterDef(
                "adx_min_threshold",
                "ADX Min Threshold",
                "float",
                22.0,
                15.0,
                35.0,
                1.0,
                description="Minimum ADX required to generate signals (suppresses choppy markets)",
            ),
            ParameterDef(
                "base_expiration_bars",
                "Expiration Bars",
                "int",
                3,
                1,
                6,
                1,
                description="Default expiration bars",
            ),
        ]
