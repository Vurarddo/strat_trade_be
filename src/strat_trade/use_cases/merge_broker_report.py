from __future__ import annotations

import logging
from typing import Any

from strat_trade.domain.analytics.xls_merger import BrokerReportMerger
from strat_trade.use_cases.manage_live_bot import get_trade_store

logger = logging.getLogger(__name__)


def process_broker_report(file_bytes: bytes, filename: str) -> dict[str, Any]:
    """Processes uploaded broker report and merges with bot telemetry."""
    store = get_trade_store()
    merger = BrokerReportMerger(trade_store=store)
    rows = merger.parse_broker_file(file_bytes, filename)
    if not rows:
        return {
            "total_broker_trades": 0,
            "matched_trades_count": 0,
            "match_rate_pct": 0.0,
            "total_broker_profit": 0.0,
            "average_slippage": 0.0,
            "strategy_breakdown": [],
            "asset_breakdown": [],
            "merged_records": [],
        }
    return merger.merge_and_analyze(rows)


def get_internal_audit_report() -> dict[str, Any]:
    """Builds audit analytics and list of records from internal database."""
    store = get_trade_store()
    merger = BrokerReportMerger(trade_store=store)
    return merger.get_internal_trades_audit()


def export_broker_report(merged_records: list[dict[str, Any]], format_type: str = "xlsx") -> bytes:
    store = get_trade_store()
    merger = BrokerReportMerger(trade_store=store)
    return merger.export_to_excel_or_csv(merged_records, format_type=format_type)


def clear_audit_trades() -> int:
    """Clears all stored trades from the database."""
    from strat_trade.use_cases.manage_live_bot import clear_live_bot_trades

    return clear_live_bot_trades()
