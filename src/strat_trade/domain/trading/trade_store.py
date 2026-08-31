from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from strat_trade.domain.trading.entities import (
    IndicatorSnapshot,
    LiveTradeRecord,
    TradeOutcome,
)


class TradeStore:
    """Persistent SQLite store for live and demo trades with full indicator telemetry."""

    def __init__(self, db_path: str | Path = "data/trades.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    broker_order_id TEXT,
                    asset TEXT NOT NULL,
                    action TEXT NOT NULL,
                    stake TEXT NOT NULL,
                    open_time TEXT NOT NULL,
                    expiration_seconds INTEGER NOT NULL,
                    open_price TEXT NOT NULL,
                    close_time TEXT,
                    close_price TEXT,
                    strategy_id TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    strategy_params TEXT NOT NULL,
                    indicator_snapshot TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reason TEXT NOT NULL,
                    payout_rate TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    pnl TEXT NOT NULL,
                    balance_after TEXT,
                    is_merged_with_broker INTEGER DEFAULT 0,
                    broker_profit TEXT,
                    slippage TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trades_broker_order ON trades(broker_order_id)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_asset ON trades(asset)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_open_time ON trades(open_time)")
            self._migrate_execution_forensics(conn)
            conn.commit()

    @staticmethod
    def _migrate_execution_forensics(conn: sqlite3.Connection) -> None:
        """Adds execution-forensics columns to stores created before they existed."""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(trades)")}
        additions = {
            "executed_params": "TEXT NOT NULL DEFAULT '{}'",
            "asset_tier": "TEXT NOT NULL DEFAULT 'NORMAL'",
            "stake_multiplier": "REAL NOT NULL DEFAULT 1.0",
            "entry_second": "INTEGER NOT NULL DEFAULT 0",
            "is_otc": "INTEGER NOT NULL DEFAULT 0",
            "open_price_source": "TEXT NOT NULL DEFAULT 'candle'",
            "settlement_source": "TEXT NOT NULL DEFAULT 'candle'",
        }
        for column, ddl in additions.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE trades ADD COLUMN {column} {ddl}")

    def save_trade(self, trade: LiveTradeRecord) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trades (
                    trade_id, broker_order_id, asset, action, stake,
                    open_time, expiration_seconds, open_price, close_time, close_price,
                    strategy_id, strategy_name, strategy_params, indicator_snapshot,
                    confidence, reason, payout_rate, outcome, pnl, balance_after,
                    is_merged_with_broker, broker_profit, slippage, created_at,
                    executed_params, asset_tier, stake_multiplier, entry_second, is_otc,
                    open_price_source, settlement_source
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?
                )
                """,
                (
                    trade.trade_id,
                    trade.broker_order_id,
                    trade.asset,
                    trade.action,
                    str(trade.stake),
                    trade.open_time.isoformat(),
                    trade.expiration_seconds,
                    str(trade.open_price),
                    trade.close_time.isoformat() if trade.close_time else None,
                    str(trade.close_price) if trade.close_price is not None else None,
                    trade.strategy_id,
                    trade.strategy_name,
                    json.dumps(trade.strategy_params),
                    json.dumps(trade.indicator_snapshot.to_dict()),
                    trade.confidence,
                    trade.reason,
                    str(trade.payout_rate),
                    trade.outcome.value,
                    str(trade.pnl),
                    str(trade.balance_after) if trade.balance_after is not None else None,
                    1 if trade.is_merged_with_broker else 0,
                    str(trade.broker_profit) if trade.broker_profit is not None else None,
                    str(trade.slippage) if trade.slippage is not None else None,
                    datetime.now(UTC).isoformat(),
                    json.dumps(trade.executed_params),
                    trade.asset_tier,
                    float(trade.stake_multiplier),
                    int(trade.entry_second),
                    1 if trade.is_otc else 0,
                    trade.open_price_source,
                    trade.settlement_source,
                ),
            )
            conn.commit()

    def update_trade_outcome(
        self,
        trade_id: str,
        close_time: datetime,
        close_price: Decimal,
        outcome: TradeOutcome,
        pnl: Decimal,
        balance_after: Decimal | None = None,
        settlement_source: str = "candle",
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE trades
                SET close_time = ?, close_price = ?, outcome = ?, pnl = ?, balance_after = ?,
                    settlement_source = ?
                WHERE trade_id = ?
                """,
                (
                    close_time.isoformat(),
                    str(close_price),
                    outcome.value,
                    str(pnl),
                    str(balance_after) if balance_after is not None else None,
                    settlement_source,
                    trade_id,
                ),
            )
            conn.commit()

    def update_broker_order_id(self, trade_id: str, broker_order_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE trades SET broker_order_id = ? WHERE trade_id = ?",
                (broker_order_id, trade_id),
            )
            conn.commit()

    def get_trade_by_id(self, trade_id: str) -> LiveTradeRecord | None:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
            row = cursor.fetchone()
            return self._row_to_entity(row) if row else None

    def get_trade_by_broker_order_id(self, broker_order_id: str) -> LiveTradeRecord | None:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM trades WHERE broker_order_id = ?", (broker_order_id,)
            )
            row = cursor.fetchone()
            return self._row_to_entity(row) if row else None

    def list_trades(self, limit: int = 100, offset: int = 0) -> list[LiveTradeRecord]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM trades ORDER BY open_time DESC LIMIT ? OFFSET ?", (limit, offset)
            )
            return [self._row_to_entity(row) for row in cursor.fetchall()]

    def list_trades_for_audit(self) -> list[LiveTradeRecord]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM trades ORDER BY open_time ASC")
            return [self._row_to_entity(row) for row in cursor.fetchall()]

    def clear_trades(self) -> int:
        """Deletes all trade records from the store and returns count of deleted items."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM trades")
            count = cursor.rowcount
            conn.commit()
            return count

    def mark_merged(
        self,
        trade_id: str,
        broker_profit: Decimal,
        slippage: Decimal,
        close_price: Decimal | None = None,
        close_time: datetime | None = None,
        outcome: TradeOutcome | None = None,
    ) -> None:
        """Updates trade record with verified broker ground truth metrics."""
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE trades
                SET is_merged_with_broker = 1,
                    broker_profit = ?,
                    pnl = ?,
                    slippage = ?,
                    close_price = COALESCE(?, close_price),
                    close_time = COALESCE(?, close_time),
                    outcome = COALESCE(?, outcome)
                WHERE trade_id = ?
                """,
                (
                    str(broker_profit),
                    str(broker_profit),
                    str(slippage),
                    str(close_price) if close_price is not None else None,
                    close_time.isoformat() if close_time is not None else None,
                    outcome.value if outcome is not None else None,
                    trade_id,
                ),
            )
            conn.commit()

    @staticmethod
    def _optional(row: sqlite3.Row, column: str, default: Any) -> Any:
        """Reads a column that may be absent in stores written before a migration."""
        try:
            value = row[column]
        except (IndexError, KeyError):
            return default
        return default if value is None else value

    def _row_to_entity(self, row: sqlite3.Row) -> LiveTradeRecord:
        snap_dict: dict[str, Any] = json.loads(row["indicator_snapshot"])
        snap = IndicatorSnapshot(
            rsi=snap_dict.get("rsi"),
            adx=snap_dict.get("adx"),
            atr=snap_dict.get("atr"),
            stoch_k=snap_dict.get("stoch_k"),
            stoch_d=snap_dict.get("stoch_d"),
            bb_upper=snap_dict.get("bb_upper"),
            bb_lower=snap_dict.get("bb_lower"),
            bb_middle=snap_dict.get("bb_middle"),
            ema_fast=snap_dict.get("ema_fast"),
            ema_slow=snap_dict.get("ema_slow"),
            raw_indicators=snap_dict.get("raw_indicators", {}),
        )

        return LiveTradeRecord(
            trade_id=row["trade_id"],
            broker_order_id=row["broker_order_id"],
            asset=row["asset"],
            action=row["action"],
            stake=Decimal(row["stake"]),
            open_time=datetime.fromisoformat(row["open_time"]),
            expiration_seconds=row["expiration_seconds"],
            open_price=Decimal(row["open_price"]),
            close_time=datetime.fromisoformat(row["close_time"]) if row["close_time"] else None,
            close_price=Decimal(row["close_price"]) if row["close_price"] is not None else None,
            strategy_id=row["strategy_id"],
            strategy_name=row["strategy_name"],
            strategy_params=json.loads(row["strategy_params"]),
            indicator_snapshot=snap,
            confidence=row["confidence"],
            reason=row["reason"],
            payout_rate=Decimal(row["payout_rate"]),
            outcome=TradeOutcome(row["outcome"]),
            pnl=Decimal(row["pnl"]),
            balance_after=Decimal(row["balance_after"]) if row["balance_after"] else None,
            is_merged_with_broker=bool(row["is_merged_with_broker"]),
            broker_profit=Decimal(row["broker_profit"]) if row["broker_profit"] else None,
            slippage=Decimal(row["slippage"]) if row["slippage"] else None,
            executed_params=json.loads(self._optional(row, "executed_params", "{}")),
            asset_tier=self._optional(row, "asset_tier", "NORMAL"),
            stake_multiplier=float(self._optional(row, "stake_multiplier", 1.0)),
            entry_second=int(self._optional(row, "entry_second", 0)),
            is_otc=bool(self._optional(row, "is_otc", 0)),
            open_price_source=str(self._optional(row, "open_price_source", "candle")),
            settlement_source=str(self._optional(row, "settlement_source", "candle")),
        )
