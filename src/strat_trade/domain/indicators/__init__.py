from __future__ import annotations

from strat_trade.domain.indicators.bollinger_bands import (
    BB_OUTPUT_LOWER,
    BB_OUTPUT_MIDDLE,
    BB_OUTPUT_UPPER,
    BOLLINGER_BANDS_ID,
    BollingerBandsCalculator,
    compute_bollinger_bands,
)
from strat_trade.domain.indicators.cci import CCI_ID, CCI_OUTPUT_CCI, CciCalculator, compute_cci
from strat_trade.domain.indicators.macd import (
    MACD_ID,
    MACD_OUTPUT_HISTOGRAM,
    MACD_OUTPUT_LINE,
    MACD_OUTPUT_SIGNAL,
    MacdCalculator,
    compute_macd,
    min_bars_macd,
)
from strat_trade.domain.indicators.parabolic_sar import (
    PARABOLIC_SAR_ID,
    PARABOLIC_SAR_OUTPUT_SAR,
    ParabolicSarCalculator,
    compute_parabolic_sar,
    min_bars_parabolic_sar,
)
from strat_trade.domain.indicators.protocol import IndicatorCalculator
from strat_trade.domain.indicators.registry import (
    REGISTERED_INDICATOR_IDS,
    build_calculator,
    build_rsi_wilder,
    min_bars_for_indicator,
)
from strat_trade.domain.indicators.rsi_wilder import (
    RSI_WILDER_ID,
    RSI_WILDER_OUTPUT_RSI,
    RsiWilderCalculator,
    compute_rsi_wilder,
)
from strat_trade.domain.indicators.stochastic import (
    STOCHASTIC_ID,
    STOCHASTIC_OUTPUT_D,
    STOCHASTIC_OUTPUT_K,
    StochasticCalculator,
    compute_stochastic,
    min_bars_stochastic,
)

__all__ = [
    "BB_OUTPUT_LOWER",
    "BB_OUTPUT_MIDDLE",
    "BB_OUTPUT_UPPER",
    "BOLLINGER_BANDS_ID",
    "BollingerBandsCalculator",
    "CCI_ID",
    "CCI_OUTPUT_CCI",
    "CciCalculator",
    "MACD_ID",
    "MACD_OUTPUT_HISTOGRAM",
    "MACD_OUTPUT_LINE",
    "MACD_OUTPUT_SIGNAL",
    "MacdCalculator",
    "IndicatorCalculator",
    "PARABOLIC_SAR_ID",
    "PARABOLIC_SAR_OUTPUT_SAR",
    "ParabolicSarCalculator",
    "REGISTERED_INDICATOR_IDS",
    "RSI_WILDER_ID",
    "RSI_WILDER_OUTPUT_RSI",
    "RsiWilderCalculator",
    "STOCHASTIC_ID",
    "STOCHASTIC_OUTPUT_D",
    "STOCHASTIC_OUTPUT_K",
    "StochasticCalculator",
    "build_calculator",
    "build_rsi_wilder",
    "compute_bollinger_bands",
    "compute_cci",
    "compute_macd",
    "compute_parabolic_sar",
    "compute_rsi_wilder",
    "compute_stochastic",
    "min_bars_for_indicator",
    "min_bars_macd",
    "min_bars_parabolic_sar",
    "min_bars_stochastic",
]
