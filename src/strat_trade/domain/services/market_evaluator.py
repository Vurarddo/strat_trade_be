from collections.abc import Mapping
from typing import Any

import pandas as pd
import pandas_ta as ta  # noqa: F401

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import InsufficientMarketDataError
from strat_trade.domain.market_state import (
    MarketRegime,
    MarketStateVector,
    PriceAction,
    SMCStructure,
)


class MarketStateEvaluator:
    """Evaluates raw candles and outputs a MarketStateVector with SMC and regimen metrics."""

    def evaluate(self, candles: list[Candle] | list[Mapping[str, Any]]) -> MarketStateVector:
        if not candles:
            raise InsufficientMarketDataError("Candles list cannot be empty for Evaluation.")

        raw_data = self._to_raw_data(candles)
        df = pd.DataFrame(raw_data)

        # Force float casting for math safety
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        current_price = float(df.iloc[-1]["close"])

        regime = self._evaluate_regime(df)
        smc = self._evaluate_smc(df, current_price)
        price_action = self._evaluate_price_action(df)

        return MarketStateVector(
            current_price=current_price,
            regime=regime,
            smc=smc,
            price_action=price_action,
        )

    def _to_raw_data(
        self, candles: list[Candle] | list[Mapping[str, Any]]
    ) -> list[dict[str, float]]:
        raw_data = []
        for c in candles:
            if isinstance(c, Candle):
                raw_data.append(
                    {
                        "open": float(c.open),
                        "high": float(c.high),
                        "low": float(c.low),
                        "close": float(c.close),
                        "volume": float(c.volume) if c.volume is not None else 0.0,
                    }
                )
            else:
                raw_data.append(
                    {
                        "open": float(c.get("open", 0.0)),
                        "high": float(c.get("high", 0.0)),
                        "low": float(c.get("low", 0.0)),
                        "close": float(c.get("close", 0.0)),
                        "volume": float(c.get("volume", 0.0)),
                    }
                )
        return raw_data

    def _evaluate_regime(self, df: pd.DataFrame) -> MarketRegime:
        if len(df) < 15:
            # Not enough data for ADX/ATR length 14
            volume_trend = self._evaluate_volume_trend(df)
            return MarketRegime(
                adx_14=None,
                atr_14=None,
                is_choppy=True,
                volume_trend=volume_trend,
            )

        # ADX calculation
        adx_df = df.ta.adx(length=14)
        adx_val = None
        if adx_df is not None and "ADX_14" in adx_df.columns:
            adx_series = adx_df["ADX_14"]
            if not adx_series.empty and not pd.isna(adx_series.iloc[-1]):
                adx_val = float(adx_series.iloc[-1])

        # ATR calculation
        atr_series = df.ta.atr(length=14)
        atr_val = None
        if atr_series is not None and not atr_series.empty and not pd.isna(atr_series.iloc[-1]):
            atr_val = float(atr_series.iloc[-1])

        is_choppy = True
        if adx_val is not None:
            is_choppy = adx_val < 20.0

        volume_trend = self._evaluate_volume_trend(df)

        return MarketRegime(
            adx_14=adx_val,
            atr_14=atr_val,
            is_choppy=is_choppy,
            volume_trend=volume_trend,
        )

    def _evaluate_volume_trend(self, df: pd.DataFrame) -> str:
        if len(df) < 5:
            return "FLAT"

        sma_vol = df["volume"].rolling(window=5).mean()
        latest_vol = df.iloc[-1]["volume"]
        sma_val = sma_vol.iloc[-1]

        if pd.isna(sma_val):
            return "FLAT"

        if latest_vol > (sma_val * 1.2):
            return "INCREASING"
        elif latest_vol < (sma_val * 0.8):
            return "DECREASING"
        return "FLAT"

    def _evaluate_smc(self, df: pd.DataFrame, current_price: float) -> SMCStructure:
        if len(df) < 5:
            return SMCStructure(
                last_swing_high_price=None,
                last_swing_low_price=None,
                has_recent_bullish_fvg=False,
                has_recent_bearish_fvg=False,
                distance_to_nearest_bull_fvg=None,
                distance_to_nearest_bear_fvg=None,
            )

        # Swing Highs / Lows
        swing_highs = df["high"].rolling(window=5, center=True).max()
        swing_lows = df["low"].rolling(window=5, center=True).min()

        valid_sh = swing_highs.dropna()
        valid_sl = swing_lows.dropna()

        last_swing_high = float(valid_sh.iloc[-1]) if not valid_sh.empty else None
        last_swing_low = float(valid_sl.iloc[-1]) if not valid_sl.empty else None

        # Fair Value Gaps
        # Bullish FVG: low[i] > high[i-2]
        # Bearish FVG: high[i] < low[i-2]
        prev_2_high = df["high"].shift(2)
        prev_2_low = df["low"].shift(2)

        is_bull_fvg = df["low"] > prev_2_high
        is_bear_fvg = df["high"] < prev_2_low

        has_recent_bull_fvg = bool(is_bull_fvg.tail(5).any())
        has_recent_bear_fvg = bool(is_bear_fvg.tail(5).any())

        # Distances
        bull_fvg_indices = df[is_bull_fvg].index
        bear_fvg_indices = df[is_bear_fvg].index

        dist_bull = None
        if not bull_fvg_indices.empty:
            idx = bull_fvg_indices[-1]
            gap_mid = (float(df.loc[idx, "low"]) + float(prev_2_high.loc[idx])) / 2.0
            dist_bull = abs(current_price - gap_mid)

        dist_bear = None
        if not bear_fvg_indices.empty:
            idx = bear_fvg_indices[-1]
            gap_mid = (float(df.loc[idx, "high"]) + float(prev_2_low.loc[idx])) / 2.0
            dist_bear = abs(current_price - gap_mid)

        return SMCStructure(
            last_swing_high_price=last_swing_high,
            last_swing_low_price=last_swing_low,
            has_recent_bullish_fvg=has_recent_bull_fvg,
            has_recent_bearish_fvg=has_recent_bear_fvg,
            distance_to_nearest_bull_fvg=dist_bull,
            distance_to_nearest_bear_fvg=dist_bear,
        )

    def _evaluate_price_action(self, df: pd.DataFrame) -> PriceAction:
        if len(df) < 15:
            return PriceAction(rsi_14=None, rsi_divergence="NONE")

        # 1. Calculate RSI
        rsi_series = df.ta.rsi(length=14)
        if rsi_series is None or rsi_series.empty:
            return PriceAction(rsi_14=None, rsi_divergence="NONE")

        df["RSI_14"] = rsi_series
        rsi_14_val = None
        if not pd.isna(rsi_series.iloc[-1]):
            rsi_14_val = float(rsi_series.iloc[-1])

        # 2. Extract RSI Divergence
        # Re-derive swing points using rolling 5 just for masking
        df["is_swing_high"] = df["high"] == df["high"].rolling(window=5, center=True).max()
        df["is_swing_low"] = df["low"] == df["low"].rolling(window=5, center=True).min()

        swing_highs_df = df[df["is_swing_high"]].dropna(subset=["RSI_14"])
        swing_lows_df = df[df["is_swing_low"]].dropna(subset=["RSI_14"])

        rsi_divergence = "NONE"

        # Regular Bearish Divergence
        # HH in Price, LH in RSI
        if len(swing_highs_df) >= 2:
            prev_sh = swing_highs_df.iloc[-2]
            curr_sh = swing_highs_df.iloc[-1]
            if curr_sh["high"] > prev_sh["high"] and curr_sh["RSI_14"] < prev_sh["RSI_14"]:
                rsi_divergence = "REGULAR_BEARISH"

        # Regular Bullish Divergence
        # LL in Price, HL in RSI
        if rsi_divergence == "NONE" and len(swing_lows_df) >= 2:
            prev_sl = swing_lows_df.iloc[-2]
            curr_sl = swing_lows_df.iloc[-1]
            if curr_sl["low"] < prev_sl["low"] and curr_sl["RSI_14"] > prev_sl["RSI_14"]:
                rsi_divergence = "REGULAR_BULLISH"

        return PriceAction(
            rsi_14=rsi_14_val,
            rsi_divergence=rsi_divergence,
        )
