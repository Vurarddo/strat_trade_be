from __future__ import annotations

import io
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from strat_trade.domain.trading.entities import (
    BrokerTradeRow,
    MergedAuditRecord,
    TradeOutcome,
)
from strat_trade.domain.trading.trade_store import TradeStore

logger = logging.getLogger(__name__)


class BrokerReportMerger:
    """Parses Pocket Option XLS/CSV export and merges with local telemetry for trade auditing."""

    def __init__(self, trade_store: TradeStore | None = None) -> None:
        self.trade_store = trade_store or TradeStore()

    def parse_broker_file(self, file_bytes: bytes, filename: str) -> list[BrokerTradeRow]:
        """Parses XLS, XLSX, or CSV exported from Pocket Option."""
        fn = filename.lower()
        df: pd.DataFrame | None = None

        if fn.endswith((".xlsx", ".xlsm")):
            df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
        elif fn.endswith(".xls"):
            try:
                df = pd.read_excel(io.BytesIO(file_bytes), engine="xlrd")
            except Exception:
                try:
                    df = pd.read_html(io.BytesIO(file_bytes))[0]
                except Exception:
                    df = pd.read_csv(io.BytesIO(file_bytes))
        elif fn.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_bytes))
        else:
            # Try excel then csv
            try:
                df = pd.read_excel(io.BytesIO(file_bytes))
            except Exception:
                df = pd.read_csv(io.BytesIO(file_bytes))

        if df is None or df.empty:
            return []

        # Standardize column headers (case-insensitive & stripped)
        col_map = {}
        for col in df.columns:
            clean = str(col).strip().lower()
            if "direction" in clean:
                col_map[col] = "direction"
            elif "order" in clean:
                col_map[col] = "order_id"
            elif "expiration" in clean:
                col_map[col] = "expiration"
            elif "asset" in clean:
                col_map[col] = "asset"
            elif "open time" in clean or "open_time" in clean or "open date" in clean:
                col_map[col] = "open_time"
            elif "close time" in clean or "close_time" in clean or "close date" in clean:
                col_map[col] = "close_time"
            elif "open price" in clean or "open_price" in clean:
                col_map[col] = "open_price"
            elif "close price" in clean or "close_price" in clean:
                col_map[col] = "close_price"
            elif "amount" in clean or "stake" in clean:
                col_map[col] = "trade_amount"
            elif "profit" in clean or "payout" in clean:
                col_map[col] = "profit"
            elif "currency" in clean:
                col_map[col] = "currency"

        df = df.rename(columns=col_map)

        rows: list[BrokerTradeRow] = []
        for _, r in df.iterrows():
            try:
                order_id = str(r.get("order_id", "")).strip()
                if not order_id or order_id == "nan":
                    continue

                direction = str(r.get("direction", "call")).strip().lower()
                expiration = str(r.get("expiration", "S60")).strip()
                asset = str(r.get("asset", "")).strip()

                open_t_raw = r.get("open_time")
                close_t_raw = r.get("close_time")
                open_time = self._parse_time(open_t_raw)
                close_time = self._parse_time(close_t_raw)

                open_price = Decimal(str(r.get("open_price", 0)))
                close_price = Decimal(str(r.get("close_price", 0)))
                trade_amount = Decimal(str(r.get("trade_amount", 0)))
                profit = Decimal(str(r.get("profit", 0)))
                currency = str(r.get("currency", "USD")).strip()

                rows.append(
                    BrokerTradeRow(
                        direction=direction,
                        order_id=order_id,
                        expiration=expiration,
                        asset=asset,
                        open_time=open_time,
                        close_time=close_time,
                        open_price=open_price,
                        close_price=close_price,
                        trade_amount=trade_amount,
                        profit=profit,
                        currency=currency,
                    )
                )
            except Exception as e:
                logger.debug("Skipping invalid row in broker report: %s (%s)", r, e)
                continue

        return rows

    def merge_and_analyze(self, broker_rows: list[BrokerTradeRow]) -> dict[str, Any]:
        """Merges broker rows with local SQLite telemetry and computes quantitative analytics."""
        all_bot_trades = self.trade_store.list_trades_for_audit()
        bot_trades_by_order = {t.broker_order_id: t for t in all_bot_trades if t.broker_order_id}

        merged_records: list[MergedAuditRecord] = []
        matched_count = 0

        strategy_stats: dict[str, dict[str, Any]] = {}
        asset_stats: dict[str, dict[str, Any]] = {}

        total_broker_profit = Decimal("0.00")
        total_slippage = Decimal("0.00")

        for b in broker_rows:
            # 1. Ground truth determination strictly from uploaded broker record
            if b.profit > 0:
                outcome_str = "WIN"
                profit = b.profit
            elif b.profit < 0:
                outcome_str = "LOSS"
                profit = b.profit
            else:
                # If broker profit field was 0, deduce from broker close vs open prices
                if b.open_price > 0 and b.close_price > 0:
                    if b.direction.upper() == "CALL":
                        if b.close_price > b.open_price:
                            outcome_str = "WIN"
                            profit = (b.trade_amount * Decimal("0.92")).quantize(Decimal("0.01"))
                        elif b.close_price < b.open_price:
                            outcome_str = "LOSS"
                            profit = -b.trade_amount
                        else:
                            outcome_str = "DRAW"
                            profit = Decimal("0.00")
                    elif b.direction.upper() == "PUT":
                        if b.close_price < b.open_price:
                            outcome_str = "WIN"
                            profit = (b.trade_amount * Decimal("0.92")).quantize(Decimal("0.01"))
                        elif b.close_price > b.open_price:
                            outcome_str = "LOSS"
                            profit = -b.trade_amount
                        else:
                            outcome_str = "DRAW"
                            profit = Decimal("0.00")
                    else:
                        outcome_str = "DRAW"
                        profit = Decimal("0.00")
                else:
                    outcome_str = "DRAW"
                    profit = Decimal("0.00")

            total_broker_profit += profit
            outcome_enum = (
                TradeOutcome.WIN
                if outcome_str == "WIN"
                else (TradeOutcome.LOSS if outcome_str == "LOSS" else TradeOutcome.DRAW)
            )

            bot_trade = bot_trades_by_order.get(b.order_id)
            if not bot_trade:
                # Fuzzy fallback by asset and timestamp (within 10s)
                for candidate in all_bot_trades:
                    if (
                        candidate.asset.replace("_", "/").upper()
                        in b.asset.replace("_", "/").upper()
                        or b.asset.replace(" ", "").upper()
                        in candidate.asset.replace(" ", "").upper()
                    ):
                        if abs((candidate.open_time - b.open_time).total_seconds()) <= 10:
                            bot_trade = candidate
                            break

            if bot_trade:
                matched_count += 1
                strat_name = bot_trade.strategy_name
                strat_id = bot_trade.strategy_id
                params = bot_trade.strategy_params
                indicators = bot_trade.indicator_snapshot.to_dict()
                conf = bot_trade.confidence
                reason = bot_trade.reason
                internal_open = bot_trade.open_price

                slippage = abs(b.open_price - internal_open)
                total_slippage += slippage

                # Update database record with verified broker ground truth
                self.trade_store.mark_merged(
                    bot_trade.trade_id,
                    broker_profit=profit,
                    slippage=slippage,
                    close_price=b.close_price,
                    close_time=b.close_time,
                    outcome=outcome_enum,
                )
            else:
                strat_name = "Manual / Unlinked"
                strat_id = "manual"
                params = {}
                indicators = {}
                conf = None
                reason = "Not matched with bot database"
                internal_open = None
                slippage = None

            # Accumulate strategy stats
            if strat_name not in strategy_stats:
                strategy_stats[strat_name] = {
                    "strategy_name": strat_name,
                    "strategy_id": strat_id,
                    "total_trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                    "net_profit": Decimal("0.00"),
                    "gross_profit": Decimal("0.00"),
                    "gross_loss": Decimal("0.00"),
                }
            s = strategy_stats[strat_name]
            s["total_trades"] += 1
            s["net_profit"] += profit
            if profit > 0:
                s["wins"] += 1
                s["gross_profit"] += profit
            elif profit < 0:
                s["losses"] += 1
                s["gross_loss"] += abs(profit)
            else:
                s["draws"] += 1

            # Accumulate asset stats
            asset_key = b.asset
            if asset_key not in asset_stats:
                asset_stats[asset_key] = {
                    "asset": asset_key,
                    "total_trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "net_profit": Decimal("0.00"),
                }
            a = asset_stats[asset_key]
            a["total_trades"] += 1
            a["net_profit"] += profit
            if profit > 0:
                a["wins"] += 1
            elif profit < 0:
                a["losses"] += 1

            merged_records.append(
                MergedAuditRecord(
                    order_id=b.order_id,
                    asset=b.asset,
                    direction=b.direction.upper(),
                    open_time=b.open_time,
                    close_time=b.close_time,
                    broker_open_price=b.open_price,
                    broker_close_price=b.close_price,
                    trade_amount=b.trade_amount,
                    broker_profit=profit,
                    outcome=outcome_str,
                    is_bot_trade=bot_trade is not None,
                    strategy_id=strat_id,
                    strategy_name=strat_name,
                    strategy_params=params,
                    indicator_snapshot=indicators,
                    confidence=conf,
                    reason=reason,
                    internal_open_price=internal_open,
                    slippage=slippage,
                    entry_second=bot_trade.entry_second if bot_trade else None,
                    open_price_source=bot_trade.open_price_source if bot_trade else None,
                    settlement_source=bot_trade.settlement_source if bot_trade else None,
                )
            )

        # Finalize strategy analytics
        strategy_summary = []
        for s in strategy_stats.values():
            decided = s["wins"] + s["losses"] + s["draws"]
            wr = (s["wins"] / decided * 100.0) if decided > 0 else 0.0
            pf = (
                (float(s["gross_profit"]) / float(s["gross_loss"]))
                if s["gross_loss"] > 0
                else (99.0 if s["gross_profit"] > 0 else 0.0)
            )
            strategy_summary.append(
                {
                    "strategy_name": s["strategy_name"],
                    "strategy_id": s["strategy_id"],
                    "total_trades": s["total_trades"],
                    "wins": s["wins"],
                    "losses": s["losses"],
                    "draws": s["draws"],
                    "win_rate_pct": round(wr, 2),
                    "profit_factor": round(pf, 2),
                    "net_profit": float(s["net_profit"]),
                }
            )
        strategy_summary.sort(key=lambda x: x["net_profit"], reverse=True)

        asset_summary = []
        for a in asset_stats.values():
            total = a["total_trades"]
            wr = (a["wins"] / total * 100.0) if total > 0 else 0.0
            asset_summary.append(
                {
                    "asset": a["asset"],
                    "total_trades": total,
                    "wins": a["wins"],
                    "losses": a["losses"],
                    "win_rate_pct": round(wr, 2),
                    "net_profit": float(a["net_profit"]),
                }
            )
        asset_summary.sort(key=lambda x: x["net_profit"], reverse=True)

        avg_slip = (float(total_slippage) / matched_count) if matched_count > 0 else 0.0

        return {
            "total_broker_trades": len(broker_rows),
            "matched_trades_count": matched_count,
            "match_rate_pct": round((matched_count / len(broker_rows) * 100.0), 2)
            if broker_rows
            else 0.0,
            "total_broker_profit": float(total_broker_profit),
            "average_slippage": avg_slip,
            "strategy_breakdown": strategy_summary,
            "asset_breakdown": asset_summary,
            "merged_records": [self._record_to_dict(r) for r in merged_records],
        }

    def get_internal_trades_audit(self) -> dict[str, Any]:
        """Builds audit report directly from internal TradeStore records without broker XLS."""
        records = self.trade_store.list_trades_for_audit()
        if not records:
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

        strategy_stats: dict[str, dict[str, Any]] = {}
        asset_stats: dict[str, dict[str, Any]] = {}
        total_pnl = Decimal("0.00")
        total_slippage = Decimal("0.00")
        slippage_count = 0
        merged_records: list[MergedAuditRecord] = []

        for t in records:
            profit = t.pnl
            total_pnl += profit
            strat_name = t.strategy_name or "Unknown"
            strat_id = t.strategy_id or "unknown"

            # Strategy breakdown
            if strat_id not in strategy_stats:
                strategy_stats[strat_id] = {
                    "strategy_name": strat_name,
                    "strategy_id": strat_id,
                    "total_trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                    "gross_profit": Decimal("0.00"),
                    "gross_loss": Decimal("0.00"),
                    "net_profit": Decimal("0.00"),
                }
            s = strategy_stats[strat_id]
            s["total_trades"] += 1
            s["net_profit"] += profit
            if profit > 0:
                s["wins"] += 1
                s["gross_profit"] += profit
            elif profit < 0:
                s["losses"] += 1
                s["gross_loss"] += abs(profit)
            else:
                s["draws"] += 1

            # Asset breakdown
            asset_key = t.asset
            if asset_key not in asset_stats:
                asset_stats[asset_key] = {
                    "asset": asset_key,
                    "total_trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "net_profit": Decimal("0.00"),
                }
            a = asset_stats[asset_key]
            a["total_trades"] += 1
            a["net_profit"] += profit
            if profit > 0:
                a["wins"] += 1
            elif profit < 0:
                a["losses"] += 1

            # Slippage
            if t.slippage is not None:
                total_slippage += t.slippage
                slippage_count += 1

            snap_dict = (
                t.indicator_snapshot.to_dict()
                if hasattr(t.indicator_snapshot, "to_dict")
                else t.indicator_snapshot
            )

            merged_records.append(
                MergedAuditRecord(
                    order_id=t.broker_order_id or t.trade_id,
                    asset=t.asset,
                    direction=t.action.upper(),
                    open_time=t.open_time,
                    close_time=t.close_time or t.open_time,
                    broker_open_price=t.open_price,
                    broker_close_price=t.close_price or t.open_price,
                    trade_amount=t.stake,
                    broker_profit=t.broker_profit if t.broker_profit is not None else profit,
                    outcome=t.outcome.value if hasattr(t.outcome, "value") else str(t.outcome),
                    is_bot_trade=True,
                    strategy_id=strat_id,
                    strategy_name=strat_name,
                    strategy_params=t.strategy_params,
                    indicator_snapshot=snap_dict,
                    confidence=t.confidence,
                    reason=t.reason,
                    internal_open_price=t.open_price,
                    slippage=t.slippage,
                    entry_second=t.entry_second,
                    open_price_source=t.open_price_source,
                    settlement_source=t.settlement_source,
                )
            )

        strategy_summary = []
        for s in strategy_stats.values():
            decided = s["wins"] + s["losses"] + s["draws"]
            wr = (s["wins"] / decided * 100.0) if decided > 0 else 0.0
            pf = (
                (float(s["gross_profit"]) / float(s["gross_loss"]))
                if s["gross_loss"] > 0
                else (99.0 if s["gross_profit"] > 0 else 0.0)
            )
            strategy_summary.append(
                {
                    "strategy_name": s["strategy_name"],
                    "strategy_id": s["strategy_id"],
                    "total_trades": s["total_trades"],
                    "wins": s["wins"],
                    "losses": s["losses"],
                    "draws": s["draws"],
                    "win_rate_pct": round(wr, 2),
                    "profit_factor": round(pf, 2),
                    "net_profit": float(s["net_profit"]),
                }
            )
        strategy_summary.sort(key=lambda x: x["net_profit"], reverse=True)

        asset_summary = []
        for a in asset_stats.values():
            total = a["total_trades"]
            wr = (a["wins"] / total * 100.0) if total > 0 else 0.0
            asset_summary.append(
                {
                    "asset": a["asset"],
                    "total_trades": total,
                    "wins": a["wins"],
                    "losses": a["losses"],
                    "win_rate_pct": round(wr, 2),
                    "net_profit": float(a["net_profit"]),
                }
            )
        asset_summary.sort(key=lambda x: x["net_profit"], reverse=True)

        avg_slip = (float(total_slippage) / slippage_count) if slippage_count > 0 else 0.0

        return {
            "total_broker_trades": len(records),
            "matched_trades_count": len(records),
            "match_rate_pct": 100.0,
            "total_broker_profit": float(total_pnl),
            "average_slippage": avg_slip,
            "strategy_breakdown": strategy_summary,
            "asset_breakdown": asset_summary,
            "merged_records": [self._record_to_dict(r) for r in merged_records],
        }

    def export_to_excel_or_csv(
        self, merged_records_data: list[dict[str, Any]], format_type: str = "xlsx"
    ) -> bytes:
        """Exports merged dataset with full indicator telemetry into XLSX or CSV bytes."""
        flat_rows = []
        for r in merged_records_data:
            snap = r.get("indicator_snapshot", {})
            params = r.get("strategy_params", {})
            flat_rows.append(
                {
                    "Broker Order UUID": r.get("order_id"),
                    "Asset": r.get("asset"),
                    "Direction": r.get("direction"),
                    "Open Time": r.get("open_time"),
                    "Close Time": r.get("close_time"),
                    "Broker Open Price": r.get("broker_open_price"),
                    "Broker Close Price": r.get("broker_close_price"),
                    "Trade Amount ($)": r.get("trade_amount"),
                    "Broker Profit ($)": r.get("broker_profit"),
                    "Outcome": r.get("outcome"),
                    "Is Bot Trade": "YES" if r.get("is_bot_trade") else "NO",
                    "Strategy Name": r.get("strategy_name"),
                    "Confidence %": f"{r.get('confidence', 0) * 100:.0f}%"
                    if r.get("confidence")
                    else "",
                    "Slippage": r.get("slippage"),
                    "Internal Open Price": r.get("internal_open_price"),
                    "Open Price Source": r.get("open_price_source"),
                    "Settlement Source": r.get("settlement_source"),
                    "Entry Second": r.get("entry_second"),
                    "RSI": snap.get("rsi"),
                    "ADX": snap.get("adx"),
                    "ATR": snap.get("atr"),
                    "Stoch %K": snap.get("stoch_k"),
                    "Strategy Parameters": str(params),
                    "Signal Reason": r.get("reason"),
                }
            )

        df = pd.DataFrame(flat_rows)
        out = io.BytesIO()
        if format_type.lower() == "csv":
            df.to_csv(out, index=False)
        else:
            with pd.ExcelWriter(out, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Audit & Telemetry")
        out.seek(0)
        return out.getvalue()

    def _parse_time(self, raw_val: Any) -> datetime:
        if isinstance(raw_val, datetime):
            return raw_val if raw_val.tzinfo else raw_val.replace(tzinfo=UTC)
        if isinstance(raw_val, str):
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%d.%m.%Y %H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
            ):
                try:
                    dt = datetime.strptime(raw_val.strip(), fmt)
                    return dt.replace(tzinfo=UTC)
                except ValueError:
                    pass
            try:
                return datetime.fromisoformat(raw_val.strip()).replace(tzinfo=UTC)
            except Exception:
                pass
        return datetime.now(UTC)

    def _record_to_dict(self, r: MergedAuditRecord) -> dict[str, Any]:
        return {
            "order_id": r.order_id,
            "asset": r.asset,
            "direction": r.direction,
            "open_time": r.open_time.isoformat()
            if isinstance(r.open_time, datetime)
            else str(r.open_time),
            "close_time": r.close_time.isoformat()
            if isinstance(r.close_time, datetime)
            else str(r.close_time),
            "broker_open_price": float(r.broker_open_price),
            "broker_close_price": float(r.broker_close_price),
            "trade_amount": float(r.trade_amount),
            "broker_profit": float(r.broker_profit),
            "outcome": r.outcome,
            "is_bot_trade": r.is_bot_trade,
            "strategy_id": r.strategy_id,
            "strategy_name": r.strategy_name,
            "strategy_params": r.strategy_params,
            "indicator_snapshot": r.indicator_snapshot,
            "confidence": r.confidence,
            "reason": r.reason,
            "internal_open_price": float(r.internal_open_price) if r.internal_open_price else None,
            "slippage": float(r.slippage) if r.slippage is not None else None,
            "entry_second": r.entry_second,
            "open_price_source": r.open_price_source,
            "settlement_source": r.settlement_source,
        }
