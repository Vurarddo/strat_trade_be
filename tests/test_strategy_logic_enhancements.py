from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.strategies.bollinger_atr_reversion import BollingerAtrReversionStrategy
from strat_trade.domain.strategies.registry import (
    get_strategy_instance,
    list_available_strategies,
)
from strat_trade.domain.strategies.volatility_squeeze_breakout import (
    VolatilitySqueezeBreakoutStrategy,
)

# ============================================================================
# Helpers for Deterministic Test Data
# ============================================================================


def _create_base_df(n: int = 60) -> pd.DataFrame:
    t0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC)
    data = []
    for i in range(n):
        data.append(
            {
                "timestamp": t0 + timedelta(minutes=i),
                "open": 1.0850,
                "high": 1.0860,
                "low": 1.0840,
                "close": 1.0850,
                "volume": 100,
            }
        )
    return pd.DataFrame(data)


# ============================================================================
# 1. VolatilitySqueezeBreakoutStrategy Unit Tests
# ============================================================================


def test_squeeze_breakout_transition_call():
    """Verify fresh squeeze release with accelerating bullish momentum fires CALL."""
    strat = VolatilitySqueezeBreakoutStrategy()
    df = _create_base_df(40)
    df["squeeze_on"] = False
    df["momentum"] = 0.0

    idx = 35
    df.loc[idx - 1, "squeeze_on"] = True
    df.loc[idx - 1, "momentum"] = 0.0005
    df.loc[idx, "squeeze_on"] = False
    df.loc[idx, "momentum"] = 0.0012

    sig = strat.evaluate_bar(df, idx)
    assert sig.action == TradeAction.CALL
    assert sig.confidence >= 0.90
    assert sig.regime == "volatility_breakout"
    assert sig.metadata.get("squeeze_on") is False
    assert sig.metadata.get("momentum") == 0.0012


def test_squeeze_breakout_transition_put():
    """Verify fresh squeeze release with accelerating bearish momentum fires PUT."""
    strat = VolatilitySqueezeBreakoutStrategy()
    df = _create_base_df(40)
    df["squeeze_on"] = False
    df["momentum"] = 0.0

    idx = 35
    df.loc[idx - 1, "squeeze_on"] = True
    df.loc[idx - 1, "momentum"] = -0.0005
    df.loc[idx, "squeeze_on"] = False
    df.loc[idx, "momentum"] = -0.0012

    sig = strat.evaluate_bar(df, idx)
    assert sig.action == TradeAction.PUT
    assert sig.confidence >= 0.90
    assert sig.regime == "volatility_breakout"
    assert sig.metadata.get("squeeze_on") is False
    assert sig.metadata.get("momentum") == -0.0012


def test_squeeze_breakout_no_phantom_signals_on_uncompressed_bars():
    """Verify uncompressed bars NEVER fire signals despite positive/negative momentum."""
    strat = VolatilitySqueezeBreakoutStrategy()
    df = _create_base_df(60)
    df["squeeze_on"] = False

    # Simulate strong consecutive upward momentum
    for i in range(len(df)):
        df.loc[i, "momentum"] = 0.0010 + (i * 0.0001)

    for i in range(30, len(df)):
        sig = strat.evaluate_bar(df, i)
        assert sig.action is None, f"Phantom signal fired at index {i}"
        assert sig.confidence == 0.0


def test_squeeze_breakout_suppression_during_continuous_squeeze():
    """Verify ongoing compression (sq_prev=True, sq_now=True) suppresses signals until release."""
    strat = VolatilitySqueezeBreakoutStrategy()
    df = _create_base_df(40)
    df["squeeze_on"] = True
    df["momentum"] = 0.0020

    for i in range(30, 40):
        sig = strat.evaluate_bar(df, i)
        assert sig.action is None
        assert sig.confidence == 0.0


def test_squeeze_breakout_suppression_on_entering_squeeze():
    """Verify entering squeeze (sq_prev=False, sq_now=True) does not fire breakout signal."""
    strat = VolatilitySqueezeBreakoutStrategy()
    df = _create_base_df(40)
    df["squeeze_on"] = False
    df["momentum"] = 0.0010

    idx = 35
    df.loc[idx - 1, "squeeze_on"] = False
    df.loc[idx, "squeeze_on"] = True
    df.loc[idx, "momentum"] = 0.0025

    sig = strat.evaluate_bar(df, idx)
    assert sig.action is None
    assert sig.confidence == 0.0


def test_squeeze_breakout_decelerating_momentum_filtered():
    """Verify squeeze release with decelerating or flat momentum is rejected."""
    strat = VolatilitySqueezeBreakoutStrategy()
    df = _create_base_df(40)
    idx = 35

    # Case A: Bullish but decelerating (mom <= prev_mom)
    df.loc[idx - 1, "squeeze_on"] = True
    df.loc[idx - 1, "momentum"] = 0.0020
    df.loc[idx, "squeeze_on"] = False
    df.loc[idx, "momentum"] = 0.0015
    sig_a = strat.evaluate_bar(df, idx)
    assert sig_a.action is None
    assert sig_a.confidence == 0.0

    # Case B: Bearish but decelerating (mom >= prev_mom)
    df.loc[idx - 1, "squeeze_on"] = True
    df.loc[idx - 1, "momentum"] = -0.0020
    df.loc[idx, "squeeze_on"] = False
    df.loc[idx, "momentum"] = -0.0015
    sig_b = strat.evaluate_bar(df, idx)
    assert sig_b.action is None
    assert sig_b.confidence == 0.0

    # Case C: Zero momentum
    df.loc[idx - 1, "squeeze_on"] = True
    df.loc[idx - 1, "momentum"] = 0.0
    df.loc[idx, "squeeze_on"] = False
    df.loc[idx, "momentum"] = 0.0
    sig_c = strat.evaluate_bar(df, idx)
    assert sig_c.action is None
    assert sig_c.confidence == 0.0


def test_squeeze_breakout_zero_division_and_flat_data():
    """Verify flat price data and warmup boundaries produce no exceptions."""
    strat = VolatilitySqueezeBreakoutStrategy()
    df = pd.DataFrame(
        {
            "open": [1.0850] * 50,
            "high": [1.0850] * 50,
            "low": [1.0850] * 50,
            "close": [1.0850] * 50,
            "volume": [100] * 50,
        }
    )
    df_prep = strat.prepare_dataframe(df)
    assert "squeeze_on" in df_prep.columns
    assert "momentum" in df_prep.columns

    # Warmup guard
    sig_warmup = strat.evaluate_bar(df_prep, 10)
    assert sig_warmup.action is None
    assert sig_warmup.regime == "warming_up"

    # Out of bounds guard
    sig_oob = strat.evaluate_bar(df_prep, 55)
    assert sig_oob.action is None
    assert sig_oob.regime == "warming_up"

    # Evaluated bar on flat series
    sig_flat = strat.evaluate_bar(df_prep, 40)
    assert sig_flat.action is None


# ============================================================================
# 2. BollingerAtrReversionStrategy Unit Tests
# ============================================================================


def _create_reversion_test_row(
    *,
    open_: float = 1.0780,
    high: float = 1.0790,
    low: float = 1.0750,
    close: float = 1.0785,
    bb_high: float = 1.0850,
    bb_low: float = 1.0770,
    rsi: float = 25.0,
    prev_rsi: float = 24.0,
    adx: float = 18.0,
    atr: float = 0.0010,
    atr_sma: float = 0.0010,
) -> tuple[pd.DataFrame, int]:
    df = _create_base_df(40)
    idx = 35
    df.loc[idx - 1, "rsi"] = prev_rsi
    df.loc[idx - 1, "atr"] = atr
    df.loc[idx - 1, "atr_sma"] = atr_sma
    df.loc[idx - 1, "adx"] = adx

    df.loc[idx, "open"] = open_
    df.loc[idx, "high"] = high
    df.loc[idx, "low"] = low
    df.loc[idx, "close"] = close
    df.loc[idx, "bb_high"] = bb_high
    df.loc[idx, "bb_low"] = bb_low
    df.loc[idx, "bb_pband"] = 0.1
    df.loc[idx, "rsi"] = rsi
    df.loc[idx, "adx"] = adx
    df.loc[idx, "atr"] = atr
    df.loc[idx, "atr_sma"] = atr_sma
    return df, idx


def test_bollinger_atr_adx_trend_suppression_call():
    """Verify mean-reversion CALL is rejected when ADX >= 25.0 (runaway trend)."""
    strat = BollingerAtrReversionStrategy(adx_trend_threshold=25.0)
    # Candle setup is otherwise ideal: low touched 1.0750 <= bb_l (1.0770), closed inside
    df, idx = _create_reversion_test_row(adx=32.0, rsi=22.0)

    sig = strat.evaluate_bar(df, idx)
    assert sig.action is None
    assert sig.confidence == 0.0
    assert sig.regime == "trend_suppressed_adx"
    assert sig.metadata.get("adx") == 32.0


def test_bollinger_atr_adx_trend_suppression_put():
    """Verify mean-reversion PUT is rejected when ADX >= 25.0 (runaway trend)."""
    strat = BollingerAtrReversionStrategy(adx_trend_threshold=25.0)
    # Bearish setup touching upper band at 1.0865 >= bb_h (1.0850), closed inside at 1.0845
    df, idx = _create_reversion_test_row(
        open_=1.0850,
        high=1.0865,
        low=1.0840,
        close=1.0845,
        bb_high=1.0850,
        bb_low=1.0770,
        rsi=76.0,
        prev_rsi=75.0,
        adx=29.5,
    )

    sig = strat.evaluate_bar(df, idx)
    assert sig.action is None
    assert sig.confidence == 0.0
    assert sig.regime == "trend_suppressed_adx"


def test_bollinger_atr_falling_knife_rejection():
    """Verify falling knife candle closing OUTSIDE the lower band (close < bb_l) is rejected."""
    strat = BollingerAtrReversionStrategy()
    # Waterfall dump: low 1.0740, close 1.0745, both below bb_l 1.0770
    df, idx = _create_reversion_test_row(
        open_=1.0780,
        high=1.0780,
        low=1.0740,
        close=1.0745,
        bb_low=1.0770,
        rsi=20.0,
        adx=15.0,
    )

    sig = strat.evaluate_bar(df, idx)
    assert sig.action is None


def test_bollinger_atr_skyrocketing_pump_rejection():
    """Verify skyrocketing candle closing OUTSIDE the upper band (close > bb_h) is rejected."""
    strat = BollingerAtrReversionStrategy()
    # Vertical breakout: low 1.0840, high 1.0880, close 1.0875, both above bb_h 1.0850
    df, idx = _create_reversion_test_row(
        open_=1.0840,
        high=1.0880,
        low=1.0840,
        close=1.0875,
        bb_high=1.0850,
        rsi=82.0,
        adx=15.0,
    )

    sig = strat.evaluate_bar(df, idx)
    assert sig.action is None


def test_bollinger_atr_bearish_candle_on_lower_band_rejected():
    """Verify red candle (close <= open) on lower band touch is rejected for CALL."""
    strat = BollingerAtrReversionStrategy()
    df, idx = _create_reversion_test_row(
        open_=1.0785,
        high=1.0790,
        low=1.0750,
        close=1.0775,  # Close < Open (bearish candle)
        bb_low=1.0770,
        rsi=24.0,
        adx=16.0,
    )

    sig = strat.evaluate_bar(df, idx)
    assert sig.action is None


def test_bollinger_atr_bullish_candle_on_upper_band_rejected():
    """Verify green candle (close >= open) on upper band touch is rejected for PUT."""
    strat = BollingerAtrReversionStrategy()
    df, idx = _create_reversion_test_row(
        open_=1.0840,
        high=1.0865,
        low=1.0835,
        close=1.0848,  # Close > Open (bullish candle)
        bb_high=1.0850,
        rsi=75.0,
        adx=16.0,
    )

    sig = strat.evaluate_bar(df, idx)
    assert sig.action is None


def test_bollinger_atr_insufficient_wick_rejection():
    """Verify candle with low touched band and close inside, but small wick is rejected."""
    strat = BollingerAtrReversionStrategy(min_wick_ratio=0.25)
    # Lower wick is 1.0770 - 1.0768 = 0.0002. Total range is 0.0022. Wick ratio = 0.09 < 0.25
    df, idx = _create_reversion_test_row(
        open_=1.0770,
        high=1.0790,
        low=1.0768,
        close=1.0785,
        bb_low=1.0770,
        rsi=25.0,
        adx=18.0,
    )

    sig = strat.evaluate_bar(df, idx)
    assert sig.action is None


def test_bollinger_atr_successful_call_reversal():
    """Verify valid Bullish Mean Reversion: pierced lower band, closed inside, bullish candle."""
    strat = BollingerAtrReversionStrategy(min_wick_ratio=0.25, adx_trend_threshold=25.0)
    # Open 1.0780, High 1.0790, Low 1.0750 (pierced bb_l 1.0770), Close 1.0785 (closed inside bb_l)
    # Lower wick = 1.0780 - 1.0750 = 0.0030. Candle range = 0.0040. Wick ratio = 0.75 >= 0.25
    df, idx = _create_reversion_test_row(
        open_=1.0780,
        high=1.0790,
        low=1.0750,
        close=1.0785,
        bb_low=1.0770,
        rsi=24.0,
        adx=16.5,
    )

    sig = strat.evaluate_bar(df, idx)
    assert sig.action == TradeAction.CALL
    assert sig.confidence >= 0.75
    assert sig.regime == "mean_reversion"
    assert sig.metadata.get("rsi") == 24.0
    assert sig.metadata.get("adx") == 16.5


def test_bollinger_atr_successful_put_reversal():
    """Verify valid Bearish Mean Reversion: pierced upper band, closed inside, bearish candle."""
    strat = BollingerAtrReversionStrategy(min_wick_ratio=0.25, adx_trend_threshold=25.0)
    # Open 1.0845, High 1.0865 (pierced bb_h 1.0850), Low 1.0835, Close 1.0840 (closed inside bb_h)
    # Upper wick = 1.0865 - 1.0845 = 0.0020. Range = 0.0030. Wick ratio = 0.667 >= 0.25
    df, idx = _create_reversion_test_row(
        open_=1.0845,
        high=1.0865,
        low=1.0835,
        close=1.0840,
        bb_high=1.0850,
        rsi=74.0,
        adx=14.0,
    )

    sig = strat.evaluate_bar(df, idx)
    assert sig.action == TradeAction.PUT
    assert sig.confidence >= 0.75
    assert sig.regime == "mean_reversion"
    assert sig.metadata.get("rsi") == 74.0


def test_bollinger_atr_volatility_spike_suppression():
    """Verify volatility spike (ATR / ATR_SMA > max_atr_ratio) suppresses reversion signal."""
    strat = BollingerAtrReversionStrategy(max_atr_ratio=2.2)
    df, idx = _create_reversion_test_row(
        open_=1.0780,
        high=1.0790,
        low=1.0750,
        close=1.0785,
        bb_low=1.0770,
        rsi=24.0,
        adx=16.0,
        atr=0.0030,
        atr_sma=0.0010,  # vol_ratio = 3.0 > 2.2
    )

    sig = strat.evaluate_bar(df, idx)
    assert sig.action is None
    assert sig.regime == "volatility_spike_suppressed"


def test_bollinger_atr_zero_division_safety():
    """Verify zero candle range (high == low) and zero ATR SMA do not raise ZeroDivisionError."""
    strat = BollingerAtrReversionStrategy()
    df, idx = _create_reversion_test_row(
        open_=1.0850,
        high=1.0850,
        low=1.0850,
        close=1.0850,
        atr=0.0,
        atr_sma=0.0,
        adx=0.0,
    )

    sig = strat.evaluate_bar(df, idx)
    assert sig is not None
    assert sig.action is None


# ============================================================================
# 3. Strategy Registry & Parameter Propagation Tests
# ============================================================================


def test_registry_parameter_metadata_verification():
    """Verify registry exposes new parameters for BollingerAtrReversionStrategy."""
    strategies = list_available_strategies()
    strat_meta = next((s for s in strategies if s["id"] == "bollinger_atr_reversion"), None)
    assert strat_meta is not None
    param_names = {p["name"] for p in strat_meta["parameters"]}

    assert "adx_period" in param_names
    assert "adx_trend_threshold" in param_names
    assert "min_wick_ratio" in param_names
    assert "bb_length" in param_names
    assert "rsi_period" in param_names


def test_registry_custom_parameter_instantiation():
    """Verify get_strategy_instance propagates parameters and filters unknown kwargs safely."""
    strat = get_strategy_instance(
        "bollinger_atr_reversion",
        {
            "adx_period": 10,
            "adx_trend_threshold": 30.0,
            "min_wick_ratio": 0.35,
            "bb_length": 25,
            "unknown_extra_param": 999,
        },
        another_extra=123,
    )
    assert isinstance(strat, BollingerAtrReversionStrategy)
    assert strat.adx_period == 10
    assert strat.adx_trend_threshold == 30.0
    assert strat.min_wick_ratio == 0.35
    assert strat.bb_length == 25
