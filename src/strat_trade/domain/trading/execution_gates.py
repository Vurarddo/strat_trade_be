"""Entry-timing gates that decide *when* a signal may be acted upon.

Two independent leaks were measured on the 24-28.08 live sample (1101 trades):

1. Bar-edge entries. Orders opened in the first seconds of a minute were 20% of
   the trades but produced 97% of the net loss (win rate 42.67%, p=0.0024,
   reproduced out-of-sample). At a bar boundary the broker's first ticks are
   still settling, so the entry price the strategy saw is not the price it gets.

2. Forming-bar evaluation. The gateway returns candles up to `now`, so the last
   element is the currently open bar. Every indicator was therefore computed on
   a partial candle whose high/low/close still change after the decision.

Both gates are pure functions of a timestamp and a candle list so they can be
unit-tested without a broker connection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

DEFAULT_TIMEFRAME_SECONDS = 60


def seconds_into_bar(now: datetime, timeframe_seconds: int = DEFAULT_TIMEFRAME_SECONDS) -> float:
    """Elapsed seconds since the current bar opened."""
    if timeframe_seconds <= 0:
        return 0.0
    ts = now.timestamp() if now.tzinfo else now.replace(tzinfo=UTC).timestamp()
    return ts % timeframe_seconds


def is_bar_edge_blocked(
    now: datetime,
    guard_seconds: float,
    timeframe_seconds: int = DEFAULT_TIMEFRAME_SECONDS,
) -> tuple[bool, str]:
    """Blocks entries inside the unstable opening window of a bar.

    Returns (is_blocked, reason).
    """
    if guard_seconds <= 0:
        return False, ""

    elapsed = seconds_into_bar(now, timeframe_seconds)
    if elapsed < guard_seconds:
        return (
            True,
            f"Bar-edge guard: {elapsed:.1f}s into the bar, "
            f"entries allowed from {guard_seconds:.1f}s",
        )
    return False, ""


def bar_open_time(candle: Any) -> datetime | None:
    """Best-effort extraction of a candle's opening timestamp."""
    raw = getattr(candle, "open_time", None) or getattr(candle, "time", None)
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if isinstance(raw, int | float):
        return datetime.fromtimestamp(float(raw), tz=UTC)
    return None


def select_closed_candles(
    candles: list[Any],
    now: datetime | None = None,
    timeframe_seconds: int = DEFAULT_TIMEFRAME_SECONDS,
) -> list[Any]:
    """Drops trailing bars that have not finished forming yet.

    When candle timestamps are unavailable the last bar is dropped
    unconditionally, because the gateway always requests history up to `now`.
    """
    if not candles:
        return []

    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    closed = list(candles)
    while closed:
        opened_at = bar_open_time(closed[-1])
        if opened_at is None:
            return closed[:-1]
        if opened_at.timestamp() + timeframe_seconds <= now.timestamp():
            break
        closed.pop()
    return closed
