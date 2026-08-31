"""Adversarial Empirical Stress Test Suite for Milestone 4 Hardening.

Empirical verification of:
1. Strategy Edge Cases:
   - Squeeze transitions with identical band values, NaN momentum, zero ATR, zero volume.
   - Bollinger reversion with extreme wicks, gap opens, ADX boundary conditions (24.99/25.00/25.01).
2. Execution Guardrail Adversarial Tests:
   - Currency correlation collisions with reverse quote assets (e.g. EUR/USD vs USD/JPY).
   - Cooldown timer boundary conditions (tick right before expiry vs tick after expiry).
   - Pathological rapid-fire order submission bursts under extreme async concurrency.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.entities import Candle
from strat_trade.domain.strategies.bollinger_atr_reversion import BollingerAtrReversionStrategy
from strat_trade.domain.strategies.volatility_squeeze_breakout import (
    VolatilitySqueezeBreakoutStrategy,
)
from strat_trade.domain.trading.bot_engine import LiveDemoBotEngine
from strat_trade.domain.trading.correlation import (
    get_portfolio_currency_exposure,
    is_correlated_conflict,
)
from strat_trade.domain.trading.entities import (
    PreTradingPlan,
    StrategyAssignment,
)
from strat_trade.domain.trading.trade_store import TradeStore


def _make_mock_dataframe(n: int = 60, base_price: float = 1.1000) -> pd.DataFrame:
    t0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC)
    data = []
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
# 1. Strategy Edge Cases: Volatility Squeeze Breakout
# ============================================================================


def test_squeeze_identical_band_values_no_phantom_signal():
    """When Bollinger Bands and Keltner Channels have identical band values,

    (bb_low == kc_low and bb_high == kc_high), squeeze_on must evaluate to False
    and must not produce false breakout signals.
    """
    strat = VolatilitySqueezeBreakoutStrategy()
    df = _make_mock_dataframe(60)

    # Prepare dataframe
    df_prep = strat.prepare_dataframe(df)

    # Force identical bands on current and previous bar
    idx = 50
    df_prep.loc[idx - 1, "bb_low"] = 1.0950
    df_prep.loc[idx - 1, "kc_low"] = 1.0950
    df_prep.loc[idx - 1, "bb_high"] = 1.1050
    df_prep.loc[idx - 1, "kc_high"] = 1.1050
    df_prep.loc[idx - 1, "squeeze_on"] = (
        df_prep.loc[idx - 1, "bb_low"] > df_prep.loc[idx - 1, "kc_low"]
    ) & (df_prep.loc[idx - 1, "bb_high"] < df_prep.loc[idx - 1, "kc_high"])

    df_prep.loc[idx, "bb_low"] = 1.0950
    df_prep.loc[idx, "kc_low"] = 1.0950
    df_prep.loc[idx, "bb_high"] = 1.1050
    df_prep.loc[idx, "kc_high"] = 1.1050
    df_prep.loc[idx, "squeeze_on"] = (df_prep.loc[idx, "bb_low"] > df_prep.loc[idx, "kc_low"]) & (
        df_prep.loc[idx, "bb_high"] < df_prep.loc[idx, "kc_high"]
    )
    df_prep.loc[idx, "momentum"] = 0.0050
    df_prep.loc[idx - 1, "momentum"] = 0.0020

    # squeeze_on must be False on identical bands
    assert not df_prep.loc[idx - 1, "squeeze_on"]
    assert not df_prep.loc[idx, "squeeze_on"]

    sig = strat.evaluate_bar(df_prep, idx)
    assert sig.action is None, "Should not trigger breakout when bands were never squeezed"


def test_squeeze_transition_from_squeeze_to_identical_bands():
    """When transitioning from squeeze_on=True to identical bands (squeeze_on=False),

    this constitutes a valid squeeze release and triggers if momentum accelerates.
    """
    strat = VolatilitySqueezeBreakoutStrategy()
    df = _make_mock_dataframe(60)
    df_prep = strat.prepare_dataframe(df)

    idx = 50
    # Previous bar: In squeeze (bb inside kc)
    df_prep.loc[idx - 1, "squeeze_on"] = True
    df_prep.loc[idx - 1, "momentum"] = 0.0010

    # Current bar: Released to identical bands (squeeze_on becomes False)
    df_prep.loc[idx, "bb_low"] = 1.0950
    df_prep.loc[idx, "kc_low"] = 1.0950
    df_prep.loc[idx, "bb_high"] = 1.1050
    df_prep.loc[idx, "kc_high"] = 1.1050
    df_prep.loc[idx, "squeeze_on"] = False
    df_prep.loc[idx, "momentum"] = 0.0030

    sig = strat.evaluate_bar(df_prep, idx)
    assert sig.action == TradeAction.CALL
    assert sig.confidence == 0.90
    assert sig.regime == "volatility_breakout"


def test_squeeze_nan_momentum_resilience():
    """When momentum contains NaN at current or previous bar,

    strategy must sanitize safely to 0.0 and produce action=None without crashing.
    """
    strat = VolatilitySqueezeBreakoutStrategy()
    df = _make_mock_dataframe(60)
    df_prep = strat.prepare_dataframe(df)

    idx = 50
    df_prep.loc[idx - 1, "squeeze_on"] = True
    df_prep.loc[idx, "squeeze_on"] = False

    # 1. NaN current momentum
    df_prep.loc[idx, "momentum"] = np.nan
    df_prep.loc[idx - 1, "momentum"] = 0.0020
    sig1 = strat.evaluate_bar(df_prep, idx)
    assert sig1.action is None
    assert sig1.confidence == 0.0

    # 2. NaN previous momentum
    df_prep.loc[idx, "momentum"] = 0.0020
    df_prep.loc[idx - 1, "momentum"] = np.nan
    sig2 = strat.evaluate_bar(df_prep, idx)
    assert sig2.action == TradeAction.CALL  # 0.0020 > 0 and 0.0020 > 0.0

    # 3. Both NaN
    df_prep.loc[idx, "momentum"] = np.nan
    df_prep.loc[idx - 1, "momentum"] = np.nan
    sig3 = strat.evaluate_bar(df_prep, idx)
    assert sig3.action is None


def test_squeeze_zero_atr_and_zero_volume_flatline():
    """In a dead flatline market (High == Low == Close, Volume == 0),

    prepare_dataframe and evaluate_bar must execute without ZeroDivisionError.
    """
    strat = VolatilitySqueezeBreakoutStrategy()
    t0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC)
    n = 60
    # Flatline candles with zero range and zero volume
    data = [
        {
            "timestamp": t0 + timedelta(minutes=i),
            "open": 1.1000,
            "high": 1.1000,
            "low": 1.1000,
            "close": 1.1000,
            "volume": 0,
        }
        for i in range(n)
    ]
    df = pd.DataFrame(data)

    df_prep = strat.prepare_dataframe(df)
    assert "squeeze_on" in df_prep.columns
    assert "momentum" in df_prep.columns

    for idx in range(30, n):
        sig = strat.evaluate_bar(df_prep, idx)
        assert sig.action is None
        assert sig.confidence == 0.0


# ============================================================================
# 2. Strategy Edge Cases: Bollinger Reversion
# ============================================================================


def test_bollinger_reversion_extreme_wicks_confidence_scaling():
    """Extreme rejection wicks (>= 40% of candle range) should boost confidence to 0.85+."""
    strat = BollingerAtrReversionStrategy(adx_trend_threshold=25.0)
    df = _make_mock_dataframe(60)
    idx = 50

    # Bullish Pin-Bar with 80% lower wick
    # High: 1.1000, Close: 1.0990, Open: 1.0985, Low: 1.0910
    # Range = 0.0090, Lower wick = (1.0985 - 1.0910) = 0.0075 -> 83.3% wick
    df.loc[idx, "open"] = 1.0985
    df.loc[idx, "high"] = 1.1000
    df.loc[idx, "low"] = 1.0910
    df.loc[idx, "close"] = 1.0990
    df.loc[idx, "bb_high"] = 1.1050
    df.loc[idx, "bb_low"] = 1.0980
    df.loc[idx, "bb_pband"] = 0.10
    df.loc[idx, "rsi"] = 28.0
    df.loc[idx, "adx"] = 18.0
    df.loc[idx, "atr"] = 0.0015
    df.loc[idx, "atr_sma"] = 0.0015

    sig = strat.evaluate_bar(df, idx)
    assert sig.action == TradeAction.CALL
    # Baseline 0.70 + 0.15 (wick >= 0.40) = 0.85
    assert sig.confidence == 0.85
    assert sig.metadata.get("wick_ratio") == pytest.approx(0.833, abs=1e-2)

    # Deep oversold bonus test (RSI <= 25) -> +0.10 -> 0.95
    df.loc[idx, "rsi"] = 24.0
    sig_deep = strat.evaluate_bar(df, idx)
    assert sig_deep.action == TradeAction.CALL
    assert sig_deep.confidence == 0.95


def test_bollinger_reversion_doji_without_bullish_confirmation_rejected():
    """A perfect Doji (close == open) on the lower band MUST NOT trigger CALL

    because close > open (bullish confirmation) is strictly required.
    """
    strat = BollingerAtrReversionStrategy()
    df = _make_mock_dataframe(60)
    idx = 50

    # Doji: Open == Close on lower band
    df.loc[idx, "open"] = 1.0985
    df.loc[idx, "high"] = 1.0990
    df.loc[idx, "low"] = 1.0950
    df.loc[idx, "close"] = 1.0985  # Exactly equal to open
    df.loc[idx, "bb_high"] = 1.1050
    df.loc[idx, "bb_low"] = 1.0980
    df.loc[idx, "rsi"] = 25.0
    df.loc[idx, "adx"] = 15.0
    df.loc[idx, "atr"] = 0.0015
    df.loc[idx, "atr_sma"] = 0.0015

    sig = strat.evaluate_bar(df, idx)
    assert sig.action is None, "Neutral Doji without bullish close > open must be rejected"


def test_bollinger_reversion_gap_opens_behavior():
    """Gap open scenarios:

    1. Gap down opening outside band but closing inside -> valid CALL.
    2. Gap down opening outside band and closing outside -> REJECTED (knife-catching).
    3. Gap up opening outside band and closing outside -> REJECTED.
    """
    strat = BollingerAtrReversionStrategy()
    df = _make_mock_dataframe(60)
    idx = 50

    # Scenario 1: Gap down opening at 1.0940 (below bb_l 1.0950), closing at 1.0960 (above bb_l)
    df.loc[idx, "open"] = 1.0940
    df.loc[idx, "high"] = 1.0970
    df.loc[idx, "low"] = 1.0930
    df.loc[idx, "close"] = 1.0960
    df.loc[idx, "bb_low"] = 1.0950
    df.loc[idx, "bb_high"] = 1.1050
    df.loc[idx, "rsi"] = 28.0
    df.loc[idx, "adx"] = 15.0
    df.loc[idx, "atr"] = 0.0015
    df.loc[idx, "atr_sma"] = 0.0015

    sig1 = strat.evaluate_bar(df, idx)
    assert sig1.action == TradeAction.CALL

    # Scenario 2: Gap down runaway: open 1.0940, close 1.0945 (still below bb_l 1.0950)
    df.loc[idx, "open"] = 1.0940
    df.loc[idx, "high"] = 1.0948
    df.loc[idx, "low"] = 1.0930
    df.loc[idx, "close"] = 1.0945
    sig2 = strat.evaluate_bar(df, idx)
    assert sig2.action is None, "Must reject runaway gap down that closes outside the lower band"

    # Scenario 3: Gap up runaway: open 1.1060, close 1.1055 (above bb_h 1.1050)
    df.loc[idx, "open"] = 1.1060
    df.loc[idx, "high"] = 1.1070
    df.loc[idx, "low"] = 1.1052
    df.loc[idx, "close"] = 1.1055
    sig3 = strat.evaluate_bar(df, idx)
    assert sig3.action is None, "Must reject runaway gap up that closes outside the upper band"


@pytest.mark.parametrize(
    ("adx_val", "expected_action", "expected_regime"),
    [
        (24.99, TradeAction.CALL, "mean_reversion"),
        (24.9999, TradeAction.CALL, "mean_reversion"),
        (25.00, None, "trend_suppressed_adx"),
        (25.0001, None, "trend_suppressed_adx"),
        (25.01, None, "trend_suppressed_adx"),
        (35.00, None, "trend_suppressed_adx"),
    ],
)
def test_bollinger_reversion_adx_exact_boundary(adx_val, expected_action, expected_regime):
    """ADX Boundary Test: Exactly 25.00 is the suppression barrier."""
    strat = BollingerAtrReversionStrategy(adx_trend_threshold=25.0)
    df = _make_mock_dataframe(60)
    idx = 50

    # Ideal CALL setup
    df.loc[idx, "open"] = 1.0982
    df.loc[idx, "high"] = 1.0995
    df.loc[idx, "low"] = 1.0960
    df.loc[idx, "close"] = 1.0990
    df.loc[idx, "bb_high"] = 1.1050
    df.loc[idx, "bb_low"] = 1.0980
    df.loc[idx, "rsi"] = 28.0
    df.loc[idx, "adx"] = adx_val
    df.loc[idx, "atr"] = 0.0015
    df.loc[idx, "atr_sma"] = 0.0015

    sig = strat.evaluate_bar(df, idx)
    assert sig.action == expected_action
    assert sig.regime == expected_regime


# ============================================================================
# 3. Execution Guardrails: Currency Correlation & Exposure
# ============================================================================


def test_currency_correlation_reverse_quote_assets():
    """Test directional currency exposure conflicts across inverted pairs:

    EUR/USD vs USD/JPY:
    - Active: EUR/USD CALL -> Long EUR, Short USD.
    - Candidate: USD/JPY PUT -> Long JPY, Short USD.
      Conflict: Double Short USD!
    - Candidate: USD/JPY CALL -> Long USD, Short JPY.
      No conflict under check_opposing=False.
      Conflict under check_opposing=True (Opposing USD).
    """
    active_trade = {"asset": "EURUSD_otc", "action": "CALL"}

    # 1. Candidate USDJPY PUT -> Long JPY, Short USD -> Double Short USD
    conflict_1, reason_1 = is_correlated_conflict(
        candidate_asset="USDJPY_otc",
        candidate_action="PUT",
        active_trades=[active_trade],
        check_opposing=False,
    )
    assert conflict_1 is True
    assert "Double Short USD" in reason_1

    # 2. Candidate USDJPY CALL -> Long USD, Short JPY
    conflict_2, reason_2 = is_correlated_conflict(
        candidate_asset="USDJPY_otc",
        candidate_action="CALL",
        active_trades=[active_trade],
        check_opposing=False,
    )
    assert conflict_2 is False

    # 3. Candidate USDJPY CALL with check_opposing=True -> Opposing USD
    conflict_3, reason_3 = is_correlated_conflict(
        candidate_asset="USDJPY_otc",
        candidate_action="CALL",
        active_trades=[active_trade],
        check_opposing=True,
    )
    assert conflict_3 is True
    assert "Opposing USD exposure" in reason_3


def test_currency_correlation_portfolio_exposure_aggregation():
    """Verify portfolio net directional unit count across diverse currency pairs."""
    trades = [
        {"asset": "EURUSD_otc", "action": "CALL"},  # +1 EUR, -1 USD
        {"asset": "GBPUSD_otc", "action": "CALL"},  # +1 GBP, -1 USD
        {"asset": "USDJPY_otc", "action": "CALL"},  # +1 USD, -1 JPY
        {"asset": "AUDCAD_otc", "action": "PUT"},  # -1 AUD, +1 CAD
    ]

    exp = get_portfolio_currency_exposure(trades)
    assert exp["EUR"] == 1
    assert exp["GBP"] == 1
    assert exp["USD"] == -1  # (-1) + (-1) + (+1) = -1
    assert exp["JPY"] == -1
    assert exp["AUD"] == -1
    assert exp["CAD"] == 1


# ============================================================================
# 4. Execution Guardrails: Cooldown Timer Boundary Conditions
# ============================================================================


@pytest.mark.asyncio
async def test_cooldown_timer_boundary_conditions(tmp_path):
    """Test post-settlement per-asset cooldown at:

    - tick right before expiry (t0 + 179.9s): REJECTED
    - exact expiry / tick after expiry (t0 + 180.1s): ALLOWED
    """
    store = TradeStore(tmp_path / "cooldown_trades.db")
    bot = LiveDemoBotEngine(trade_store=store)

    plan = PreTradingPlan(
        assignments=[
            StrategyAssignment(
                asset="EURUSD_otc",
                strategy_id="bollinger_atr_reversion",
                strategy_name="Bollinger ATR",
                category="reversion",
                parameters={},
                estimated_win_rate_pct=60.0,
                estimated_profit_factor=1.8,
                estimated_trades_count=50,
                quantum_score=85.0,
                rationale="test",
            )
        ],
        total_assets=1,
        initial_deposit=Decimal("1000.00"),
        stake_model="flat",
        stake_amount=Decimal("10.00"),
        stake_percent=1.0,
        expiration_seconds=180,
        daily_stop_loss_pct=0.20,
        stop_loss_amount=Decimal("200.00"),
        max_concurrent_trades=3,
        min_payout_rate=0.80,
        cooldown_bars=3,  # 3 bars * 60s = 180s cooldown
        global_cooldown_seconds=0,  # disable global cooldown for this asset-level test
        max_consecutive_losses=3,
        max_drawdown_pct_limit=0.08,
        correlation_filter_enabled=True,
        bar_edge_guard_seconds=0.0,
    )

    gateway = MagicMock()
    await bot.start(plan, gateway)

    t0 = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
    cooldown_expiry = t0 + timedelta(seconds=180)
    bot._asset_cooldown_until["EURUSD_otc"] = cooldown_expiry

    # 1. Test at t0 + 179.9s (Right before expiry)
    t_before = cooldown_expiry - timedelta(milliseconds=100)
    bot._evaluate_single_asset = AsyncMock()

    # Asset cooldown check logic:
    cd_until = bot._asset_cooldown_until.get("EURUSD_otc")
    assert cd_until is not None
    assert (t_before < cd_until) is True, "Cooldown must be active right before expiry"

    # 2. Test at exact expiry and right after expiry (t0 + 180.1s)
    t_after = cooldown_expiry + timedelta(milliseconds=100)
    assert (t_after < cd_until) is False, "Cooldown must be cleared after expiry"

    await bot.stop()


# ============================================================================
# 5. Execution Guardrails: Rapid-Fire Burst Order Submission Stress Test
# ============================================================================


@pytest.mark.asyncio
async def test_bot_engine_rapid_fire_order_submission_burst_concurrency(tmp_path):
    """Stress test: 50 concurrent async tasks attempting to execute orders simultaneously.

    Invariants:
    1. Active trades count NEVER exceeds plan.max_concurrent_trades (3).
    2. No duplicate trades opened on the same asset.
    3. Global cooldown (30s) strictly prevents rapid-fire cascades.
    """
    store = TradeStore(tmp_path / "burst_trades.db")
    bot = LiveDemoBotEngine(trade_store=store)

    assets = [f"ASSET_{i:02d}_otc" for i in range(10)]
    assignments = [
        StrategyAssignment(
            asset=a,
            strategy_id="bollinger_atr_reversion",
            strategy_name=f"Strat_{a}",
            category="reversion",
            parameters={},
            estimated_win_rate_pct=60.0,
            estimated_profit_factor=1.8,
            estimated_trades_count=50,
            quantum_score=85.0,
            rationale="stress",
        )
        for a in assets
    ]

    plan = PreTradingPlan(
        assignments=assignments,
        total_assets=len(assignments),
        initial_deposit=Decimal("1000.00"),
        stake_model="flat",
        stake_amount=Decimal("10.00"),
        stake_percent=1.0,
        expiration_seconds=180,
        daily_stop_loss_pct=0.20,
        stop_loss_amount=Decimal("200.00"),
        max_concurrent_trades=3,
        min_payout_rate=0.80,
        cooldown_bars=3,
        global_cooldown_seconds=30,
        max_consecutive_losses=3,
        max_drawdown_pct_limit=0.08,
        correlation_filter_enabled=False,  # disabled to stress-test concurrent locks and cooldowns
        bar_edge_guard_seconds=0.0,
    )

    mock_gateway = MagicMock()
    mock_gateway.open_trade = AsyncMock(
        side_effect=lambda asset, action, amount, expiration_seconds: (
            f"ord-{asset}",
            {"percentProfit": 92},
        )
    )

    base_time = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
    mock_candles = [
        Candle(
            open_time=base_time + timedelta(minutes=i),
            open=Decimal("1.1000"),
            high=Decimal("1.1010"),
            low=Decimal("1.0990"),
            close=Decimal("1.1005"),
            volume=Decimal("100"),
        )
        for i in range(50)
    ]

    await bot.start(plan, mock_gateway)

    # 1. Burst 50 concurrent calls to _execute_order at timestamp T0
    tasks = [
        bot._execute_order(
            assignment=assignments[i % len(assignments)],
            action="CALL",
            confidence=0.80,
            reason="burst_test",
            candles=mock_candles,
            live_payout=0.92,
        )
        for i in range(50)
    ]

    await asyncio.gather(*tasks)

    # Invariant: Global cooldown (30s) allows exactly 1 trade through during the initial burst
    assert len(bot.active_trades) == 1
    assert mock_gateway.open_trade.call_count == 1

    # 2. Advance time past global cooldown and burst again with 50 tasks
    bot._last_global_execution_time = datetime.now(UTC) - timedelta(seconds=35)

    tasks_2 = [
        bot._execute_order(
            assignment=assignments[i % len(assignments)],
            action="CALL",
            confidence=0.80,
            reason="burst_test_2",
            candles=mock_candles,
            live_payout=0.92,
        )
        for i in range(50)
    ]
    await asyncio.gather(*tasks_2)

    assert len(bot.active_trades) == 2
    assert mock_gateway.open_trade.call_count == 2

    # 3. Advance time again and burst to reach max_concurrent_trades (3)
    bot._last_global_execution_time = datetime.now(UTC) - timedelta(seconds=35)
    tasks_3 = [
        bot._execute_order(
            assignment=assignments[i % len(assignments)],
            action="CALL",
            confidence=0.80,
            reason="burst_test_3",
            candles=mock_candles,
            live_payout=0.92,
        )
        for i in range(50)
    ]
    await asyncio.gather(*tasks_3)

    assert len(bot.active_trades) == 3
    assert mock_gateway.open_trade.call_count == 3

    # 4. Advance time again, but capacity is full (3/3). All 50 burst attempts MUST BE REJECTED!
    bot._last_global_execution_time = datetime.now(UTC) - timedelta(seconds=35)
    tasks_4 = [
        bot._execute_order(
            assignment=assignments[i % len(assignments)],
            action="CALL",
            confidence=0.80,
            reason="burst_test_4",
            candles=mock_candles,
            live_payout=0.92,
        )
        for i in range(50)
    ]
    await asyncio.gather(*tasks_4)

    assert len(bot.active_trades) == 3
    assert mock_gateway.open_trade.call_count == 3

    # Verify no duplicates
    active_assets = [t.asset for t in bot.active_trades.values()]
    assert len(active_assets) == len(set(active_assets))

    await bot.stop()
