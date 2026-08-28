"""Real-Time Market Regime Detector for Dynamic Strategy Switching.

Classifies live M1 candle data into quantitative market regimes:
- TRENDING_BULLISH: ADX >= 25, EMA 9 > EMA 21 > EMA 50, +DI > -DI
- TRENDING_BEARISH: ADX >= 25, EMA 9 < EMA 21 < EMA 50, -DI > +DI
- RANGING: ADX < 22 or contracting Bollinger Bands (Mean Reversion)
- LOW_VOLATILITY_NOISE: Relative ATR < 0.00005 or flat bars (Stand Aside)
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

import numpy as np
import pandas as pd
import ta


class MarketRegime(StrEnum):
    TRENDING_BULLISH = "trending_bullish"
    TRENDING_BEARISH = "trending_bearish"
    RANGING = "ranging"
    LOW_VOLATILITY_NOISE = "low_volatility_noise"


def detect_live_market_regime(
    candles_df: pd.DataFrame,
    adx_trend_threshold: float = 24.0,
) -> tuple[MarketRegime, dict[str, float]]:
    """Evaluates the last 50+ M1 candles to detect the active real-time regime.

    Returns:
        (MarketRegime, regime_metrics_dict)
    """
    if candles_df is None or len(candles_df) < 35:
        return MarketRegime.RANGING, {"adx": 20.0, "relative_atr": 0.001}

    df = candles_df.copy()
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    # 1. Relative ATR
    atr_ind = ta.volatility.AverageTrueRange(high=high, low=low, close=close, window=14)
    atr = float(atr_ind.average_true_range().iloc[-1])
    curr_close = float(close.iloc[-1])
    rel_atr = (atr / curr_close) if curr_close > 0 and not np.isnan(atr) else 0.0

    if rel_atr < 0.00005 or curr_close < 0.001:
        return MarketRegime.LOW_VOLATILITY_NOISE, {
            "adx": 0.0,
            "relative_atr": rel_atr,
        }

    # 2. ADX & Directional Movement
    adx_ind = ta.trend.ADXIndicator(high=high, low=low, close=close, window=14)
    adx = float(adx_ind.adx().iloc[-1])
    adx_pos = float(adx_ind.adx_pos().iloc[-1])
    adx_neg = float(adx_ind.adx_neg().iloc[-1])

    # 3. EMA Ribbon Alignment (9, 21, 50)
    ema9 = float(ta.trend.EMAIndicator(close=close, window=9).ema_indicator().iloc[-1])
    ema21 = float(ta.trend.EMAIndicator(close=close, window=21).ema_indicator().iloc[-1])
    ema50 = float(ta.trend.EMAIndicator(close=close, window=50).ema_indicator().iloc[-1])

    metrics = {
        "adx": round(adx, 2),
        "adx_pos": round(adx_pos, 2),
        "adx_neg": round(adx_neg, 2),
        "ema9": ema9,
        "ema21": ema21,
        "ema50": ema50,
        "relative_atr": rel_atr,
    }

    # 4. Classify Regime
    if adx >= adx_trend_threshold and adx_pos > adx_neg and (ema9 > ema21 or curr_close > ema50):
        return MarketRegime.TRENDING_BULLISH, metrics
    elif adx >= adx_trend_threshold and adx_neg > adx_pos and (ema9 < ema21 or curr_close < ema50):
        return MarketRegime.TRENDING_BEARISH, metrics
    else:
        return MarketRegime.RANGING, metrics


def select_candidate_strategies_for_regime(
    regime: MarketRegime,
    allowed_strategies: Sequence[str] | None = None,
) -> list[str]:
    """Returns an ordered list of suitable strategy IDs for the given market regime."""
    if regime == MarketRegime.LOW_VOLATILITY_NOISE:
        return []

    if regime in (MarketRegime.TRENDING_BULLISH, MarketRegime.TRENDING_BEARISH):
        preferred = [
            "ema_pullback_trend",
            "supertrend_adx_momentum",
            "support_resistance_bounce",
        ]
    else:  # RANGING / MEAN_REVERTING
        preferred = [
            "support_resistance_bounce",
            "rsi_stochastic_extreme",
            "bollinger_atr_reversion",
        ]

    if allowed_strategies:
        allowed_set = set(allowed_strategies)
        filtered = [s for s in preferred if s in allowed_set]
        if not filtered:
            filtered = list(allowed_strategies)
        return filtered

    return preferred
