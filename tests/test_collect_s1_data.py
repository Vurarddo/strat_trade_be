from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from scripts.collect_s1_data import (
    collect_cycle,
    main,
    parse_args,
    resolve_ssid,
    run_collector_loop,
)
from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import (
    BrokerUnavailableError,
    InvalidMarketParametersError,
)
from strat_trade.domain.trading.market_data_store import MarketDataStore


def _mock_candles(count: int = 5, start_ts: float = 1700000000.0) -> list[Candle]:
    return [
        Candle(
            open_time=datetime.fromtimestamp(start_ts + i, tz=UTC),
            open=Decimal("1.0850"),
            high=Decimal("1.0860"),
            low=Decimal("1.0840"),
            close=Decimal("1.0855"),
            volume=Decimal("10.0"),
        )
        for i in range(count)
    ]


class TestResolveSSID:
    def test_cli_ssid_override(self) -> None:
        ssid = resolve_ssid(cli_ssid="cli_token_123")
        assert ssid == "cli_token_123"

    def test_cli_ssid_file(self, tmp_path: Path) -> None:
        ssid_file = tmp_path / "my.ssid"
        ssid_file.write_text("token_from_file_456\n", encoding="utf-8")
        ssid = resolve_ssid(cli_ssid_file=str(ssid_file))
        assert ssid == "token_from_file_456"

    def test_env_var_ssid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POCKET_OPTION_SSID", "env_token_789")
        ssid = resolve_ssid()
        assert ssid == "env_token_789"

    def test_env_var_ssid_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("POCKET_OPTION_SSID", raising=False)
        monkeypatch.delenv("STRAT_TRADE_POCKET_OPTION_SSID", raising=False)
        ssid_file = tmp_path / "env.ssid"
        ssid_file.write_text("token_from_env_file\n", encoding="utf-8")
        monkeypatch.setenv("POCKET_OPTION_SSID_FILE", str(ssid_file))
        ssid = resolve_ssid()
        assert ssid == "token_from_env_file"

    def test_fallback_demo(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("POCKET_OPTION_SSID", raising=False)
        monkeypatch.delenv("STRAT_TRADE_POCKET_OPTION_SSID", raising=False)
        monkeypatch.delenv("POCKET_OPTION_SSID_FILE", raising=False)
        monkeypatch.delenv("STRAT_TRADE_POCKET_OPTION_SSID_FILE", raising=False)
        with patch("scripts.collect_s1_data.Settings", side_effect=Exception("No settings")):
            with patch("scripts.collect_s1_data.PROJECT_ROOT", tmp_path):
                ssid = resolve_ssid()
                assert ssid == "demo"


class TestCollectCycle:
    @pytest.mark.asyncio
    async def test_collect_cycle_success(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "market.db")
        mock_gateway = AsyncMock()
        mock_gateway.get_candles.side_effect = [
            _mock_candles(10, 1000.0),
            _mock_candles(10, 1000.0),
            _mock_candles(10, 1000.0),
        ]

        assets = ["EURUSD_otc", "GOLD_otc", "AUDNZD_otc"]
        results = await collect_cycle(
            gateway=mock_gateway,
            store=store,
            assets=assets,
            timeframe=1,
            count=10,
            throttle_delay=0.0,
        )

        assert results == {"EURUSD_otc": 10, "GOLD_otc": 10, "AUDNZD_otc": 10}
        assert store.count_candles("EURUSD_otc") == 10
        assert store.count_candles("GOLD_otc") == 10
        assert store.count_candles("AUDNZD_otc") == 10
        assert mock_gateway.get_candles.call_count == 3

    @pytest.mark.asyncio
    async def test_collect_cycle_timeout_and_broker_unavailable_resilience(
        self, tmp_path: Path
    ) -> None:
        store = MarketDataStore(db_path=tmp_path / "market.db")
        mock_gateway = AsyncMock()
        mock_gateway.get_candles.side_effect = [
            TimeoutError("Request timed out"),
            _mock_candles(5, 1000.0),
            BrokerUnavailableError("Broker connection reset"),
        ]

        assets = ["EURUSD_otc", "GOLD_otc", "AUDNZD_otc"]
        results = await collect_cycle(
            gateway=mock_gateway,
            store=store,
            assets=assets,
            timeframe=1,
            count=5,
            throttle_delay=0.0,
        )

        # Asset 1 failed, Asset 2 succeeded (5 saved), Asset 3 failed
        assert "EURUSD_otc" not in results
        assert results.get("GOLD_otc") == 5
        assert "AUDNZD_otc" not in results
        assert store.count_candles("GOLD_otc") == 5
        assert store.count_candles("EURUSD_otc") == 0
        assert store.count_candles("AUDNZD_otc") == 0

    @pytest.mark.asyncio
    async def test_collect_cycle_generic_runtime_error_resilience(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "market.db")
        mock_gateway = AsyncMock()
        mock_gateway.get_candles.side_effect = [
            RuntimeError("Unexpected socket termination"),
            InvalidMarketParametersError("Invalid timeframe"),
            _mock_candles(8, 2000.0),
        ]

        assets = ["EURUSD_otc", "GOLD_otc", "AUDNZD_otc"]
        results = await collect_cycle(
            gateway=mock_gateway,
            store=store,
            assets=assets,
            timeframe=1,
            count=8,
            throttle_delay=0.0,
        )

        assert results == {"AUDNZD_otc": 8}
        assert store.count_candles("AUDNZD_otc") == 8

    @pytest.mark.asyncio
    async def test_collect_cycle_aborts_on_shutdown_event(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "market.db")
        mock_gateway = AsyncMock()
        shutdown = asyncio.Event()
        shutdown.set()

        assets = ["EURUSD_otc", "GOLD_otc"]
        results = await collect_cycle(
            gateway=mock_gateway,
            store=store,
            assets=assets,
            throttle_delay=0.0,
            shutdown_event=shutdown,
        )
        assert results == {}
        assert mock_gateway.get_candles.call_count == 0


class TestRunCollectorLoop:
    @pytest.mark.asyncio
    async def test_run_collector_loop_once_mode(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "market.db")
        mock_gateway = AsyncMock()
        mock_gateway.get_candles.return_value = _mock_candles(5, 1000.0)

        await run_collector_loop(
            gateway=mock_gateway,
            store=store,
            assets=["EURUSD_otc"],
            interval=10.0,
            once=True,
            throttle_delay=0.0,
        )

        assert mock_gateway.get_candles.call_count == 1
        assert store.count_candles("EURUSD_otc") == 5

    @pytest.mark.asyncio
    async def test_run_collector_loop_max_cycles(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "market.db")
        mock_gateway = AsyncMock()
        mock_gateway.get_candles.side_effect = [
            _mock_candles(5, 1000.0),
            _mock_candles(5, 1005.0),
            _mock_candles(5, 1010.0),
        ]

        await run_collector_loop(
            gateway=mock_gateway,
            store=store,
            assets=["EURUSD_otc"],
            interval=0.001,
            max_cycles=3,
            throttle_delay=0.0,
        )

        assert mock_gateway.get_candles.call_count == 3
        assert store.count_candles("EURUSD_otc") == 15

    @pytest.mark.asyncio
    async def test_run_collector_loop_interrupted_by_shutdown_event(self, tmp_path: Path) -> None:
        store = MarketDataStore(db_path=tmp_path / "market.db")
        mock_gateway = AsyncMock()
        mock_gateway.get_candles.return_value = _mock_candles(5, 1000.0)
        shutdown = asyncio.Event()

        async def _trigger_shutdown() -> None:
            await asyncio.sleep(0.01)
            shutdown.set()

        asyncio.create_task(_trigger_shutdown())

        await run_collector_loop(
            gateway=mock_gateway,
            store=store,
            assets=["EURUSD_otc"],
            interval=10.0,
            throttle_delay=0.0,
            shutdown_event=shutdown,
        )

        assert mock_gateway.get_candles.call_count == 1


class TestCLIAndMain:
    def test_parse_args_custom_values(self) -> None:
        args = parse_args(
            [
                "--assets",
                "EURUSD_otc,BTCUSD",
                "--timeframe",
                "5",
                "--count",
                "100",
                "--interval",
                "15.5",
                "--db-path",
                "data/custom.db",
                "--ssid",
                "secret123",
                "--live",
                "--once",
                "--max-cycles",
                "4",
                "--throttle-delay",
                "0.1",
                "--log-level",
                "DEBUG",
            ]
        )
        assert args.assets == "EURUSD_otc,BTCUSD"
        assert args.timeframe == 5
        assert args.count == 100
        assert args.interval == 15.5
        assert args.db_path == "data/custom.db"
        assert args.ssid == "secret123"
        assert args.demo is False
        assert args.once is True
        assert args.max_cycles == 4
        assert args.throttle_delay == 0.1
        assert args.log_level == "DEBUG"

    @pytest.mark.asyncio
    async def test_main_execution_and_gateway_closure(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "main_test.db")
        mock_gateway_inst = AsyncMock()
        mock_gateway_inst.get_candles.return_value = _mock_candles(3, 1000.0)
        mock_gateway_inst.aclose = AsyncMock()

        with patch(
            "scripts.collect_s1_data.PocketOptionTradingGateway",
            return_value=mock_gateway_inst,
        ):
            await main(
                [
                    "--once",
                    "--assets",
                    "EURUSD_otc",
                    "--db-path",
                    db_path,
                    "--throttle-delay",
                    "0.0",
                ]
            )

        assert mock_gateway_inst.get_candles.call_count == 1
        mock_gateway_inst.aclose.assert_awaited_once()

        store = MarketDataStore(db_path=db_path)
        assert store.count_candles("EURUSD_otc") == 3
