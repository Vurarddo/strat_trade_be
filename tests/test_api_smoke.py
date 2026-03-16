"""Smoke test: app starts and /docs is reachable."""

import pytest
from httpx import ASGITransport, AsyncClient

from strat_trade.main import app


@pytest.mark.asyncio
async def test_docs_returns_200():
    """GET /docs returns 200 (Swagger UI)."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/docs")
    assert response.status_code == 200
