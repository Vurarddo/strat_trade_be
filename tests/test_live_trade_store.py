from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from strat_trade.domain.trading.entities import (
    IndicatorSnapshot,
    LiveTradeRecord,
    TradeOutcome,
)
from strat_trade.domain.trading.trade_store import TradeStore


def test_trade_store_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_trades.db"
        store = TradeStore(db_path=db_path)

        trade = LiveTradeRecord(
            trade_id="t-101",
            broker_order_id="e384a8f6-c371-4b8f-916a-112ae0a60456",
            asset="USD/CHF OTC",
            action="CALL",
            stake=Decimal("10.00"),
            open_time=datetime(2026, 8, 19, 22, 23, 28, tzinfo=UTC),
            expiration_seconds=3,
            open_price=Decimal("0.82359"),
            strategy_id="bollinger_atr_reversion",
            strategy_name="Bollinger ATR Reversion",
            strategy_params={"bb_period": 20, "bb_std": 2.0},
            indicator_snapshot=IndicatorSnapshot(rsi=28.5, adx=26.4, atr=0.00045),
            confidence=0.85,
            reason="RSI oversold + BB lower touch",
            payout_rate=Decimal("0.92"),
            outcome=TradeOutcome.PENDING,
            pnl=Decimal("0.00"),
        )

        store.save_trade(trade)

        # Retrieve by trade_id
        fetched = store.get_trade_by_id("t-101")
        assert fetched is not None
        assert fetched.asset == "USD/CHF OTC"
        assert fetched.broker_order_id == "e384a8f6-c371-4b8f-916a-112ae0a60456"
        assert fetched.indicator_snapshot.rsi == 28.5

        # Retrieve by broker_order_id
        fetched_by_order = store.get_trade_by_broker_order_id(
            "e384a8f6-c371-4b8f-916a-112ae0a60456"
        )
        assert fetched_by_order is not None
        assert fetched_by_order.trade_id == "t-101"

        # Update outcome
        store.update_trade_outcome(
            trade_id="t-101",
            close_time=datetime(2026, 8, 19, 22, 23, 31, tzinfo=UTC),
            close_price=Decimal("0.82377"),
            outcome=TradeOutcome.WIN,
            pnl=Decimal("9.20"),
            balance_after=Decimal("1009.20"),
        )

        updated = store.get_trade_by_id("t-101")
        assert updated is not None
        assert updated.outcome == TradeOutcome.WIN
        assert updated.pnl == Decimal("9.20")
        assert updated.close_price == Decimal("0.82377")
