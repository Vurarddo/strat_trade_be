from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from strat_trade.domain.entities import Candle


def candles_to_ohlcv_df(candles: list[Candle]) -> pd.DataFrame:
    """Build a lowercase OHLCV frame for pandas-ta (same row order as `candles`)."""
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    vols: list[float] = []
    for c in candles:
        opens.append(float(c.open))
        highs.append(float(c.high))
        lows.append(float(c.low))
        closes.append(float(c.close))
        vols.append(0.0 if c.volume is None else float(c.volume))

    times: list[datetime] = []
    for c in candles:
        t = c.open_time
        times.append(t if t.tzinfo else t.replace(tzinfo=UTC))
    idx = pd.DatetimeIndex(times, name="time")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=idx,
        dtype="float64",
    )
