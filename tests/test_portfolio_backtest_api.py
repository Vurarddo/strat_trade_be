from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.backtest import router as backtest_router
from strat_trade.domain.entities import Candle


class _FakePortfolioCandleFeed:
    async def get_candles(
        self,
        asset: str,
        timeframe: int | str,
        *,
        count: int,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        candles: list[Candle] = []
        for i in range(count):
            t = base + timedelta(minutes=i)
            # Add price variation
            c = Decimal("1.0500") + Decimal(str(round(0.005 * ((i % 10) - 5), 4)))
            candles.append(
                Candle(
                    open_time=t,
                    open=c - Decimal("0.0001"),
                    high=c + Decimal("0.0005"),
                    low=c - Decimal("0.0005"),
                    close=c,
                    volume=Decimal("100"),
                )
            )
        return candles

    async def get_assets(self) -> list[dict]:
        return [
            {
                "symbol": "EURUSD_otc",
                "name": "EUR/USD OTC",
                "payout": 92,
                "is_otc": True,
                "asset_type": "currency",
            },
            {
                "symbol": "GBPUSD_otc",
                "name": "GBP/USD OTC",
                "payout": 92,
                "is_otc": True,
                "asset_type": "currency",
            },
        ]


def test_portfolio_backtest_api_endpoint() -> None:
    app = FastAPI()
    feed = _FakePortfolioCandleFeed()
    app.dependency_overrides[type(feed)] = lambda: feed
    from strat_trade.api.deps import get_candle_feed

    app.dependency_overrides[get_candle_feed] = lambda: feed
    register_domain_exception_handlers(app)
    app.include_router(backtest_router, prefix="/api/v1")

    client = TestClient(app)

    payload = {
        "assets": ["EURUSD_otc", "GBPUSD_otc"],
        "max_concurrent_trades": 2,
        "timeframe_seconds": 60,
        "initial_deposit": 1000.0,
        "stake_model": "flat",
        "stake_amount": 10.0,
        "payout_rates": {"EURUSD_otc": 0.92, "GBPUSD_otc": 0.92},
        "min_payout_rate": 0.80,
        "expiration_bars": 3,
        "candle_count": 100,
    }

    r = client.post("/api/v1/backtest/portfolio/run", json=payload)
    assert r.status_code == 200
    data = r.json()

    assert "assets" in data
    assert len(data["assets"]) == 2
    assert "per_asset_stats" in data
    assert "trades" in data
    assert "equity_curve" in data
    assert data["initial_deposit"] == 1000.0
    assert "final_balance" in data
