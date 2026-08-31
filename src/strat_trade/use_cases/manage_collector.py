from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from strat_trade.api.schemas import CollectorAssetStatResponse, CollectorStatusResponse
from strat_trade.domain.errors import (
    BrokerUnavailableError,
    InvalidMarketParametersError,
)
from strat_trade.domain.trading.market_data_store import MarketDataStore

logger = logging.getLogger(__name__)


class CollectorStatus(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"


class AsyncCollectorEngine:
    """Singleton service managing the asynchronous background candle collection lifecycle."""

    def __init__(self, store: MarketDataStore | None = None) -> None:
        self._store = store or MarketDataStore()
        self._status = CollectorStatus.IDLE
        self._started_at: datetime | None = None
        self._active_assets: list[str] = []
        self._timeframe_seconds: int = 1
        self._candles_count: int = 300
        self._interval_seconds: float = 60.0
        self._throttle_delay: float = 0.5
        self._cycles_completed: int = 0
        self._total_candles_saved: int = 0
        self._last_cycle_at: datetime | None = None
        self._gateway: Any | None = None
        self._task: asyncio.Task[None] | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def status(self) -> CollectorStatus:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._status == CollectorStatus.RUNNING

    @property
    def store(self) -> MarketDataStore:
        return self._store

    def set_store(self, store: MarketDataStore) -> None:
        self._store = store

    async def start(
        self,
        gateway: Any,
        assets: Sequence[str],
        *,
        timeframe_seconds: int = 1,
        candles_count: int = 300,
        interval_seconds: float = 60.0,
        throttle_delay: float = 0.5,
        store: MarketDataStore | None = None,
    ) -> CollectorStatusResponse:
        """Starts or reconfigures the background candle collection task."""
        lock = self._get_lock()
        async with lock:
            if store is not None:
                self._store = store

            clean_assets = [a.strip() for a in assets if a and a.strip()]
            clean_assets = list(dict.fromkeys(clean_assets))
            if not clean_assets:
                raise InvalidMarketParametersError("Assets list cannot be empty.")

            self._gateway = gateway
            self._active_assets = clean_assets
            self._timeframe_seconds = timeframe_seconds
            self._candles_count = candles_count
            self._interval_seconds = interval_seconds
            self._throttle_delay = throttle_delay

            if self._status == CollectorStatus.RUNNING:
                logger.info(
                    "Collector already running; updated active assets: %s",
                    self._active_assets,
                )
                return self.get_status()

            self._started_at = datetime.now(UTC)
            self._cycles_completed = 0
            self._total_candles_saved = 0
            self._last_cycle_at = None
            self._shutdown_event = asyncio.Event()
            self._status = CollectorStatus.RUNNING
            self._task = asyncio.create_task(self._run_loop(self._shutdown_event))
            logger.info(
                "AsyncCollectorEngine started: %d assets, interval=%.1fs, throttle=%.2fs",
                len(self._active_assets),
                self._interval_seconds,
                self._throttle_delay,
            )
            return self.get_status()

    async def stop(self) -> CollectorStatusResponse:
        """Gracefully halts the background collection loop."""
        lock = self._get_lock()
        async with lock:
            if self._status != CollectorStatus.RUNNING:
                return self.get_status()

            self._status = CollectorStatus.STOPPED
            if self._shutdown_event is not None:
                self._shutdown_event.set()
            task = self._task
            self._task = None

        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Exception during collector task cancellation: %s", exc)

        logger.info("AsyncCollectorEngine stopped.")
        return self.get_status()

    def get_status(self, store: MarketDataStore | None = None) -> CollectorStatusResponse:
        """Constructs a point-in-time status snapshot including per-asset database statistics."""
        current_store = store or self._store
        stored_assets = current_store.get_stored_assets()

        all_assets_dict: dict[str, None] = {}
        for a in self._active_assets:
            all_assets_dict[a] = None
        for a in stored_assets:
            all_assets_dict[a] = None

        asset_stats: list[CollectorAssetStatResponse] = []
        is_running = self._status == CollectorStatus.RUNNING

        for asset in all_assets_dict:
            raw_stat = current_store.get_asset_stats(asset)
            is_otc = "_otc" in asset.lower()
            payout = 92 if is_otc else 80
            is_collecting = is_running and (asset in self._active_assets)

            asset_stats.append(
                CollectorAssetStatResponse(
                    asset=raw_stat["asset"],
                    name=raw_stat["asset"],
                    count=raw_stat["count"],
                    first_timestamp=raw_stat["first_timestamp"],
                    last_timestamp=raw_stat["last_timestamp"],
                    first_time=raw_stat["first_time"],
                    last_time=raw_stat["last_time"],
                    payout=payout,
                    is_otc=is_otc,
                    is_collecting=is_collecting,
                )
            )

        total_db_candles = current_store.get_total_candle_count()

        return CollectorStatusResponse(
            status=self._status.value,
            is_running=is_running,
            started_at=self._started_at,
            active_assets=list(self._active_assets),
            timeframe_seconds=self._timeframe_seconds,
            candles_count=self._candles_count,
            interval_seconds=self._interval_seconds,
            throttle_delay=self._throttle_delay,
            cycles_completed=self._cycles_completed,
            total_candles_saved=self._total_candles_saved,
            last_cycle_at=self._last_cycle_at,
            asset_stats=asset_stats,
            total_database_candles=total_db_candles,
        )

    async def _run_loop(self, event: asyncio.Event) -> None:
        """Internal worker loop executing sequential asset collection passes."""
        try:
            while not event.is_set():
                self._cycles_completed += 1
                assets_to_process = list(self._active_assets)
                logger.debug(
                    "Starting collector cycle #%d across %d assets",
                    self._cycles_completed,
                    len(assets_to_process),
                )

                for asset in assets_to_process:
                    if event.is_set():
                        break

                    try:
                        if self._gateway is not None:
                            candles = await self._gateway.get_candles(
                                asset=asset,
                                timeframe=self._timeframe_seconds,
                                count=self._candles_count,
                            )
                            inserted = self._store.insert_candles(asset, candles)
                            self._total_candles_saved += inserted
                            logger.debug(
                                "[%s] Fetched %d candles, inserted %d new rows",
                                asset,
                                len(candles),
                                inserted,
                            )
                    except (
                        BrokerUnavailableError,
                        TimeoutError,
                        InvalidMarketParametersError,
                        ConnectionError,
                        OSError,
                    ) as exc:
                        logger.warning("Collector transient error on asset %s: %s", asset, exc)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.error(
                            "Collector unexpected error on asset %s: %s",
                            asset,
                            exc,
                            exc_info=True,
                        )

                    if self._throttle_delay > 0 and not event.is_set():
                        try:
                            await asyncio.sleep(self._throttle_delay)
                        except asyncio.CancelledError:
                            raise

                self._last_cycle_at = datetime.now(UTC)

                if event.is_set():
                    break

                try:
                    await asyncio.wait_for(
                        event.wait(),
                        timeout=max(0.001, self._interval_seconds),
                    )
                except TimeoutError:
                    pass
                except asyncio.CancelledError:
                    raise
        except asyncio.CancelledError:
            logger.info("Collector loop cancelled.")
            raise
        except Exception as exc:
            logger.error("Fatal error in collector loop: %s", exc, exc_info=True)
            self._status = CollectorStatus.STOPPED


# Global singleton collector engine instance
_global_collector_engine = AsyncCollectorEngine()


def get_collector_engine() -> AsyncCollectorEngine:
    return _global_collector_engine


async def start_collector(
    gateway: Any,
    assets: Sequence[str],
    *,
    timeframe_seconds: int = 1,
    candles_count: int = 300,
    interval_seconds: float = 60.0,
    throttle_delay: float = 0.5,
    store: MarketDataStore | None = None,
) -> CollectorStatusResponse:
    engine = get_collector_engine()
    return await engine.start(
        gateway=gateway,
        assets=assets,
        timeframe_seconds=timeframe_seconds,
        candles_count=candles_count,
        interval_seconds=interval_seconds,
        throttle_delay=throttle_delay,
        store=store,
    )


async def stop_collector() -> CollectorStatusResponse:
    engine = get_collector_engine()
    return await engine.stop()


def get_collector_status(store: MarketDataStore | None = None) -> CollectorStatusResponse:
    engine = get_collector_engine()
    return engine.get_status(store=store)
