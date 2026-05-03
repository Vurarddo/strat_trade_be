from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.indicator_catalog import router as indicator_catalog_router
from strat_trade.api.routes.indicators import router as indicators_router
from strat_trade.domain.entities import Candle
from tests.test_candles_api import DummySettings, FakeCandleFeed

_BASE = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)


class TrendingCandleFeed(FakeCandleFeed):
    """OHLC similar to trending prices so RSI(pandas-ta) is defined (flat closes → NaN RSI)."""

    def __init__(self) -> None:
        super().__init__()
        self.all_bars = [
            Candle(
                open_time=_BASE + timedelta(minutes=i),
                open=Decimal(str(100 + i * 0.1)),
                high=Decimal(str(101 + i * 0.1)),
                low=Decimal(str(99 + i * 0.1)),
                close=Decimal(str(100 + i * 0.1)),
                volume=Decimal("100"),
            )
            for i in range(50)
        ]


def test_get_indicators_catalog() -> None:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.state.trading_gateway = FakeCandleFeed()
    app.state.settings = DummySettings()
    app.include_router(indicator_catalog_router, prefix="/api/v1", tags=["Market data"])
    client = TestClient(app)
    r = client.get("/api/v1/indicators")
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 32
    ids = {row["id"] for row in data}
    assert "rsi" in ids and "macd" in ids and "moving_average" in ids


def test_post_indicators_recent_window_rsi() -> None:
    feed = TrendingCandleFeed()
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
    assert ind["start_index"] >= 0
    assert all(0.0 <= v <= 100.0 for v in ind["values"])


def test_post_indicators_duplicate_keys_400() -> None:
    feed = TrendingCandleFeed()
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
    feed = TrendingCandleFeed()
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
    assert data["indicators"]["fast"]["params"]["period"] == 2
    assert data["indicators"]["slow"]["params"]["period"] == 4
    assert data["indicators"]["fast"]["start_index"] >= 0
    assert data["indicators"]["slow"]["start_index"] >= 0
    assert len(data["indicators"]["fast"]["values"]) >= 1
    assert len(data["indicators"]["slow"]["values"]) >= 1
