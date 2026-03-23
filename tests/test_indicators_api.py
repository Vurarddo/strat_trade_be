from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.indicators import router as indicators_router
from tests.test_candles_api import DummySettings, FakeCandleFeed


def test_post_indicators_recent_window_rsi() -> None:
    feed = FakeCandleFeed()
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.state.trading_gateway = feed
    app.state.settings = DummySettings()
    app.include_router(indicators_router, prefix="/api/v1", tags=["Market data"])
    client = TestClient(app)

    r = client.post(
        "/api/v1/market/indicators",
        json={
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "window": {"type": "recent", "count": 5},
            "indicators": [{"key": "r", "id": "rsi", "params": {"period": 2}}],
            "include_candles": False,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["asset"] == "EURUSD_otc"
    assert len(data["open_times"]) == 5
    assert data["candles"] is None
    assert "r" in data["indicators"]
    ind = data["indicators"]["r"]
    assert ind["start_index"] == 1
    assert ind["values"][0] == 100.0
    assert len(ind["values"]) == 4


def test_post_indicators_duplicate_keys_400() -> None:
    feed = FakeCandleFeed()
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.state.trading_gateway = feed
    app.state.settings = DummySettings()
    app.include_router(indicators_router, prefix="/api/v1", tags=["Market data"])
    client = TestClient(app)

    r = client.post(
        "/api/v1/market/indicators",
        json={
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "window": {"type": "recent", "count": 3},
            "indicators": [
                {"key": "x", "id": "rsi", "params": {}},
                {"key": "x", "id": "rsi", "params": {"period": 7}},
            ],
        },
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_MARKET_PARAMETERS"


def test_post_indicators_two_instances() -> None:
    feed = FakeCandleFeed()
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.state.trading_gateway = feed
    app.state.settings = DummySettings()
    app.include_router(indicators_router, prefix="/api/v1", tags=["Market data"])
    client = TestClient(app)

    r = client.post(
        "/api/v1/market/indicators",
        json={
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "window": {"type": "recent", "count": 10},
            "indicators": [
                {"key": "fast", "id": "rsi", "params": {"period": 2}},
                {"key": "slow", "id": "rsi", "params": {"period": 4}},
            ],
            "include_candles": True,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data["indicators"]) == {"fast", "slow"}
    assert len(data["candles"]) == 10
    assert data["indicators"]["fast"]["params"] == {"period": 2}
    assert data["indicators"]["slow"]["params"] == {"period": 4}
    assert data["indicators"]["fast"]["start_index"] == 1
    assert data["indicators"]["slow"]["start_index"] == 3
    assert len(data["indicators"]["fast"]["values"]) == 9
    assert len(data["indicators"]["slow"]["values"]) == 7


def test_post_indicators_macd_and_rsi_together() -> None:
    feed = FakeCandleFeed()
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.state.trading_gateway = feed
    app.state.settings = DummySettings()
    app.include_router(indicators_router, prefix="/api/v1", tags=["Market data"])
    client = TestClient(app)

    r = client.post(
        "/api/v1/market/indicators",
        json={
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "window": {"type": "recent", "count": 50},
            "indicators": [
                {"key": "rsi_14", "id": "rsi", "params": {"period": 14}},
                {
                    "key": "macd_hist",
                    "id": "macd",
                    "params": {
                        "fast_period": 12,
                        "slow_period": 26,
                        "signal_period": 9,
                        "component": "hist",
                    },
                },
            ],
            "include_candles": False,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["candles"] is None
    assert set(data["indicators"]) == {"rsi_14", "macd_hist"}
    assert data["indicators"]["macd_hist"]["params"]["component"] == "hist"
    assert data["indicators"]["macd_hist"]["start_index"] > 0
    assert len(data["indicators"]["macd_hist"]["values"]) > 0
