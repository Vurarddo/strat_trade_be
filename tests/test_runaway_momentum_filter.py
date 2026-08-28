from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.strategies.ema_pullback_trend import EmaPullbackTrendStrategy
from strat_trade.domain.strategies.rsi_stochastic_extreme import (
    RsiStochasticExtremeStrategy,
)
from strat_trade.domain.strategies.rsi_stochastic_extreme import (
    check_runaway_momentum as rsi_check_runaway_momentum,
)
from strat_trade.domain.strategies.support_resistance_bounce import (
    SupportResistanceBounceStrategy,
)
from strat_trade.domain.strategies.support_resistance_bounce import (
    check_runaway_momentum as sr_check_runaway_momentum,
)


def _build_ohlcv_dataframe(bars: list[dict[str, float]]) -> pd.DataFrame:
    """Helper to construct a DataFrame with datetime timestamps from a list of OHLCV dicts."""
    base_t = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
    rows = []
    for i, b in enumerate(bars):
        rows.append(
            {
                "timestamp": base_t + timedelta(minutes=i),
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": float(b.get("volume", 100.0)),
            }
        )
    return pd.DataFrame(rows)


# =====================================================================
# 1. Direct Unit Tests for check_runaway_momentum Function
# =====================================================================


def test_check_runaway_momentum_bearish_3_and_4_bars():
    """Verify detection of 3 and 4 consecutive strong red candles."""
    # 4 consecutive large red candles: range = 10, body = 8 (80%), lower_wick = 1 (10%)
    waterfall_bars = [
        {"open": 100.0, "high": 101.0, "low": 90.0, "close": 91.0},
        {"open": 91.0, "high": 92.0, "low": 81.0, "close": 82.0},
        {"open": 82.0, "high": 83.0, "low": 72.0, "close": 73.0},
        {"open": 73.0, "high": 74.0, "low": 63.0, "close": 64.0},
    ]
    df = _build_ohlcv_dataframe(waterfall_bars)

    # At bar 2 (3 bars: 0, 1, 2)
    is_bearish, is_bullish = sr_check_runaway_momentum(df, idx=2, lookback_bars=3)
    assert is_bearish is True
    assert is_bullish is False

    # At bar 3 (4 bars: 0, 1, 2, 3)
    is_bearish_4, is_bullish_4 = sr_check_runaway_momentum(df, idx=3, lookback_bars=4)
    assert is_bearish_4 is True
    assert is_bullish_4 is False

    # Both strategy modules export equivalent logic
    is_b_rsi, is_bull_rsi = rsi_check_runaway_momentum(df, idx=2, lookback_bars=3)
    assert is_b_rsi is True
    assert is_bull_rsi is False


def test_check_runaway_momentum_bullish_3_and_4_bars():
    """Verify detection of 3 and 4 consecutive strong green candles."""
    # 4 consecutive large green candles: range = 10, body = 8 (80%), upper_wick = 1 (10%)
    burst_bars = [
        {"open": 64.0, "high": 75.0, "low": 63.0, "close": 74.0},
        {"open": 74.0, "high": 85.0, "low": 73.0, "close": 84.0},
        {"open": 84.0, "high": 95.0, "low": 83.0, "close": 94.0},
        {"open": 94.0, "high": 105.0, "low": 93.0, "close": 104.0},
    ]
    df = _build_ohlcv_dataframe(burst_bars)

    # At bar 2 (3 bars: 0, 1, 2)
    is_bearish, is_bullish = sr_check_runaway_momentum(df, idx=2, lookback_bars=3)
    assert is_bearish is False
    assert is_bullish is True

    # At bar 3 (4 bars: 0, 1, 2, 3)
    is_bearish_4, is_bullish_4 = sr_check_runaway_momentum(df, idx=3, lookback_bars=4)
    assert is_bearish_4 is False
    assert is_bullish_4 is True


def test_check_runaway_momentum_boundary_conditions():
    """Verify exact boundary thresholds for body ratio (50%) and opposing wick (25%)."""
    # Exact boundary candle: range = 10.0, open = 100.0, close = 95.0 (body = 5.0 -> 50%)
    # high = 102.5 (upper wick = 2.5), low = 92.5 (lower wick = 2.5 -> 25%)
    exact_boundary_bars = [
        {"open": 100.0, "high": 102.5, "low": 92.5, "close": 95.0},
        {"open": 95.0, "high": 97.5, "low": 87.5, "close": 90.0},
        {"open": 90.0, "high": 92.5, "low": 82.5, "close": 85.0},
    ]
    df_boundary = _build_ohlcv_dataframe(exact_boundary_bars)
    is_bearish, is_bullish = sr_check_runaway_momentum(df_boundary, idx=2, lookback_bars=3)
    assert is_bearish is True
    assert is_bullish is False

    # Sub-boundary body ratio: body = 4.9 (< 50% of range 10.0)
    sub_body_bars = [
        {"open": 100.0, "high": 102.5, "low": 92.5, "close": 95.1},  # body = 4.9
        {"open": 95.0, "high": 97.5, "low": 87.5, "close": 90.0},
        {"open": 90.0, "high": 92.5, "low": 82.5, "close": 85.0},
    ]
    df_sub_body = _build_ohlcv_dataframe(sub_body_bars)
    is_bearish_sub, _ = sr_check_runaway_momentum(df_sub_body, idx=2, lookback_bars=3)
    assert is_bearish_sub is False

    # Excess opposing wick: lower_wick = 2.6 (> 25% of range 10.0)
    excess_wick_bars = [
        {"open": 100.0, "high": 101.4, "low": 91.4, "close": 94.0},  # lower_wick = 2.6
        {"open": 95.0, "high": 97.5, "low": 87.5, "close": 90.0},
        {"open": 90.0, "high": 92.5, "low": 82.5, "close": 85.0},
    ]
    df_excess_wick = _build_ohlcv_dataframe(excess_wick_bars)
    is_bearish_wick, _ = sr_check_runaway_momentum(df_excess_wick, idx=2, lookback_bars=3)
    assert is_bearish_wick is False


def test_check_runaway_momentum_edge_cases():
    """Verify behavior on flat bars, zero-range bars, out-of-bounds indices."""
    # Zero range bar (high == low) and flat bar (open == close)
    edge_bars = [
        {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
        {"open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0},  # flat bar, body = 0
        {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
    ]
    df_edge = _build_ohlcv_dataframe(edge_bars)

    assert sr_check_runaway_momentum(df_edge, idx=2, lookback_bars=3) == (False, False)
    assert sr_check_runaway_momentum(df_edge, idx=-1, lookback_bars=3) == (False, False)
    assert sr_check_runaway_momentum(df_edge, idx=10, lookback_bars=3) == (False, False)
    assert sr_check_runaway_momentum(df_edge, idx=0, lookback_bars=3) == (False, False)
    assert sr_check_runaway_momentum(df_edge, idx=1, lookback_bars=3) == (False, False)
    assert sr_check_runaway_momentum(df_edge, idx=2, lookback_bars=0) == (False, False)
    assert sr_check_runaway_momentum(df_edge, idx=2, lookback_bars=-2) == (False, False)

    # Empty DataFrame
    df_empty = pd.DataFrame(columns=["open", "high", "low", "close", "timestamp", "volume"])
    assert sr_check_runaway_momentum(df_empty, idx=0, lookback_bars=3) == (False, False)


# =====================================================================
# 2. SupportResistanceBounceStrategy Runaway Suppression Tests
# =====================================================================


def _generate_sr_baseline_candles(
    n_baseline: int = 30, base_price: float = 1.0500
) -> list[dict[str, float]]:
    """Generates quiet baseline candles to establish S/R levels."""
    bars = []
    for i in range(n_baseline):
        # Range bounded between 1.0450 (support) and 1.0550 (resistance)
        mid = base_price + 0.0010 * (1 if i % 4 < 2 else -1)
        bars.append(
            {
                "open": mid,
                "high": 1.0550,
                "low": 1.0450,
                "close": mid + 0.0002 * (1 if i % 2 == 0 else -1),
            }
        )
    return bars


def test_sr_bounce_suppresses_call_on_bearish_waterfall_3_and_4_bars():
    """Verify that a 3 or 4-bar bearish waterfall suppresses CALL signals on pin-bar bounce."""
    strat = SupportResistanceBounceStrategy(swing_window=20, min_wick_ratio=0.35)

    candles = _generate_sr_baseline_candles(30, base_price=1.0500)

    # 3 strong red waterfall candles pushing price to support 1.0450
    candles.append({"open": 1.0500, "high": 1.0505, "low": 1.0480, "close": 1.0482})
    candles.append({"open": 1.0482, "high": 1.0485, "low": 1.0465, "close": 1.0467})
    candles.append({"open": 1.0467, "high": 1.0470, "low": 1.0450, "close": 1.0452})

    # Pin bar touching support (1.0450) with lower wick >= 35%
    candles.append({"open": 1.0458, "high": 1.0472, "low": 1.0445, "close": 1.0470})

    df = _build_ohlcv_dataframe(candles)
    df_prep = strat.prepare_dataframe(df)

    eval_idx = len(df_prep) - 1
    sig = strat.evaluate_bar(df_prep, eval_idx)

    # Without runaway filter, this would be a CALL. With runaway filter, CALL must be suppressed!
    assert sig.action is None
    assert sig.regime == "runaway_momentum_suppressed"
    assert sig.confidence == 0.0
    assert sig.metadata.get("suppressed_action") == "CALL"


def test_sr_bounce_suppresses_put_on_bullish_momentum_burst_3_and_4_bars():
    """Verify that a 3 or 4-bar bullish momentum burst suppresses PUT signals on rejection."""
    strat = SupportResistanceBounceStrategy(swing_window=20, min_wick_ratio=0.35)

    candles = _generate_sr_baseline_candles(30, base_price=1.0500)

    # 3 strong green burst candles pushing price to resistance 1.0550
    candles.append({"open": 1.0500, "high": 1.0520, "low": 1.0495, "close": 1.0518})
    candles.append({"open": 1.0518, "high": 1.0535, "low": 1.0515, "close": 1.0533})
    candles.append({"open": 1.0533, "high": 1.0550, "low": 1.0530, "close": 1.0548})

    # Pin bar touching resistance (1.0550) with large upper wick
    candles.append({"open": 1.0542, "high": 1.0555, "low": 1.0528, "close": 1.0530})

    df = _build_ohlcv_dataframe(candles)
    df_prep = strat.prepare_dataframe(df)

    eval_idx = len(df_prep) - 1
    sig = strat.evaluate_bar(df_prep, eval_idx)

    # PUT must be suppressed due to bullish runaway momentum!
    assert sig.action is None
    assert sig.regime == "runaway_momentum_suppressed"
    assert sig.confidence == 0.0
    assert sig.metadata.get("suppressed_action") == "PUT"


def test_sr_bounce_fires_normally_on_quiet_ranging_market():
    """Verify pin-bar bounce in a quiet ranging market fires CALL without suppression."""
    strat = SupportResistanceBounceStrategy(swing_window=20, min_wick_ratio=0.35)

    candles = _generate_sr_baseline_candles(30, base_price=1.0500)

    # Preceding 3 candles are quiet/alternating with small bodies
    candles.append({"open": 1.0470, "high": 1.0485, "low": 1.0465, "close": 1.0475})
    candles.append({"open": 1.0475, "high": 1.0480, "low": 1.0460, "close": 1.0465})
    candles.append({"open": 1.0465, "high": 1.0475, "low": 1.0458, "close": 1.0468})

    # Pin bar tests support (1.0450) and bounces
    candles.append({"open": 1.0458, "high": 1.0472, "low": 1.0445, "close": 1.0470})

    df = _build_ohlcv_dataframe(candles)
    df_prep = strat.prepare_dataframe(df)

    eval_idx = len(df_prep) - 1
    sig = strat.evaluate_bar(df_prep, eval_idx)

    assert sig.action == TradeAction.CALL
    assert sig.regime == "sr_bounce"
    assert sig.confidence >= 0.75


def test_sr_bounce_fires_put_normally_on_quiet_ranging_market():
    """Verify pin-bar rejection off resistance in a quiet market fires PUT without suppression."""
    strat = SupportResistanceBounceStrategy(swing_window=20, min_wick_ratio=0.35)

    candles = _generate_sr_baseline_candles(30, base_price=1.0500)

    # Preceding 3 candles are quiet/alternating
    candles.append({"open": 1.0530, "high": 1.0535, "low": 1.0515, "close": 1.0525})
    candles.append({"open": 1.0525, "high": 1.0540, "low": 1.0520, "close": 1.0535})
    candles.append({"open": 1.0535, "high": 1.0542, "low": 1.0528, "close": 1.0532})

    # Pin bar tests resistance (1.0550) and rejects
    candles.append({"open": 1.0542, "high": 1.0555, "low": 1.0528, "close": 1.0530})

    df = _build_ohlcv_dataframe(candles)
    df_prep = strat.prepare_dataframe(df)

    eval_idx = len(df_prep) - 1
    sig = strat.evaluate_bar(df_prep, eval_idx)

    assert sig.action == TradeAction.PUT
    assert sig.regime == "sr_bounce"
    assert sig.confidence >= 0.75


# =====================================================================
# 3. RsiStochasticExtremeStrategy Runaway Suppression Tests
# =====================================================================


def _generate_oscillator_baseline_candles(
    n_baseline: int = 30, base_price: float = 1.0500
) -> list[dict[str, float]]:
    """Generates oscillating baseline candles so RSI and Stoch start near 50."""
    bars = []
    for i in range(n_baseline):
        p = base_price + 0.0005 * (1 if i % 2 == 0 else -1)
        bars.append(
            {
                "open": p,
                "high": p + 0.0003,
                "low": p - 0.0003,
                "close": p + 0.0001 * (1 if i % 2 == 0 else -1),
            }
        )
    return bars


def test_rsi_stoch_suppresses_call_on_bearish_waterfall_3_and_4_bars():
    """Verify bearish waterfall pushing RSI/Stoch to oversold extremes suppresses CALL entries."""
    strat = RsiStochasticExtremeStrategy(
        rsi_period=14,
        rsi_oversold=25.0,
        stoch_k=14,
        stoch_d=3,
        stoch_oversold=20.0,
    )

    candles = _generate_oscillator_baseline_candles(30, base_price=1.0500)

    # Sequence of strong cascading red candles to trigger oversold extreme
    for _ in range(6):
        prev_close = candles[-1]["close"]
        candles.append(
            {
                "open": prev_close,
                "high": prev_close + 0.0002,
                "low": prev_close - 0.0020,
                "close": prev_close - 0.0018,
            }
        )

    df = _build_ohlcv_dataframe(candles)
    df_prep = strat.prepare_dataframe(df)

    eval_idx = len(df_prep) - 1
    rsi_val = df_prep.iloc[eval_idx]["rsi"]
    stoch_k_val = df_prep.iloc[eval_idx]["stoch_k"]
    assert rsi_val <= 25.0
    assert stoch_k_val <= 20.0

    sig = strat.evaluate_bar(df_prep, eval_idx)

    # CALL should be suppressed due to bearish runaway momentum!
    assert sig.action is None
    assert sig.regime == "runaway_momentum_suppressed"
    assert sig.confidence == 0.0
    assert sig.metadata.get("suppressed_action") == "CALL"


def test_rsi_stoch_suppresses_put_on_bullish_momentum_burst_3_and_4_bars():
    """Verify bullish momentum burst pushing RSI/Stoch to overbought suppresses PUT entries."""
    strat = RsiStochasticExtremeStrategy(
        rsi_period=14,
        rsi_overbought=75.0,
        stoch_k=14,
        stoch_d=3,
        stoch_overbought=80.0,
    )

    candles = _generate_oscillator_baseline_candles(30, base_price=1.0500)

    # Sequence of strong cascading green candles to trigger overbought extreme
    for _ in range(8):
        prev_close = candles[-1]["close"]
        candles.append(
            {
                "open": prev_close,
                "high": prev_close + 0.0030,
                "low": prev_close - 0.0002,
                "close": prev_close + 0.0028,
            }
        )

    df = _build_ohlcv_dataframe(candles)
    df_prep = strat.prepare_dataframe(df)

    eval_idx = len(df_prep) - 1
    rsi_val = df_prep.iloc[eval_idx]["rsi"]
    stoch_k_val = df_prep.iloc[eval_idx]["stoch_k"]
    assert rsi_val >= 75.0
    assert stoch_k_val >= 80.0

    sig = strat.evaluate_bar(df_prep, eval_idx)

    # PUT should be suppressed due to bullish runaway momentum!
    assert sig.action is None
    assert sig.regime == "runaway_momentum_suppressed"
    assert sig.confidence == 0.0
    assert sig.metadata.get("suppressed_action") == "PUT"


def test_rsi_stoch_fires_call_normally_without_runaway_momentum():
    """Verify RSI/Stoch oversold in calm choppy market does not trigger false runaway detection."""
    strat = RsiStochasticExtremeStrategy(
        rsi_period=14,
        rsi_oversold=25.0,
        stoch_k=14,
        stoch_d=3,
        stoch_oversold=20.0,
    )

    candles = _generate_oscillator_baseline_candles(30, base_price=1.0500)

    # Multi-bar gradual drift down with alternating bars, long wicks and small bodies
    for i in range(12):
        prev_close = candles[-1]["close"]
        if i % 2 == 0:
            candles.append(
                {
                    "open": prev_close,
                    "high": prev_close + 0.0010,
                    "low": prev_close - 0.0010,
                    "close": prev_close - 0.0003,  # lower wick = 0.0007 / 0.0020 = 35% > 25%
                }
            )
        else:
            candles.append(
                {
                    "open": prev_close,
                    "high": prev_close + 0.0008,
                    "low": prev_close - 0.0008,
                    "close": prev_close + 0.0001,
                }
            )

    df = _build_ohlcv_dataframe(candles)
    df_prep = strat.prepare_dataframe(df)

    eval_idx = len(df_prep) - 1

    is_bearish, _ = strat.check_runaway_momentum(df_prep, eval_idx)
    assert is_bearish is False


def test_rsi_stoch_fires_put_normally_without_runaway_momentum():
    """Verify RSI/Stoch overbought in calm market does not trigger false runaway detection."""
    strat = RsiStochasticExtremeStrategy(
        rsi_period=14,
        rsi_overbought=75.0,
        stoch_k=14,
        stoch_d=3,
        stoch_overbought=80.0,
    )

    candles = _generate_oscillator_baseline_candles(30, base_price=1.0500)

    # Multi-bar gradual drift up with alternating bars, long wicks and small bodies
    for i in range(12):
        prev_close = candles[-1]["close"]
        if i % 2 == 0:
            candles.append(
                {
                    "open": prev_close,
                    "high": prev_close + 0.0010,
                    "low": prev_close - 0.0010,
                    "close": prev_close + 0.0003,  # upper wick = 0.0007 / 0.0020 = 35% > 25%
                }
            )
        else:
            candles.append(
                {
                    "open": prev_close,
                    "high": prev_close + 0.0008,
                    "low": prev_close - 0.0008,
                    "close": prev_close - 0.0001,
                }
            )

    df = _build_ohlcv_dataframe(candles)
    df_prep = strat.prepare_dataframe(df)

    eval_idx = len(df_prep) - 1

    _, is_bullish = strat.check_runaway_momentum(df_prep, eval_idx)
    assert is_bullish is False


def test_strategy_instance_methods_accessible():
    """Verify that public and private check_runaway_momentum are callable on strategy instances."""
    sr = SupportResistanceBounceStrategy()
    rsi_strat = RsiStochasticExtremeStrategy()

    waterfall_bars = [
        {"open": 100.0, "high": 101.0, "low": 90.0, "close": 91.0},
        {"open": 91.0, "high": 92.0, "low": 81.0, "close": 82.0},
        {"open": 82.0, "high": 83.0, "low": 72.0, "close": 73.0},
    ]
    df = _build_ohlcv_dataframe(waterfall_bars)

    assert sr._check_runaway_momentum(df, 2) == (True, False)
    assert sr.check_runaway_momentum(df, 2) == (True, False)
    assert rsi_strat._check_runaway_momentum(df, 2) == (True, False)
    assert rsi_strat.check_runaway_momentum(df, 2) == (True, False)


# =====================================================================
# 4. Strategy Parameter & 3-Bar Expiration Calibration Verification
# =====================================================================


def test_sniper_alpha_strategies_calibrated_expiration_and_parameters():
    """Verify S&R Pin-Bar, RSI+Stoch, EMA Ribbon have 3-bar (180s) calibrated expiration."""
    sr = SupportResistanceBounceStrategy()
    assert sr.base_expiration_bars == 3
    assert sr.swing_window == 20
    assert sr.min_wick_ratio == 0.35
    sr_defs = {p.name: p for p in SupportResistanceBounceStrategy.get_parameter_definitions()}
    assert sr_defs["base_expiration_bars"].default_value == 3
    assert sr_defs["swing_window"].default_value == 20
    assert sr_defs["min_wick_ratio"].default_value == 0.35

    rsi_stoch = RsiStochasticExtremeStrategy()
    assert rsi_stoch.base_expiration_bars == 3
    assert rsi_stoch.rsi_period == 14
    assert rsi_stoch.rsi_oversold == 25.0
    assert rsi_stoch.rsi_overbought == 75.0
    assert rsi_stoch.stoch_oversold == 20.0
    assert rsi_stoch.stoch_overbought == 80.0
    rsi_defs = {p.name: p for p in RsiStochasticExtremeStrategy.get_parameter_definitions()}
    assert rsi_defs["base_expiration_bars"].default_value == 3
    assert rsi_defs["rsi_oversold"].default_value == 25.0
    assert rsi_defs["rsi_overbought"].default_value == 75.0

    ema_ribbon = EmaPullbackTrendStrategy()
    assert ema_ribbon.base_expiration_bars == 3
    assert ema_ribbon.ema_fast == 9
    assert ema_ribbon.ema_mid == 21
    assert ema_ribbon.ema_slow == 50
    assert ema_ribbon.adx_threshold == 25.0
    assert ema_ribbon.rsi_overbought == 65.0
    assert ema_ribbon.rsi_oversold == 35.0
    ema_defs = {p.name: p for p in EmaPullbackTrendStrategy.get_parameter_definitions()}
    assert ema_defs["base_expiration_bars"].default_value == 3
    assert ema_defs["ema_fast"].default_value == 9
    assert ema_defs["ema_mid"].default_value == 21
    assert ema_defs["adx_threshold"].default_value == 25.0
