from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes import strategy as strategy_route
from strat_trade.api.routes.strategy import router as strategy_router
from strat_trade.domain.indicators.types import IndicatorSeries
from tests.test_candles_api import DummySettings, FakeCandleFeed


class _FakePsarCalculator:
    def compute(self, candles):
        values = [None, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0]
        return IndicatorSeries(
            indicator_id="psar",
            params={"step": 0.02, "max_step": 0.2, "component": "sar"},
            values=values[: len(candles)],
        )


class _FakeRegistry:
    def build(self, indicator_id: str, params: dict[str, object]):
        assert indicator_id == "psar"
        return _FakePsarCalculator()


def _app() -> FastAPI:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.state.trading_gateway = FakeCandleFeed()
    app.state.settings = DummySettings()
    app.include_router(strategy_router, prefix="/api/v1", tags=["Backtests"])
    return app


def _payload(*, expiry_seconds: int) -> dict:
    return {
        "asset": "EURUSD_otc",
        "timeframe_seconds": 15,
        "expiry_seconds": expiry_seconds,
        "window": {
            "type": "range",
            "from": "2025-01-01T12:43:00Z",
            "to": "2025-01-01T12:49:00Z",
        },
        "indicators": [
            {"key": "psar_main", "id": "psar", "params": {"step": 0.02, "max_step": 0.2}}
        ],
        "strategy": {
            "type": "psar_reversal",
            "signal_on_close": True,
            "conditions": [{"indicator_key": "psar_main", "operator": "psar_reversal"}],
        },
    }


def test_post_strategy_test_winrate_happy_path(monkeypatch) -> None:
    monkeypatch.setattr(strategy_route, "default_indicator_registry", lambda: _FakeRegistry())

    client = TestClient(_app())
    response = client.post("/api/v1/strategy/test-winrate", json=_payload(expiry_seconds=30))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["asset"] == "EURUSD_otc"
    assert body["timeframe_seconds"] == 15
    assert body["expiry_seconds"] == 30
    assert body["total_signals"] == 5
    assert body["wins"] == 0
    assert body["losses"] == 3
    assert body["skipped_signals"] == 2
    assert body["winrate_percent"] == 0.0


def test_post_strategy_test_winrate_expiry_must_be_divisible() -> None:
    client = TestClient(_app())
    response = client.post("/api/v1/strategy/test-winrate", json=_payload(expiry_seconds=20))

    assert response.status_code == 422
