from __future__ import annotations

import numpy as np
import pandas as pd

from strat_trade.domain.trading.regime_detector import (
    MarketRegime,
    detect_live_market_regime,
    select_candidate_strategies_for_regime,
)


def _generate_synthetic_candles(
    trend_slope: float, noise: float = 0.0001, count: int = 60
) -> pd.DataFrame:
    base_price = 1.1000
    rows = []
    for i in range(count):
        close = base_price + trend_slope * i + np.sin(i * 0.5) * noise
        high = close + 0.0003
        low = close - 0.0003
        open_ = close - trend_slope * 0.5
        rows.append({"open": open_, "high": high, "low": low, "close": close, "volume": 100})
    return pd.DataFrame(rows)


def test_detect_trending_bullish():
    # Strong upward trend
    df = _generate_synthetic_candles(trend_slope=0.0008, noise=0.00005, count=60)
    regime, metrics = detect_live_market_regime(df)
    assert regime == MarketRegime.TRENDING_BULLISH
    assert metrics["adx"] >= 20.0
    assert metrics["adx_pos"] > metrics["adx_neg"]


def test_detect_trending_bearish():
    # Strong downward trend
    df = _generate_synthetic_candles(trend_slope=-0.0008, noise=0.00005, count=60)
    regime, metrics = detect_live_market_regime(df)
    assert regime == MarketRegime.TRENDING_BEARISH
    assert metrics["adx"] >= 20.0
    assert metrics["adx_neg"] > metrics["adx_pos"]


def test_detect_ranging():
    # Sideways chop
    df = _generate_synthetic_candles(trend_slope=0.0, noise=0.0002, count=60)
    regime, _metrics = detect_live_market_regime(df)
    assert regime == MarketRegime.RANGING


def test_detect_low_volatility_noise():
    # Flat / micro-pip price
    df = pd.DataFrame(
        {
            "open": [0.000067] * 60,
            "high": [0.000067] * 60,
            "low": [0.000067] * 60,
            "close": [0.000067] * 60,
            "volume": [0] * 60,
        }
    )
    regime, _metrics = detect_live_market_regime(df)
    assert regime == MarketRegime.LOW_VOLATILITY_NOISE


def test_select_candidate_strategies():
    strats_trend = select_candidate_strategies_for_regime(MarketRegime.TRENDING_BULLISH)
    assert "ema_pullback_trend" in strats_trend

    strats_range = select_candidate_strategies_for_regime(MarketRegime.RANGING)
    assert "support_resistance_bounce" in strats_range
    assert "rsi_stochastic_extreme" in strats_range

    strats_noise = select_candidate_strategies_for_regime(MarketRegime.LOW_VOLATILITY_NOISE)
    assert len(strats_noise) == 0

    # Strict user selection filtering:
    user_selection = ["rsi_stochastic_extreme", "support_resistance_bounce", "ema_pullback_trend"]
    trend_filtered = select_candidate_strategies_for_regime(
        MarketRegime.TRENDING_BULLISH, allowed_strategies=user_selection
    )
    assert "ema_pullback_trend" in trend_filtered
    assert "supertrend_adx_momentum" not in trend_filtered
    assert "macd_divergence_break" not in trend_filtered
