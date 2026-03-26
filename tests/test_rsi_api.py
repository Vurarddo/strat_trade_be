from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.indicators import router as indicators_router
from strat_trade.api.routes.market_indicators_batch import router as market_indicators_batch_router
from strat_trade.domain.entities import Candle

_BASE = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)


class DummySettings:
    max_candles_per_request = 500
    max_candles_range_total = 25_000
    max_candles_range_fetch_rounds = 80
    max_indicators_per_market_request = 32


def _bar(i: int, close: str = "1.5") -> Candle:
    t = _BASE + timedelta(minutes=i)
    return Candle(
        open_time=t,
        open=Decimal("1"),
        high=Decimal("2"),
        low=Decimal("0.5"),
        close=Decimal(close),
        volume=Decimal("100"),
    )


class FakeCandleFeed:
    def __init__(self) -> None:
        self.all_bars = [_bar(i) for i in range(50)]

    async def get_candles(
        self,
        asset: str,
        timeframe: int | str,
        *,
        count: int,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        if end_time is not None:
            cap = end_time
        else:
            cap = self.all_bars[-1].open_time + timedelta(minutes=1)
        eligible = [c for c in self.all_bars if c.open_time <= cap]
        if len(eligible) >= count:
            return eligible[-count:]
        return eligible


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(indicators_router, prefix="/api/v1")
    app.include_router(market_indicators_batch_router, prefix="/api/v1")

    feed = FakeCandleFeed()
    app.state.trading_gateway = feed
    app.state.settings = DummySettings()
    return TestClient(app)


def test_get_rsi_indicator_info(client: TestClient) -> None:
    r = client.get("/api/v1/indicators/rsi")
    assert r.status_code == 200
    body = r.json()
    assert body["indicator_id"] == "rsi_wilder"
    assert "Wilder" in body["title"]
    assert len(body["parameters"]) == 1
    assert body["parameters"][0]["name"] == "length"


def test_get_bollinger_bands_indicator_info(client: TestClient) -> None:
    r = client.get("/api/v1/indicators/bollinger-bands")
    assert r.status_code == 200
    body = r.json()
    assert body["indicator_id"] == "bollinger_bands"
    assert "Bollinger" in body["title"]
    assert body["outputs"] == ["middle", "upper", "lower"]
    names = {p["name"] for p in body["parameters"]}
    assert names == {"length", "mult"}


def test_post_market_indicators_requires_enough_bars(client: TestClient) -> None:
    payload = {
        "asset": "EURUSD_otc",
        "timeframe_seconds": 60,
        "count": 10,
        "indicators": [{"indicator_id": "rsi_wilder", "params": {"length": 14}}],
    }
    r = client.post("/api/v1/market/indicators", json=payload)
    assert r.status_code == 400
    assert "count must be >=" in r.json()["error"]["message"]


def test_post_market_indicators_candles_plus_indicators_by_open_time(client: TestClient) -> None:
    payload = {
        "asset": "EURUSD_otc",
        "timeframe_seconds": 60,
        "count": 40,
        "indicators": [
            {"indicator_id": "rsi_wilder", "params": {"length": 14}, "key": "rsi_14"},
            {"indicator_id": "rsi_wilder", "params": {"length": 21}, "key": "rsi_21"},
        ],
    }
    r = client.post("/api/v1/market/indicators", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["align_by"] == "open_time"
    assert "bars" not in body
    assert len(body["candles"]) == 40
    c14 = body["candles"][14]
    ot14 = c14["open_time"]
    ind0, ind1 = body["indicators"][0], body["indicators"][1]
    assert ind0["params"]["length"] == 14
    assert ind1["params"]["length"] == 21
    rsi14_pts = ind0["outputs"]["rsi"]
    rsi21_pts = ind1["outputs"]["rsi"]
    assert {"open_time", "value"} == set(rsi14_pts[0].keys())
    assert any(p["open_time"] == ot14 for p in rsi14_pts)
    assert not any(p["open_time"] == ot14 for p in rsi21_pts)
    c21 = body["candles"][21]
    ot21 = c21["open_time"]
    assert any(p["open_time"] == ot21 for p in rsi21_pts)


def test_post_market_indicators_duplicate_key_rejected(client: TestClient) -> None:
    payload = {
        "asset": "EURUSD_otc",
        "timeframe_seconds": 60,
        "count": 30,
        "indicators": [
            {"indicator_id": "rsi_wilder", "key": "x"},
            {"indicator_id": "rsi_wilder", "key": "x"},
        ],
    }
    r = client.post("/api/v1/market/indicators", json=payload)
    assert r.status_code == 400
    assert "Duplicate indicator key" in r.json()["error"]["message"]


def test_post_market_indicators_bollinger_bands(client: TestClient) -> None:
    payload = {
        "asset": "EURUSD_otc",
        "timeframe_seconds": 60,
        "count": 30,
        "indicators": [{"indicator_id": "bollinger_bands", "params": {"length": 10, "mult": 2.0}}],
    }
    r = client.post("/api/v1/market/indicators", json=payload)
    assert r.status_code == 200
    body = r.json()
    row = body["indicators"][0]
    assert row["indicator_id"] == "bollinger_bands"
    assert row["params"]["length"] == 10
    assert row["params"]["mult"] == 2.0
    assert set(row["outputs"].keys()) == {"middle", "upper", "lower"}
    last_ot = body["candles"][-1]["open_time"]
    assert any(p["open_time"] == last_ot for p in row["outputs"]["middle"])


def test_post_market_indicators_auto_run_keys(client: TestClient) -> None:
    payload = {
        "asset": "EURUSD_otc",
        "timeframe_seconds": 60,
        "count": 30,
        "indicators": [
            {"indicator_id": "rsi_wilder", "params": {"length": 14}},
            {"indicator_id": "rsi_wilder", "params": {"length": 21}},
        ],
    }
    r = client.post("/api/v1/market/indicators", json=payload)
    assert r.status_code == 200
    last_ot = r.json()["candles"][-1]["open_time"]
    inds = r.json()["indicators"]
    assert any(p["open_time"] == last_ot for p in inds[0]["outputs"]["rsi"])
    assert any(p["open_time"] == last_ot for p in inds[1]["outputs"]["rsi"])
