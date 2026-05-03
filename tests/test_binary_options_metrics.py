from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from strat_trade.domain.binary_options_metrics import compute_binary_options_signal_metrics


def test_bo_metrics_call_put_vectorized() -> None:
    # Two settled calls: one win (price up), one loss; one settled put: win (price down).
    close = np.array([100.0, 101.0, 99.0, 98.0, 97.0], dtype="float64")
    sig = np.array([1.0, 1.0, -1.0, 0.0, 1.0], dtype="float64")
    df = pd.DataFrame({"close": close, "signal": sig})
    m = compute_binary_options_signal_metrics(
        df,
        signal_column="signal",
        expiration_bars=1,
        payout=0.82,
    )
    # index0 call: 100 vs 101 -> win; index1 call: 101 vs 99 -> loss; index2 put: 99 vs 98 -> win
    # index4 call: no future -> excluded
    assert m["total_trades"] == 3
    assert m["wins"] == 2
    assert m["losses"] == 1
    assert m["ties"] == 0
    assert m["winrate_pct"] == pytest.approx(200.0 / 3.0)
    p_win = 2 / 3
    p_loss = 1 / 3
    assert m["expected_value_per_1_usd"] == pytest.approx(p_win * 0.82 - p_loss * 1.0)


def test_bo_metrics_tie_counts() -> None:
    df = pd.DataFrame({"close": [1.0, 1.0, 1.0], "signal": [1.0, -1.0, 0.0]})
    m = compute_binary_options_signal_metrics(df, expiration_bars=1, payout=0.5)
    assert m["total_trades"] == 2
    assert m["wins"] == 0
    assert m["losses"] == 0
    assert m["ties"] == 2


def test_bo_metrics_vectorized_perf_10k() -> None:
    rng = np.random.default_rng(0)
    n = 10_000
    close = np.cumsum(rng.standard_normal(n)).astype("float64") + 100.0
    sig = rng.choice([0.0, 1.0, -1.0], size=n, p=[0.9, 0.05, 0.05]).astype("float64")
    df = pd.DataFrame({"close": close, "signal": sig})
    t0 = time.perf_counter()
    compute_binary_options_signal_metrics(df, expiration_bars=5, payout=0.82)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    # Vectorized path should stay well under a millisecond on CI-sized hardware.
    assert elapsed_ms < 50.0
