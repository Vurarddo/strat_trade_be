from __future__ import annotations

from fastapi import APIRouter

from strat_trade.api.deps import CandleFeedDep, GeminiLlmDep, SettingsDep
from strat_trade.api.schemas import GeminiMarketIndicatorsRequest, GeminiMarketIndicatorsResponse
from strat_trade.use_cases.gemini_market_analysis import run_gemini_market_analysis

router = APIRouter(prefix="/market")


@router.post(
    "/indicators/gemini",
    response_model=GeminiMarketIndicatorsResponse,
    summary="Gemini analysis on candles + indicators (extends POST /market/indicators body)",
    description=(
        "Same fields as `POST /api/v1/market/indicators`, plus optional `expiration_time_seconds`: "
        "when set, the response uses that exact duration for `expiration` (canonical text) and "
        "`close_time` (entry + N seconds), regardless of the model wording. "
        "Sends combined JSON (candles, indicators, optional cap) to Gemini and returns "
        "`direction`, `expiration`, `win_probability`, `analysis`, `entry_time`, `close_time`, "
        "plus model and echo. "
        "Requires `STRAT_TRADE_GOOGLE_GEMINI_API_KEY` (or `GOOGLE_API_KEY` / `GEMINI_API_KEY`)."
    ),
    operation_id="postMarketIndicatorsGemini",
)
async def gemini_market_indicators(
    body: GeminiMarketIndicatorsRequest,
    feed: CandleFeedDep,
    settings: SettingsDep,
    llm: GeminiLlmDep,
) -> GeminiMarketIndicatorsResponse:
    out = await run_gemini_market_analysis(
        feed,
        body=body,
        max_candles_per_request=settings.max_candles_per_request,
        max_indicator_runs=settings.max_indicators_per_market_request,
        llm=llm,
        gemini_model=settings.google_gemini_model,
    )
    return GeminiMarketIndicatorsResponse(
        direction=out.direction,
        expiration=out.expiration,
        win_probability=out.win_probability,
        analysis=out.analysis,
        entry_time=out.entry_time,
        close_time=out.close_time,
        model=out.model,
        asset=out.asset,
        timeframe_seconds=out.timeframe_seconds,
    )
