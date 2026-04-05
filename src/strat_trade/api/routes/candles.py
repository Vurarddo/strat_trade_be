from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from strat_trade.api.deps import (
    CandleFeedDep,
    LlmGatewayDep,
    SettingsDep,
    SignalRepositoryDep,
    TradingGatewayDep,
)
from strat_trade.api.schemas import CandleBarResponse, CandlesResponse, ErrorBody, ErrorEnvelope
from strat_trade.domain.entities import HistoryResponse
from strat_trade.domain.market_state import MarketStateVector
from strat_trade.domain.trade_record import TradeSignalRecord
from strat_trade.use_cases.evaluate_market import EvaluateMarketUseCase
from strat_trade.use_cases.fetch_candles import fetch_candles_in_range, fetch_recent_candles
from strat_trade.use_cases.generate_trading_signal import GenerateTradingSignalUseCase
from strat_trade.use_cases.delete_trade_signal import DeleteTradeSignalUseCase
from strat_trade.use_cases.get_recent_signals import GetRecentSignalsUseCase

router = APIRouter(prefix="/market")


def _bars_to_response(
    asset: str,
    timeframe_seconds: int,
    page,
) -> CandlesResponse:
    return CandlesResponse(
        asset=asset.strip(),
        timeframe_seconds=timeframe_seconds,
        candles=[
            CandleBarResponse(
                open_time=c.open_time,
                open=float(c.open),
                high=float(c.high),
                low=float(c.low),
                close=float(c.close),
                volume=None if c.volume is None else float(c.volume),
            )
            for c in page.candles
        ],
        has_more=page.has_more,
        next_cursor=page.next_cursor,
        total=page.total,
        broker_chunk_oldest=page.broker_chunk_oldest,
        broker_chunk_newest=page.broker_chunk_newest,
        broker_overlap=page.broker_overlap,
    )


@router.get(
    "/candles/range",
    response_model=CandlesResponse,
    summary="Candles inside a fixed time window",
    description=(
        "**What this endpoint is:** all candles from Pocket Option history for `[from, to]` "
        "in UTC in **one** response (ascending by open time), from a broker fetch anchored at "
        "`to`. "
        "Depth is capped by `STRAT_TRADE_MAX_CANDLES_PER_REQUEST`, "
        "`STRAT_TRADE_MAX_CANDLES_RANGE_TOTAL`, and native PO bar periods "
        "(1, 5, 15, 30, 60, 300 seconds). Very deep ranges may still need persisted candles "
        "(see `docs/PROJECT_CONTEXT.md`). "
        "\n\nBounds must not be in the future. "
        "`broker_chunk_*` shows the raw broker span—`[from, to]` should overlap it. "
        "**`YYYY-MM-DD`:** middle field is month (`02` February, `03` March)."
    ),
    operation_id="getMarketCandlesInRange",
)
async def read_candles_in_range(
    feed: CandleFeedDep,
    settings: SettingsDep,
    asset: str = Query(
        "EURUSD_otc",
        min_length=1,
        max_length=128,
        examples=["EURUSD_otc"],
        description="Pocket Option asset / pair identifier.",
    ),
    timeframe_seconds: int = Query(
        60,
        ge=1,
        le=2_592_000,
        examples=[60, 300],
        description=(
            "Candle period in seconds. Pocket Option native bars: 1, 5, 15, 30, 60, 300 "
            "(e.g. 1m=60, 5m=300). Other values return 400."
        ),
    ),
    range_start: datetime = Query(
        "2026-03-22T04:00:00Z",
        alias="from",
        description=(
            "Interval start (inclusive), ISO 8601 UTC (`YYYY-MM-DD`, MM=month). "
            "Must overlap `broker_chunk_oldest`…`broker_chunk_newest` (same calendar day/month)."
        ),
        examples=["2026-03-22T04:00:00Z"],
    ),
    range_end: datetime = Query(
        "2026-03-22T04:30:00Z",
        alias="to",
        description="Interval end (inclusive), not in the future (UTC).",
        examples=["2026-03-22T04:30:00Z"],
    ),
) -> CandlesResponse:
    page = await fetch_candles_in_range(
        feed,
        asset=asset,
        timeframe_seconds=timeframe_seconds,
        range_start=range_start,
        range_end=range_end,
        max_chunk=settings.max_candles_per_request,
        max_bars_in_range=settings.max_candles_range_total,
        max_fetch_rounds=settings.max_candles_range_fetch_rounds,
    )
    return _bars_to_response(asset, timeframe_seconds, page)


@router.get(
    "/candles",
    response_model=CandlesResponse,
    summary="Recent candles (tail history)",
    description=(
        "Latest `count` bars from Pocket Option, ascending by open time within the page. "
        "Optional `end_at` anchors the window end (omit for broker “now”). "
        "Older data: repeat with `cursor` = `next_cursor` (do not send `end_at` with `cursor`). "
        "`count` is capped by `STRAT_TRADE_MAX_CANDLES_PER_REQUEST`."
    ),
    operation_id="getMarketCandles",
)
async def read_recent_candles(
    feed: CandleFeedDep,
    settings: SettingsDep,
    asset: str = Query(
        "EURUSD_otc",
        min_length=1,
        max_length=128,
        examples=["EURUSD_otc"],
        description="Pocket Option asset / pair identifier.",
    ),
    timeframe_seconds: int = Query(
        60,
        ge=1,
        le=2_592_000,
        examples=[60, 300],
        description=(
            "Candle period in seconds. Pocket Option native bars: 1, 5, 15, 30, 60, 300 "
            "(e.g. 1m=60, 5m=300). Other values return 400."
        ),
    ),
    count: int = Query(
        100,
        ge=1,
        le=5000,
        description="Page size (max bars per request, capped by server settings).",
    ),
    end_at: datetime | None = Query(
        None,
        description="First page only: broker window end (ISO 8601). Omit for “now”.",
    ),
    cursor: datetime | None = Query(
        None,
        description=(
            "Older pages: `next_cursor` from the previous response (exclusive upper bound "
            "on bar open times for the next chunk)."
        ),
    ),
) -> CandlesResponse:
    page = await fetch_recent_candles(
        feed,
        asset=asset,
        timeframe_seconds=timeframe_seconds,
        count=count,
        max_count=settings.max_candles_per_request,
        end_at=end_at,
        cursor=cursor,
    )
    return _bars_to_response(asset, timeframe_seconds, page)


@router.get(
    "/evaluate",
    response_model=MarketStateVector,
    summary="Evaluate Market State (SMC + Math/Regime)",
    description=(
        "**Test via Swagger (Feature Engineering pipeline):**\n"
        "Execute this endpoint with the defaults to test the integration of the Math/SMC Core:\n\n"
        "`GET /api/v1/market/evaluate?asset=EURUSD_otc&timeframe_seconds=60&count=100`"
    ),
    operation_id="evaluateMarketState",
)
async def evaluate_market_state(
    feed: CandleFeedDep,
    settings: SettingsDep,
    asset: str = Query(
        "EURUSD_otc",
        min_length=1,
        max_length=128,
        description="Pocket Option asset / pair identifier.",
    ),
    timeframe_seconds: int = Query(
        60,
        ge=1,
        le=2_592_000,
        description="Candle period in seconds.",
    ),
    count: int = Query(
        100,
        ge=15,
        le=5000,
        description="Number of candles to fetch for the evaluation (minimum 15 for ADX).",
    ),
) -> MarketStateVector:
    use_case = EvaluateMarketUseCase(candle_feed=feed, max_count=settings.max_candles_per_request)
    return await use_case.execute(asset=asset, timeframe_seconds=timeframe_seconds, count=count)


@router.get(
    "/signal",
    response_model=dict[str, Any],
    summary="Generate LLM Trading Signal",
    description=(
        "**Test via Swagger (AI Feature pipeline):**\n"
        "Execute this endpoint with the defaults to test the integration of Gemini LLM:\n\n"
        "`GET /api/v1/market/signal?asset=EURUSD_otc&timeframe_seconds=60&count=100`"
    ),
    operation_id="generateTradingSignal",
)
async def generate_trading_signal(
    feed: CandleFeedDep,
    llm_gateway: LlmGatewayDep,
    signal_repository: SignalRepositoryDep,
    trading_gateway: TradingGatewayDep,
    settings: SettingsDep,
    asset: str = Query(
        "EURUSD_otc",
        min_length=1,
        max_length=128,
        description="Pocket Option asset / pair identifier.",
    ),
    timeframe_seconds: int = Query(
        60,
        ge=1,
        le=2_592_000,
        description="Candle period in seconds.",
    ),
    count: int = Query(
        100,
        ge=15,
        le=5000,
        description="Number of candles to fetch for the evaluation (minimum 15 for ADX).",
    ),
    auto_trade: bool = Query(
        False, description="Whether to automatically execute the generated signal."
    ),
    amount: float = Query(1.0, ge=1.0, description="Amount to trade if auto_trade is True."),
) -> dict[str, Any]:
    use_case = GenerateTradingSignalUseCase(
        candle_feed=feed,
        llm_gateway=llm_gateway,
        signal_repository=signal_repository,
        trading_gateway=trading_gateway,
        max_count=settings.max_candles_per_request,
    )
    return await use_case.execute(
        asset=asset,
        timeframe_seconds=timeframe_seconds,
        count=count,
        auto_trade=auto_trade,
        amount=amount,
    )


@router.get(
    "/signals/history",
    response_model=HistoryResponse,
    summary="Retrieve Recent Trade Signals",
    description="Retrieve the forward testing trade signals generated by the LLM along with aggregated statistics.",
    operation_id="getRecentSignals",
)
async def get_recent_signals(
    signal_repository: SignalRepositoryDep,
    limit: int = Query(50, ge=1, le=1000, description="Max number of signals to retrieve"),
) -> HistoryResponse:
    use_case = GetRecentSignalsUseCase(signal_repository=signal_repository)
    result = await use_case.execute(limit=limit)
    return HistoryResponse(**result)


@router.delete(
    "/signals/{signal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a forward-test trade signal",
    description=(
        "Deletes one row from the `trade_signals` table in the forward-test SQLite database "
        "(`forward_test.db`) by primary key."
    ),
    operation_id="deleteTradeSignal",
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "Row removed."},
        status.HTTP_404_NOT_FOUND: {
            "description": "No signal with the given id.",
            "model": ErrorEnvelope,
        },
    },
)
async def delete_trade_signal(
    signal_id: int,
    signal_repository: SignalRepositoryDep,
) -> None:
    use_case = DeleteTradeSignalUseCase(signal_repository=signal_repository)
    deleted = await use_case.execute(signal_id=signal_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorEnvelope(
                error=ErrorBody(
                    code="SIGNAL_NOT_FOUND",
                    message=f"No trade signal with id={signal_id}.",
                )
            ).model_dump(),
        )
