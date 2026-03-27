from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.market_indicators_gemini import (
    router as market_indicators_gemini_router,
)
from strat_trade.domain.entities import Candle

_BASE = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)


class DummySettingsGemini:
    max_candles_per_request = 500
    max_candles_range_total = 25_000
    max_candles_range_fetch_rounds = 80
    max_indicators_per_market_request = 32
    google_gemini_model = "gemini-test-model"


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


class FakeLlmMarketAnalysis:
    def __init__(self) -> None:
        self.last_user_content: str | None = None
        self.last_system: str | None = None

    async def analyze(
        self,
        *,
        system_instruction: str,
        user_content: str,
        model: str,
    ) -> str:
        self.last_system = system_instruction
        self.last_user_content = user_content
        assert model == "gemini-test-model"
        return json.dumps(
            {
                "direction": "NEUTRAL",
                "expiration": "1 min",
                "win_probability": "50%",
                "analysis": "mock analysis body",
                "entry_time": "2026-03-27T12:34:00Z",
                "close_time": "2026-03-27T12:36:00Z",
            },
        )


@pytest.fixture
def gemini_client() -> TestClient:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(market_indicators_gemini_router, prefix="/api/v1")

    feed = FakeCandleFeed()
    app.state.trading_gateway = feed
    app.state.settings = DummySettingsGemini()
    app.state.gemini_llm = FakeLlmMarketAnalysis()
    return TestClient(app)


def test_post_market_indicators_gemini_returns_llm_text(gemini_client: TestClient) -> None:
    payload = {
        "asset": "EURUSD_otc",
        "timeframe_seconds": 60,
        "count": 40,
        "indicators": [{"indicator_id": "rsi_wilder", "params": {"length": 14}, "key": "rsi_14"}],
        "expiration_time_seconds": 120,
    }
    r = gemini_client.post("/api/v1/market/indicators/gemini", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["direction"] == "NEUTRAL"
    assert body["expiration"] == "1 min"
    assert body["win_probability"] == "50%"
    assert body["analysis"] == "mock analysis body"
    assert body["entry_time"] == "2026-03-27T12:34:00Z"
    assert body["close_time"] == "2026-03-27T12:36:00Z"
    assert body["model"] == "gemini-test-model"
    assert body["asset"] == "EURUSD_otc"
    assert body["timeframe_seconds"] == 60

    app = gemini_client.app
    fake = app.state.gemini_llm
    assert isinstance(fake, FakeLlmMarketAnalysis)
    assert fake.last_user_content is not None
    assert fake.last_system is not None
    assert "ProTrader AI" in fake.last_system
    parsed = json.loads(fake.last_user_content)
    assert "candles" in parsed and "indicators" in parsed
    assert parsed.get("expiration_time_seconds") == 120
    assert len(parsed["candles"]) == 40


def test_post_market_indicators_gemini_503_without_key() -> None:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(market_indicators_gemini_router, prefix="/api/v1")
    app.state.trading_gateway = FakeCandleFeed()
    app.state.settings = DummySettingsGemini()
    app.state.gemini_llm = None
    client = TestClient(app)
    payload = {
        "asset": "EURUSD_otc",
        "timeframe_seconds": 60,
        "count": 40,
        "indicators": [{"indicator_id": "rsi_wilder", "params": {"length": 14}}],
    }
    r = client.post("/api/v1/market/indicators/gemini", json=payload)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "GEMINI_NOT_CONFIGURED"
