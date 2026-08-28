from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import BacktestConfig, TradeAction
from strat_trade.domain.strategies.volatility_squeeze_breakout import (
    VolatilitySqueezeBreakoutStrategy,
)

# ============================================================================
# Adversarial Generators & Oracles
# ============================================================================


def generate_synthetic_ohlcv(
    n: int,
    base_price: float = 1.0850,
    volatility: float = 0.0002,
    trend: float = 0.0,
    seed: int | None = 42,
) -> pd.DataFrame:
    """Generate realistic synthetic OHLCV data."""
    if seed is not None:
        np.random.seed(seed)

    t0 = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
    returns = np.random.normal(trend, volatility, n)
    prices = base_price * np.exp(np.cumsum(returns))

    data = []
    for i in range(n):
        c = float(prices[i])
        o = float(prices[i - 1]) if i > 0 else c
        spread = abs(np.random.normal(0, volatility * 0.5))
        h = max(o, c) + spread
        low_val = min(o, c) - spread
        data.append(
            {
                "timestamp": t0 + timedelta(minutes=i),
                "open": o,
                "high": h,
                "low": low_val,
                "close": c,
                "volume": 100 + int(np.random.uniform(0, 50)),
            }
        )
    return pd.DataFrame(data)


# ============================================================================
# Challenge 1: Continuous Chop & Uncompressed Ranging Zero-Signal Oracle
# ============================================================================


@pytest.mark.parametrize("seed", [101, 202, 303, 404, 505, 606, 707, 808, 909, 1000])
def test_adversarial_continuous_uncompressed_ranging_zero_signals(seed: int):
    """Oracle Test: Under continuous choppy / uncompressed ranging conditions,

    the strategy MUST NOT produce a single breakout signal across all bars.
    """
    strat = VolatilitySqueezeBreakoutStrategy()
    df = generate_synthetic_ohlcv(n=500, volatility=0.0010, seed=seed)
    df_prep = strat.prepare_dataframe(df)

    # Force squeeze_on to False everywhere (continuous uncompressed chop)
    df_prep["squeeze_on"] = False

    signals = []
    for i in range(30, len(df_prep)):
        sig = strat.evaluate_bar(df_prep, i)
        if sig.action is not None:
            signals.append((i, sig.action, sig.confidence))

    assert len(signals) == 0, (
        f"Phantom signals detected during uncompressed chop with seed {seed}: {signals}"
    )


def test_adversarial_sinusoidal_ranging_fuzz():
    """Fuzz over 1000 bars of alternating oscillating price waves without squeeze."""
    strat = VolatilitySqueezeBreakoutStrategy()
    t0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC)
    n = 1000
    prices = 1.0850 + 0.0030 * np.sin(np.linspace(0, 50 * np.pi, n))

    df = pd.DataFrame(
        {
            "timestamp": [t0 + timedelta(minutes=i) for i in range(n)],
            "open": prices,
            "high": prices + 0.0010,
            "low": prices - 0.0010,
            "close": prices,
            "volume": 100,
        }
    )
    df_prep = strat.prepare_dataframe(df)
    # Ensure squeeze never fired
    df_prep["squeeze_on"] = False

    fired = [
        (i, strat.evaluate_bar(df_prep, i).action)
        for i in range(30, n)
        if strat.evaluate_bar(df_prep, i).action is not None
    ]
    assert len(fired) == 0, f"Expected 0 signals during sinusoidal ranging, found {len(fired)}"


# ============================================================================
# Challenge 2: Squeeze Transition Strict Single-Bar Timing Oracle
# ============================================================================


def test_adversarial_strict_breakout_bar_triggering():
    """Oracle Test: Signals MUST ONLY fire on the exact transition bar (squeeze release).

    Bars before (during squeeze) and bars after (post-breakout continuation)
    must NEVER trigger new signals.
    """
    strat = VolatilitySqueezeBreakoutStrategy()
    df = generate_synthetic_ohlcv(100, seed=42)
    df["squeeze_on"] = False
    df["momentum"] = 0.0

    # Create a 10-bar squeeze from idx 40 to 49
    # Release on idx 50
    for i in range(40, 50):
        df.loc[i, "squeeze_on"] = True
        df.loc[i, "momentum"] = 0.0001 * (i - 39)

    # Transition bar: idx 50
    df.loc[50, "squeeze_on"] = False
    df.loc[50, "momentum"] = 0.0030  # accelerating breakout

    # Post-transition bars: idx 51..60 (still uncompressed, surging momentum)
    for i in range(51, 61):
        df.loc[i, "squeeze_on"] = False
        df.loc[i, "momentum"] = 0.0030 + 0.0010 * (i - 50)  # even stronger momentum

    signals_by_bar = {}
    for i in range(30, 65):
        sig = strat.evaluate_bar(df, i)
        if sig.action is not None:
            signals_by_bar[i] = sig.action

    # Verification: EXACTLY bar 50 should have fired, and NO other bars
    assert 50 in signals_by_bar, "Breakout bar idx 50 failed to fire!"
    assert signals_by_bar[50] == TradeAction.CALL

    invalid_firings = {k: v for k, v in signals_by_bar.items() if k != 50}
    assert len(invalid_firings) == 0, (
        f"Signals improperly fired on non-transition bars: {invalid_firings}"
    )


def test_adversarial_multi_cycle_squeeze_and_release():
    """Oracle Test: Multiple distinct sequential squeeze-release cycles.

    Verify that EACH cycle triggers exactly ONE signal at its release bar, and
    intermediate states (within squeeze, uncompressed drift) generate zero signals.
    """
    strat = VolatilitySqueezeBreakoutStrategy()
    n = 200
    df = generate_synthetic_ohlcv(n, seed=777)
    df["squeeze_on"] = False
    df["momentum"] = 0.0

    # Cycle 1: Squeeze 35..45, Release at 46 (Bullish)
    for i in range(35, 46):
        df.loc[i, "squeeze_on"] = True
        df.loc[i, "momentum"] = 0.0002
    df.loc[46, "squeeze_on"] = False
    df.loc[46, "momentum"] = 0.0025  # Bullish release

    # Drift 47..70: No squeeze, high momentum
    for i in range(47, 71):
        df.loc[i, "squeeze_on"] = False
        df.loc[i, "momentum"] = 0.0035

    # Cycle 2: Squeeze 71..85, Release at 86 (Bearish)
    for i in range(71, 86):
        df.loc[i, "squeeze_on"] = True
        df.loc[i, "momentum"] = -0.0001
    df.loc[86, "squeeze_on"] = False
    df.loc[86, "momentum"] = -0.0030  # Bearish release

    # Cycle 3: Squeeze 110..120, Release at 121 (Decelerating -> should NOT fire)
    for i in range(110, 121):
        df.loc[i, "squeeze_on"] = True
        df.loc[i, "momentum"] = 0.0020
    df.loc[121, "squeeze_on"] = False
    df.loc[121, "momentum"] = 0.0010  # Decelerating release

    signals_map = {}
    for i in range(30, n):
        sig = strat.evaluate_bar(df, i)
        if sig.action is not None:
            signals_map[i] = sig.action

    # Cycle 1 must fire CALL at 46
    assert 46 in signals_map
    assert signals_map[46] == TradeAction.CALL

    # Cycle 2 must fire PUT at 86
    assert 86 in signals_map
    assert signals_map[86] == TradeAction.PUT

    # Cycle 3 must NOT fire at 121
    assert 121 not in signals_map

    # Total fired signals across all 200 bars MUST be exactly 2
    assert len(signals_map) == 2, f"Unexpected signals fired: {signals_map}"


# ============================================================================
# Challenge 3: Momentum Acceleration and Direction Matrix
# ============================================================================


@pytest.mark.parametrize(
    ("mom_prev", "mom_now", "expected_action", "scenario_name"),
    [
        # Bullish accelerating
        (0.0005, 0.0015, TradeAction.CALL, "Bullish accelerating (+) -> (+)"),
        (-0.0005, 0.0015, TradeAction.CALL, "Bullish surging from (-) to (+)"),
        # Bullish decelerating / flat
        (0.0015, 0.0005, None, "Bullish decelerating"),
        (0.0015, 0.0015, None, "Bullish equal momentum"),
        # Bearish accelerating
        (-0.0005, -0.0015, TradeAction.PUT, "Bearish accelerating (-) -> (-)"),
        (0.0005, -0.0015, TradeAction.PUT, "Bearish plunging from (+) to (-)"),
        # Bearish decelerating / flat
        (-0.0015, -0.0005, None, "Bearish decelerating (becoming less negative)"),
        (-0.0015, -0.0015, None, "Bearish equal momentum"),
        # Opposite direction counter-intuitive tests
        (-0.0020, -0.0001, None, "Momentum rising but remains negative (no CALL, no PUT)"),
        (0.0020, 0.0001, None, "Momentum falling but remains positive (no PUT, no CALL)"),
        (0.0, 0.0, None, "Zero momentum"),
        # Micro precision boundary tests
        (0.0, 1e-7, TradeAction.CALL, "Micro bullish acceleration from 0.0"),
        (0.0, -1e-7, TradeAction.PUT, "Micro bearish acceleration from 0.0"),
        (1e-7, 0.0, None, "Micro bullish deceleration to 0.0"),
        (-1e-7, 0.0, None, "Micro bearish deceleration to 0.0"),
    ],
)
def test_adversarial_momentum_direction_matrix(
    mom_prev: float, mom_now: float, expected_action: TradeAction | None, scenario_name: str
):
    """Stress test the exact combinatorial momentum matrix at the moment of squeeze release."""
    strat = VolatilitySqueezeBreakoutStrategy()
    df = generate_synthetic_ohlcv(50, seed=42)
    idx = 35

    df.loc[idx - 1, "squeeze_on"] = True
    df.loc[idx - 1, "momentum"] = mom_prev
    df.loc[idx, "squeeze_on"] = False
    df.loc[idx, "momentum"] = mom_now

    sig = strat.evaluate_bar(df, idx)
    assert sig.action == expected_action, (
        f"Scenario '{scenario_name}' failed: expected {expected_action}, got {sig.action} "
        f"(mom_prev={mom_prev}, mom_now={mom_now})"
    )


# ============================================================================
# Challenge 4: Extreme Noise, Random Walk & Boundary Stress Harness
# ============================================================================


def test_adversarial_extreme_flash_crash_and_recovery():
    """Verify behavior under extreme price spikes / flash crashes (100x moves)."""
    strat = VolatilitySqueezeBreakoutStrategy()
    df = generate_synthetic_ohlcv(80, seed=42)
    df.loc[45, "open"] = 1.0850
    df.loc[45, "high"] = 2.5000  # Massive spike
    df.loc[45, "low"] = 0.5000  # Massive drop
    df.loc[45, "close"] = 1.0850

    df_prep = strat.prepare_dataframe(df)
    assert len(df_prep) == 80
    assert not df_prep["momentum"].isna().all()

    # Evaluating across the spike
    for i in range(30, len(df_prep)):
        sig = strat.evaluate_bar(df_prep, i)
        assert sig is not None
        assert sig.confidence <= 0.95


def test_adversarial_nan_and_inf_resilience():
    """Verify NaN and Inf values in raw series do not crash the strategy or evaluate_bar."""
    strat = VolatilitySqueezeBreakoutStrategy()
    df = generate_synthetic_ohlcv(60, seed=42)
    df.loc[20, "close"] = np.nan
    df.loc[21, "high"] = np.inf
    df.loc[22, "low"] = -np.inf

    # Indicator computation should handle or propagate gracefully
    df_prep = strat.prepare_dataframe(df)
    assert len(df_prep) == 60

    # Ensure evaluate_bar is robust to NaNs in indicator columns
    df_prep["squeeze_on"] = df_prep["squeeze_on"].astype(object)
    df_prep.loc[35, "momentum"] = np.nan
    df_prep.loc[35, "squeeze_on"] = np.nan
    df_prep.loc[34, "squeeze_on"] = np.nan

    sig = strat.evaluate_bar(df_prep, 35)
    assert sig.action is None
    assert sig.confidence == 0.0


def test_adversarial_minimal_and_undersized_dataframes():
    """Verify boundary lengths (0 to 35 bars) never raise uncaught index/slice exceptions."""
    strat = VolatilitySqueezeBreakoutStrategy()

    # Empty DataFrame
    df_empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    prep_empty = strat.prepare_dataframe(df_empty)
    assert len(prep_empty) == 0

    # Micro DataFrames (length 1 to 30)
    for length in [1, 2, 5, 15, 29, 30]:
        df_micro = generate_synthetic_ohlcv(length, seed=42)
        prep_micro = strat.prepare_dataframe(df_micro)
        assert len(prep_micro) == length
        for idx in range(length):
            sig = strat.evaluate_bar(prep_micro, idx)
            assert sig.action is None
            assert sig.regime == "warming_up"


def test_adversarial_lookahead_bias_invariance():
    """Verify that indicators and signals at bar K are 100% invariant to future data.

    Signal evaluated on df[0..K] MUST equal signal evaluated on full df[0..N].
    """
    strat = VolatilitySqueezeBreakoutStrategy()
    df_full = generate_synthetic_ohlcv(120, seed=999)
    df_full_prep = strat.prepare_dataframe(df_full)

    for k in range(35, 110, 10):
        df_slice = df_full.iloc[: k + 1].copy()
        df_slice_prep = strat.prepare_dataframe(df_slice)

        sig_full = strat.evaluate_bar(df_full_prep, k)
        sig_slice = strat.evaluate_bar(df_slice_prep, k)

        assert sig_full.action == sig_slice.action, f"Lookahead bias detected at bar {k}!"
        assert np.isclose(sig_full.confidence, sig_slice.confidence)
        assert sig_full.metadata == sig_slice.metadata


# ============================================================================
# Challenge 5: Monte Carlo Backtest Execution Realism
# ============================================================================


@pytest.mark.parametrize("mc_seed", range(10))
def test_adversarial_monte_carlo_backtest_stability(mc_seed: int):
    """Execute complete backtest on 10 random-walk Monte Carlo datasets.

    Verify backtest finishes with finite balance, valid trade records,
    and no unexpected crashes.
    """
    df = generate_synthetic_ohlcv(n=300, volatility=0.0004, seed=1000 + mc_seed)
    cfg = BacktestConfig(
        asset=f"SYNTH_{mc_seed}_otc",
        timeframe_seconds=60,
        strategy_name="volatility_squeeze_breakout",
        initial_deposit=Decimal("1000.0"),
        payout_rate=Decimal("0.92"),
        stake_amount=Decimal("10.0"),
    )
    engine = BinaryBacktestEngine(cfg)
    summary = engine.run(df)

    assert summary is not None
    assert summary.initial_deposit == Decimal("1000.0")
    assert np.isfinite(float(summary.final_balance))
    assert summary.final_balance > Decimal("0.0")
    assert summary.total_trades >= 0
    assert Decimal("0.0") <= summary.win_rate_pct <= Decimal("100.0")
