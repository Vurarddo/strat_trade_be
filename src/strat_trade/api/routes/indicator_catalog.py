from __future__ import annotations

from fastapi import APIRouter

from strat_trade.api.schemas import IndicatorCatalogItemResponse
from strat_trade.domain.indicators import default_indicator_registry

router = APIRouter(prefix="/indicators")


@router.get(
    "",
    response_model=list[IndicatorCatalogItemResponse],
    summary="List registered technical indicators",
    description=(
        "Returns catalog metadata (id, name, category, default parameters) for all "
        "indicators registered in the domain `IndicatorRegistry` (pandas-ta backed)."
    ),
    operation_id="listIndicators",
)
def list_indicators() -> list[IndicatorCatalogItemResponse]:
    reg = default_indicator_registry()
    return [
        IndicatorCatalogItemResponse(
            id=m.id,
            name=m.name,
            category=str(m.category.value),
            default_params=dict(m.default_params),
            fill_sparse=m.fill_sparse,
        )
        for m in reg.get_all_metadata()
    ]
