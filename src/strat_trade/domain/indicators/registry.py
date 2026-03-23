from __future__ import annotations

from collections.abc import Callable, Mapping

from strat_trade.domain.errors import UnknownIndicatorError
from strat_trade.domain.indicators.cci import CciCalculator
from strat_trade.domain.indicators.macd import MacdCalculator
from strat_trade.domain.indicators.protocol import IndicatorCalculator
from strat_trade.domain.indicators.psar import PsarCalculator
from strat_trade.domain.indicators.rsi import RsiCalculator
from strat_trade.domain.indicators.stochastic import StochasticCalculator

IndicatorFactory = Callable[[Mapping[str, object]], IndicatorCalculator]

_DEFAULT_FACTORIES: dict[str, IndicatorFactory] = {
    "cci": CciCalculator.from_params,
    "macd": MacdCalculator.from_params,
    "psar": PsarCalculator.from_params,
    "rsi": RsiCalculator.from_params,
    "stochastic": StochasticCalculator.from_params,
}


class IndicatorRegistry:
    """Maps stable indicator ids to factories; extend by passing a copy of factories dict."""

    __slots__ = ("_factories",)

    def __init__(self, factories: dict[str, IndicatorFactory] | None = None) -> None:
        self._factories = dict(factories if factories is not None else _DEFAULT_FACTORIES)

    def build(self, indicator_id: str, params: Mapping[str, object]) -> IndicatorCalculator:
        key = indicator_id.strip().lower()
        factory = self._factories.get(key)
        if factory is None:
            raise UnknownIndicatorError(
                f"Unknown indicator id {indicator_id!r}. "
                f"Supported: {', '.join(sorted(self._factories))}."
            )
        return factory(params)


def default_indicator_registry() -> IndicatorRegistry:
    return IndicatorRegistry()
