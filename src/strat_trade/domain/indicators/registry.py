from __future__ import annotations

from collections.abc import Callable, Mapping

from strat_trade.domain.errors import UnknownIndicatorError
from strat_trade.domain.indicators.protocol import IndicatorCalculator
from strat_trade.domain.indicators.types import IndicatorMetadata

IndicatorFactory = Callable[[Mapping[str, object]], IndicatorCalculator]

_REGISTRY_SINGLETON: IndicatorRegistry | None = None


class IndicatorRegistry:
    """Maps indicator ids to factories and exposes catalog metadata."""

    __slots__ = ("_factories", "_metadata")

    def __init__(self) -> None:
        self._factories: dict[str, IndicatorFactory] = {}
        self._metadata: dict[str, IndicatorMetadata] = {}

    def register(self, metadata: IndicatorMetadata, factory: IndicatorFactory) -> IndicatorFactory:
        key = metadata.id.strip().lower()
        if key in self._factories:
            msg = f"Duplicate indicator registration for id {metadata.id!r}."
            raise ValueError(msg)
        self._metadata[key] = IndicatorMetadata(
            id=key,
            name=metadata.name,
            category=metadata.category,
            default_params=dict(metadata.default_params),
            fill_sparse=metadata.fill_sparse,
        )
        self._factories[key] = factory
        return factory

    def build(self, indicator_id: str, params: Mapping[str, object]) -> IndicatorCalculator:
        key = indicator_id.strip().lower()
        factory = self._factories.get(key)
        if factory is None:
            known = ", ".join(sorted(self._factories)[:24])
            suffix = "" if len(self._factories) <= 24 else ", …"
            raise UnknownIndicatorError(
                f"Unknown indicator id {indicator_id!r}. Supported (sample): {known}{suffix}."
            )
        return factory(params)

    def get_all_metadata(self) -> list[IndicatorMetadata]:
        return [self._metadata[k] for k in sorted(self._metadata)]


def default_indicator_registry() -> IndicatorRegistry:
    global _REGISTRY_SINGLETON
    if _REGISTRY_SINGLETON is None:
        reg = IndicatorRegistry()
        # Populate on first access (import side effects stay inside domain.indicators).
        from strat_trade.domain.indicators import catalog  # noqa: PLC0415

        catalog.register_all(reg)
        _REGISTRY_SINGLETON = reg
    return _REGISTRY_SINGLETON
