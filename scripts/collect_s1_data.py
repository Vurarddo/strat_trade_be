#!/usr/bin/env python3
"""Standalone high-frequency (1-second) candle data collector for Pocket Option.

Fetches S1 candles periodically using PocketOptionTradingGateway and persists
them to a local SQLite database via MarketDataStore with duplicate suppression.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from collections.abc import Sequence
from pathlib import Path

# Add project and src root to sys.path if needed
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from strat_trade.adapters.pocket_option_gateway import PocketOptionTradingGateway  # noqa: E402
from strat_trade.domain.errors import (  # noqa: E402
    BrokerUnavailableError,
    InvalidMarketParametersError,
)
from strat_trade.domain.trading.market_data_store import MarketDataStore  # noqa: E402
from strat_trade.settings import Settings  # noqa: E402

DEFAULT_TARGET_ASSETS: list[str] = ["EURUSD_otc", "GOLD_otc", "AUDNZD_otc"]
DEFAULT_INTERVAL_SECONDS: float = 60.0
DEFAULT_CANDLES_COUNT: int = 300
DEFAULT_TIMEFRAME: int = 1
DEFAULT_DB_PATH: str = "data/market_data.db"

logger = logging.getLogger("collect_s1_data")


def resolve_ssid(
    cli_ssid: str | None = None,
    cli_ssid_file: str | None = None,
) -> str:
    """Resolves Pocket Option SSID from CLI args, Settings, environment, or fallbacks."""
    if cli_ssid and cli_ssid.strip():
        return cli_ssid.strip()

    if cli_ssid_file and cli_ssid_file.strip():
        file_path = Path(cli_ssid_file.strip()).expanduser()
        if file_path.is_file():
            content = file_path.read_text(encoding="utf-8").removeprefix("\ufeff").strip()
            if content:
                return content

    try:
        settings = Settings()
        if settings.pocket_option_ssid and settings.pocket_option_ssid.strip():
            return settings.pocket_option_ssid.strip()
    except Exception:
        pass

    for env_var in ("STRAT_TRADE_POCKET_OPTION_SSID", "POCKET_OPTION_SSID"):
        val = os.getenv(env_var)
        if val and val.strip():
            return val.strip()

    for file_var in (
        "STRAT_TRADE_POCKET_OPTION_SSID_FILE",
        "POCKET_OPTION_SSID_FILE",
        "POCKETOPTION_SSID_FILE",
    ):
        file_env = os.getenv(file_var)
        if file_env and file_env.strip():
            fp = Path(file_env.strip()).expanduser()
            if fp.is_file():
                content = fp.read_text(encoding="utf-8").removeprefix("\ufeff").strip()
                if content:
                    return content

    root_ssid = PROJECT_ROOT / ".ssid"
    if root_ssid.is_file():
        content = root_ssid.read_text(encoding="utf-8").removeprefix("\ufeff").strip()
        if content:
            return content

    return "demo"


async def collect_cycle(
    gateway: PocketOptionTradingGateway,
    store: MarketDataStore,
    assets: Sequence[str],
    *,
    timeframe: int = DEFAULT_TIMEFRAME,
    count: int = DEFAULT_CANDLES_COUNT,
    throttle_delay: float = 0.5,
    shutdown_event: asyncio.Event | None = None,
) -> dict[str, int]:
    """Runs a single data collection pass across target assets.

    Returns mapping of asset -> newly inserted candle count.
    """
    results: dict[str, int] = {}
    for asset in assets:
        if shutdown_event and shutdown_event.is_set():
            logger.info("Shutdown signaled, aborting remaining assets in cycle.")
            break

        clean_asset = asset.strip()
        if not clean_asset:
            continue

        try:
            logger.debug(
                "Fetching %d S%d candles for %s...",
                count,
                timeframe,
                clean_asset,
            )
            candles = await gateway.get_candles(
                clean_asset,
                timeframe=timeframe,
                count=count,
            )
            inserted = store.insert_candles(clean_asset, candles)
            results[clean_asset] = inserted
            total_db = store.count_candles(clean_asset)
            logger.info(
                "[%s] Fetched %d candles, saved %d new rows (total stored: %d).",
                clean_asset,
                len(candles),
                inserted,
                total_db,
            )
        except (BrokerUnavailableError, TimeoutError) as exc:
            logger.warning(
                "[%s] Transient broker error or timeout: %s. Continuing loop.",
                clean_asset,
                exc,
            )
        except InvalidMarketParametersError as exc:
            logger.warning(
                "[%s] Invalid market parameters: %s. Continuing loop.",
                clean_asset,
                exc,
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "[%s] Network error: %s. Continuing loop.",
                clean_asset,
                exc,
            )
        except Exception as exc:
            logger.error(
                "[%s] Unexpected exception during candle fetch: %s",
                clean_asset,
                exc,
                exc_info=True,
            )

        if throttle_delay > 0 and not (shutdown_event and shutdown_event.is_set()):
            await asyncio.sleep(throttle_delay)

    return results


async def run_collector_loop(
    gateway: PocketOptionTradingGateway,
    store: MarketDataStore,
    assets: Sequence[str],
    *,
    timeframe: int = DEFAULT_TIMEFRAME,
    count: int = DEFAULT_CANDLES_COUNT,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    once: bool = False,
    max_cycles: int | None = None,
    throttle_delay: float = 0.5,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Asynchronous infinite collection loop with graceful shutdown support."""
    event = shutdown_event or asyncio.Event()
    logger.info(
        "Starting S%d collection loop: assets=%s, interval=%.1fs, count=%d, once=%s, max_cycles=%s",
        timeframe,
        list(assets),
        interval,
        count,
        once,
        max_cycles,
    )

    cycles_completed = 0
    while not event.is_set():
        cycles_completed += 1
        logger.info("=== Starting collection cycle #%d ===", cycles_completed)

        await collect_cycle(
            gateway=gateway,
            store=store,
            assets=assets,
            timeframe=timeframe,
            count=count,
            throttle_delay=throttle_delay,
            shutdown_event=event,
        )

        if once:
            logger.info("Single-pass mode (--once) active; finishing collector loop.")
            break

        if max_cycles is not None and cycles_completed >= max_cycles:
            logger.info(
                "Reached maximum cycle limit (%d); exiting collector loop.",
                max_cycles,
            )
            break

        if event.is_set():
            break

        logger.info(
            "Cycle #%d finished. Sleeping for %.1fs until next cycle...",
            cycles_completed,
            interval,
        )
        try:
            await asyncio.wait_for(event.wait(), timeout=max(0.001, interval))
        except TimeoutError:
            pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses command-line arguments for the S1 collector."""
    parser = argparse.ArgumentParser(
        description="High-frequency S1 candle collector for Pocket Option AutoTrader Pro.",
    )
    parser.add_argument(
        "--assets",
        default=",".join(DEFAULT_TARGET_ASSETS),
        help=f"Comma-separated list of asset symbols (default: {','.join(DEFAULT_TARGET_ASSETS)})",
    )
    parser.add_argument(
        "--timeframe",
        type=int,
        default=DEFAULT_TIMEFRAME,
        help=f"Candle timeframe in seconds (default: {DEFAULT_TIMEFRAME})",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_CANDLES_COUNT,
        help=f"Number of candles to query per batch (default: {DEFAULT_CANDLES_COUNT})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Polling interval between cycles in seconds (default: {DEFAULT_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--ssid",
        default=None,
        help="Pocket Option session SSID (overrides environment and .ssid file)",
    )
    parser.add_argument(
        "--ssid-file",
        default=None,
        help="Path to file containing Pocket Option SSID",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        default=True,
        help="Use demo account mode (default: True)",
    )
    parser.add_argument(
        "--live",
        action="store_false",
        dest="demo",
        help="Use real money live account mode",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single collection cycle and exit immediately",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Maximum collection cycles to run before exiting (default: infinite)",
    )
    parser.add_argument(
        "--throttle-delay",
        type=float,
        default=0.5,
        help="Sleep delay in seconds between asset queries in a cycle (default: 0.5s)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console logging verbosity level (default: INFO)",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    """Script entrypoint."""
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    assets = [a.strip() for a in args.assets.split(",") if a.strip()]
    if not assets:
        logger.error("No valid assets provided. Exiting.")
        return

    ssid = resolve_ssid(args.ssid, args.ssid_file)
    logger.info("Resolved SSID (length: %d chars, is_demo: %s)", len(ssid), args.demo)

    store = MarketDataStore(db_path=args.db_path)
    gateway = PocketOptionTradingGateway(ssid=ssid, is_demo=args.demo)

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except (NotImplementedError, RuntimeError):
            pass

    try:
        await run_collector_loop(
            gateway=gateway,
            store=store,
            assets=assets,
            timeframe=args.timeframe,
            count=args.count,
            interval=args.interval,
            once=args.once,
            max_cycles=args.max_cycles,
            throttle_delay=args.throttle_delay,
            shutdown_event=shutdown_event,
        )
    except asyncio.CancelledError:
        logger.info("Collector task received cancellation request.")
    finally:
        logger.info("Shutting down Pocket Option gateway connection...")
        try:
            await gateway.aclose()
        except Exception as exc:
            logger.debug("Error while closing gateway: %s", exc)
        logger.info("Collector shutdown successfully completed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Process interrupted by user.")
