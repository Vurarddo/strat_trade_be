from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.assets import router as assets_router
from strat_trade.domain.entities import AccountBalance, BrokerAsset
from strat_trade.domain.errors import BrokerUnavailableError


class FakeGateway:
    def __init__(
        self,
        assets: list[BrokerAsset] | None = None,
        *,
        fail: bool = False,
    ) -> None:
        self._assets = assets or [
            BrokerAsset(
                asset_id="1",
                symbol="EURUSD_otc",
                name="EUR/USD OTC",
                asset_type="currency",
                payout=92.0,
                is_otc=True,
                is_active=True,
                allowed_candles=(60, 300),
            ),
            BrokerAsset(
                asset_id="2",
                symbol="GBPUSD",
                name="GBP/USD",
                asset_type="currency",
                payout=88.0,
                is_otc=False,
                is_active=False,
                allowed_candles=(5, 60),
            ),
        ]
        self._fail = fail
        self.closed = False

    async def get_balance(self) -> AccountBalance:
        return AccountBalance(amount=Decimal("1"), currency="USD", is_demo=True)

    async def list_assets(self) -> list[BrokerAsset]:
        if self._fail:
            raise BrokerUnavailableError("simulated broker failure")
        return list(self._assets)

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def app_with_gateway() -> tuple[FastAPI, FakeGateway]:
    gateway = FakeGateway()
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.state.trading_gateway = gateway
    app.include_router(assets_router, prefix="/api/v1", tags=["Market data"])
    return app, gateway


def test_get_assets_returns_catalog(app_with_gateway: tuple[FastAPI, FakeGateway]) -> None:
    app, _gateway = app_with_gateway
    client = TestClient(app)
    response = client.get("/api/v1/market/assets")
    assert response.status_code == 200
    body = response.json()
    assert body["active_only"] is False
    assert len(body["assets"]) == 2
    symbols = {a["symbol"] for a in body["assets"]}
    assert symbols == {"EURUSD_otc", "GBPUSD"}


def test_get_assets_active_only_filters(app_with_gateway: tuple[FastAPI, FakeGateway]) -> None:
    app, _gateway = app_with_gateway
    client = TestClient(app)
    response = client.get("/api/v1/market/assets?active_only=true")
    assert response.status_code == 200
    body = response.json()
    assert body["active_only"] is True
    assert len(body["assets"]) == 1
    assert body["assets"][0]["symbol"] == "EURUSD_otc"
    assert body["assets"][0]["is_active"] is True


def test_assets_broker_error_maps_to_envelope(app_with_gateway: tuple[FastAPI, FakeGateway]) -> None:
    app, gateway = app_with_gateway
    gateway._fail = True  # noqa: SLF001 — test double
    client = TestClient(app)
    response = client.get("/api/v1/market/assets")
    assert response.status_code == 502
    payload = response.json()
    assert payload["error"]["code"] == "BROKER_UNAVAILABLE"
