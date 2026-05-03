from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from typing import cast

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from strat_trade.adapters.trading_view_gateway import (
    TRADINGVIEW_REST_API_INTERVAL_MAP,
    TradingViewGateway,
    tradingview_rest_api_interval,
)
from strat_trade.api.schemas import TvCandleResponse
from strat_trade.domain.errors import InvalidMarketParametersError

router = APIRouter(prefix="/tradingview")


def _tv_frame_to_candles(df: pd.DataFrame) -> list[TvCandleResponse]:
    """Build response models; map NaN to None for JSON."""
    if df.empty:
        return []
    out: list[TvCandleResponse] = []
    for rec in df.to_dict(orient="records"):
        ts = rec["timestamp"]
        if isinstance(ts, pd.Timestamp):
            ts_py = ts.to_pydatetime()
            if ts_py.tzinfo is None:
                ts_py = ts_py.replace(tzinfo=UTC)
            ts = ts_py
        elif isinstance(ts, datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        def num(v: object) -> float | None:
            if v is None:
                return None
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return None
            try:
                f = float(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
            if math.isnan(f) or math.isinf(f):
                return None
            return f

        out.append(
            TvCandleResponse(
                timestamp=cast(datetime, ts),
                open=num(rec.get("open")),
                high=num(rec.get("high")),
                low=num(rec.get("low")),
                close=num(rec.get("close")),
                volume=num(rec.get("volume")),
            ),
        )
    return out


@router.get(
    "/candles",
    response_model=list[TvCandleResponse],
    summary="TradingView OHLCV preview",
    description=(
        "Fetches normalized historical bars via tvdatafeed (blocking I/O runs in a thread). "
        f"Supported `interval` values: {', '.join(sorted(TRADINGVIEW_REST_API_INTERVAL_MAP))}."
    ),
    operation_id="getTradingViewCandles",
)
async def get_tradingview_candles(
    symbol: str = Query(
        ...,
        min_length=1,
        max_length=64,
        examples=["BTCUSD"],
        description="TradingView symbol (ticker), e.g. BTCUSD.",
    ),
    exchange: str = Query(
        ...,
        min_length=1,
        max_length=64,
        examples=["BINANCE"],
        description="TradingView exchange id, e.g. BINANCE, FX_IDC, OANDA.",
    ),
    interval: str = Query(
        ...,
        min_length=1,
        max_length=8,
        examples=["1h"],
        description="Bar size (REST token mapped to tvDatafeed.Interval).",
    ),
    limit: int = Query(
        500,
        ge=1,
        le=5000,
        description="Number of bars to request (most recent `limit` bars).",
    ),
) -> list[TvCandleResponse]:
    try:
        tv_interval = tradingview_rest_api_interval(interval)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    def _run() -> pd.DataFrame:
        gateway = TradingViewGateway()
        return gateway.fetch_ohlcv(
            symbol.strip(),
            exchange.strip(),
            tv_interval,
            n_bars=limit,
        )

    try:
        df = await asyncio.to_thread(_run)
    except InvalidMarketParametersError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover - network / TV client failures
        raise HTTPException(
            status_code=404,
            detail="Unable to fetch TradingView candles for this symbol or exchange.",
        ) from e

    if df.empty:
        raise HTTPException(
            status_code=404,
            detail="No candle data returned (unknown symbol/exchange or empty history).",
        )

    return _tv_frame_to_candles(df)
