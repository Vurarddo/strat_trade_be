from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.audit import router as audit_router
from strat_trade.api.routes.bot import router as bot_router
from strat_trade.domain.entities import Candle


def _make_dummy_candles(n: int = 150) -> list[Candle]:
    base = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
    return [
        Candle(
            open_time=base + timedelta(minutes=i),
            open=Decimal(str(round(1.0850 + i * 0.0001, 5))),
            high=Decimal(str(round(1.0860 + i * 0.0001, 5))),
            low=Decimal(str(round(1.0840 + i * 0.0001, 5))),
            close=Decimal(str(round(1.0855 + i * 0.0001, 5))),
            volume=Decimal("100"),
        )
        for i in range(n)
    ]


class FakeTradingGateway:
    def __init__(self) -> None:
        self.candles = _make_dummy_candles(150)

    async def get_candles(
        self, asset: str, timeframe: int | str, *, count: int, end_time: datetime | None = None
    ) -> list[Candle]:
        return self.candles[-count:]

    async def get_assets(self) -> list[dict]:
        return [
            {
                "symbol": "EURUSD_otc",
                "name": "EUR/USD OTC",
                "payout": 92,
                "is_otc": True,
                "asset_type": "currency",
            }
        ]

    async def open_trade(
        self, asset: str, action: str, amount: float, expiration_seconds: int
    ) -> tuple[str, dict]:
        return "test-order-uuid-12345", {"status": "ok"}


def _get_test_app() -> TestClient:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.state.trading_gateway = FakeTradingGateway()
    app.include_router(bot_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")
    return TestClient(app)


def test_bot_auto_assign_and_lifecycle_api():
    client = _get_test_app()

    # 1. Auto-assign
    payload = {
        "assets": ["EURUSD_otc"],
        "initial_deposit": 1000.0,
        "stake_model": "flat",
        "stake_amount": 10.0,
        "stake_percent": 1.0,
        "expiration_seconds": 180,
        "daily_stop_loss_pct": 0.05,
        "max_concurrent_trades": 3,
        "min_payout_rate": 0.80,
    }
    res = client.post("/api/v1/bot/auto-assign", json=payload)
    assert res.status_code == 200
    plan_data = res.json()
    assert len(plan_data["assignments"]) == 1
    assert plan_data["assignments"][0]["asset"] == "EURUSD_otc"
    assert plan_data["stop_loss_amount"] == 50.0

    # 2. Start Bot
    start_res = client.post("/api/v1/bot/start", json={"plan": plan_data})
    assert start_res.status_code == 200
    status_data = start_res.json()
    assert status_data["status"] == "RUNNING"

    # 3. Status
    st_res = client.get("/api/v1/bot/status")
    assert st_res.status_code == 200
    assert st_res.json()["status"] == "RUNNING"

    # 4. Stop Bot
    stop_res = client.post("/api/v1/bot/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["status"] == "STOPPED"

    # 5. Trades list
    trades_res = client.get("/api/v1/bot/trades")
    assert trades_res.status_code == 200
    assert isinstance(trades_res.json(), list)


def test_audit_upload_and_export_api():
    client = _get_test_app()

    # Generate CSV content
    csv_content = (
        b"Direction,Order,Expiration,Asset,Open time,Close time,"
        b"Open price,Close price,Trade amount,Profit,Currency\n"
        b"call,e384a8f6-c371-4b8f-916a-112ae0a60456,S3,USD/CHF OTC,"
        b"2026-08-19 22:23:28,2026-08-19 22:23:31,0.82359,0.82377,10,9.2,USD\n"
    )

    files = {"file": ("pocket_option_history.csv", io.BytesIO(csv_content), "text/csv")}
    upload_res = client.post("/api/v1/audit/upload-xls", files=files)
    assert upload_res.status_code == 200
    data = upload_res.json()
    assert data["total_broker_trades"] == 1
    assert data["total_broker_profit"] == 9.2

    # Export CSV
    export_res = client.get("/api/v1/audit/export?format=csv")
    assert export_res.status_code == 200
    assert "Broker Order UUID" in export_res.text


def test_internal_audit_and_clear_endpoints():
    client = _get_test_app()

    # 1. Fetch internal audit records
    audit_res = client.get("/api/v1/audit/records")
    assert audit_res.status_code == 200
    data = audit_res.json()
    assert "strategy_breakdown" in data
    assert "asset_breakdown" in data
    assert "merged_records" in data

    # 2. Clear trades via audit endpoint
    clear_audit_res = client.post("/api/v1/audit/clear")
    assert clear_audit_res.status_code == 200
    assert clear_audit_res.json()["status"] == "ok"

    # 3. Clear trades via bot endpoint
    clear_bot_res = client.post("/api/v1/bot/clear-trades")
    assert clear_bot_res.status_code == 200
    assert clear_bot_res.json()["status"] == "ok"


def test_bot_auto_assign_without_expiration_payload():
    """Verify auto-assign endpoint defaults expiration to 180s when client omits
    expiration_seconds.
    """
    client = _get_test_app()

    payload = {
        "assets": ["EURUSD_otc", "USDCLP_otc"],
        "initial_deposit": 1000.0,
        "stake_model": "flat",
        "stake_amount": 10.0,
        "stake_percent": 1.0,
        # expiration_seconds omitted as per R2 UI simplification
        "daily_stop_loss_pct": 0.05,
        "max_concurrent_trades": 3,
        "min_payout_rate": 0.80,
    }
    res = client.post("/api/v1/bot/auto-assign", json=payload)
    assert res.status_code == 200
    plan_data = res.json()
    assert plan_data["expiration_seconds"] == 180
    assert len(plan_data["assignments"]) == 2
    for assignment in plan_data["assignments"]:
        assert assignment["parameters"].get("base_expiration_bars") == 3
