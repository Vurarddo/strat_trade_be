"""Sanity: OHLCV DataFrame (~100 bars) → Candles → `ta` RSI via domain calculator."""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal

import pandas as pd

from strat_trade.domain.entities import Candle
from strat_trade.domain.indicators import RsiCalculator


def test_hundred_row_ohlcv_dataframe_ta_rsi_sanity() -> None:
    n = 100
    idx = pd.date_range("2025-01-01", periods=n, freq="1min", tz="UTC")
    close = pd.Series(range(100, 100 + n), dtype="float64", index=idx)
    df = pd.DataFrame(
        {
            "Open": close,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Volume": 1.0,
        },
        index=idx,
    )
    candles: list[Candle] = []
    for ts, row in df.iterrows():
        ts_utc = ts.to_pydatetime()
        if ts_utc.tzinfo is None:
            ts_utc = ts_utc.replace(tzinfo=UTC)
        else:
            ts_utc = ts_utc.astimezone(UTC)
        o, h, lo, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        vol = Decimal(str(row["Volume"]))
        candles.append(
            Candle(open_time=ts_utc, open=o, high=h, low=lo, close=c, volume=vol),
        )
    series = RsiCalculator(14).compute(candles)
    assert len(series.values) == n
    assert series.values[-1] is not None
