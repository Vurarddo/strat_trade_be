from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.strategies.bollinger_atr_reversion import BollingerAtrReversionStrategy

# ============================================================================
# Helpers for Deterministic and Stochastic Test Generators
# ============================================================================


def _create_mock_df(n: int = 100) -> pd.DataFrame:
    """Generate baseline OHLCV dataframe with valid warmup space."""
    t0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC)
    data = []
    base_price = 1.1000
    for i in range(n):
        data.append(
            {
                "timestamp": t0 + timedelta(minutes=i),
                "open": base_price,
                "high": base_price + 0.0010,
                "low": base_price - 0.0010,
                "close": base_price,
                "volume": 500,
            }
        )
    return pd.DataFrame(data)


# ============================================================================
# 1. Oracle: Runaway Trend Regime Suppression (ADX >= 25, 30, 40, 50+)
# ============================================================================


@pytest.mark.parametrize("adx_val", [25.0, 25.0001, 26.0, 30.0, 40.0, 50.0, 75.0, 99.9])
def test_oracle_adx_trend_suppression_call_sweep(adx_val: float):
    """Oracle Invariant: An ideal CALL pin-bar setup MUST BE suppressed when ADX >= threshold."""
    strat = BollingerAtrReversionStrategy(adx_trend_threshold=25.0)
    df = _create_mock_df(60)
    idx = 50

    # Perfect CALL pin-bar geometry:
    # Low pierced lower band (1.0960 <= 1.0980), closed above lower band (1.0990 >= 1.0980)
    # Green candle (close 1.0990 > open 1.0982), huge lower wick (0.0022 / 0.0035 = 62.8%)
    # Deep oversold RSI (18.0 <= 30.0)
    df.loc[idx, "open"] = 1.0982
    df.loc[idx, "high"] = 1.0995
    df.loc[idx, "low"] = 1.0960
    df.loc[idx, "close"] = 1.0990
    df.loc[idx, "bb_high"] = 1.1050
    df.loc[idx, "bb_low"] = 1.0980
    df.loc[idx, "bb_pband"] = 0.05
    df.loc[idx, "rsi"] = 18.0
    df.loc[idx, "adx"] = adx_val
    df.loc[idx, "atr"] = 0.0015
    df.loc[idx, "atr_sma"] = 0.0015

    sig = strat.evaluate_bar(df, idx)
    assert sig.action is None, f"CALL trade leaked during runaway trend with ADX={adx_val}"
    assert sig.confidence == 0.0
    assert sig.regime == "trend_suppressed_adx"
    assert sig.metadata.get("adx") == round(adx_val, 2)


@pytest.mark.parametrize("adx_val", [25.0, 25.0001, 26.0, 30.0, 40.0, 50.0, 75.0, 99.9])
def test_oracle_adx_trend_suppression_put_sweep(adx_val: float):
    """Oracle Invariant: An ideal PUT pin-bar setup MUST BE suppressed when ADX >= threshold."""
    strat = BollingerAtrReversionStrategy(adx_trend_threshold=25.0)
    df = _create_mock_df(60)
    idx = 50

    # Perfect PUT pin-bar geometry:
    # High pierced upper band (1.1040 >= 1.1020), closed below upper band (1.1010 <= 1.1020)
    # Red candle (close 1.1010 < open 1.1018), huge upper wick (0.0022 / 0.0035 = 62.8%)
    # Deep overbought RSI (82.0 >= 70.0)
    df.loc[idx, "open"] = 1.1018
    df.loc[idx, "high"] = 1.1040
    df.loc[idx, "low"] = 1.1005
    df.loc[idx, "close"] = 1.1010
    df.loc[idx, "bb_high"] = 1.1020
    df.loc[idx, "bb_low"] = 1.0950
    df.loc[idx, "bb_pband"] = 0.95
    df.loc[idx, "rsi"] = 82.0
    df.loc[idx, "adx"] = adx_val
    df.loc[idx, "atr"] = 0.0015
    df.loc[idx, "atr_sma"] = 0.0015

    sig = strat.evaluate_bar(df, idx)
    assert sig.action is None, f"PUT trade leaked during runaway trend with ADX={adx_val}"
    assert sig.confidence == 0.0
    assert sig.regime == "trend_suppressed_adx"
    assert sig.metadata.get("adx") == round(adx_val, 2)


def test_oracle_adx_boundary_precision():
    """Verify sharp boundary transition around adx_trend_threshold."""
    strat = BollingerAtrReversionStrategy(adx_trend_threshold=25.0, min_wick_ratio=0.25)
    df = _create_mock_df(60)
    idx = 50

    df.loc[idx, "open"] = 1.0980
    df.loc[idx, "high"] = 1.0995
    df.loc[idx, "low"] = 1.0960
    df.loc[idx, "close"] = 1.0990
    df.loc[idx, "bb_high"] = 1.1050
    df.loc[idx, "bb_low"] = 1.0980
    df.loc[idx, "rsi"] = 22.0
    df.loc[idx, "atr"] = 0.0015
    df.loc[idx, "atr_sma"] = 0.0015

    # Case 1: Just below threshold (24.99) -> Trade fires
    df.loc[idx, "adx"] = 24.99
    sig_allowed = strat.evaluate_bar(df, idx)
    assert sig_allowed.action == TradeAction.CALL
    assert sig_allowed.regime == "mean_reversion"

    # Case 2: Exact threshold (25.00) -> Suppressed
    df.loc[idx, "adx"] = 25.00
    sig_exact = strat.evaluate_bar(df, idx)
    assert sig_exact.action is None
    assert sig_exact.regime == "trend_suppressed_adx"

    # Case 3: Just above threshold (25.01) -> Suppressed
    df.loc[idx, "adx"] = 25.01
    sig_above = strat.evaluate_bar(df, idx)
    assert sig_above.action is None
    assert sig_above.regime == "trend_suppressed_adx"


# ============================================================================
# 2. Oracle: Falling Knife 100% Rejection Generator
# ============================================================================


def test_oracle_falling_knife_100_percent_rejection_fuzzer():
    """Adversarial Generator: Fuzz 500 falling knife candles with 0 or minimal wick.

    Candles closing outside bb_low must be rejected.
    """
    strat = BollingerAtrReversionStrategy()
    rng = random.Random(42)
    df = _create_mock_df(60)
    idx = 50

    bb_low = 1.0800
    df.loc[idx, "bb_high"] = 1.0900
    df.loc[idx, "bb_low"] = bb_low
    df.loc[idx, "rsi"] = 15.0  # Ultra oversold
    df.loc[idx, "adx"] = 18.0  # Low ADX (so ADX filter alone does not catch it)
    df.loc[idx, "atr"] = 0.0010
    df.loc[idx, "atr_sma"] = 0.0010

    for test_i in range(500):
        # Scenario A: Full Marubozu dump outside band (open > close, close <= low, close < bb_low)
        open_ = 1.0820 + rng.uniform(0.0001, 0.0030)
        close = bb_low - rng.uniform(0.0001, 0.0050)
        high = open_ + rng.uniform(0.0, 0.0002)
        low = close - rng.uniform(0.0, 0.0002)  # tiny or zero wick

        df.loc[idx, "open"] = open_
        df.loc[idx, "high"] = high
        df.loc[idx, "low"] = low
        df.loc[idx, "close"] = close

        sig = strat.evaluate_bar(df, idx)
        assert sig.action is None, (
            f"Falling knife iteration {test_i} triggered false CALL! "
            f"open={open_}, high={high}, low={low}, close={close}, bb_low={bb_low}"
        )


def test_oracle_falling_knife_bullish_close_outside_band_rejected():
    """Adversarial: If close < bb_low it MUST BE rejected even if close > open."""
    strat = BollingerAtrReversionStrategy()
    df = _create_mock_df(60)
    idx = 50

    # Candle bounced slightly from extreme bottom, but remains deep below lower band
    # open 1.0720, close 1.0740 (green candle!), low 1.0700, high 1.0745, bb_low 1.0780
    df.loc[idx, "open"] = 1.0720
    df.loc[idx, "high"] = 1.0745
    df.loc[idx, "low"] = 1.0700
    df.loc[idx, "close"] = 1.0740  # Still < 1.0780
    df.loc[idx, "bb_high"] = 1.0900
    df.loc[idx, "bb_low"] = 1.0780
    df.loc[idx, "rsi"] = 20.0
    df.loc[idx, "adx"] = 15.0
    df.loc[idx, "atr"] = 0.0010
    df.loc[idx, "atr_sma"] = 0.0010

    sig = strat.evaluate_bar(df, idx)
    assert sig.action is None, "Green candle closing below lower band must not fire CALL"


# ============================================================================
# 3. Oracle: Skyrocketing Breakout 100% Rejection Generator
# ============================================================================


def test_oracle_skyrocketing_pump_100_percent_rejection_fuzzer():
    """Adversarial Generator: Fuzz 500 skyrocketing pump candles.

    Candles with 0 or minimal wick closing outside bb_high must be rejected.
    """
    strat = BollingerAtrReversionStrategy()
    rng = random.Random(99)
    df = _create_mock_df(60)
    idx = 50

    bb_high = 1.1000
    df.loc[idx, "bb_high"] = bb_high
    df.loc[idx, "bb_low"] = 1.0900
    df.loc[idx, "rsi"] = 85.0  # Ultra overbought
    df.loc[idx, "adx"] = 18.0  # Low ADX
    df.loc[idx, "atr"] = 0.0010
    df.loc[idx, "atr_sma"] = 0.0010

    for test_i in range(500):
        # Scenario: Huge green candle exploding above upper band
        open_ = 1.0980 - rng.uniform(0.0001, 0.0030)
        close = bb_high + rng.uniform(0.0001, 0.0050)
        low = open_ - rng.uniform(0.0, 0.0002)
        high = close + rng.uniform(0.0, 0.0002)

        df.loc[idx, "open"] = open_
        df.loc[idx, "high"] = high
        df.loc[idx, "low"] = low
        df.loc[idx, "close"] = close

        sig = strat.evaluate_bar(df, idx)
        assert sig.action is None, (
            f"Skyrocketing pump iteration {test_i} triggered false PUT! "
            f"open={open_}, high={high}, low={low}, close={close}, bb_high={bb_high}"
        )


def test_oracle_skyrocketing_bearish_close_outside_band_rejected():
    """Adversarial: Even if candle is red (close < open), if close > bb_high it MUST BE rejected."""
    strat = BollingerAtrReversionStrategy()
    df = _create_mock_df(60)
    idx = 50

    # Candle pulled back slightly from high, but remains far above upper band
    # open 1.1080, close 1.1060 (red candle!), high 1.1100, low 1.1055, bb_high 1.1000
    df.loc[idx, "open"] = 1.1080
    df.loc[idx, "high"] = 1.1100
    df.loc[idx, "low"] = 1.1055
    df.loc[idx, "close"] = 1.1060  # Still > 1.1000
    df.loc[idx, "bb_high"] = 1.1000
    df.loc[idx, "bb_low"] = 1.0900
    df.loc[idx, "rsi"] = 80.0
    df.loc[idx, "adx"] = 15.0
    df.loc[idx, "atr"] = 0.0010
    df.loc[idx, "atr_sma"] = 0.0010

    sig = strat.evaluate_bar(df, idx)
    assert sig.action is None, "Red candle closing above upper band must not fire PUT"


# ============================================================================
# 4. Oracle: Valid Pin-Bar Rejection & Confidence Matrix
# ============================================================================


@pytest.mark.parametrize(
    ("wick_ratio", "rsi_val", "expected_action", "expected_conf"),
    [
        # Standard CALL pin-bar (wick in [0.25, 0.39], RSI in [25.1, 30.0]) -> conf 0.70
        (0.30, 28.0, TradeAction.CALL, 0.70),
        # Strong CALL pin-bar (wick >= 0.40, RSI in [25.1, 30.0]) -> conf 0.85
        (0.50, 28.0, TradeAction.CALL, 0.85),
        # Deep RSI standard CALL (wick in [0.25, 0.39], RSI <= 25.0) -> conf 0.80
        (0.30, 22.0, TradeAction.CALL, 0.80),
        # Strong wick + Deep RSI CALL -> conf 0.95 (max cap)
        (0.60, 20.0, TradeAction.CALL, 0.95),
    ],
)
def test_oracle_call_pinbar_confidence_matrix(
    wick_ratio: float, rsi_val: float, expected_action: TradeAction, expected_conf: float
):
    strat = BollingerAtrReversionStrategy(min_wick_ratio=0.25)
    df = _create_mock_df(60)
    idx = 50

    bb_low = 1.0770
    candle_range = 0.0060
    high = 1.0810
    low = 1.0750  # pierced bb_low (1.0750 <= 1.0770)
    lower_wick = wick_ratio * candle_range
    open_ = low + lower_wick
    # Close inside band (>= bb_low) and bullish (close > open_)
    close = max(open_ + 0.0005, bb_low + 0.0005)

    df.loc[idx, "open"] = open_
    df.loc[idx, "high"] = high
    df.loc[idx, "low"] = low
    df.loc[idx, "close"] = close
    df.loc[idx, "bb_high"] = 1.0850
    df.loc[idx, "bb_low"] = bb_low
    df.loc[idx, "rsi"] = rsi_val
    df.loc[idx, "adx"] = 16.0
    df.loc[idx, "atr"] = 0.0010
    df.loc[idx, "atr_sma"] = 0.0010

    sig = strat.evaluate_bar(df, idx)
    assert sig.action == expected_action
    assert math.isclose(sig.confidence, expected_conf, abs_tol=1e-3)
    assert sig.regime == "mean_reversion"


@pytest.mark.parametrize(
    ("wick_ratio", "rsi_val", "expected_action", "expected_conf"),
    [
        # Standard PUT pin-bar (wick in [0.25, 0.39], RSI in [70.0, 74.9]) -> conf 0.70
        (0.30, 72.0, TradeAction.PUT, 0.70),
        # Strong PUT pin-bar (wick >= 0.40, RSI in [70.0, 74.9]) -> conf 0.85
        (0.50, 72.0, TradeAction.PUT, 0.85),
        # Deep RSI standard PUT (wick in [0.25, 0.39], RSI >= 75.0) -> conf 0.80
        (0.30, 78.0, TradeAction.PUT, 0.80),
        # Strong wick + Deep RSI PUT -> conf 0.95 (max cap)
        (0.60, 80.0, TradeAction.PUT, 0.95),
    ],
)
def test_oracle_put_pinbar_confidence_matrix(
    wick_ratio: float, rsi_val: float, expected_action: TradeAction, expected_conf: float
):
    strat = BollingerAtrReversionStrategy(min_wick_ratio=0.25)
    df = _create_mock_df(60)
    idx = 50

    bb_high = 1.0850
    candle_range = 0.0040
    low = 1.0820
    high = low + candle_range  # 1.0860 (pierced bb_high 1.0850)
    # upper_wick = (high - max(open, close)) = wick_ratio * candle_range
    upper_wick = wick_ratio * candle_range
    open_ = high - upper_wick
    close = open_ - 0.0005  # Red candle closing below open and below bb_high

    df.loc[idx, "open"] = open_
    df.loc[idx, "high"] = high
    df.loc[idx, "low"] = low
    df.loc[idx, "close"] = close
    df.loc[idx, "bb_high"] = bb_high
    df.loc[idx, "bb_low"] = 1.0750
    df.loc[idx, "rsi"] = rsi_val
    df.loc[idx, "adx"] = 16.0
    df.loc[idx, "atr"] = 0.0010
    df.loc[idx, "atr_sma"] = 0.0010

    sig = strat.evaluate_bar(df, idx)
    assert sig.action == expected_action
    assert math.isclose(sig.confidence, expected_conf, abs_tol=1e-3)
    assert sig.regime == "mean_reversion"


# ============================================================================
# 5. Oracle: Degenerate Zero-Range & Pathological Bars
# ============================================================================


def test_oracle_degenerate_zero_range_candle():
    """Oracle Invariant: high == low == open == close must NEVER throw ZeroDivisionError."""
    strat = BollingerAtrReversionStrategy()
    df = _create_mock_df(60)
    idx = 50

    # Flat candle
    df.loc[idx, "open"] = 1.0850
    df.loc[idx, "high"] = 1.0850
    df.loc[idx, "low"] = 1.0850
    df.loc[idx, "close"] = 1.0850
    df.loc[idx, "bb_high"] = 1.0850
    df.loc[idx, "bb_low"] = 1.0850
    df.loc[idx, "rsi"] = 50.0
    df.loc[idx, "adx"] = 0.0
    df.loc[idx, "atr"] = 0.0
    df.loc[idx, "atr_sma"] = 0.0

    sig = strat.evaluate_bar(df, idx)
    assert sig is not None
    assert sig.action is None
    assert sig.confidence == 0.0


def test_oracle_degenerate_nan_and_missing_indicators():
    """Oracle Invariant: NaN in any indicator must gracefully default and not throw exceptions."""
    strat = BollingerAtrReversionStrategy()
    df = _create_mock_df(60)
    idx = 50

    df.loc[idx, "bb_high"] = np.nan
    df.loc[idx, "bb_low"] = np.nan
    df.loc[idx, "rsi"] = np.nan
    df.loc[idx, "adx"] = np.nan
    df.loc[idx, "atr"] = np.nan
    df.loc[idx, "atr_sma"] = np.nan

    sig = strat.evaluate_bar(df, idx)
    assert sig is not None
    assert sig.action is None
    assert sig.confidence == 0.0


def test_oracle_boundary_index_safety():
    """Oracle Invariant: Out of bound indices return warmup status safely."""
    strat = BollingerAtrReversionStrategy()
    df = _create_mock_df(50)

    # Warmup index
    sig_early = strat.evaluate_bar(df, 5)
    assert sig_early.regime == "warming_up"
    assert sig_early.action is None

    # Length boundary
    sig_end = strat.evaluate_bar(df, len(df))
    assert sig_end.regime == "warming_up"
    assert sig_end.action is None

    # Beyond length
    sig_oob = strat.evaluate_bar(df, len(df) + 100)
    assert sig_oob.regime == "warming_up"
    assert sig_oob.action is None


# ============================================================================
# 6. End-to-End Synthetic Market Simulator (Multi-Regime Fuzzer)
# ============================================================================


def test_oracle_synthetic_multi_regime_stress_simulation():
    """Run a 2,000-bar multi-regime simulation through prepare_dataframe and evaluate_bar."""
    np.random.seed(1337)
    t0 = datetime(2026, 8, 20, 0, 0, 0, tzinfo=UTC)

    n_bars = 2000

    # Generate synthetic walk with regimes:
    # 0..400: Ranging / Mean-reverting channel
    # 400..800: Strong Bull Trend
    # 800..1200: Flash Volatility Spike & Shock
    # 1200..1600: Strong Bear Trend (Waterfall)
    # 1600..2000: Flat / Zero Volatility Consolidation

    candles = []
    current_p = 1.1000

    for i in range(n_bars):
        if i < 400:
            # Mean reverting around 1.1000
            drift = -0.1 * (current_p - 1.1000)
            noise = np.random.normal(0, 0.0003)
            delta = drift + noise
            high_ext = abs(np.random.normal(0.0004, 0.0002))
            low_ext = abs(np.random.normal(0.0004, 0.0002))
        elif i < 800:
            # Strong Bull Trend
            drift = 0.0004
            noise = np.random.normal(0, 0.0002)
            delta = drift + noise
            high_ext = abs(np.random.normal(0.0005, 0.0002))
            low_ext = abs(np.random.normal(0.0001, 0.0001))
        elif i < 1200:
            # High volatility shock
            delta = np.random.normal(0, 0.0020)
            high_ext = abs(np.random.normal(0.0025, 0.0010))
            low_ext = abs(np.random.normal(0.0025, 0.0010))
        elif i < 1600:
            # Strong Bear Trend
            drift = -0.0004
            noise = np.random.normal(0, 0.0002)
            delta = drift + noise
            high_ext = abs(np.random.normal(0.0001, 0.0001))
            low_ext = abs(np.random.normal(0.0005, 0.0002))
        else:
            # Flat consolidation
            delta = np.random.normal(0, 0.00001)
            high_ext = 0.00002
            low_ext = 0.00002

        open_p = current_p
        close_p = open_p + delta
        high_p = max(open_p, close_p) + high_ext
        low_p = min(open_p, close_p) - low_ext
        current_p = close_p

        candles.append(
            {
                "timestamp": t0 + timedelta(minutes=i),
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": 1000,
            }
        )

    df_sim = pd.DataFrame(candles)
    strat = BollingerAtrReversionStrategy(
        bb_length=20,
        bb_std=2.0,
        rsi_period=14,
        adx_period=14,
        adx_trend_threshold=25.0,
        min_wick_ratio=0.25,
    )

    df_prep = strat.prepare_dataframe(df_sim)
    assert "adx" in df_prep.columns
    assert "bb_high" in df_prep.columns
    assert "bb_low" in df_prep.columns
    assert "rsi" in df_prep.columns
    assert "atr_sma" in df_prep.columns

    signals_count = 0
    suppressed_trend_count = 0
    suppressed_vol_count = 0

    for i in range(len(df_prep)):
        sig = strat.evaluate_bar(df_prep, i)
        assert sig is not None

        if sig.regime == "trend_suppressed_adx":
            suppressed_trend_count += 1
            assert sig.action is None
            assert sig.confidence == 0.0
            row_adx = df_prep.loc[i, "adx"]
            assert row_adx >= 25.0 or np.isnan(row_adx)

        if sig.regime == "volatility_spike_suppressed":
            suppressed_vol_count += 1
            assert sig.action is None
            assert sig.confidence == 0.0

        if sig.action is not None:
            signals_count += 1
            # Verify that every fired trade strictly satisfies all 5 invariants:
            row = df_prep.iloc[i]
            row_adx = float(row["adx"])
            row_rsi = float(row["rsi"])
            row_open = float(row["open"])
            row_close = float(row["close"])
            row_high = float(row["high"])
            row_low = float(row["low"])
            row_bb_h = float(row["bb_high"])
            row_bb_l = float(row["bb_low"])
            candle_rng = row_high - row_low

            assert row_adx < 25.0, f"Trade fired with ADX={row_adx} >= 25.0 at bar {i}"

            if sig.action == TradeAction.CALL:
                lower_wick = min(row_open, row_close) - row_low
                lower_wick_ratio = lower_wick / candle_rng if candle_rng > 0 else 0
                assert row_low <= row_bb_l, "CALL fired without piercing lower band"
                assert row_close >= row_bb_l, "CALL fired on candle closing below lower band"
                assert row_close > row_open, "CALL fired on non-bullish candle"
                assert lower_wick_ratio >= 0.25, (
                    f"CALL fired with insufficient lower wick ratio {lower_wick_ratio}"
                )
                assert row_rsi <= 30.0, f"CALL fired with non-oversold RSI {row_rsi}"

            elif sig.action == TradeAction.PUT:
                upper_wick = row_high - max(row_open, row_close)
                upper_wick_ratio = upper_wick / candle_rng if candle_rng > 0 else 0
                assert row_high >= row_bb_h, "PUT fired without piercing upper band"
                assert row_close <= row_bb_h, "PUT fired on candle closing above upper band"
                assert row_close < row_open, "PUT fired on non-bearish candle"
                assert upper_wick_ratio >= 0.25, (
                    f"PUT fired with insufficient upper wick ratio {upper_wick_ratio}"
                )
                assert row_rsi >= 70.0, f"PUT fired with non-overbought RSI {row_rsi}"

    assert suppressed_trend_count > 0, "ADX filter never triggered in 2000 bars"
    assert suppressed_vol_count > 0, "Volatility filter never triggered in 2000 bars"


# ============================================================================
# 7. Oracle: Adaptive Expiration Bars Logic
# ============================================================================


def test_oracle_adaptive_expiration_enabled_and_disabled():
    """Verify adaptive expiration adjusts bar duration according to volatility ratio."""
    strat_disabled = BollingerAtrReversionStrategy(
        base_expiration_bars=3, adaptive_expiration_enabled=False
    )
    strat_enabled = BollingerAtrReversionStrategy(
        base_expiration_bars=3, adaptive_expiration_enabled=True
    )

    df = _create_mock_df(60)
    idx = 50

    # Base valid CALL candle
    df.loc[idx, "open"] = 1.0980
    df.loc[idx, "high"] = 1.0995
    df.loc[idx, "low"] = 1.0960
    df.loc[idx, "close"] = 1.0990
    df.loc[idx, "bb_high"] = 1.1050
    df.loc[idx, "bb_low"] = 1.0980
    df.loc[idx, "rsi"] = 22.0
    df.loc[idx, "adx"] = 15.0

    # Case A: Low volatility (vol_ratio = 0.5 < 0.8)
    df.loc[idx, "atr"] = 0.0005
    df.loc[idx, "atr_sma"] = 0.0010
    sig_dis_a = strat_disabled.evaluate_bar(df, idx)
    sig_en_a = strat_enabled.evaluate_bar(df, idx)
    assert sig_dis_a.action == TradeAction.CALL and sig_dis_a.expiration_bars == 3
    assert sig_en_a.action == TradeAction.CALL and sig_en_a.expiration_bars == 4  # 3 + 1

    # Case B: High volatility (vol_ratio = 1.5 > 1.3, but <= 2.2)
    df.loc[idx, "atr"] = 0.0015
    df.loc[idx, "atr_sma"] = 0.0010
    sig_dis_b = strat_disabled.evaluate_bar(df, idx)
    sig_en_b = strat_enabled.evaluate_bar(df, idx)
    assert sig_dis_b.action == TradeAction.CALL and sig_dis_b.expiration_bars == 3
    assert sig_en_b.action == TradeAction.CALL and sig_en_b.expiration_bars == 2  # 3 - 1

    # Case C: Normal volatility (vol_ratio = 1.0)
    df.loc[idx, "atr"] = 0.0010
    df.loc[idx, "atr_sma"] = 0.0010
    sig_en_c = strat_enabled.evaluate_bar(df, idx)
    assert sig_en_c.action == TradeAction.CALL and sig_en_c.expiration_bars == 3


# ============================================================================
# 8. Oracle: Short DataFrames and Constant Series Preparation
# ============================================================================


def test_oracle_prepare_dataframe_undersized_series():
    """Verify DataFrames shorter than lookback window are returned gracefully."""
    strat = BollingerAtrReversionStrategy()
    df_short = _create_mock_df(15)  # Shorter than max(20, 14) + 10 = 30
    df_result = strat.prepare_dataframe(df_short)
    assert len(df_result) == 15
    assert "bb_high" not in df_result.columns or df_result["bb_high"].isna().all()


def test_oracle_prepare_dataframe_constant_price_series():
    """Verify flat prices (zero variance) in prepare_dataframe do not crash."""
    strat = BollingerAtrReversionStrategy()
    df_flat = pd.DataFrame(
        {
            "open": [1.1000] * 50,
            "high": [1.1000] * 50,
            "low": [1.1000] * 50,
            "close": [1.1000] * 50,
            "volume": [100] * 50,
        }
    )
    df_result = strat.prepare_dataframe(df_flat)
    assert "bb_high" in df_result.columns
    assert "adx" in df_result.columns
    sig = strat.evaluate_bar(df_result, 40)
    assert sig is not None
    assert sig.action is None


# ============================================================================
# 9. Oracle: Stochastic 1,000-Iteration Bar Fuzzer & Invariant Verifier
# ============================================================================


def test_oracle_fuzzing_1000_random_bars_integrity():
    """Adversarial Fuzzer: 1,000 randomized bars to verify invariant satisfaction."""
    strat = BollingerAtrReversionStrategy(
        bb_length=20,
        bb_std=2.0,
        rsi_period=14,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        adx_trend_threshold=25.0,
        min_wick_ratio=0.25,
    )
    rng = random.Random(777)
    df = _create_mock_df(60)
    idx = 50

    for i in range(1000):
        # Generate random OHLCV values
        base_price = rng.uniform(1.0500, 1.1500)
        p1 = base_price + rng.uniform(-0.0050, 0.0050)
        p2 = base_price + rng.uniform(-0.0050, 0.0050)
        p3 = base_price + rng.uniform(-0.0050, 0.0050)
        p4 = base_price + rng.uniform(-0.0050, 0.0050)

        high = max(p1, p2, p3, p4)
        low = min(p1, p2, p3, p4)
        open_ = p1
        close = p4

        bb_mid = base_price + rng.uniform(-0.0020, 0.0020)
        bb_width = rng.uniform(0.0010, 0.0100)
        bb_high = bb_mid + bb_width
        bb_low = bb_mid - bb_width

        rsi = rng.uniform(0.0, 100.0)
        adx = rng.uniform(0.0, 100.0)
        atr = rng.uniform(0.0, 0.0100)
        atr_sma = rng.uniform(0.0001, 0.0100)

        df.loc[idx, "open"] = open_
        df.loc[idx, "high"] = high
        df.loc[idx, "low"] = low
        df.loc[idx, "close"] = close
        df.loc[idx, "bb_high"] = bb_high
        df.loc[idx, "bb_low"] = bb_low
        df.loc[idx, "rsi"] = rsi
        df.loc[idx, "adx"] = adx
        df.loc[idx, "atr"] = atr
        df.loc[idx, "atr_sma"] = atr_sma

        sig = strat.evaluate_bar(df, idx)
        assert sig is not None, f"evaluate_bar returned None at iteration {i}"
        assert sig.confidence >= 0.0 and sig.confidence <= 0.95
        assert sig.expiration_bars >= 1

        candle_range = high - low

        if sig.action == TradeAction.CALL:
            assert adx < 25.0, f"CALL leaked with ADX={adx} at iteration {i}"
            assert atr / atr_sma <= 2.2, (
                f"CALL leaked with vol_ratio={atr / atr_sma} at iteration {i}"
            )
            assert low <= bb_low, f"CALL leaked without touching bb_low at iteration {i}"
            assert close >= bb_low, f"CALL leaked closing below bb_low at iteration {i}"
            assert close > open_, f"CALL leaked on red candle at iteration {i}"
            lower_wick = (min(open_, close) - low) if candle_range > 0 else 0.0
            wick_ratio = lower_wick / candle_range if candle_range > 0 else 0.0
            assert wick_ratio >= 0.25, f"CALL leaked with wick_ratio={wick_ratio} at iteration {i}"
            assert rsi <= 30.0, f"CALL leaked with rsi={rsi} at iteration {i}"

        elif sig.action == TradeAction.PUT:
            assert adx < 25.0, f"PUT leaked with ADX={adx} at iteration {i}"
            assert atr / atr_sma <= 2.2, (
                f"PUT leaked with vol_ratio={atr / atr_sma} at iteration {i}"
            )
            assert high >= bb_high, f"PUT leaked without touching bb_high at iteration {i}"
            assert close <= bb_high, f"PUT leaked closing above bb_high at iteration {i}"
            assert close < open_, f"PUT leaked on green candle at iteration {i}"
            upper_wick = (high - max(open_, close)) if candle_range > 0 else 0.0
            wick_ratio = upper_wick / candle_range if candle_range > 0 else 0.0
            assert wick_ratio >= 0.25, f"PUT leaked with wick_ratio={wick_ratio} at iteration {i}"
            assert rsi >= 70.0, f"PUT leaked with rsi={rsi} at iteration {i}"
