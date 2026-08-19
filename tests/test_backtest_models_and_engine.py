from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd

from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import BacktestConfig, StakeModel


def _generate_synthetic_candles(n: int = 250) -> pd.DataFrame:
    base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    timestamps = [base_t + timedelta(minutes=i) for i in range(n)]

    # Generate an oscillatory price series with multiple swings and trends
    np.random.seed(42)
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


def test_backtest_engine_flat_stake() -> None:
    df = _generate_synthetic_candles(250)
    config = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        initial_deposit=Decimal("1000"),
        stake_model=StakeModel.FLAT,
        stake_amount=Decimal("20"),
        payout_rate=Decimal("0.85"),
        min_payout_rate=Decimal("0.80"),
        expiration_bars=3,
        adaptive_expiration=False,
    )
    engine = BinaryBacktestEngine(config)
    summary = engine.run(df)

    assert summary.asset == "EURUSD_otc"
    assert summary.initial_deposit == Decimal("1000")
    assert summary.total_trades > 0
    assert (
        summary.winning_trades + summary.losing_trades + summary.draw_trades == summary.total_trades
    )
    assert summary.win_rate_pct >= Decimal("0.0")
    assert len(summary.trades) == summary.total_trades
    assert len(summary.equity_curve) == summary.total_trades + 1


def test_backtest_engine_percent_stake() -> None:
    df = _generate_synthetic_candles(250)
    config = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        initial_deposit=Decimal("1000"),
        stake_model=StakeModel.PERCENT,
        stake_percent=Decimal("2.0"),  # 2%
        payout_rate=Decimal("0.85"),
        expiration_bars=2,
    )
    engine = BinaryBacktestEngine(config)
    summary = engine.run(df)

    assert summary.total_trades > 0
    if summary.trades:
        # First trade should have stake around $20
        assert summary.trades[0].stake == Decimal("20.00")


def test_backtest_engine_martingale_stake() -> None:
    df = _generate_synthetic_candles(250)
    config = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        initial_deposit=Decimal("1000"),
        stake_model=StakeModel.MARTINGALE,
        stake_amount=Decimal("10"),
        martingale_multiplier=Decimal("2.0"),
        martingale_max_steps=2,
        payout_rate=Decimal("0.85"),
        expiration_bars=2,
    )
    engine = BinaryBacktestEngine(config)
    summary = engine.run(df)

    assert summary.total_trades > 0


def test_payout_filter_rejection() -> None:
    df = _generate_synthetic_candles(100)
    config = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        payout_rate=Decimal("0.70"),  # 70% is below 80% min threshold
        min_payout_rate=Decimal("0.80"),
    )
    engine = BinaryBacktestEngine(config)
    summary = engine.run(df)

    # Should refuse and return 0 trades
    assert summary.total_trades == 0
    assert summary.net_profit == Decimal("0.0")


def test_stop_loss_circuit_breaker() -> None:
    df = _generate_synthetic_candles(100)
    config = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        initial_deposit=Decimal("100"),
        stake_model=StakeModel.FLAT,
        stake_amount=Decimal("50"),
        daily_stop_loss_pct=Decimal("0.05"),  # 5% max loss = $5
        payout_rate=Decimal("0.85"),
    )
    engine = BinaryBacktestEngine(config)
    summary = engine.run(df)

    # After first loss of $50, drawdown is 50% which is > 5%, engine should halt
    assert summary.total_trades <= 2
