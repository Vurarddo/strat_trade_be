from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from strat_trade.domain.errors import InvalidMarketParametersError
from strat_trade.domain.indicators import IndicatorRegistry, IndicatorSeries
from strat_trade.ports.candles import CandleFeed
from strat_trade.use_cases.fetch_candles import (
    CandlesPageResult,
    fetch_candles_in_range,
    fetch_recent_candles,
)


@dataclass(frozen=True, slots=True)
class ClientIndicatorSpec:
    """One requested indicator instance (client-chosen key for the response map)."""

    key: str
    indicator_id: str
    params: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class MarketIndicatorsResult:
    page: CandlesPageResult
    include_candles: bool
    indicators: dict[str, IndicatorSeries]


def _dedupe_keys(specs: Sequence[ClientIndicatorSpec]) -> None:
    seen: set[str] = set()
    for s in specs:
        if s.key in seen:
            raise InvalidMarketParametersError(f"Duplicate indicator key {s.key!r}.")
        seen.add(s.key)


async def compute_market_indicators(
    feed: CandleFeed,
    registry: IndicatorRegistry,
    *,
    asset: str,
    timeframe_seconds: int,
    include_candles: bool,
    specs: Sequence[ClientIndicatorSpec],
    recent: tuple[int, datetime | None, datetime | None] | None,
    range_window: tuple[datetime, datetime] | None,
    max_candles_per_request: int,
    max_candles_range_total: int,
    max_candles_range_fetch_rounds: int,
) -> MarketIndicatorsResult:
    """
    Load candles (recent page or fixed range), then run every indicator spec on the same series.
    """
    if (recent is None) == (range_window is None):
        raise InvalidMarketParametersError("Provide exactly one window: recent or range.")
    _dedupe_keys(specs)

    if recent is not None:
        count, end_at, cursor = recent
        page = await fetch_recent_candles(
            feed,
            asset=asset,
            timeframe_seconds=timeframe_seconds,
            count=count,
            max_count=max_candles_per_request,
            end_at=end_at,
            cursor=cursor,
        )
    else:
        assert range_window is not None
        rs, re = range_window
        page = await fetch_candles_in_range(
            feed,
            asset=asset,
            timeframe_seconds=timeframe_seconds,
            range_start=rs,
            range_end=re,
            max_chunk=max_candles_per_request,
            max_bars_in_range=max_candles_range_total,
            max_fetch_rounds=max_candles_range_fetch_rounds,
        )

    candles = page.candles
    indicators: dict[str, IndicatorSeries] = {}
    for spec in specs:
        calc = registry.build(spec.indicator_id, spec.params)
        indicators[spec.key] = calc.compute(candles)

    return MarketIndicatorsResult(page=page, include_candles=include_candles, indicators=indicators)
