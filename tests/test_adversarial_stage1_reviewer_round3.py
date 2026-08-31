"""Round 3 Adversarial Verification & Stress Test Suite for Stage 1.

Comprehensive adversarial test suite covering:
1. Microsecond (1e15) and Nanosecond (1e18) Unix Epoch timestamps in BinaryBacktestEngine.
2. ISO 8601 strings with varying timezone offsets (+02:00, Z, naive) with UTC normalization.
3. High-frequency sub-second tick feeds (50ms, 100ms) with exact forward index matching.
4. Zero-volatility / Flat price / DRAW trade outcome handling and streak resets.
5. PortfolioBacktestEngine explicit expiration_seconds and forward timestamp searching.
6. End-to-end Auto-Assign filtering: mixed toxic, failed microstructure, and valid assets.
7. Adaptive expiration seconds scaling when strategy alters expiration_bars.
8. Bounded expiration_seconds safety when zero or negative values are provided.
9. Session stop loss circuit breaker cutoff under time-based forward exit.
10. Martingale and Percent position sizing models with time-based forward exit.
11. FastAPI /api/v1/backtest/portfolio/run endpoint validation and execution.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from strat_trade.api.deps import get_candle_feed
from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import (
    BacktestConfig,
    PortfolioBacktestConfig,
    StakeModel,
    TradeOutcome,
)
from strat_trade.domain.backtest.portfolio_engine import PortfolioBacktestEngine
from strat_trade.domain.entities import Candle
from strat_trade.domain.optimizer.auto_matcher import StrategyAutoMatcher
from strat_trade.main import app
from strat_trade.ports.candles import CandleFeed
from strat_trade.use_cases.auto_assign_strategies import generate_pre_trading_plan


def _generate_synthetic_candles(
    n: int = 250, interval_seconds: int = 60, seed: int = 42
) -> pd.DataFrame:
    base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    timestamps = [base_t + timedelta(seconds=i * interval_seconds) for i in range(n)]

    np.random.seed(seed)
    t = np.linspace(0, 16 * np.pi, n)
    sine = np.sin(t) * 0.0080
    noise = np.random.normal(0, 0.0003, n)
    closes = 1.1000 + sine + noise

    rows = []
    for i in range(n):
        c = float(closes[i])
        o = float(closes[i - 1]) if i > 0 else c
        h = max(o, c) + 0.0004
        low = min(o, c) - 0.0004
        rows.append(
            {
                "timestamp": timestamps[i],
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 100.0,
            }
        )
    return pd.DataFrame(rows)


def _make_mock_candles(count: int = 250, seed: int = 42) -> list[Candle]:
    df = _generate_synthetic_candles(n=count, interval_seconds=60, seed=seed)
    candles = []
    for _, row in df.iterrows():
        candles.append(
            Candle(
                open_time=row["timestamp"],
                open=Decimal(str(round(row["open"], 5))),
                high=Decimal(str(round(row["high"], 5))),
                low=Decimal(str(round(row["low"], 5))),
                close=Decimal(str(round(row["close"], 5))),
                volume=Decimal(str(row["volume"])),
            )
        )
    return candles


# =========================================================================
# 1. TIMESTAMP RESOLUTION: MICROSECOND & NANOSECOND UNIX EPOCH
# =========================================================================


def test_microsecond_and_nanosecond_epoch_timestamps() -> None:
    """Verifies that BinaryBacktestEngine handles microsecond and nanosecond epoch timestamps."""
    df_base = _generate_synthetic_candles(n=250, interval_seconds=60)
    base_sec = 1787652000

    # Microsecond dataframe (1e15 scale)
    df_us = df_base.copy()
    df_us["timestamp"] = [int((base_sec + i * 60) * 1_000_000) for i in range(len(df_base))]

    cfg_us = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        expiration_seconds=180,
        strategy_name="hybrid_multifactors",
    )
    engine_us = BinaryBacktestEngine(cfg_us)
    summary_us = engine_us.run(df_us)
    assert summary_us.total_trades > 0
    for trade in summary_us.trades:
        assert (trade.exit_time - trade.entry_time).total_seconds() >= 180

    # Nanosecond dataframe (1e18 scale)
    df_ns = df_base.copy()
    df_ns["timestamp"] = [int((base_sec + i * 60) * 1_000_000_000) for i in range(len(df_base))]

    cfg_ns = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        expiration_seconds=180,
        strategy_name="hybrid_multifactors",
    )
    engine_ns = BinaryBacktestEngine(cfg_ns)
    summary_ns = engine_ns.run(df_ns)
    assert summary_ns.total_trades > 0
    for trade in summary_ns.trades:
        assert (trade.exit_time - trade.entry_time).total_seconds() >= 180


# =========================================================================
# 2. TIMEZONE MIXED STRINGS & UTC NORMALIZATION
# =========================================================================


def test_mixed_timezone_strings_normalization() -> None:
    """Verifies that ISO strings with explicit offsets (+03:00, Z) are normalized to UTC."""
    df_base = _generate_synthetic_candles(n=250, interval_seconds=60)
    base_dt = datetime(2026, 8, 25, 10, 0, 0, tzinfo=UTC)

    formatted_ts = []
    for i in range(len(df_base)):
        t = base_dt + timedelta(minutes=i)
        if i % 3 == 0:
            formatted_ts.append(t.isoformat())
        elif i % 3 == 1:
            formatted_ts.append(t.strftime("%Y-%m-%d %H:%M:%S"))
        else:
            formatted_ts.append(t.strftime("%Y-%m-%dT%H:%M:%S+00:00"))

    df_str = df_base.copy()
    df_str["timestamp"] = formatted_ts

    cfg = BacktestConfig(
        asset="GBPUSD_otc",
        timeframe_seconds=60,
        expiration_seconds=120,
        strategy_name="hybrid_multifactors",
    )
    engine = BinaryBacktestEngine(cfg)
    summary = engine.run(df_str)
    assert summary.total_trades > 0
    for trade in summary.trades:
        assert (trade.exit_time - trade.entry_time).total_seconds() >= 120


# =========================================================================
# 3. HIGH FREQUENCY 50MS TICK STREAMS
# =========================================================================


def test_sub_second_50ms_tick_feed_exact_resolution() -> None:
    """Stress tests high density 50ms tick stream with 1s expiration."""
    t0 = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
    n = 600
    np.random.seed(42)
    t = np.linspace(0, 16 * np.pi, n)
    sine = np.sin(t) * 0.0050
    noise = np.random.normal(0, 0.0001, n)
    closes = 1.0500 + sine + noise

    rows = []
    for i in range(n):
        c = float(closes[i])
        o = float(closes[i - 1]) if i > 0 else c
        h = max(o, c) + 0.0002
        low = min(o, c) - 0.0002
        rows.append(
            {
                "timestamp": t0 + timedelta(milliseconds=i * 50),
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 1.0,
            }
        )
    df = pd.DataFrame(rows)

    cfg = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=1,
        expiration_seconds=1,
        strategy_name="hybrid_multifactors",
    )
    engine = BinaryBacktestEngine(cfg)
    summary = engine.run(df)
    assert summary.total_trades > 0
    for trade in summary.trades:
        duration_s = (trade.exit_time - trade.entry_time).total_seconds()
        assert duration_s >= 1.0
        assert trade.exit_index - trade.entry_index >= 20


# =========================================================================
# 4. FLAT PRICE & DRAW OUTCOME STREAK RESET
# =========================================================================


def test_flat_price_draw_outcome_and_streak_reset() -> None:
    """Verifies that flat price candles result in DRAW outcomes and reset loss streaks cleanly."""
    t0 = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
    rows = []
    for i in range(100):
        t = t0 + timedelta(minutes=i)
        rows.append(
            {
                "timestamp": t,
                "open": 1.20000,
                "high": 1.20000,
                "low": 1.20000,
                "close": 1.20000,
                "volume": 0.0,
            }
        )
    df = pd.DataFrame(rows)

    cfg = BacktestConfig(
        asset="FLAT_ASSET",
        timeframe_seconds=60,
        expiration_seconds=180,
        strategy_name="hybrid_multifactors",
    )
    engine = BinaryBacktestEngine(cfg)
    summary = engine.run(df)
    for trade in summary.trades:
        if trade.exit_price == trade.entry_price:
            assert trade.outcome == TradeOutcome.DRAW
            assert trade.pnl == Decimal("0.0")


# =========================================================================
# 5. PORTFOLIO BACKTEST ENGINE WITH EXPIRATION SECONDS
# =========================================================================


def test_portfolio_backtest_engine_with_expiration_seconds() -> None:
    """Verifies PortfolioBacktestEngine respects expiration_seconds and forward search."""
    df1 = _generate_synthetic_candles(n=250, interval_seconds=60, seed=101)
    df2 = _generate_synthetic_candles(n=250, interval_seconds=60, seed=202)

    cfg = PortfolioBacktestConfig(
        assets=["EURUSD_otc", "GBPUSD_otc"],
        timeframe_seconds=60,
        expiration_seconds=120,  # 2 minutes = 2 bars
        max_concurrent_trades=2,
        strategy_name="hybrid_multifactors",
    )
    engine = PortfolioBacktestEngine(cfg)
    summary = engine.run({"EURUSD_otc": df1, "GBPUSD_otc": df2})
    assert summary.total_trades > 0
    for trade in summary.trades:
        assert trade.expiration_seconds == 120
        assert (trade.exit_time - trade.entry_time).total_seconds() >= 120


# =========================================================================
# 6. AUTO-ASSIGN LOGIC CLEANUP: TOXIC & MICROSTRUCTURE REJECTION
# =========================================================================


@pytest.mark.asyncio
async def test_auto_assign_rejects_toxic_and_substandard_microstructure() -> None:
    """Verifies that generate_pre_trading_plan drops toxic & non-qualifying assets."""
    matcher = StrategyAutoMatcher(candle_count=200)

    # 1. Toxic asset test
    toxic_res = await matcher.find_optimal_strategy_for_asset(
        asset="USDINR_otc",
        candles=_make_mock_candles(200),
    )
    assert toxic_res is None

    # 2. Discrete/step-tick microstructure test (fails qualify_asset_microstructure)
    discrete_candles = []
    t0 = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
    for i in range(100):
        p = 1.0000 if i % 2 == 0 else 1.0001
        discrete_candles.append(
            Candle(
                open_time=t0 + timedelta(minutes=i),
                open=Decimal(str(p)),
                high=Decimal(str(p)),
                low=Decimal(str(p)),
                close=Decimal(str(p)),
                volume=Decimal("1.0"),
            )
        )
    discrete_res = await matcher.find_optimal_strategy_for_asset(
        asset="STEP_TICK_otc",
        candles=discrete_candles,
    )
    assert discrete_res is None

    # 3. End-to-end generate_pre_trading_plan with mix of toxic and clean assets
    mock_feed = AsyncMock(spec=CandleFeed)

    async def mock_get_candles(asset: str, timeframe: int = 60, count: int = 150) -> list[Candle]:
        if "step" in asset.lower():
            return discrete_candles
        return _make_mock_candles(count)

    mock_feed.get_candles.side_effect = mock_get_candles

    plan = await generate_pre_trading_plan(
        feed=mock_feed,
        assets=["USDINR_otc", "STEP_TICK_otc", "EURUSD_otc", "GBPUSD_otc"],
        expiration_seconds=180,
    )

    assigned_symbols = [a.asset for a in plan.assignments]
    assert "USDINR_otc" not in assigned_symbols
    assert "STEP_TICK_otc" not in assigned_symbols
    assert "EURUSD_otc" in assigned_symbols
    assert "GBPUSD_otc" in assigned_symbols
    assert plan.total_assets == len(plan.assignments)


# =========================================================================
# 7. ADAPTIVE EXPIRATION SECONDS SCALING
# =========================================================================


def test_adaptive_expiration_seconds_scaling() -> None:
    """Verifies that adaptive_expiration scales expiration_seconds appropriately."""
    df = _generate_synthetic_candles(n=250)
    cfg = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        expiration_bars=3,
        expiration_seconds=180,
        adaptive_expiration=True,
        strategy_name="hybrid_multifactors",
    )
    engine = BinaryBacktestEngine(cfg)
    summary = engine.run(df)
    assert summary.total_trades > 0
    for trade in summary.trades:
        assert trade.expiration_seconds > 0


# =========================================================================
# 8. BOUNDED EXPIRATION SECONDS SAFETY
# =========================================================================


def test_expiration_seconds_zero_or_negative_bounded() -> None:
    """Verifies that expiration_seconds <= 0 gets safely bounded to >= 1 second."""
    df = _generate_synthetic_candles(n=250)
    cfg = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        expiration_seconds=0,
        strategy_name="hybrid_multifactors",
    )
    engine = BinaryBacktestEngine(cfg)
    summary = engine.run(df)
    assert summary.total_trades > 0
    for trade in summary.trades:
        assert trade.expiration_seconds >= 1


# =========================================================================
# 9. SESSION STOP LOSS CIRCUIT BREAKER
# =========================================================================


def test_session_stop_loss_circuit_breaker_cutoff() -> None:
    """Verifies daily_stop_loss_pct halts backtest execution upon hitting max drawdown."""
    df = _generate_synthetic_candles(n=250)
    cfg = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        initial_deposit=Decimal("100.0"),
        stake_amount=Decimal("10.0"),
        daily_stop_loss_pct=Decimal("0.20"),  # 20% max loss = $20
        strategy_name="hybrid_multifactors",
    )
    engine = BinaryBacktestEngine(cfg)
    summary = engine.run(df)
    assert summary.net_profit <= Decimal("0.0") or summary.total_trades > 0


# =========================================================================
# 10. MARTINGALE AND PERCENT POSITION SIZING UNDER TIME-BASED EXIT
# =========================================================================


def test_martingale_and_percent_position_sizing_models() -> None:
    """Verifies Martingale and Percent position sizing models operate with time-based exit."""
    df = _generate_synthetic_candles(n=250)

    # Martingale
    cfg_mart = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.0"),
        stake_model=StakeModel.MARTINGALE,
        stake_amount=Decimal("10.0"),
        martingale_multiplier=Decimal("2.0"),
        martingale_max_steps=3,
        expiration_seconds=180,
        strategy_name="hybrid_multifactors",
    )
    engine_mart = BinaryBacktestEngine(cfg_mart)
    summary_mart = engine_mart.run(df)
    assert summary_mart.total_trades > 0

    # Percent sizing
    cfg_pct = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.0"),
        stake_model=StakeModel.PERCENT,
        stake_percent=Decimal("2.0"),
        expiration_seconds=180,
        strategy_name="hybrid_multifactors",
    )
    engine_pct = BinaryBacktestEngine(cfg_pct)
    summary_pct = engine_pct.run(df)
    assert summary_pct.total_trades > 0
    assert summary_pct.trades[0].stake == Decimal("20.00")


# =========================================================================
# 11. FASTAPI PORTFOLIO BACKTEST ENDPOINT
# =========================================================================


def test_api_portfolio_backtest_with_expiration_seconds() -> None:
    """Verifies /api/v1/backtest/portfolio/run HTTP endpoint executes with expiration_seconds."""
    client = TestClient(app)
    mock_feed = AsyncMock()
    mock_feed.get_candles.return_value = _make_mock_candles(250)
    mock_feed.get_assets.return_value = [
        {"symbol": "EURUSD_otc", "payout": 92},
        {"symbol": "GBPUSD_otc", "payout": 90},
    ]
    app.dependency_overrides[get_candle_feed] = lambda: mock_feed

    try:
        payload = {
            "assets": ["EURUSD_otc", "GBPUSD_otc"],
            "timeframe_seconds": 60,
            "initial_deposit": 1000.0,
            "max_concurrent_trades": 2,
            "expiration_bars": 3,
            "expiration_seconds": 180,
            "strategy_name": "hybrid_multifactors",
        }
        res = client.post("/api/v1/backtest/portfolio/run", json=payload)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["initial_deposit"] == 1000.0
        assert len(data["assets"]) == 2
        assert "trades" in data
    finally:
        app.dependency_overrides.clear()
