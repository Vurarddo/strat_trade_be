from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from strat_trade.api.schemas import (
    AssetAuditItem,
    BrokerReportAuditResponse,
    MergedRecordItem,
    StrategyAuditItem,
)
from strat_trade.use_cases.merge_broker_report import (
    clear_audit_trades,
    export_broker_report,
    get_internal_audit_report,
    process_broker_report,
)

router = APIRouter(prefix="/audit", tags=["Trade Audit & XLS Merger"])

# In-memory cache for latest merged report to allow instant export
_latest_merged_cache: list[dict] = []


@router.get("/records", response_model=BrokerReportAuditResponse)
def get_audit_records_endpoint() -> BrokerReportAuditResponse:
    """Returns audit analytics and breakdown for all internal bot trades stored in the database."""
    global _latest_merged_cache
    result = get_internal_audit_report()
    _latest_merged_cache = result["merged_records"]

    return BrokerReportAuditResponse(
        total_broker_trades=result["total_broker_trades"],
        matched_trades_count=result["matched_trades_count"],
        match_rate_pct=result["match_rate_pct"],
        total_broker_profit=result["total_broker_profit"],
        average_slippage=result["average_slippage"],
        strategy_breakdown=[StrategyAuditItem(**s) for s in result["strategy_breakdown"]],
        asset_breakdown=[AssetAuditItem(**a) for a in result["asset_breakdown"]],
        merged_records=[MergedRecordItem(**r) for r in result["merged_records"]],
    )


@router.post("/clear")
def clear_trades_endpoint() -> dict[str, Any]:
    """Deletes all trade history from the internal store and memory."""
    global _latest_merged_cache
    deleted_count = clear_audit_trades()
    _latest_merged_cache = []
    return {"status": "ok", "cleared_trades": deleted_count}


@router.post("/upload-xls", response_model=BrokerReportAuditResponse)
async def upload_broker_report_endpoint(
    file: UploadFile = File(...),
) -> BrokerReportAuditResponse:
    """Uploads a Pocket Option exported report and reconciles with bot telemetry."""
    global _latest_merged_cache
    try:
        content = await file.read()
        filename = file.filename or "broker_report.xlsx"
        result = process_broker_report(file_bytes=content, filename=filename)

        _latest_merged_cache = result["merged_records"]

        return BrokerReportAuditResponse(
            total_broker_trades=result["total_broker_trades"],
            matched_trades_count=result["matched_trades_count"],
            match_rate_pct=result["match_rate_pct"],
            total_broker_profit=result["total_broker_profit"],
            average_slippage=result["average_slippage"],
            strategy_breakdown=[StrategyAuditItem(**s) for s in result["strategy_breakdown"]],
            asset_breakdown=[AssetAuditItem(**a) for a in result["asset_breakdown"]],
            merged_records=[MergedRecordItem(**r) for r in result["merged_records"]],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Помилка обробки файлу брокера: {exc}",
        ) from exc


@router.get("/export")
def export_merged_report_endpoint(
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
) -> Response:
    """Exports the latest reconciled audit report into Excel (.xlsx) or CSV format."""
    global _latest_merged_cache
    if not _latest_merged_cache:
        # Fallback to internal trades if no broker report was uploaded
        res = get_internal_audit_report()
        _latest_merged_cache = res.get("merged_records", [])

    if not _latest_merged_cache:
        raise HTTPException(
            status_code=400,
            detail="Немає активних даних для експорту. Виконайте угоди або завантажте звіт.",
        )

    file_bytes = export_broker_report(_latest_merged_cache, format_type=format)
    media_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if format == "xlsx"
        else "text/csv"
    )
    filename = f"pocket_option_audit_merged.{format}"

    return Response(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
