from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timezone

from strat_trade.domain.entities import Candle
from strat_trade.ports.candles import CandleFeed
from strat_trade.ports.signal_repository import SignalRepository

logger = logging.getLogger(__name__)

_ONE_MINUTE_SECONDS = 60


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _minute_bar_open_time(expected_close: datetime) -> datetime:
    """UTC open time of the 1-minute candle that contains `expected_close`."""
    u = _utc(expected_close)
    epoch = int(u.timestamp())
    start = epoch - (epoch % _ONE_MINUTE_SECONDS)
    return datetime.fromtimestamp(start, tz=UTC)


def _find_one_minute_candle(candles: list[Candle], bar_open: datetime) -> Candle | None:
    target = _utc(bar_open)
    for c in candles:
        if _utc(c.open_time) == target:
            return c
    return None


def _price_compare(actual: float, entry: float) -> int:
    """Return -1 if actual < entry, 0 if ~equal, 1 if actual > entry."""
    if math.isclose(actual, entry, rel_tol=0.0, abs_tol=1e-9):
        return 0
    return 1 if actual > entry else -1


def _pnl_for_direction(direction: str, actual: float, entry: float) -> str:
    d = direction.strip().upper()
    cmp = _price_compare(actual, entry)
    if cmp == 0:
        return "TIE"
    if d == "BUY":
        return "WIN" if cmp > 0 else "LOSS"
    if d == "SELL":
        return "WIN" if cmp < 0 else "LOSS"
    raise ValueError(f"Unsupported direction for PnL: {direction!r}")


class EvaluatePendingSignalsUseCase:
    """Resolve forward-test signals whose expiry has passed using broker 1m candles."""

    def __init__(self, signal_repository: SignalRepository, candle_feed: CandleFeed) -> None:
        self._signal_repository = signal_repository
        self._candle_feed = candle_feed

    async def execute(self) -> dict[str, str | int]:
        now_utc = datetime.now(timezone.utc)
        unresolved_signals = await self._signal_repository.get_unresolved_signals(
            up_to_time=now_utc
        )
        updated = 0

        for signal in unresolved_signals:
            if signal.id is None:
                logger.warning("Skipping signal without id")
                continue

            direction = signal.direction.strip().upper()
            if direction == "NEUTRAL":
                await self._signal_repository.update_signal_resolution(
                    signal.id,
                    signal.entry_price,
                    "TIE",
                )
                updated += 1
                continue

            bar_open = _minute_bar_open_time(signal.expected_close_time)
            try:
                candles = await self._candle_feed.get_candles(
                    signal.asset.strip(),
                    _ONE_MINUTE_SECONDS,
                    count=10,
                    end_time=_utc(signal.expected_close_time),
                )
            except Exception as exc:
                logger.warning(
                    "Broker candle fetch failed for signal id=%s asset=%s: %s",
                    signal.id,
                    signal.asset,
                    exc,
                )
                continue

            match = _find_one_minute_candle(candles, bar_open)
            if match is None:
                logger.warning(
                    "No 1m candle for expected_close signal id=%s asset=%s bar_open=%s",
                    signal.id,
                    signal.asset,
                    bar_open.isoformat(),
                )
                continue

            actual_close_price = float(match.close)
            try:
                pnl_result = _pnl_for_direction(signal.direction, actual_close_price, signal.entry_price)
            except ValueError as exc:
                logger.warning("Signal id=%s: %s", signal.id, exc)
                continue

            await self._signal_repository.update_signal_resolution(
                signal.id,
                actual_close_price,
                pnl_result,
            )
            updated += 1
            print(f"🏁 [TRADE RESOLVED] {signal.asset} | Dir: {signal.direction} | Entry: {signal.entry_price} | Close: {actual_close_price} | Result: {pnl_result}", flush=True)

        return {"signals_evaluated": updated, "status": "success"}
