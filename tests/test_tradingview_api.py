from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.tradingview import router as tradingview_router


def _make_app() -> TestClient:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(tradingview_router, prefix="/api/v1", tags=["TradingView"])
    return TestClient(app)


def test_tradingview_candles_ok() -> None:
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2025-01-01 12:00:00+00:00"]),
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1234.0],
        },
    )
    mock_inst = MagicMock()
    mock_inst.fetch_ohlcv.return_value = df
    with patch("strat_trade.api.routes.tradingview.TradingViewGateway", return_value=mock_inst):
        client = _make_app()
        r = client.get(
            "/api/v1/tradingview/candles",
            params={"symbol": "BTCUSD", "exchange": "BINANCE", "interval": "1h", "limit": 10},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 1
    row = data[0]
    assert row["open"] == 100.0
    assert row["high"] == 101.0
    assert row["low"] == 99.0
    assert row["close"] == 100.5
    assert row["volume"] == 1234.0
    mock_inst.fetch_ohlcv.assert_called_once()


def test_tradingview_candles_invalid_interval_400() -> None:
    mock_inst = MagicMock()
    with patch("strat_trade.api.routes.tradingview.TradingViewGateway", return_value=mock_inst):
        client = _make_app()
        r = client.get(
            "/api/v1/tradingview/candles",
            params={"symbol": "BTCUSD", "exchange": "BINANCE", "interval": "2h"},
        )
    assert r.status_code == 400
    mock_inst.fetch_ohlcv.assert_not_called()


def test_tradingview_candles_empty_404() -> None:
    mock_inst = MagicMock()
    mock_inst.fetch_ohlcv.return_value = pd.DataFrame(
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    with patch("strat_trade.api.routes.tradingview.TradingViewGateway", return_value=mock_inst):
        client = _make_app()
        r = client.get(
            "/api/v1/tradingview/candles",
            params={"symbol": "UNKNOWN", "exchange": "BINANCE", "interval": "1d"},
        )
    assert r.status_code == 404


def test_tradingview_candles_limit_default_and_cap() -> None:
    mock_inst = MagicMock()
    mock_inst.fetch_ohlcv.return_value = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2025-01-01 12:00:00+00:00"]),
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [0.0],
        },
    )
    with patch("strat_trade.api.routes.tradingview.TradingViewGateway", return_value=mock_inst):
        client = _make_app()
        r = client.get(
            "/api/v1/tradingview/candles",
            params={"symbol": "X", "exchange": "Y", "interval": "1m"},
        )
    assert r.status_code == 200
    _call = mock_inst.fetch_ohlcv.call_args
    assert _call.kwargs["n_bars"] == 500

    r2 = client.get(
        "/api/v1/tradingview/candles",
        params={"symbol": "X", "exchange": "Y", "interval": "1m", "limit": 5001},
    )
    assert r2.status_code == 422
