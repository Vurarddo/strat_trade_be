"""Tests the gateway's reading of broker-side fill prices and trade verdicts.

The bot now settles against these answers, so a malformed or partial payload
must degrade to "I don't know" rather than to a confident wrong verdict.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest

from strat_trade.adapters.pocket_option_gateway import PocketOptionTradingGateway


def _gateway(client: Any) -> PocketOptionTradingGateway:
    gw = PocketOptionTradingGateway(ssid="test-ssid", is_demo=True)
    gw._client_connected = AsyncMock(return_value=client)  # type: ignore[method-assign]
    return gw


class TestEntryPrice:
    @pytest.mark.asyncio
    async def test_reads_the_fill_from_the_open_deal(self) -> None:
        client = AsyncMock()
        client.get_opened_deal.return_value = {"id": "o1", "entry_price": 1.23456}

        assert await _gateway(client).get_deal_entry_price("o1") == Decimal("1.23456")

    @pytest.mark.asyncio
    async def test_falls_through_to_the_closed_deal(self) -> None:
        client = AsyncMock()
        client.get_opened_deal.return_value = None
        client.get_closed_deal.return_value = {"entry_price": 1.5}

        assert await _gateway(client).get_deal_entry_price("o1") == Decimal("1.5")

    @pytest.mark.asyncio
    async def test_accepts_the_camel_case_spelling(self) -> None:
        client = AsyncMock()
        client.get_opened_deal.return_value = {"openPrice": "1.98765"}

        assert await _gateway(client).get_deal_entry_price("o1") == Decimal("1.98765")

    @pytest.mark.asyncio
    async def test_returns_nothing_for_an_empty_order_id(self) -> None:
        client = AsyncMock()

        assert await _gateway(client).get_deal_entry_price("") is None
        client.get_opened_deal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_broker_error_is_swallowed(self) -> None:
        client = AsyncMock()
        client.get_opened_deal.side_effect = RuntimeError("socket closed")

        assert await _gateway(client).get_deal_entry_price("o1") is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", [None, {}, {"entry_price": 0}, {"entry_price": "abc"}])
    async def test_unusable_payloads_yield_nothing(self, payload: Any) -> None:
        client = AsyncMock()
        client.get_opened_deal.return_value = payload
        client.get_closed_deal.return_value = payload

        assert await _gateway(client).get_deal_entry_price("o1") is None


class TestTradeResult:
    @pytest.mark.asyncio
    async def test_reads_a_full_verdict(self) -> None:
        client = AsyncMock()
        client.get_closed_deal.return_value = {
            "result": "win",
            "profit": 18.4,
            "close_price": 1.1055,
            "entry_price": 1.1000,
        }

        result = await _gateway(client).get_trade_result("o1")

        assert result == {
            "result": "win",
            "profit": Decimal("18.4"),
            "close_price": Decimal("1.1055"),
            "entry_price": Decimal("1.1"),
        }

    @pytest.mark.asyncio
    async def test_a_pending_deal_reads_as_unknown(self) -> None:
        client = AsyncMock()
        client.get_closed_deal.return_value = None

        assert await _gateway(client).get_trade_result("o1") is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("profit", "expected"),
        [(12.5, "win"), (-20.0, "loss"), (0.0, "draw")],
    )
    async def test_derives_the_verdict_from_profit_when_absent(
        self, profit: float, expected: str
    ) -> None:
        client = AsyncMock()
        client.get_closed_deal.return_value = {"profit": profit}

        result = await _gateway(client).get_trade_result("o1")

        assert result is not None
        assert result["result"] == expected

    @pytest.mark.asyncio
    async def test_a_payload_with_neither_verdict_nor_profit_is_unknown(self) -> None:
        client = AsyncMock()
        client.get_closed_deal.return_value = {"id": "o1", "asset": "EURUSD_otc"}

        assert await _gateway(client).get_trade_result("o1") is None

    @pytest.mark.asyncio
    async def test_a_broker_error_reads_as_unknown(self) -> None:
        client = AsyncMock()
        client.get_closed_deal.side_effect = RuntimeError("channel closed")

        assert await _gateway(client).get_trade_result("o1") is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("profit", "expected_result", "close", "entry"),
        [
            ("23", "win", "0.59709", "0.59729"),
            ("-25", "loss", "160.485", "160.635"),
        ],
    )
    async def test_verbatim_pocket_option_payload(
        self, profit: str, expected_result: str, close: str, entry: str
    ) -> None:
        """The real broker payload: camelCase prices and no `result` key at all.

        Captured from live closed deals on 30.08. Pocket Option never sends the
        verdict directly, so it has to be derived from the sign of `profit`, and
        the prices arrive as openPrice/closePrice rather than the snake_case names
        in the SDK docstrings.
        """
        client = AsyncMock()
        client.get_closed_deal.return_value = {
            "id": "68f8b8e3-6999-4fd7-b7f6-17978d96c7b8",
            "asset": "NZDUSD_otc",
            "command": 0,
            "amount": "25",
            "profit": profit,
            "percentProfit": 92,
            "percentLoss": 100,
            "openPrice": entry,
            "closePrice": close,
            "openTime": "2026-08-29 22:02:07",
            "closeTime": "2026-08-29 22:05:07",
        }

        result = await _gateway(client).get_trade_result("o1")

        assert result == {
            "result": expected_result,
            "profit": Decimal(profit),
            "close_price": Decimal(close),
            "entry_price": Decimal(entry),
        }

    @pytest.mark.asyncio
    async def test_result_casing_is_normalised(self) -> None:
        client = AsyncMock()
        client.get_closed_deal.return_value = {"result": "LOSS", "profit": -20}

        result = await _gateway(client).get_trade_result("o1")

        assert result is not None
        assert result["result"] == "loss"
