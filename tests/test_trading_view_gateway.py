from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from strat_trade.adapters.trading_view_gateway import (
    TradingViewGateway,
    normalize_tradingview_ohlcv,
)
from strat_trade.domain.errors import InvalidMarketParametersError


def test_normalize_tradingview_ohlcv_sorts_and_columns() -> None:
    raw = pd.DataFrame(
        {
            "symbol": ["X", "X"],
            "open": [2.0, 1.0],
            "high": [2.5, 1.5],
            "low": [1.5, 0.5],
            "close": [2.0, 1.0],
            "volume": [10.0, 5.0],
        },
        index=pd.DatetimeIndex(
            ["2025-01-02T00:00:00Z", "2025-01-01T00:00:00Z"],
            name="datetime",
        ),
    )
    out = normalize_tradingview_ohlcv(raw)
    assert list(out.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert out["timestamp"].is_monotonic_increasing
    assert list(out["close"]) == [1.0, 2.0]
    assert list(out.index) == [0, 1]


def test_trading_view_gateway_delegates_to_client() -> None:
    client = MagicMock()
    client.get_hist.return_value = pd.DataFrame(
        {
            "symbol": ["NASDAQ:AAPL"],
            "open": [1.0],
            "high": [2.0],
            "low": [0.5],
            "close": [1.5],
            "volume": [100.0],
        },
        index=pd.DatetimeIndex(["2025-01-01T00:00:00Z"], name="datetime"),
    )
    gw = TradingViewGateway(client=client)
    df = gw.get_historical_ohlcv("AAPL", "NASDAQ", "1d", n_bars=1)
    client.get_hist.assert_called_once()
    assert len(df) == 1
    assert df.loc[0, "close"] == 1.5


def test_trading_view_gateway_rejects_bad_interval() -> None:
    gw = TradingViewGateway(client=MagicMock())
    with pytest.raises(InvalidMarketParametersError):
        gw.get_historical_ohlcv("AAPL", "NASDAQ", "not-a-timeframe", n_bars=10)
