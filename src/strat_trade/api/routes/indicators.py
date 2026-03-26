from __future__ import annotations

from fastapi import APIRouter

from strat_trade.api.schemas import (
    BollingerBandsIndicatorInfoResponse,
    IndicatorParameterField,
    RsiWilderIndicatorInfoResponse,
)
from strat_trade.domain.indicators.bollinger_bands import (
    BB_OUTPUT_LOWER,
    BB_OUTPUT_MIDDLE,
    BB_OUTPUT_UPPER,
    BOLLINGER_FORMULA,
    BOLLINGER_BANDS_ID,
    BOLLINGER_SUMMARY,
    BOLLINGER_TITLE,
)
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


@router.get(
    "/bollinger-bands",
    response_model=BollingerBandsIndicatorInfoResponse,
    summary="Bollinger Bands — definition and parameters",
    description=(
        "Read-only metadata for **Bollinger Bands** (John Bollinger): SMA middle, population "
        "standard deviation (÷ length), upper/lower = middle ± mult × σ. "
        "Computed values: `POST /api/v1/market/indicators` with `indicator_id`: `bollinger_bands`."
    ),
    operation_id="getBollingerBandsIndicatorInfo",
)
async def read_bollinger_bands_info() -> BollingerBandsIndicatorInfoResponse:
    return BollingerBandsIndicatorInfoResponse(
        indicator_id=BOLLINGER_BANDS_ID,
        title=BOLLINGER_TITLE,
        summary=BOLLINGER_SUMMARY,
        formula=BOLLINGER_FORMULA,
        parameters=[
            IndicatorParameterField(
                name="length",
                type="integer",
                default=20,
                min_value=1,
                description="SMA and stdev window (classic 20).",
            ),
            IndicatorParameterField(
                name="mult",
                type="number",
                default=2.0,
                min_value=0.001,
                description="Standard deviation multiplier for upper/lower bands (classic 2.0).",
            ),
        ],
        outputs=[BB_OUTPUT_MIDDLE, BB_OUTPUT_UPPER, BB_OUTPUT_LOWER],
    )
