from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import BacktestConfig, TradeAction
from strat_trade.domain.strategies.registry import get_strategy_instance, list_available_strategies


def _make_dummy_ohlcv(n: int = 150) -> pd.DataFrame:
    np.random.seed(42)
    base_price = 1.0850
    t0 = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)

    # Random walk with oscillation
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
            {
                "timestamp": t,
                "open": o,
                "high": h,
                "low": low_val,
                "close": c,
                "volume": 100 + i,
            }
        )
    return pd.DataFrame(data)


def test_registry_lists_all_eight_strategies():
    strategies = list_available_strategies()
    assert len(strategies) == 8
    ids = {s["id"] for s in strategies}
    assert "hybrid_multifactors" in ids
    assert "bollinger_atr_reversion" in ids
    assert "ema_pullback_trend" in ids
    assert "rsi_stochastic_extreme" in ids
    assert "macd_divergence_break" in ids
    assert "volatility_squeeze_breakout" in ids
    assert "supertrend_adx_momentum" in ids
    assert "support_resistance_bounce" in ids


@pytest.mark.parametrize(
    "strat_id",
    [
        "hybrid_multifactors",
        "bollinger_atr_reversion",
        "ema_pullback_trend",
        "rsi_stochastic_extreme",
        "macd_divergence_break",
        "volatility_squeeze_breakout",
        "supertrend_adx_momentum",
        "support_resistance_bounce",
    ],
)
def test_all_strategies_evaluation_and_backtest(strat_id: str):
    df = _make_dummy_ohlcv(200)
    strat = get_strategy_instance(strat_id)
    df_prepared = strat.prepare_dataframe(df)
    assert len(df_prepared) == 200

    # Evaluate bar
    sig = strat.evaluate_bar(df_prepared, 100)
    assert sig is not None
    assert sig.action in (TradeAction.CALL, TradeAction.PUT, None)
    assert 0.0 <= sig.confidence <= 1.0

    # Backtest engine run
    cfg = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        strategy_name=strat_id,
        initial_deposit=1000.0,
        payout_rate=0.85,
    )
    engine = BinaryBacktestEngine(cfg)
    summary = engine.run(df)
    assert summary is not None
    assert summary.final_balance > 0
