from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.balance import router as balance_router
from strat_trade.domain.entities import AccountBalance
from strat_trade.domain.errors import BrokerUnavailableError


class FakeGateway:
    def __init__(self, balance: AccountBalance | None = None, *, fail: bool = False) -> None:
        self._balance = balance or AccountBalance(
            amount=Decimal("1000.00"),
            currency="USD",
            is_demo=True,
        )
        self._fail = fail
        self.closed = False

    async def get_balance(self) -> AccountBalance:
        if self._fail:
            raise BrokerUnavailableError("simulated broker failure")
        return self._balance

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def app_with_gateway() -> tuple[FastAPI, FakeGateway]:
    gateway = FakeGateway()
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.state.trading_gateway = gateway
    app.include_router(balance_router, prefix="/api/v1", tags=["Account"])
    return app, gateway


def test_get_balance_returns_normalized_json(app_with_gateway: tuple[FastAPI, FakeGateway]) -> None:
    app, _gateway = app_with_gateway
    client = TestClient(app)
    response = client.get("/api/v1/balance")
    assert response.status_code == 200
    assert response.json() == {"amount": 1000.0, "currency": "USD", "is_demo": True}


def test_broker_error_maps_to_envelope(app_with_gateway: tuple[FastAPI, FakeGateway]) -> None:
    app, gateway = app_with_gateway
    gateway._fail = True  # noqa: SLF001 — test double
    client = TestClient(app)
    response = client.get("/api/v1/balance")
    assert response.status_code == 502
    payload = response.json()
    assert payload["error"]["code"] == "BROKER_UNAVAILABLE"
    assert "simulated" in payload["error"]["message"]
