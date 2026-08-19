from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from strat_trade.domain.optimizer.grid_search import StrategyOptimizerEngine


def _make_dummy_ohlcv(n: int = 150) -> pd.DataFrame:
    np.random.seed(42)
    base_price = 1.0850
    t0 = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)

    walk = np.cumsum(np.random.normal(0, 0.0003, n)) + np.sin(np.linspace(0, 10, n)) * 0.001
    prices = base_price + walk

    data = []
    for i in range(n):
        c = float(prices[i])
        o = float(prices[i - 1]) if i > 0 else c
        h = max(o, c) + abs(np.random.normal(0, 0.0001))
        low_val = min(o, c) - abs(np.random.normal(0, 0.0001))
        t = t0 + timedelta(minutes=i)
        data.append(
            {"timestamp": t, "open": o, "high": h, "low": low_val, "close": c, "volume": 100}
        )
    return pd.DataFrame(data)


def test_strategy_optimizer_grid_search():
    df = _make_dummy_ohlcv(180)
    optimizer = StrategyOptimizerEngine(
        strategy_name="bollinger_atr_reversion",
        asset="EURUSD_otc",
        timeframe_seconds=60,
        initial_deposit=1000.0,
        payout_rate=0.85,
        max_combinations=20,
    )

    grid = {
        "bb_length": [15, 20],
        "bb_std": [1.8, 2.0],
        "rsi_period": [10, 14],
        "base_expiration_bars": [2, 3],
    }

    report = optimizer.run(df, grid)
    assert report.total_combinations_tested == 16
    assert len(report.results) == 16
    assert report.results[0].rank == 1
    assert report.results[-1].rank == 16
    assert report.best_params is not None
