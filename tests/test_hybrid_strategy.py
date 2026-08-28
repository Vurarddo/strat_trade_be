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
        "adx_sub_threshold_choppy",
    )
    assert 0.0 <= res.confidence <= 1.0
    assert res.expiration_bars >= 1


def _make_prepared_df(
    *,
    close: float = 1.0500,
    ema_fast: float = 1.0500,
    ema_mid: float = 1.0490,
    ema_slow: float = 1.0480,
    rsi: float = 55.0,
    stoch_k: float = 60.0,
    stoch_d: float = 50.0,
    bb_high: float = 1.0550,
    bb_low: float = 1.0450,
    bb_mid: float = 1.0500,
    bb_pband: float = 0.50,
    adx: float = 26.0,
    adx_pos: float = 28.0,
    adx_neg: float = 14.0,
    atr: float = 0.0005,
    atr_sma: float = 0.0005,
) -> pd.DataFrame:
    rows = []
    base_t = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    for i in range(60):
        rows.append(
            {
                "timestamp": base_t + timedelta(minutes=i),
                "open": close,
                "high": close + 0.0002,
                "low": close - 0.0002,
                "close": close,
                "volume": 100.0,
                "ema_fast": ema_fast,
                "ema_mid": ema_mid,
                "ema_slow": ema_slow,
                "rsi": rsi,
                "stoch_k": stoch_k,
                "stoch_d": stoch_d,
                "bb_high": bb_high,
                "bb_low": bb_low,
                "bb_mid": bb_mid,
                "bb_pband": bb_pband,
                "adx": adx,
                "adx_pos": adx_pos,
                "adx_neg": adx_neg,
                "atr": atr,
                "atr_sma": atr_sma,
            }
        )
    return pd.DataFrame(rows)


def test_hybrid_strategy_adx_sub_threshold_choppy_gating() -> None:
    """Verify ADX < 22.0 gating suppresses trading and flags choppy regime."""
    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0)
    df = _make_prepared_df(adx=19.5, adx_pos=28.0, adx_neg=12.0)
    res = strat.evaluate_bar(df, 55)

    assert res.action is None
    assert res.confidence == 0.0
    assert res.regime == "adx_sub_threshold_choppy"
    assert res.metadata["adx"] == 19.5


def test_hybrid_strategy_bullish_3way_concordance_call() -> None:
    """Verify bullish multi-indicator concordance generates CALL signal."""
    from strat_trade.domain.backtest.models import TradeAction

    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0)
    df = _make_prepared_df(
        close=1.0505,
        ema_fast=1.0500,
        ema_mid=1.0485,
        rsi=56.0,
        stoch_k=65.0,
        stoch_d=48.0,
        adx=26.5,
        adx_pos=29.0,
        adx_neg=11.0,
    )
    res = strat.evaluate_bar(df, 55)

    assert res.action == TradeAction.CALL
    assert res.confidence >= 0.70
    assert res.regime == "trending"


def test_hybrid_strategy_bearish_3way_concordance_put() -> None:
    """Verify bearish multi-indicator concordance generates PUT signal."""
    from strat_trade.domain.backtest.models import TradeAction

    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0)
    df = _make_prepared_df(
        close=1.0475,
        ema_fast=1.0480,
        ema_mid=1.0495,
        rsi=40.0,
        stoch_k=25.0,
        stoch_d=40.0,
        adx=25.0,
        adx_pos=10.0,
        adx_neg=28.0,
    )
    res = strat.evaluate_bar(df, 55)

    assert res.action == TradeAction.PUT
    assert res.confidence >= 0.70
    assert res.regime == "trending"


def test_hybrid_strategy_rsi_conflict_suppression() -> None:
    """Verify signal is suppressed when RSI conflicts with directional trend."""
    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0)

    # Bullish trend but RSI overbought (> 68)
    df_overbought = _make_prepared_df(
        close=1.0505,
        ema_fast=1.0500,
        ema_mid=1.0485,
        rsi=72.0,
        stoch_k=65.0,
        stoch_d=48.0,
        adx=26.5,
        adx_pos=29.0,
        adx_neg=11.0,
    )
    res_ob = strat.evaluate_bar(df_overbought, 55)
    assert res_ob.action is None

    # Bullish trend but RSI sub-corridor (< 45)
    df_sub = _make_prepared_df(
        close=1.0505,
        ema_fast=1.0500,
        ema_mid=1.0485,
        rsi=42.0,
        stoch_k=65.0,
        stoch_d=48.0,
        adx=26.5,
        adx_pos=29.0,
        adx_neg=11.0,
    )
    res_sub = strat.evaluate_bar(df_sub, 55)
    assert res_sub.action is None


def test_hybrid_strategy_ema_conflict_suppression() -> None:
    """Verify signal is suppressed when EMA ribbon alignment conflicts."""
    strat = HybridMultiFactorsStrategy(adx_min_threshold=22.0)

    # Bullish ADX/RSI/Stoch but EMA fast < EMA mid (bearish ribbon)
    df_ema_conflict = _make_prepared_df(
        close=1.0505,
        ema_fast=1.0480,
        ema_mid=1.0500,
        rsi=56.0,
        stoch_k=65.0,
        stoch_d=48.0,
        adx=26.5,
        adx_pos=29.0,
        adx_neg=11.0,
    )
    res = strat.evaluate_bar(df_ema_conflict, 55)
    assert res.action is None
