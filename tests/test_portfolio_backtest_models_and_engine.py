from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd

from strat_trade.domain.backtest.models import (
    PortfolioBacktestConfig,
    StakeModel,
    TradeAction,
    TradeOutcome,
)
from strat_trade.domain.backtest.portfolio_engine import PortfolioBacktestEngine


def _generate_synthetic_candles(
    n: int = 250, base_price: float = 1.0500, freq_scale: float = 1.0
) -> pd.DataFrame:
    base_t = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    timestamps = [base_t + timedelta(minutes=i) for i in range(n)]

    np.random.seed(42)
    # Generate oscillating wave to trigger clear indicators and signals
    x = np.linspace(0, 10 * np.pi * freq_scale, n)
    wave = np.sin(x) * 0.0080
    noise = np.random.normal(0, 0.0005, n)
    closes = base_price + wave + noise

    rows = []
    for i in range(n):
        c = float(closes[i])
        o = float(closes[i - 1]) if i > 0 else c
        h = max(o, c) + 0.0008
        low_p = min(o, c) - 0.0008
        rows.append(
            {
                "timestamp": timestamps[i],
                "open": o,
                "high": h,
                "low": low_p,
                "close": c,
                "volume": 120.0 + float(np.random.randint(10, 50)),
            }
        )
    return pd.DataFrame(rows)


def test_portfolio_backtest_engine_simulation() -> None:
    df1 = _generate_synthetic_candles(250, base_price=1.0500, freq_scale=1.0)
    df2 = _generate_synthetic_candles(250, base_price=1.2500, freq_scale=1.2)
    df3 = _generate_synthetic_candles(250, base_price=145.50, freq_scale=0.8)

    dfs = {
        "EURUSD_otc": df1,
        "GBPUSD_otc": df2,
        "USDJPY_otc": df3,
    }

    config = PortfolioBacktestConfig(
        assets=["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc"],
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.0"),
        max_concurrent_trades=2,
        stake_model=StakeModel.FLAT,
        stake_amount=Decimal("20.0"),
        payout_rates={
            "EURUSD_otc": Decimal("0.92"),
            "GBPUSD_otc": Decimal("0.92"),
            "USDJPY_otc": Decimal("0.85"),
        },
        min_payout_rate=Decimal("0.80"),
        expiration_bars=3,
        adaptive_expiration=False,
    )

    engine = PortfolioBacktestEngine(config)
    summary = engine.run(dfs)

    assert summary.initial_deposit == Decimal("1000.0")
    assert summary.total_trades > 0
    assert (
        summary.winning_trades + summary.losing_trades + summary.draw_trades == summary.total_trades
    )
    assert len(summary.per_asset_stats) == 3
    assert len(summary.equity_curve) > 0

    # Verify per-asset stats match total
    per_asset_trades_sum = sum(s.total_trades for s in summary.per_asset_stats)
    assert per_asset_trades_sum == summary.total_trades

    # Verify trades have asset tag
    for t in summary.trades:
        assert t.asset in dfs
        assert t.action in (TradeAction.CALL, TradeAction.PUT)
        assert t.outcome in (TradeOutcome.WIN, TradeOutcome.LOSS, TradeOutcome.DRAW)


def test_portfolio_backtest_empty_data() -> None:
    config = PortfolioBacktestConfig(
        assets=["EURUSD_otc"],
        timeframe_seconds=60,
        initial_deposit=Decimal("500.0"),
    )
    engine = PortfolioBacktestEngine(config)
    summary = engine.run({})

    assert summary.initial_deposit == Decimal("500.0")
    assert summary.total_trades == 0
    assert summary.final_balance == Decimal("500.0")
    assert len(summary.trades) == 0
    assert len(summary.per_asset_stats) == 0
