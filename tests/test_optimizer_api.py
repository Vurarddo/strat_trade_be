from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.backtest import router as backtest_router
from strat_trade.domain.entities import Candle


def _make_dummy_candles(n: int = 150) -> list[Candle]:
    base = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)
    return [
        Candle(
            open_time=base + timedelta(minutes=i),
            open=Decimal("1.0850"),
            high=Decimal("1.0860"),
            low=Decimal("1.0840"),
            close=Decimal("1.0855"),
            volume=Decimal("100"),
        )
        for i in range(n)
    ]


class FakeCandleFeed:
    def __init__(self, count: int = 150) -> None:
        self.all_bars = _make_dummy_candles(count)

    async def get_candles(
        self,
        asset: str,
        timeframe: int | str,
        *,
        count: int,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        return self.all_bars[-count:]


def _get_test_client() -> TestClient:
    feed = FakeCandleFeed()
    test_app = FastAPI()
    register_domain_exception_handlers(test_app)
    test_app.state.trading_gateway = feed
    test_app.include_router(backtest_router, prefix="/api/v1")
    return TestClient(test_app)


def test_list_strategies_api():
    client = _get_test_client()
    res = client.get("/api/v1/backtest/strategies")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 8
    assert any(s["id"] == "bollinger_atr_reversion" for s in data)


def test_optimize_strategy_api():
    client = _get_test_client()
    payload = {
        "strategy_name": "rsi_stochastic_extreme",
        "asset": "EURUSD_otc",
        "timeframe_seconds": 60,
        "candle_count": 150,
        "max_combinations": 10,
        "parameter_grid": {
            "rsi_period": [10, 14],
            "base_expiration_bars": [2, 3],
        },
    }

    res = client.post("/api/v1/backtest/optimize", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["strategy_name"] == "rsi_stochastic_extreme"
    assert data["total_combinations_tested"] == 4
    assert len(data["results"]) == 4
    assert data["best_params"] is not None
