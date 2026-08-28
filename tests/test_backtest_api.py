from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.backtest import router as backtest_router
from strat_trade.api.routes.web import router as web_router
from strat_trade.domain.entities import Candle

_BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _bar(i: int) -> Candle:
    t = _BASE + timedelta(minutes=i)
    # Generate simple wave for prices
    val = 1.2000 + (0.0010 if (i % 4 < 2) else -0.0010)
    return Candle(
        open_time=t,
        open=Decimal(str(val)),
        high=Decimal(str(val + 0.0005)),
        low=Decimal(str(val - 0.0005)),
        close=Decimal(str(val + 0.0002)),
        volume=Decimal("100"),
    )


class FakeCandleFeed:
    def __init__(self, count: int = 150) -> None:
        self.all_bars = [_bar(i) for i in range(count)]

    async def get_candles(
        self,
        asset: str,
        timeframe: int | str,
        *,
        count: int,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        return self.all_bars[-count:]


@pytest.fixture
def app_backtest() -> tuple[FastAPI, FakeCandleFeed]:
    feed = FakeCandleFeed()
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.state.trading_gateway = feed
    app.include_router(web_router)
    app.include_router(backtest_router, prefix="/api/v1")
    return app, feed


def test_get_dashboard_html(app_backtest: tuple[FastAPI, FakeCandleFeed]) -> None:
    app, _ = app_backtest
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    assert "Strat Trade" in res.text

    res2 = client.get("/dashboard")
    assert res2.status_code == 200

    res_fav = client.get("/favicon.svg")
    assert res_fav.status_code == 200
    assert "image/svg+xml" in res_fav.headers["content-type"]


def test_post_backtest_run(app_backtest: tuple[FastAPI, FakeCandleFeed]) -> None:
    app, _ = app_backtest
    client = TestClient(app)
    payload = {
        "asset": "EURUSD_otc",
        "timeframe_seconds": 60,
        "initial_deposit": 1000.0,
        "stake_model": "flat",
        "stake_amount": 10.0,
        "payout_rate": 0.85,
        "min_payout_rate": 0.80,
        "expiration_bars": 2,
        "candle_count": 100,
    }
    res = client.post("/api/v1/backtest/run", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["asset"] == "EURUSD_otc"
    assert data["initial_deposit"] == 1000.0
    assert "win_rate_pct" in data
    assert "profit_factor" in data
    assert "trades" in data
    assert "equity_curve" in data


def test_post_backtest_upload_csv(app_backtest: tuple[FastAPI, FakeCandleFeed]) -> None:
    app, _ = app_backtest
    client = TestClient(app)
    csv_content = "timestamp,open,high,low,close,volume\n"
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    for i in range(120):
        t = t0 + timedelta(minutes=i)
        p = 1.1000 + (0.0020 if i % 6 < 3 else -0.0020)
        csv_content += f"{t.isoformat()},{p},{p + 0.0005},{p - 0.0005},{p + 0.0001},100\n"

    files = {"file": ("test_data.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    data = {
        "initial_deposit": "500",
        "stake_model": "flat",
        "stake_amount": "10",
        "payout_rate": "0.85",
    }
    res = client.post("/api/v1/backtest/upload", files=files, data=data)
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["initial_deposit"] == 500.0
    assert "win_rate_pct" in res_data
