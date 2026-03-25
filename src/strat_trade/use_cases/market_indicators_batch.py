from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from strat_trade.domain.entities import Candle
from strat_trade.domain.errors import InvalidMarketParametersError
from strat_trade.domain.indicators.registry import build_calculator, min_bars_for_indicator
from strat_trade.ports.candles import CandleFeed
from strat_trade.use_cases.fetch_candles import fetch_recent_candles


@dataclass(frozen=True, slots=True)
class IndicatorRunSpec:
    indicator_id: str
    params: dict[str, Any]
    response_key: str


@dataclass(frozen=True, slots=True)
class IndicatorSeriesBlock:
    indicator_id: str
    params: dict[str, Any]
    outputs: dict[str, list[float | None]]


@dataclass(frozen=True, slots=True)
class MarketIndicatorsBatchResult:
    candles: list[Candle]
    indicator_blocks: list[IndicatorSeriesBlock]
    has_more: bool
    next_cursor: datetime | None


async def compute_market_indicators_batch(
    feed: CandleFeed,
    *,
    asset: str,
    timeframe_seconds: int,
    count: int,
    max_count: int,
    max_indicator_runs: int,
    runs: list[IndicatorRunSpec],
    end_at: datetime | None = None,
    cursor: datetime | None = None,
) -> MarketIndicatorsBatchResult:
    """
    One candle fetch; compute every requested indicator on the same bar window (order preserved).
    """
    if not runs:
        raise InvalidMarketParametersError("At least one indicator run is required.")
    if len(runs) > max_indicator_runs:
        raise InvalidMarketParametersError(
            f"At most {max_indicator_runs} indicator runs per request "
            f"(raise STRAT_TRADE_MAX_INDICATORS_PER_MARKET_REQUEST if needed)."
        )

    min_bars = 1
    for spec in runs:
        need = min_bars_for_indicator(spec.indicator_id, spec.params)
        if need > min_bars:
            min_bars = need

    if count < min_bars:
        raise InvalidMarketParametersError(
            f"count must be >= {min_bars} for the selected indicators (largest warmup window)."
        )

    page = await fetch_recent_candles(
        feed,
        asset=asset,
        timeframe_seconds=timeframe_seconds,
        count=count,
        max_count=max_count,
        end_at=end_at,
        cursor=cursor,
    )

    blocks: list[IndicatorSeriesBlock] = []
    for spec in runs:
        calc = build_calculator(spec.indicator_id, spec.params)
        outputs = calc.compute(page.candles)
        blocks.append(
            IndicatorSeriesBlock(
                indicator_id=spec.indicator_id,
                params=dict(spec.params),
                outputs=outputs,
            )
        )

    return MarketIndicatorsBatchResult(
        candles=page.candles,
        indicator_blocks=blocks,
        has_more=page.has_more,
        next_cursor=page.next_cursor,
    )


def build_indicator_rows_by_time_key(
    time_keys: list[str],
    runs: list[IndicatorRunSpec],
    blocks: list[IndicatorSeriesBlock],
) -> list[tuple[str, str, dict[str, Any], dict[str, dict[str, float]]]]:
    """
    One row per request run, same order as `runs`. Each row:
    (response_key, indicator_id, params, outputs) where outputs is output_name -> { time_key: value }.
    Empty series are omitted; `outputs` may be {} if nothing is defined yet.
    """
    if len(runs) != len(blocks):
        raise ValueError("runs and blocks must have the same length.")
    n = len(time_keys)
    rows: list[tuple[str, str, dict[str, Any], dict[str, dict[str, float]]]] = []
    for spec, block in zip(runs, blocks, strict=True):
        out_maps: dict[str, dict[str, float]] = {}
        for out_name, series in block.outputs.items():
            point_map: dict[str, float] = {}
            for i, val in enumerate(series):
                if i >= n:
                    break
                if val is not None:
                    point_map[time_keys[i]] = val
            if point_map:
                out_maps[out_name] = point_map
        rows.append((spec.response_key, block.indicator_id, dict(block.params), out_maps))
    return rows
