from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def compute_binary_options_signal_metrics(
    df: pd.DataFrame,
    *,
    signal_column: str = "signal",
    expiration_bars: int,
    payout: float,
    close_column: str = "close",
) -> dict[str, Any]:
    """
    Vectorized binary-option outcome stats from a signal column vs future close.

    Signals: ``1`` = Call, ``-1`` = Put, ``0`` = flat. Settlement compares entry
    ``close`` at the signal bar to ``close`` shifted by ``-expiration_bars``.
    """
    if expiration_bars < 1:
        msg = "expiration_bars must be >= 1."
        raise ValueError(msg)
    if payout < 0:
        msg = "payout must be >= 0."
        raise ValueError(msg)
    if signal_column not in df.columns:
        msg = f"Missing signal column {signal_column!r}."
        raise ValueError(msg)
    if close_column not in df.columns:
        msg = f"Missing close column {close_column!r}."
        raise ValueError(msg)

    sig = df[signal_column].to_numpy(dtype="float64", copy=False)
    close = df[close_column].to_numpy(dtype="float64", copy=False)
    future = df[close_column].shift(-expiration_bars).to_numpy(dtype="float64", copy=False)

    active = np.not_equal(sig, 0.0)
    settled = active & np.isfinite(future) & np.isfinite(close)

    is_call = np.equal(sig, 1.0) & settled
    is_put = np.equal(sig, -1.0) & settled

    gt = future > close
    lt = future < close
    eq = np.equal(future, close)

    wins = (is_call & gt) | (is_put & lt)
    losses = (is_call & lt) | (is_put & gt)
    ties = (is_call & eq) | (is_put & eq)

    total_trades = int(np.count_nonzero(settled))
    w = int(np.count_nonzero(wins))
    l_ = int(np.count_nonzero(losses))
    t = int(np.count_nonzero(ties))

    winrate_pct = (w / total_trades * 100.0) if total_trades else 0.0
    if total_trades:
        p_win = w / total_trades
        p_loss = l_ / total_trades
        expected_value_per_1_usd = (p_win * payout) - (p_loss * 1.0)
    else:
        expected_value_per_1_usd = 0.0

    return {
        "total_trades": total_trades,
        "wins": w,
        "losses": l_,
        "ties": t,
        "winrate_pct": float(winrate_pct),
        "expected_value_per_1_usd": float(expected_value_per_1_usd),
    }
