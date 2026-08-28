from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

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


def _make_df(bars: list[dict[str, float]]) -> pd.DataFrame:
    """Construct an OHLCV DataFrame with timestamps from a list of dicts."""
    base_t = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
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
# A. ZERO-RANGE, MICRO-RANGE, AND EPSILON NUMERICAL STABILITY TESTS
# =====================================================================


def test_zero_range_candles_no_division_by_zero():
    """Verify check_runaway_momentum handles zero-range candles without DivisionByZero or NaN."""
    flat_bars = [
        {"open": 1.0500, "high": 1.0500, "low": 1.0500, "close": 1.0500},
        {"open": 1.0500, "high": 1.0500, "low": 1.0500, "close": 1.0500},
        {"open": 1.0500, "high": 1.0500, "low": 1.0500, "close": 1.0500},
        {"open": 1.0500, "high": 1.0500, "low": 1.0500, "close": 1.0500},
    ]
    df = _make_df(flat_bars)
    for idx in range(len(df)):
        res_sr = sr_check_runaway_momentum(df, idx)
        res_rsi = rsi_check_runaway_momentum(df, idx)
        assert res_sr == (False, False)
        assert res_rsi == (False, False)


@pytest.mark.parametrize(
    "micro_rng",
    [1e-15, 1e-12, 1e-10, 1e-9, 1e-8, 1e-7, 1e-6],
)
def test_micro_range_candles_floating_point_stability(micro_rng: float):
    """Verify micro-range candles near and below 1e-9 float epsilon do not raise or crash."""
    base = 1.0500
    bars = [
        {
            "open": base,
            "high": base + micro_rng,
            "low": base,
            "close": base + micro_rng * 0.8,
        },
        {
            "open": base + micro_rng * 0.8,
            "high": base + micro_rng * 1.8,
            "low": base + micro_rng * 0.8,
            "close": base + micro_rng * 1.6,
        },
        {
            "open": base + micro_rng * 1.6,
            "high": base + micro_rng * 2.6,
            "low": base + micro_rng * 1.6,
            "close": base + micro_rng * 2.4,
        },
    ]
    df = _make_df(bars)
    res = sr_check_runaway_momentum(df, 2, lookback_bars=3)
    assert isinstance(res, tuple)
    assert len(res) == 2
    assert isinstance(res[0], bool)
    assert isinstance(res[1], bool)
    if micro_rng <= 1e-9:
        # rng <= 1e-9 triggers early return False in _is_bullish / _is_bearish
        assert res == (False, False)
    else:
        # Above 1e-9, 80% body and 20% upper wick qualifies as bullish runaway
        assert res == (False, True)


# =====================================================================
# B. BOUNDARY TESTS FOR BODY RATIO (0.49 vs 0.50 vs 0.51) AND OPPOSING WICK (0.24 vs 0.25 vs 0.26)
# =====================================================================


@pytest.mark.parametrize(
    ("body_pct", "expected_is_bearish"),
    [
        (0.4900, False),
        (0.4999, False),
        (0.5000, True),
        (0.5001, True),
        (0.5100, True),
    ],
)
def test_bearish_body_ratio_boundaries(body_pct: float, expected_is_bearish: bool):
    """Test precise threshold of min_body_ratio=0.50 for bearish runaway candles."""
    range_val = 100.0
    lower_wick = 10.0
    close_val = lower_wick
    open_val = close_val + (range_val * body_pct)
    high_val = range_val
    low_val = 0.0

    bars = [
        {"open": open_val, "high": high_val, "low": low_val, "close": close_val} for _ in range(3)
    ]
    df = _make_df(bars)
    is_bearish, is_bullish = sr_check_runaway_momentum(
        df, 2, lookback_bars=3, min_body_ratio=0.50, max_opposing_wick_ratio=0.25
    )
    assert is_bearish is expected_is_bearish
    assert is_bullish is False


@pytest.mark.parametrize(
    ("wick_pct", "expected_is_bearish"),
    [
        (0.2400, True),
        (0.2499, True),
        (0.2500, True),
        (0.2501, False),
        (0.2600, False),
    ],
)
def test_bearish_opposing_wick_ratio_boundaries(wick_pct: float, expected_is_bearish: bool):
    """Test precise threshold of max_opposing_wick_ratio=0.25 for bearish runaway candles."""
    range_val = 100.0
    close_val = range_val * wick_pct
    open_val = close_val + 60.0
    high_val = 100.0
    low_val = 0.0

    bars = [
        {"open": open_val, "high": high_val, "low": low_val, "close": close_val} for _ in range(3)
    ]
    df = _make_df(bars)
    is_bearish, is_bullish = sr_check_runaway_momentum(
        df, 2, lookback_bars=3, min_body_ratio=0.50, max_opposing_wick_ratio=0.25
    )
    assert is_bearish is expected_is_bearish
    assert is_bullish is False


@pytest.mark.parametrize(
    ("body_pct", "expected_is_bullish"),
    [
        (0.4900, False),
        (0.4999, False),
        (0.5000, True),
        (0.5001, True),
        (0.5100, True),
    ],
)
def test_bullish_body_ratio_boundaries(body_pct: float, expected_is_bullish: bool):
    """Test precise threshold of min_body_ratio=0.50 for bullish runaway candles."""
    range_val = 100.0
    high_val = 100.0
    low_val = 0.0
    close_val = 90.0
    open_val = close_val - (range_val * body_pct)

    bars = [
        {"open": open_val, "high": high_val, "low": low_val, "close": close_val} for _ in range(3)
    ]
    df = _make_df(bars)
    is_bearish, is_bullish = sr_check_runaway_momentum(
        df, 2, lookback_bars=3, min_body_ratio=0.50, max_opposing_wick_ratio=0.25
    )
    assert is_bullish is expected_is_bullish
    assert is_bearish is False


@pytest.mark.parametrize(
    ("wick_pct", "expected_is_bullish"),
    [
        (0.2400, True),
        (0.2499, True),
        (0.2500, True),
        (0.2501, False),
        (0.2600, False),
    ],
)
def test_bullish_opposing_wick_ratio_boundaries(wick_pct: float, expected_is_bullish: bool):
    """Test precise threshold of max_opposing_wick_ratio=0.25 for bullish runaway candles."""
    range_val = 100.0
    high_val = 100.0
    low_val = 0.0
    close_val = 100.0 - (range_val * wick_pct)
    open_val = close_val - 60.0

    bars = [
        {"open": open_val, "high": high_val, "low": low_val, "close": close_val} for _ in range(3)
    ]
    df = _make_df(bars)
    is_bearish, is_bullish = sr_check_runaway_momentum(
        df, 2, lookback_bars=3, min_body_ratio=0.50, max_opposing_wick_ratio=0.25
    )
    assert is_bullish is expected_is_bullish
    assert is_bearish is False


# =====================================================================
# C. ALTERNATING MULTI-BAR SEQUENCES (2-BAR vs 3-BAR vs 4-BAR vs BROKEN RUNS)
# =====================================================================


def test_alternating_and_broken_sequences():
    """Verify that alternating colors and broken runs never trigger false runaway momentum."""
    bars_alt = [
        {"open": 100.0, "high": 101.0, "low": 90.0, "close": 91.0},  # Bearish
        {"open": 91.0, "high": 100.0, "low": 90.0, "close": 99.0},  # Bullish
        {"open": 99.0, "high": 100.0, "low": 89.0, "close": 90.0},  # Bearish
        {"open": 90.0, "high": 99.0, "low": 89.0, "close": 98.0},  # Bullish
        {"open": 98.0, "high": 99.0, "low": 88.0, "close": 89.0},  # Bearish
    ]
    df_alt = _make_df(bars_alt)
    for idx in range(len(df_alt)):
        assert sr_check_runaway_momentum(df_alt, idx, lookback_bars=3) == (False, False)

    # Pattern: 2 Red, 1 Green, 2 Red (broken streak)
    bars_broken = [
        {"open": 100.0, "high": 101.0, "low": 90.0, "close": 91.0},  # Bearish 1
        {"open": 91.0, "high": 92.0, "low": 81.0, "close": 82.0},  # Bearish 2
        {"open": 82.0, "high": 88.0, "low": 81.0, "close": 87.0},  # Bullish interrupter
        {"open": 87.0, "high": 88.0, "low": 77.0, "close": 78.0},  # Bearish 1
        {"open": 78.0, "high": 79.0, "low": 68.0, "close": 69.0},  # Bearish 2
    ]
    df_broken = _make_df(bars_broken)
    # At idx=2: window [0,1,2] has a green bar -> False
    assert sr_check_runaway_momentum(df_broken, 2, lookback_bars=3) == (False, False)
    # At idx=3: window [1,2,3] has green bar; preceding [0,1,2] has green bar -> False
    assert sr_check_runaway_momentum(df_broken, 3, lookback_bars=3) == (False, False)
    # At idx=4: window [2,3,4] has green bar; preceding [1,2,3] has green bar -> False
    assert sr_check_runaway_momentum(df_broken, 4, lookback_bars=3) == (False, False)


def test_2_bar_vs_3_bar_vs_4_bar_lookbacks():
    """Verify sensitivity to lookback_bars parameter."""
    # 2 consecutive strong red bars
    bars_2 = [
        {"open": 100.0, "high": 101.0, "low": 90.0, "close": 91.0},
        {"open": 91.0, "high": 92.0, "low": 81.0, "close": 82.0},
    ]
    df_2 = _make_df(bars_2)
    # lookback 3 should be False (not enough bars)
    assert sr_check_runaway_momentum(df_2, 1, lookback_bars=3) == (False, False)
    # lookback 2 should be True
    assert sr_check_runaway_momentum(df_2, 1, lookback_bars=2) == (True, False)

    # 3 consecutive strong red bars
    bars_3 = [
        {"open": 100.0, "high": 101.0, "low": 90.0, "close": 91.0},
        {"open": 91.0, "high": 92.0, "low": 81.0, "close": 82.0},
        {"open": 82.0, "high": 83.0, "low": 72.0, "close": 73.0},
    ]
    df_3 = _make_df(bars_3)
    assert sr_check_runaway_momentum(df_3, 2, lookback_bars=3) == (True, False)
    assert sr_check_runaway_momentum(df_3, 2, lookback_bars=4) == (False, False)

    # 4 consecutive strong red bars
    bars_4 = [
        {"open": 100.0, "high": 101.0, "low": 90.0, "close": 91.0},
        {"open": 91.0, "high": 92.0, "low": 81.0, "close": 82.0},
        {"open": 82.0, "high": 83.0, "low": 72.0, "close": 73.0},
        {"open": 73.0, "high": 74.0, "low": 63.0, "close": 64.0},
    ]
    df_4 = _make_df(bars_4)
    assert sr_check_runaway_momentum(df_4, 3, lookback_bars=3) == (True, False)
    assert sr_check_runaway_momentum(df_4, 3, lookback_bars=4) == (True, False)
    assert sr_check_runaway_momentum(df_4, 3, lookback_bars=5) == (False, False)


def test_preceding_runaway_burst_ending_at_idx_minus_1():
    """Verify that a 3-bar runaway burst ending at idx-1 suppresses counter-trend signal."""
    # 3 strong red bars, followed by a green hammer/pin-bar at idx=3
    bars = [
        {"open": 100.0, "high": 101.0, "low": 90.0, "close": 91.0},  # bar 0
        {"open": 91.0, "high": 92.0, "low": 81.0, "close": 82.0},  # bar 1
        {"open": 82.0, "high": 83.0, "low": 72.0, "close": 73.0},  # bar 2
        {"open": 72.5, "high": 76.0, "low": 71.0, "close": 75.5},  # bar 3 (green bounce)
    ]
    df = _make_df(bars)
    # At idx=3, bars [0, 1, 2] is a 3-bar bearish waterfall ending at idx-1.
    is_bearish, is_bullish = sr_check_runaway_momentum(df, 3, lookback_bars=3)
    assert is_bearish is True
    assert is_bullish is False


# =====================================================================
# D. PRICE GAPS, FLASH VOLATILITY, INVERTED/MALFORMED TICKS
# =====================================================================


def test_extreme_price_gaps_and_flash_crashes():
    """Verify massive price gaps and flash crashes do not overflow or fail."""
    flash_bars = [
        {"open": 1_000_000.0, "high": 1_000_050.0, "low": 500_000.0, "close": 500_100.0},
        {"open": 400_000.0, "high": 400_050.0, "low": 200_000.0, "close": 200_050.0},
        {"open": 150_000.0, "high": 150_050.0, "low": 50_000.0, "close": 50_010.0},
    ]
    df = _make_df(flash_bars)
    is_bearish, is_bullish = sr_check_runaway_momentum(df, 2, lookback_bars=3)
    assert is_bearish is True
    assert is_bullish is False


def test_inverted_or_malformed_ohlc():
    """Verify malformed data (High < Low, Open > High) is safely handled without exception."""
    malformed_bars = [
        {"open": 100.0, "high": 90.0, "low": 110.0, "close": 95.0},
        {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
        {"open": 100.0, "high": 105.0, "low": 95.0, "close": 90.0},
    ]
    df = _make_df(malformed_bars)
    res = sr_check_runaway_momentum(df, 2, lookback_bars=3)
    assert isinstance(res, tuple)
    assert res == (False, False)


def test_doji_and_marubozu_candle_types():
    """Verify exact behavior on Doji vs Marubozu candles."""
    doji_bars = [
        {"open": 100.0, "high": 110.0, "low": 100.0, "close": 100.0},
        {"open": 100.0, "high": 110.0, "low": 100.0, "close": 100.0},
        {"open": 100.0, "high": 110.0, "low": 100.0, "close": 100.0},
    ]
    df_doji = _make_df(doji_bars)
    assert sr_check_runaway_momentum(df_doji, 2, lookback_bars=3) == (False, False)

    # Bearish Marubozu: Open = High, Close = Low (body = 100%, lower_wick = 0%)
    marubozu_bear_bars = [
        {"open": 100.0, "high": 100.0, "low": 90.0, "close": 90.0},
        {"open": 90.0, "high": 90.0, "low": 80.0, "close": 80.0},
        {"open": 80.0, "high": 80.0, "low": 70.0, "close": 70.0},
    ]
    df_mb = _make_df(marubozu_bear_bars)
    assert sr_check_runaway_momentum(df_mb, 2, lookback_bars=3) == (True, False)

    # Bullish Marubozu: Open = Low, Close = High (body = 100%, upper_wick = 0%)
    marubozu_bull_bars = [
        {"open": 70.0, "high": 80.0, "low": 70.0, "close": 80.0},
        {"open": 80.0, "high": 90.0, "low": 80.0, "close": 90.0},
        {"open": 90.0, "high": 100.0, "low": 90.0, "close": 100.0},
    ]
    df_mb_bull = _make_df(marubozu_bull_bars)
    assert sr_check_runaway_momentum(df_mb_bull, 2, lookback_bars=3) == (False, True)


# =====================================================================
# E. END-TO-END STRATEGY EVALUATE_BAR STRESS & SUPPRESSION ADHERENCE
# =====================================================================


def test_sr_bounce_strategy_suppression_exhaustive():
    """Verify S&R bounce strategy evaluate_bar returns exact suppressed SignalResult."""
    strat = SupportResistanceBounceStrategy(swing_window=20, min_wick_ratio=0.35)

    candles = []
    base_price = 1.0500
    for i in range(30):
        mid = base_price + 0.0010 * (1 if i % 4 < 2 else -1)
        candles.append(
            {
                "open": mid,
                "high": 1.0550,
                "low": 1.0450,
                "close": mid + 0.0002 * (1 if i % 2 == 0 else -1),
            }
        )

    # Scenario 1: Bearish waterfall suppressing CALL
    s1_candles = list(candles)
    s1_candles.append({"open": 1.0500, "high": 1.0505, "low": 1.0480, "close": 1.0482})
    s1_candles.append({"open": 1.0482, "high": 1.0485, "low": 1.0465, "close": 1.0467})
    s1_candles.append({"open": 1.0467, "high": 1.0470, "low": 1.0450, "close": 1.0452})
    s1_candles.append({"open": 1.0458, "high": 1.0472, "low": 1.0445, "close": 1.0470})

    df1 = strat.prepare_dataframe(_make_df(s1_candles))
    sig1 = strat.evaluate_bar(df1, len(df1) - 1)
    assert sig1.action is None
    assert sig1.confidence == 0.0
    assert sig1.regime == "runaway_momentum_suppressed"
    assert sig1.metadata["suppressed_action"] == "CALL"
    assert sig1.expiration_bars == 3

    # Scenario 2: Bullish burst suppressing PUT
    s2_candles = list(candles)
    s2_candles.append({"open": 1.0500, "high": 1.0520, "low": 1.0495, "close": 1.0518})
    s2_candles.append({"open": 1.0518, "high": 1.0535, "low": 1.0515, "close": 1.0533})
    s2_candles.append({"open": 1.0533, "high": 1.0550, "low": 1.0530, "close": 1.0548})
    s2_candles.append({"open": 1.0542, "high": 1.0555, "low": 1.0528, "close": 1.0530})

    df2 = strat.prepare_dataframe(_make_df(s2_candles))
    sig2 = strat.evaluate_bar(df2, len(df2) - 1)
    assert sig2.action is None
    assert sig2.confidence == 0.0
    assert sig2.regime == "runaway_momentum_suppressed"
    assert sig2.metadata["suppressed_action"] == "PUT"
    assert sig2.expiration_bars == 3

    # Scenario 3: Flat bar (H == L) returns flat_bar regime
    s3_candles = list(candles)
    s3_candles.append({"open": 1.0500, "high": 1.0500, "low": 1.0500, "close": 1.0500})
    df3 = strat.prepare_dataframe(_make_df(s3_candles))
    sig3 = strat.evaluate_bar(df3, len(df3) - 1)
    assert sig3.action is None
    assert sig3.regime == "flat_bar"

    # Scenario 4: Warming up
    df_warm = strat.prepare_dataframe(_make_df(candles[:10]))
    sig_warm = strat.evaluate_bar(df_warm, 5)
    assert sig_warm.action is None
    assert sig_warm.regime == "warming_up"


def test_rsi_stoch_strategy_suppression_exhaustive():
    """Verify RSI+Stoch Extreme strategy evaluate_bar returns exact suppressed SignalResult."""
    strat = RsiStochasticExtremeStrategy(
        rsi_period=14,
        rsi_oversold=25.0,
        rsi_overbought=75.0,
        stoch_k=14,
        stoch_d=3,
        stoch_oversold=20.0,
        stoch_overbought=80.0,
    )

    candles = []
    base_price = 1.0500
    for i in range(30):
        p = base_price + 0.0005 * (1 if i % 2 == 0 else -1)
        candles.append(
            {
                "open": p,
                "high": p + 0.0003,
                "low": p - 0.0003,
                "close": p + 0.0001 * (1 if i % 2 == 0 else -1),
            }
        )

    # Waterfall driving RSI <= 25 and Stoch <= 20
    s1_candles = list(candles)
    for _ in range(6):
        prev_close = s1_candles[-1]["close"]
        s1_candles.append(
            {
                "open": prev_close,
                "high": prev_close + 0.0002,
                "low": prev_close - 0.0020,
                "close": prev_close - 0.0018,
            }
        )
    df1 = strat.prepare_dataframe(_make_df(s1_candles))
    sig1 = strat.evaluate_bar(df1, len(df1) - 1)
    assert sig1.action is None
    assert sig1.confidence == 0.0
    assert sig1.regime == "runaway_momentum_suppressed"
    assert sig1.metadata["suppressed_action"] == "CALL"

    # Bullish burst driving RSI >= 75 and Stoch >= 80
    s2_candles = list(candles)
    for _ in range(8):
        prev_close = s2_candles[-1]["close"]
        s2_candles.append(
            {
                "open": prev_close,
                "high": prev_close + 0.0030,
                "low": prev_close - 0.0002,
                "close": prev_close + 0.0028,
            }
        )
    df2 = strat.prepare_dataframe(_make_df(s2_candles))
    sig2 = strat.evaluate_bar(df2, len(df2) - 1)
    assert sig2.action is None
    assert sig2.confidence == 0.0
    assert sig2.regime == "runaway_momentum_suppressed"
    assert sig2.metadata["suppressed_action"] == "PUT"

    # Warming up
    df_warm = strat.prepare_dataframe(_make_df(candles[:15]))
    sig_warm = strat.evaluate_bar(df_warm, 10)
    assert sig_warm.action is None
    assert sig_warm.regime == "warming_up"


# =====================================================================
# F. RANDOMIZED MONTE CARLO FUZZ STRESS TEST (1,000 CANDLE SEQUENCES)
# =====================================================================


def test_fuzz_check_runaway_momentum_1000_iterations():
    """Fuzz check_runaway_momentum across 1,000 randomized synthetic candle windows."""
    random.seed(42)

    for _ in range(1000):
        seq_len = random.randint(1, 20)
        base_p = random.uniform(0.0001, 100000.0)

        bars = []
        cur_p = base_p
        for _ in range(seq_len):
            candle_type = random.choice(["normal", "zero", "micro", "spike", "inverted"])
            if candle_type == "zero":
                bars.append({"open": cur_p, "high": cur_p, "low": cur_p, "close": cur_p})
            elif candle_type == "micro":
                eps = random.uniform(1e-12, 1e-6)
                bars.append(
                    {"open": cur_p, "high": cur_p + eps, "low": cur_p - eps, "close": cur_p}
                )
            elif candle_type == "spike":
                spk = cur_p * random.uniform(0.5, 2.0)
                bars.append(
                    {
                        "open": cur_p,
                        "high": cur_p + spk,
                        "low": max(0.00001, cur_p - spk),
                        "close": cur_p + spk * 0.5,
                    }
                )
                cur_p += spk * 0.5
            elif candle_type == "inverted":
                bars.append(
                    {"open": cur_p, "high": cur_p - 10.0, "low": cur_p + 10.0, "close": cur_p}
                )
            else:
                delta = random.uniform(-50.0, 50.0)
                opn = cur_p
                cls = cur_p + delta
                hi = max(opn, cls) + random.uniform(0.0, 10.0)
                lo = min(opn, cls) - random.uniform(0.0, 10.0)
                bars.append({"open": opn, "high": hi, "low": lo, "close": cls})
                cur_p = cls

        df = _make_df(bars)
        eval_idx = random.randint(-5, seq_len + 5)
        lookback = random.randint(-2, 6)
        min_body = random.uniform(-0.5, 1.5)
        max_wick = random.uniform(-0.5, 1.5)

        # Ensure NO exception is raised under any chaotic input
        res_sr = sr_check_runaway_momentum(
            df,
            idx=eval_idx,
            lookback_bars=lookback,
            min_body_ratio=min_body,
            max_opposing_wick_ratio=max_wick,
        )
        res_rsi = rsi_check_runaway_momentum(
            df,
            idx=eval_idx,
            lookback_bars=lookback,
            min_body_ratio=min_body,
            max_opposing_wick_ratio=max_wick,
        )

        assert isinstance(res_sr, tuple) and len(res_sr) == 2
        assert isinstance(res_sr[0], bool) and isinstance(res_sr[1], bool)
        assert res_sr == res_rsi
        # Can never be both bearish and bullish simultaneously
        assert not (res_sr[0] and res_sr[1])
