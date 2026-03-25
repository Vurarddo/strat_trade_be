from __future__ import annotations

from fastapi import APIRouter

from strat_trade.api.schemas import IndicatorParameterField, RsiWilderIndicatorInfoResponse
from strat_trade.domain.indicators.rsi_wilder import (
    RSI_WILDER_FORMULA,
    RSI_WILDER_ID,
    RSI_WILDER_SUMMARY,
    RSI_WILDER_TITLE,
)

router = APIRouter(prefix="/indicators")


@router.get(
    "/rsi",
    response_model=RsiWilderIndicatorInfoResponse,
    summary="RSI (Wilder) — definition and parameters",
    description=(
        "Read-only metadata for the **Relative Strength Index** as defined by J. Welles Wilder: "
        "Wilder smoothing of average gain and average loss, not an SMA of RS. "
        "Computed values: `POST /api/v1/market/indicators` (several indicators, per-bar `key`)."
    ),
    operation_id="getRsiWilderIndicatorInfo",
)
async def read_rsi_wilder_info() -> RsiWilderIndicatorInfoResponse:
    return RsiWilderIndicatorInfoResponse(
        indicator_id=RSI_WILDER_ID,
        title=RSI_WILDER_TITLE,
        summary=RSI_WILDER_SUMMARY,
        formula=RSI_WILDER_FORMULA,
        parameters=[
            IndicatorParameterField(
                name="length",
                type="integer",
                default=14,
                min_value=1,
                description="Number of periods for average gain/loss (Wilder default 14).",
            ),
        ],
    )
