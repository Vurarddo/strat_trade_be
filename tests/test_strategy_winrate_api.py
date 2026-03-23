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


class _FakeCciCalculator:
    """Fixed CCI path: BUY at index 2, SELL at index 4 (seven-bar window)."""

    def compute(self, candles):
        template = [None, 90.0, 105.0, -50.0, -120.0, 80.0, 99.0]
        values = template[: len(candles)]
        return IndicatorSeries(
            indicator_id="cci",
            params={"period": 20, "constant": 0.015},
            values=values,
        )


class _FakeRegistryCci:
    def build(self, indicator_id: str, params: dict[str, object]):
        assert indicator_id == "cci"
        return _FakeCciCalculator()


class _FakePsarAlignedWithCciBuyAt2:
    """PSAR BUY only at bar index 2 (matches _FakeCciBuyAt2)."""

    def compute(self, candles):
        base = [None, 2.0, 1.0]
        rest = [2.0] * max(0, len(candles) - len(base))
        values = (base + rest)[: len(candles)]
        return IndicatorSeries(
            indicator_id="psar",
            params={"step": 0.02, "max_step": 0.2, "component": "sar"},
            values=values,
        )


class _FakeCciBuyAt2:
    """CCI BUY at index 2 only (cross +100: cci[1]=99, cci[2]=100)."""

    def compute(self, candles):
        base = [None, 99.0, 100.0]
        rest = [0.0] * max(0, len(candles) - len(base))
        values = (base + rest)[: len(candles)]
        return IndicatorSeries(
            indicator_id="cci",
            params={"period": 20, "constant": 0.015},
            values=values,
        )


class _FakeRegistryComposite:
    def build(self, indicator_id: str, params: dict[str, object]):
        if indicator_id == "psar":
            return _FakePsarAlignedWithCciBuyAt2()
        if indicator_id == "cci":
            return _FakeCciBuyAt2()
        raise AssertionError(indicator_id)


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


def _cci_payload(*, expiry_seconds: int) -> dict:
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
            {"key": "cci_20", "id": "cci", "params": {"period": 20, "constant": 0.015}},
        ],
        "strategy": {
            "type": "cci_level_cross",
            "signal_on_close": True,
            "conditions": [{"indicator_key": "cci_20", "operator": "cci_level_cross"}],
        },
    }


def test_post_strategy_test_winrate_cci_level_cross_happy_path(monkeypatch) -> None:
    monkeypatch.setattr(strategy_route, "default_indicator_registry", lambda: _FakeRegistryCci())

    client = TestClient(_app())
    response = client.post("/api/v1/strategy/test-winrate", json=_cci_payload(expiry_seconds=30))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["asset"] == "EURUSD_otc"
    assert body["timeframe_seconds"] == 15
    assert body["expiry_seconds"] == 30
    assert body["total_signals"] == 2
    assert body["wins"] == 0
    assert body["losses"] == 2
    assert body["skipped_signals"] == 0
    assert body["winrate_percent"] == 0.0


def test_post_strategy_test_winrate_type_operator_mismatch_422() -> None:
    bad = _payload(expiry_seconds=30)
    bad["strategy"]["type"] = "psar_reversal"
    bad["strategy"]["conditions"] = [{"indicator_key": "psar_main", "operator": "cci_level_cross"}]

    client = TestClient(_app())
    response = client.post("/api/v1/strategy/test-winrate", json=bad)

    assert response.status_code == 422


def _composite_payload(*, expiry_seconds: int) -> dict:
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
            {"key": "psar_main", "id": "psar", "params": {"step": 0.02, "max_step": 0.2}},
            {"key": "cci_20", "id": "cci", "params": {"period": 20, "constant": 0.015}},
        ],
        "strategy": {
            "type": "composite",
            "combinator": "all",
            "signal_on_close": True,
            "conditions": [
                {"indicator_key": "psar_main", "operator": "psar_reversal"},
                {"indicator_key": "cci_20", "operator": "cci_level_cross"},
            ],
        },
    }


def test_post_strategy_test_winrate_composite_and_happy_path(monkeypatch) -> None:
    monkeypatch.setattr(strategy_route, "default_indicator_registry", lambda: _FakeRegistryComposite())

    client = TestClient(_app())
    response = client.post("/api/v1/strategy/test-winrate", json=_composite_payload(expiry_seconds=30))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_signals"] == 1
    assert body["wins"] == 0
    assert body["losses"] == 1
    assert body["skipped_signals"] == 0


def test_post_strategy_composite_missing_combinator_422() -> None:
    p = _composite_payload(expiry_seconds=30)
    del p["strategy"]["combinator"]

    client = TestClient(_app())
    assert client.post("/api/v1/strategy/test-winrate", json=p).status_code == 422


def test_post_strategy_composite_single_condition_422() -> None:
    p = _composite_payload(expiry_seconds=30)
    p["strategy"]["conditions"] = [
        {"indicator_key": "psar_main", "operator": "psar_reversal"},
    ]

    client = TestClient(_app())
    assert client.post("/api/v1/strategy/test-winrate", json=p).status_code == 422


def test_post_strategy_single_strategy_combinator_forbidden_422() -> None:
    p = _payload(expiry_seconds=30)
    p["strategy"]["combinator"] = "all"

    client = TestClient(_app())
    assert client.post("/api/v1/strategy/test-winrate", json=p).status_code == 422
