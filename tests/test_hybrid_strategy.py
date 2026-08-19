from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from strat_trade.domain.strategies.hybrid_multifactors import HybridMultiFactorsStrategy


def _make_sample_df(n: int = 100) -> pd.DataFrame:
    base_t = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    timestamps = [base_t + timedelta(minutes=i) for i in range(n)]

    np.random.seed(123)
    closes = 1.0500 + np.cumsum(np.random.normal(0, 0.0004, n))
    rows = []
    for i in range(n):
        c = float(closes[i])
        o = float(closes[i - 1]) if i > 0 else c
        h = max(o, c) + 0.0002
        low_p = min(o, c) - 0.0002
        rows.append(
            {
                "timestamp": timestamps[i],
                "open": o,
                "high": h,
                "low": low_p,
                "close": c,
                "volume": 80.0,
            }
        )
    return pd.DataFrame(rows)


def test_hybrid_strategy_indicators_computation() -> None:
    strat = HybridMultiFactorsStrategy()
    df = _make_sample_df(100)
    prep = strat.prepare_dataframe(df)

    assert "ema_fast" in prep.columns
    assert "ema_mid" in prep.columns
    assert "ema_slow" in prep.columns
    assert "rsi" in prep.columns
    assert "stoch_k" in prep.columns
    assert "bb_high" in prep.columns
    assert "atr" in prep.columns
    assert "adx" in prep.columns


def test_hybrid_strategy_evaluate_bar() -> None:
    strat = HybridMultiFactorsStrategy(adaptive_expiration_enabled=True)
    df = _make_sample_df(100)
    prep = strat.prepare_dataframe(df)

    res = strat.evaluate_bar(prep, 60)
    assert res.regime in (
        "trending",
        "ranging",
        "transitional",
        "warming_up",
        "volatility_spike_suppressed",
    )
    assert 0.0 <= res.confidence <= 1.0
    assert res.expiration_bars >= 1
