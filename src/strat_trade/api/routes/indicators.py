from __future__ import annotations

from fastapi import APIRouter

from strat_trade.api.schemas import (
    BollingerBandsIndicatorInfoResponse,
    CciIndicatorInfoResponse,
    IndicatorParameterField,
    MacdIndicatorInfoResponse,
    ParabolicSarIndicatorInfoResponse,
    RsiWilderIndicatorInfoResponse,
    StochasticIndicatorInfoResponse,
)
from strat_trade.domain.indicators.bollinger_bands import (
    BB_OUTPUT_LOWER,
    BB_OUTPUT_MIDDLE,
    BB_OUTPUT_UPPER,
    BOLLINGER_BANDS_ID,
    BOLLINGER_FORMULA,
    BOLLINGER_SUMMARY,
    BOLLINGER_TITLE,
)
from strat_trade.domain.indicators.cci import (
    CCI_FORMULA,
    CCI_ID,
    CCI_OUTPUT_CCI,
    CCI_SUMMARY,
    CCI_TITLE,
)
from strat_trade.domain.indicators.macd import (
    MACD_FORMULA,
    MACD_ID,
    MACD_OUTPUT_HISTOGRAM,
    MACD_OUTPUT_LINE,
    MACD_OUTPUT_SIGNAL,
    MACD_SUMMARY,
    MACD_TITLE,
)
from strat_trade.domain.indicators.parabolic_sar import (
    PARABOLIC_SAR_FORMULA,
    PARABOLIC_SAR_ID,
    PARABOLIC_SAR_OUTPUT_SAR,
    PARABOLIC_SAR_SUMMARY,
    PARABOLIC_SAR_TITLE,
)
from strat_trade.domain.indicators.rsi_wilder import (
    RSI_WILDER_FORMULA,
    RSI_WILDER_ID,
    RSI_WILDER_SUMMARY,
    RSI_WILDER_TITLE,
)
from strat_trade.domain.indicators.stochastic import (
    STOCHASTIC_FORMULA,
    STOCHASTIC_ID,
    STOCHASTIC_OUTPUT_D,
    STOCHASTIC_OUTPUT_K,
    STOCHASTIC_SUMMARY,
    STOCHASTIC_TITLE,
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


@router.get(
    "/macd",
    response_model=MacdIndicatorInfoResponse,
    summary="MACD — definition and parameters",
    description=(
        "Read-only metadata for **MACD**: EMA(fast) − EMA(slow), signal = EMA(MACD), "
        "histogram = MACD − signal. "
        "Computed values: `POST /api/v1/market/indicators` with `indicator_id`: `macd`."
    ),
    operation_id="getMacdIndicatorInfo",
)
async def read_macd_info() -> MacdIndicatorInfoResponse:
    return MacdIndicatorInfoResponse(
        indicator_id=MACD_ID,
        title=MACD_TITLE,
        summary=MACD_SUMMARY,
        formula=MACD_FORMULA,
        parameters=[
            IndicatorParameterField(
                name="fast_length",
                type="integer",
                default=12,
                min_value=1,
                description="Fast EMA period (classic 12).",
            ),
            IndicatorParameterField(
                name="slow_length",
                type="integer",
                default=26,
                min_value=1,
                description="Slow EMA period (classic 26).",
            ),
            IndicatorParameterField(
                name="signal_length",
                type="integer",
                default=9,
                min_value=1,
                description="Signal EMA period applied to MACD line (classic 9).",
            ),
        ],
        outputs=[MACD_OUTPUT_LINE, MACD_OUTPUT_SIGNAL, MACD_OUTPUT_HISTOGRAM],
    )


@router.get(
    "/stochastic",
    response_model=StochasticIndicatorInfoResponse,
    summary="Stochastic Oscillator — definition and parameters",
    description=(
        "Read-only metadata for the **Stochastic Oscillator**: %K from close vs high–low range, "
        "optional `%K` smoothing (`smooth_k`), %D = SMA of that series. "
        "Computed values: `POST /api/v1/market/indicators` with `indicator_id`: `stochastic`."
    ),
    operation_id="getStochasticIndicatorInfo",
)
async def read_stochastic_info() -> StochasticIndicatorInfoResponse:
    return StochasticIndicatorInfoResponse(
        indicator_id=STOCHASTIC_ID,
        title=STOCHASTIC_TITLE,
        summary=STOCHASTIC_SUMMARY,
        formula=STOCHASTIC_FORMULA,
        parameters=[
            IndicatorParameterField(
                name="k_length",
                type="integer",
                default=14,
                min_value=1,
                description="Lookback for highest high and lowest low (classic 14).",
            ),
            IndicatorParameterField(
                name="d_length",
                type="integer",
                default=3,
                min_value=1,
                description="SMA length for %D (classic 3).",
            ),
            IndicatorParameterField(
                name="smooth_k",
                type="integer",
                default=1,
                min_value=1,
                description="SMA length applied to raw %K before %D (1 = fast; 3 = slow stoch).",
            ),
        ],
        outputs=[STOCHASTIC_OUTPUT_K, STOCHASTIC_OUTPUT_D],
    )


@router.get(
    "/cci",
    response_model=CciIndicatorInfoResponse,
    summary="CCI — definition and parameters",
    description=(
        "Read-only metadata for the **Commodity Channel Index** on typical price. "
        "Computed values: `POST /api/v1/market/indicators` with `indicator_id`: `cci`."
    ),
    operation_id="getCciIndicatorInfo",
)
async def read_cci_info() -> CciIndicatorInfoResponse:
    return CciIndicatorInfoResponse(
        indicator_id=CCI_ID,
        title=CCI_TITLE,
        summary=CCI_SUMMARY,
        formula=CCI_FORMULA,
        parameters=[
            IndicatorParameterField(
                name="length",
                type="integer",
                default=20,
                min_value=1,
                description="SMA and mean deviation window (common 20).",
            ),
        ],
        outputs=[CCI_OUTPUT_CCI],
    )


@router.get(
    "/parabolic-sar",
    response_model=ParabolicSarIndicatorInfoResponse,
    summary="Parabolic SAR — definition and parameters",
    description=(
        "Read-only metadata for **Parabolic SAR** (Wilder). "
        "Computed values: `POST /api/v1/market/indicators` with `indicator_id`: `parabolic_sar`."
    ),
    operation_id="getParabolicSarIndicatorInfo",
)
async def read_parabolic_sar_info() -> ParabolicSarIndicatorInfoResponse:
    return ParabolicSarIndicatorInfoResponse(
        indicator_id=PARABOLIC_SAR_ID,
        title=PARABOLIC_SAR_TITLE,
        summary=PARABOLIC_SAR_SUMMARY,
        formula=PARABOLIC_SAR_FORMULA,
        parameters=[
            IndicatorParameterField(
                name="af_start",
                type="number",
                default=0.02,
                min_value=0.001,
                description="Initial acceleration factor (classic 0.02).",
            ),
            IndicatorParameterField(
                name="af_increment",
                type="number",
                default=0.02,
                min_value=0.001,
                description="AF step on new extremes (classic 0.02).",
            ),
            IndicatorParameterField(
                name="af_max",
                type="number",
                default=0.2,
                min_value=0.001,
                description="Maximum AF (classic 0.2).",
            ),
        ],
        outputs=[PARABOLIC_SAR_OUTPUT_SAR],
    )
