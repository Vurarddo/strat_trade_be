from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from scripts.collect_s1_data import (
    collect_cycle,
    main,
    parse_args,
    run_collector_loop,
)
from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import BacktestConfig
from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import (
    BrokerUnavailableError,
    InvalidMarketParametersError,
)
from strat_trade.domain.trading.market_data_store import MarketDataStore


def _create_mock_candles(
    count: int = 10,
    start_ts: float = 1700000000.0,
    base_price: float = 1.0850,
) -> list[Candle]:
    return [
        Candle(
            open_time=datetime.fromtimestamp(start_ts + i, tz=UTC),
            open=Decimal(str(round(base_price + (i % 20) * 0.0001, 5))),
            high=Decimal(str(round(base_price + (i % 20) * 0.0001 + 0.0003, 5))),
            low=Decimal(str(round(base_price + (i % 20) * 0.0001 - 0.0003, 5))),
            close=Decimal(str(round(base_price + (i % 20) * 0.0001 + 0.0001, 5))),
            volume=Decimal("15.0"),
        )
        for i in range(count)
    ]


class TestFaultInjectionAndNetworkResilience:
    """Stress tests simulating network dropouts, broker crashes, and transient timeouts."""

    @pytest.mark.asyncio
    async def test_heterogeneous_fault_injection_multi_asset_isolation(
        self, tmp_path: Path
    ) -> None:
        """Simulates 6 assets in a cycle where each asset experiences a different fault.

        Asset 1: BrokerUnavailableError (e.g. broker disconnect)
        Asset 2: asyncio.TimeoutError (e.g. gateway socket stall)
        Asset 3: ConnectionResetError (e.g. OS pipe / TCP reset)
        Asset 4: InvalidMarketParametersError (e.g. bad symbol or timeframe)
        Asset 5: Generic RuntimeError (e.g. unexpected protocol state)
        Asset 6: Normal Healthy Response (10 candles)
        """
        db_file = tmp_path / "fault_isolation.db"
        store = MarketDataStore(db_path=db_file)

        mock_gateway = AsyncMock()
        mock_gateway.get_candles.side_effect = [
            BrokerUnavailableError("Broker WebSocket connection severed"),
            TimeoutError("Gateway request timed out after 10.0s"),
            ConnectionResetError("Connection reset by peer"),
            InvalidMarketParametersError("Unsupported asset timeframe"),
            RuntimeError("Unexpected gateway protocol state"),
            _create_mock_candles(10, 1700000000.0, 1.0500),
        ]

        assets = [
            "FAULT_BROKER_otc",
            "FAULT_TIMEOUT_otc",
            "FAULT_CONN_otc",
            "FAULT_INVALID_otc",
            "FAULT_RUNTIME_otc",
            "HEALTHY_ASSET_otc",
        ]

        results = await collect_cycle(
            gateway=mock_gateway,
            store=store,
            assets=assets,
            timeframe=1,
            count=10,
            throttle_delay=0.0,
        )

        assert "HEALTHY_ASSET_otc" in results
        assert results["HEALTHY_ASSET_otc"] == 10
        assert store.count_candles("HEALTHY_ASSET_otc") == 10

        # All fault assets should have 0 stored candles
        for fault_asset in assets[:-1]:
            assert fault_asset not in results
            assert store.count_candles(fault_asset) == 0

        assert store.get_total_candle_count() == 10

    @pytest.mark.asyncio
    async def test_recovery_after_consecutive_transient_failures(self, tmp_path: Path) -> None:
        """Simulates 3 consecutive failed cycles (network blackout) followed by full recovery."""
        db_file = tmp_path / "transient_recovery.db"
        store = MarketDataStore(db_path=db_file)

        mock_gateway = AsyncMock()
        mock_gateway.get_candles.side_effect = [
            # Cycle 1
            TimeoutError("Timeout #1"),
            TimeoutError("Timeout #2"),
            # Cycle 2
            BrokerUnavailableError("Broker down #1"),
            BrokerUnavailableError("Broker down #2"),
            # Cycle 3
            ConnectionError("Network dead #1"),
            ConnectionError("Network dead #2"),
            # Cycle 4 (Success)
            _create_mock_candles(5, 1700000100.0, 1.1000),
            _create_mock_candles(5, 1700000100.0, 1.2000),
        ]

        assets = ["EURUSD_otc", "GBPUSD_otc"]

        await run_collector_loop(
            gateway=mock_gateway,
            store=store,
            assets=assets,
            interval=0.001,
            max_cycles=4,
            throttle_delay=0.0,
        )

        assert mock_gateway.get_candles.call_count == 8
        assert store.count_candles("EURUSD_otc") == 5
        assert store.count_candles("GBPUSD_otc") == 5
        assert store.get_total_candle_count() == 10

    @pytest.mark.asyncio
    async def test_high_frequency_random_fault_injection_loop(self, tmp_path: Path) -> None:
        """Runs 25 simulated cycles with a 40% pseudo-random failure rate."""
        db_file = tmp_path / "stochastic_fault.db"
        store = MarketDataStore(db_path=db_file)

        import random

        rng = random.Random(1337)
        call_index = 0

        async def _flaky_get_candles(
            asset: str, timeframe: int = 1, count: int = 300
        ) -> list[Candle]:
            nonlocal call_index
            call_index += 1
            roll = rng.random()
            if roll < 0.15:
                raise BrokerUnavailableError("Simulated random broker drop")
            if roll < 0.30:
                raise TimeoutError("Simulated random timeout")
            if roll < 0.40:
                raise OSError("Simulated random socket disconnect")

            # Healthy response: sliding window of 20 candles
            base_t = 1700000000.0 + (call_index * 5)
            return _create_mock_candles(count=20, start_ts=base_t, base_price=1.0800)

        mock_gateway = AsyncMock()
        mock_gateway.get_candles.side_effect = _flaky_get_candles

        assets = ["EURUSD_otc", "GOLD_otc", "AUDNZD_otc"]
        await run_collector_loop(
            gateway=mock_gateway,
            store=store,
            assets=assets,
            interval=0.001,
            max_cycles=25,
            throttle_delay=0.0,
        )

        assert call_index == 25 * 3  # 75 total gateway attempts
        total_stored = store.get_total_candle_count()
        assert total_stored > 0

        # Verify no duplicate timestamps exist in SQLite for any asset
        for asset in assets:
            df = store.get_candles_df(asset)
            if len(df) > 0:
                assert df["timestamp"].is_monotonic_increasing
                assert not df["timestamp"].duplicated().any()


class TestCorruptedAndAdversarialResponses:
    """Stress tests simulating malformed, corrupt, or unexpected gateway payloads."""

    @pytest.mark.asyncio
    async def test_corrupted_payload_handling_in_cycle(self, tmp_path: Path) -> None:
        """Verifies empty or malformed payloads from the gateway do not crash cycle."""
        db_file = tmp_path / "corrupted_payload.db"
        store = MarketDataStore(db_path=db_file)

        mock_gateway = AsyncMock()
        mock_gateway.get_candles.side_effect = [
            [],  # Empty list
            [{"malformed": "dict_without_timestamp"}],  # Missing required fields
            _create_mock_candles(8, 1700000000.0),  # Valid
        ]

        assets = ["EMPTY_otc", "MALFORMED_otc", "VALID_otc"]
        results = await collect_cycle(
            gateway=mock_gateway,
            store=store,
            assets=assets,
            throttle_delay=0.0,
        )

        assert results.get("EMPTY_otc") == 0
        assert results.get("MALFORMED_otc") == 0
        assert results.get("VALID_otc") == 8
        assert store.count_candles("VALID_otc") == 8
        assert store.get_total_candle_count() == 8

    @pytest.mark.asyncio
    async def test_mixed_types_raw_wire_format_and_domain_entities(self, tmp_path: Path) -> None:
        """Verifies that MarketDataStore safely accepts mixed formats in batch inserts."""
        db_file = tmp_path / "mixed_types.db"
        store = MarketDataStore(db_path=db_file)

        base_t = 1700005000.0
        mixed_batch: list[Any] = [
            # Domain Candle entity
            Candle(
                open_time=datetime.fromtimestamp(base_t, tz=UTC),
                open=Decimal("1.1000"),
                high=Decimal("1.1010"),
                low=Decimal("1.0990"),
                close=Decimal("1.1005"),
                volume=Decimal("100.0"),
            ),
            # Dict with 'time'
            {
                "time": base_t + 1,
                "open": 1.1005,
                "high": 1.1015,
                "low": 1.1000,
                "close": 1.1010,
                "volume": 50.0,
            },
            # Dict with 'timestamp'
            {
                "timestamp": base_t + 2,
                "open": 1.1010,
                "high": 1.1020,
                "low": 1.1005,
                "close": 1.1015,
            },
            # Dict with short keys 't', 'o', 'h', 'l', 'c', 'v'
            {
                "t": base_t + 3,
                "o": 1.1015,
                "h": 1.1025,
                "l": 1.1010,
                "c": 1.1020,
                "v": 25.0,
            },
            # Corrupt item in the middle
            {"garbage": 12345},
            None,
            "not_a_candle",
        ]

        inserted = store.insert_candles("MIXED_otc", mixed_batch)
        assert inserted == 4
        assert store.count_candles("MIXED_otc") == 4

        df = store.get_candles_df("MIXED_otc")
        assert len(df) == 4
        assert list(df["open"]) == [1.1000, 1.1005, 1.1010, 1.1015]


class TestGracefulCancellationAndCleanup:
    """Verifies clean shutdown, signal handling, and gateway resource release."""

    @pytest.mark.asyncio
    async def test_shutdown_event_aborts_subsequent_assets_in_cycle(self, tmp_path: Path) -> None:
        """Verifies setting shutdown_event halts subsequent asset queries in cycle immediately."""
        db_file = tmp_path / "throttle_shutdown.db"
        store = MarketDataStore(db_path=db_file)

        mock_gateway = AsyncMock()
        mock_gateway.get_candles.return_value = _create_mock_candles(5)

        shutdown = asyncio.Event()

        # Custom collect cycle where shutdown is triggered after first asset
        async def _run() -> dict[str, int]:
            return await collect_cycle(
                gateway=mock_gateway,
                store=store,
                assets=["A1", "A2", "A3", "A4"],
                throttle_delay=0.05,
                shutdown_event=shutdown,
            )

        task = asyncio.create_task(_run())
        # Let first asset fetch happen
        await asyncio.sleep(0.01)
        # Signal shutdown
        shutdown.set()
        results = await asyncio.wait_for(task, timeout=1.0)

        # Only 1 asset was fetched before shutdown halted remaining assets
        assert mock_gateway.get_candles.call_count == 1
        assert "A1" in results
        assert "A2" not in results

    @pytest.mark.asyncio
    async def test_shutdown_event_during_interval_sleep(self, tmp_path: Path) -> None:
        """Verifies setting shutdown_event wakes up the inter-cycle sleep immediately."""
        db_file = tmp_path / "interval_shutdown.db"
        store = MarketDataStore(db_path=db_file)

        mock_gateway = AsyncMock()
        mock_gateway.get_candles.return_value = _create_mock_candles(3)

        shutdown = asyncio.Event()

        task = asyncio.create_task(
            run_collector_loop(
                gateway=mock_gateway,
                store=store,
                assets=["EURUSD_otc"],
                interval=60.0,  # 60s sleep
                throttle_delay=0.0,
                shutdown_event=shutdown,
            )
        )

        await asyncio.sleep(0.05)  # Cycle 1 finishes, enters 60s wait
        shutdown.set()  # Trigger shutdown
        # Must exit within < 0.5s instead of waiting 60s
        await asyncio.wait_for(task, timeout=1.0)
        assert mock_gateway.get_candles.call_count == 1

    @pytest.mark.asyncio
    async def test_main_cancels_and_guarantees_gateway_aclose(self, tmp_path: Path) -> None:
        """Verifies main() guarantees gateway.aclose() even on asyncio.CancelledError."""
        db_file = str(tmp_path / "main_cancel.db")

        mock_gateway = AsyncMock()

        async def _long_fetch(*args: Any, **kwargs: Any) -> list[Candle]:
            await asyncio.sleep(10.0)
            return []

        mock_gateway.get_candles.side_effect = _long_fetch
        mock_gateway.aclose = AsyncMock()

        with patch(
            "scripts.collect_s1_data.PocketOptionTradingGateway",
            return_value=mock_gateway,
        ):
            main_task = asyncio.create_task(
                main(
                    [
                        "--assets",
                        "EURUSD_otc",
                        "--db-path",
                        db_file,
                        "--interval",
                        "10.0",
                        "--throttle-delay",
                        "0.0",
                    ]
                )
            )

            await asyncio.sleep(0.05)
            main_task.cancel()
            try:
                await main_task
            except asyncio.CancelledError:
                pass

        mock_gateway.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_main_aclose_error_does_not_mask_exit(self, tmp_path: Path) -> None:
        """Verifies if gateway.aclose() raises an error during cleanup, it does not crash."""
        db_file = str(tmp_path / "aclose_err.db")

        mock_gateway = AsyncMock()
        mock_gateway.get_candles.return_value = _create_mock_candles(2)
        mock_gateway.aclose = AsyncMock(side_effect=RuntimeError("Socket cleanup failed"))

        with patch(
            "scripts.collect_s1_data.PocketOptionTradingGateway",
            return_value=mock_gateway,
        ):
            # Should complete without throwing RuntimeError
            await main(["--once", "--assets", "EURUSD_otc", "--db-path", db_file])

        mock_gateway.aclose.assert_awaited_once()


class TestCLIExecutionAndEdgeCases:
    """Verifies CLI arguments parsing, environment fallbacks, and command-line execution."""

    def test_parse_args_all_switches_and_defaults(self) -> None:
        default_args = parse_args([])
        assert default_args.assets == "EURUSD_otc,GOLD_otc,AUDNZD_otc"
        assert default_args.timeframe == 1
        assert default_args.count == 300
        assert default_args.interval == 60.0
        assert default_args.db_path == "data/market_data.db"
        assert default_args.demo is True
        assert default_args.once is False
        assert default_args.max_cycles is None
        assert default_args.throttle_delay == 0.5
        assert default_args.log_level == "INFO"

        custom_args = parse_args(
            [
                "--assets",
                "CADCHF_otc,USDCAD",
                "--timeframe",
                "5",
                "--count",
                "500",
                "--interval",
                "30.0",
                "--db-path",
                "custom/path/data.db",
                "--ssid",
                "my_custom_token",
                "--live",
                "--once",
                "--max-cycles",
                "10",
                "--throttle-delay",
                "1.5",
                "--log-level",
                "DEBUG",
            ]
        )
        assert custom_args.assets == "CADCHF_otc,USDCAD"
        assert custom_args.timeframe == 5
        assert custom_args.count == 500
        assert custom_args.interval == 30.0
        assert custom_args.db_path == "custom/path/data.db"
        assert custom_args.ssid == "my_custom_token"
        assert custom_args.demo is False
        assert custom_args.once is True
        assert custom_args.max_cycles == 10
        assert custom_args.throttle_delay == 1.5
        assert custom_args.log_level == "DEBUG"

    @pytest.mark.asyncio
    async def test_main_empty_assets_arg_exits_cleanly(self, tmp_path: Path) -> None:
        """Verifies passing empty or whitespace assets exits cleanly without unhandled exception."""
        db_file = str(tmp_path / "empty_assets.db")
        mock_gateway = AsyncMock()

        with patch(
            "scripts.collect_s1_data.PocketOptionTradingGateway",
            return_value=mock_gateway,
        ):
            await main(["--assets", "   ,  , ", "--db-path", db_file])

        assert mock_gateway.get_candles.call_count == 0

    def test_subprocess_cli_invocation_once_mode(self, tmp_path: Path) -> None:
        """Executes `scripts/collect_s1_data.py` as a real external subprocess with `--once`."""
        db_path = tmp_path / "subprocess_test.db"

        cmd = [
            sys.executable,
            "scripts/collect_s1_data.py",
            "--once",
            "--assets",
            "EURUSD_otc",
            "--count",
            "10",
            "--db-path",
            str(db_path),
            "--throttle-delay",
            "0.0",
            "--ssid",
            "demo",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(Path(__file__).resolve().parent.parent),
        )

        # The script should exit with code 0 (even in offline/demo mode, it exits cleanly)
        assert result.returncode == 0
        assert db_path.is_file()


class TestEndToEndBacktestAndDataPipelineCompatibility:
    """Verifies that collected candles stored in SQLite cleanly fuel BinaryBacktestEngine."""

    def test_stored_s1_candles_execute_seamlessly_in_backtest_engine(self, tmp_path: Path) -> None:
        """Simulates 500 S1 candles collected across 5 overlapping cycles and backtests them."""
        db_file = tmp_path / "backtest_pipeline.db"
        store = MarketDataStore(db_path=db_file)

        # Simulate 5 collection cycles with overlapping windows
        base_t = 1700000000.0
        for cycle in range(5):
            cycle_start = base_t + cycle * 50
            candles = _create_mock_candles(
                count=100,
                start_ts=cycle_start,
                base_price=1.0850 + cycle * 0.0005,
            )
            store.insert_candles("EURUSD_otc", candles)

        total_candles = store.count_candles("EURUSD_otc")
        # 5 cycles: [0..99], [50..149], [100..199], [150..249], [200..299] -> 300 unique timestamps
        assert total_candles == 300

        # Retrieve canonical DataFrame
        df = store.get_candles_df("EURUSD_otc")
        assert len(df) == 300
        assert df["timestamp"].is_monotonic_increasing
        assert df["timestamp"].dt.tz is not None

        # Verify time-based backtest engine compatibility (Stage 1 integration)
        config = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=1,  # S1 timeframe
            strategy_name="support_resistance_bounce",
            initial_deposit=Decimal("1000.0"),
            stake_amount=Decimal("25.0"),
            expiration_bars=3,
            expiration_seconds=180,
        )

        engine = BinaryBacktestEngine(config=config)
        summary = engine.run(df)

        assert summary is not None
        assert summary.initial_deposit == Decimal("1000.0")
        assert summary.total_trades >= 0
        assert summary.win_rate_pct >= Decimal("0.0")
