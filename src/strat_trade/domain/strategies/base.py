from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from strat_trade.domain.backtest.models import TradeAction


@dataclass
class SignalResult:
    action: TradeAction | None
    confidence: float
    expiration_bars: int
    regime: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParameterDef:
    name: str
    display_name: str
    param_type: str  # "int", "float", "bool"
    default_value: Any
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    options: list[Any] | None = None
    description: str = ""


class BaseStrategy(ABC):
    """Abstract base class for all quantitative binary options trading strategies."""

    def __init__(self, **kwargs: Any) -> None:
        pass

    @abstractmethod
    def prepare_dataframe(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        """Computes indicators on the OHLCV DataFrame."""
        pass

    @abstractmethod
    def evaluate_bar(self, df: pd.DataFrame, idx: int) -> SignalResult:
        """Evaluates signal conditions at bar `idx`."""
        pass

    @classmethod
    @abstractmethod
    def get_parameter_definitions(cls) -> list[ParameterDef]:
        """Returns metadata for configurable/optimizable parameters."""
        pass
