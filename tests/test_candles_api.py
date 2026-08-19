from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.candles import router as candles_router
from strat_trade.domain.entities import Candle

_BASE = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)


def _bar(i: int) -> Candle:
    t = _BASE + timedelta(minutes=i)
    return Candle(
        open_time=t,
        open=Decimal("1"),
        high=Decimal("2"),
        low=Decimal("0.5"),
        close=Decimal("1.5"),
        volume=Decimal("100"),
    )


class FakeCandleFeed:
    """Returns a fixed timeline of minute bars; emulates broker window + count semantics."""

    def __init__(self) -> None:
        self.all_bars = [_bar(i) for i in range(50)]
        self.calls: list[tuple[object, ...]] = []

    async def get_candles(
        self,
        asset: str,
        timeframe: int | str,
        *,
        count: int,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        self.calls.append((asset, timeframe, count, end_time))
        if end_time is not None:
            cap = end_time
        else:
            cap = self.all_bars[-1].open_time + timedelta(minutes=1)
        eligible = [c for c in self.all_bars if c.open_time <= cap]
        if len(eligible) >= count:
            return eligible[-count:]
        return eligible


class DummySettings:
    max_candles_per_request = 500
    max_candles_range_total = 25_000


@pytest.fixture
def app_candles() -> tuple[FastAPI, FakeCandleFeed]:
    feed = FakeCandleFeed()
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.state.trading_gateway = feed
    app.state.settings = DummySettings()
    app.include_router(candles_router, prefix="/api/v1", tags=["Market data"])
    return app, feed


def test_candles_pagination_cursor_chain(app_candles: tuple[FastAPI, FakeCandleFeed]) -> None:
    app, feed = app_candles
    client = TestClient(app)
    r1 = client.get(
        "/api/v1/market/candles",
        params={
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "count": 5,
        },
    )
    assert r1.status_code == 200
    p1 = r1.json()
    assert len(p1["candles"]) == 5
    assert p1["has_more"] is True
    assert p1["next_cursor"] is not None
    assert p1.get("total") is None

    r2 = client.get(
        "/api/v1/market/candles",
        params={
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "count": 5,
            "cursor": p1["next_cursor"],
        },
    )
    assert r2.status_code == 200
    p2 = r2.json()
    assert len(p2["candles"]) == 5
    t1_oldest = datetime.fromisoformat(p1["candles"][0]["open_time"])
    t2_newest = datetime.fromisoformat(p2["candles"][-1]["open_time"])
    assert t2_newest < t1_oldest

    times_p1 = {c["open_time"] for c in p1["candles"]}
    times_p2 = {c["open_time"] for c in p2["candles"]}
    assert times_p1.isdisjoint(times_p2)

    assert len(feed.calls) == 2


def test_cursor_and_end_at_rejected(app_candles: tuple[FastAPI, FakeCandleFeed]) -> None:
    app, _feed = app_candles
    client = TestClient(app)
    when = datetime(2025, 1, 1, 15, 0, tzinfo=UTC).isoformat()
    cur = datetime(2025, 1, 1, 14, 0, tzinfo=UTC).isoformat()
    r = client.get(
        "/api/v1/market/candles",
        params={
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "count": 3,
            "end_at": when,
            "cursor": cur,
        },
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_MARKET_PARAMETERS"


def test_candles_range_returns_full_window(app_candles: tuple[FastAPI, FakeCandleFeed]) -> None:
    app, _feed = app_candles
    client = TestClient(app)
    t0 = (_BASE + timedelta(minutes=10)).isoformat()
    t1 = (_BASE + timedelta(minutes=20)).isoformat()
    r = client.get(
        "/api/v1/market/candles/range",
        params={
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "from": t0,
            "to": t1,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 11
    assert len(body["candles"]) == 11
    assert body["has_more"] is False
    assert body["next_cursor"] is None


def test_range_disjoint_sets_overlap_false_and_hint(
    app_candles: tuple[FastAPI, FakeCandleFeed],
) -> None:
    app, _feed = app_candles
    client = TestClient(app)
    t0 = (_BASE + timedelta(minutes=100)).isoformat()
    t1 = (_BASE + timedelta(minutes=101)).isoformat()
    r = client.get(
        "/api/v1/market/candles/range",
        params={
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "from": t0,
            "to": t1,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["broker_overlap"] is False
    assert "candles_empty_hint" not in body
    assert "range_data_source" not in body


def test_range_rejects_future_to(app_candles: tuple[FastAPI, FakeCandleFeed]) -> None:
    app, _feed = app_candles
    client = TestClient(app)
    t0 = (_BASE + timedelta(minutes=10)).isoformat()
    t1 = "2099-01-01T00:00:00+00:00"
    r = client.get(
        "/api/v1/market/candles/range",
        params={
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "from": t0,
            "to": t1,
        },
    )
    assert r.status_code == 400
    assert "future" in r.json()["error"]["message"].lower()


def test_candles_response_includes_volume(app_candles: tuple[FastAPI, FakeCandleFeed]) -> None:
    app, _feed = app_candles
    client = TestClient(app)
    r = client.get(
        "/api/v1/market/candles",
        params={
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "count": 2,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["candles"]) == 2
    for c in data["candles"]:
        assert c["volume"] == 100.0


def test_pocket_option_gateway_payload_normalization() -> None:
    from strat_trade.adapters.pocket_option_gateway import (
        _candle_from_dict,
        _list_to_candle_dict,
        _normalize_candles_payload,
    )

    # Advanced candle dict with volume as string or number
    raw_adv = [
        {
            "symbol": "EURUSD_otc",
            "timestamp": 1700000000,
            "open": "1.2345",
            "high": "1.2350",
            "low": "1.2340",
            "close": "1.2348",
            "volume": "85",
        }
    ]
    norm = _normalize_candles_payload(raw_adv)
    assert len(norm) == 1
    candle = _candle_from_dict(norm[0])
    assert candle.volume == Decimal("85")

    # Tuple candle with 6 elements [t, open, high, low, close, volume]
    tuple_row = [1700000000, 1.2345, 1.2350, 1.2340, 1.2348, 42.0]
    candle_dict = _list_to_candle_dict(tuple_row)
    assert candle_dict["volume"] == 42.0


def test_market_assets_endpoint(app_candles: tuple[FastAPI, FakeCandleFeed]) -> None:
    app, _ = app_candles
    client = TestClient(app)
    r = client.get("/api/v1/market/assets")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) > 0
    symbols = {a["symbol"] for a in data}
    assert "EURUSD_otc" in symbols
    for a in data:
        assert "symbol" in a
        assert "name" in a
        assert "payout" in a
        assert "is_otc" in a
