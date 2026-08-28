from __future__ import annotations

import io
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from strat_trade.domain.analytics.xls_merger import BrokerReportMerger
from strat_trade.domain.trading.entities import IndicatorSnapshot, LiveTradeRecord, TradeOutcome
from strat_trade.domain.trading.trade_store import TradeStore


def test_broker_report_parser_and_merger():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_trades.db"
        store = TradeStore(db_path=db_path)

        # Seed local trade in database
        trade = LiveTradeRecord(
            trade_id="bot-t1",
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
            reason="RSI oversold",
            payout_rate=Decimal("0.92"),
            outcome=TradeOutcome.WIN,
            pnl=Decimal("9.20"),
        )
        store.save_trade(trade)

        merger = BrokerReportMerger(trade_store=store)

        # Create mock DataFrame exactly matching the user's screenshot
        raw_data = {
            "Direction": ["call", "put"],
            "Order": [
                "e384a8f6-c371-4b8f-916a-112ae0a60456",
                "f99999f6-c371-4b8f-916a-112ae0a60999",
            ],
            "Expiration": ["S3", "M1"],
            "Asset": ["USD/CHF OTC", "EUR/USD OTC"],
            "Open time": ["2026-08-19 22:23:28", "2026-08-19 22:25:00"],
            "Close time": ["2026-08-19 22:23:31", "2026-08-19 22:26:00"],
            "Open price": [0.82359, 1.08550],
            "Close price": [0.82377, 1.08520],
            "Trade amount": [10.0, 10.0],
            "Profit": [9.2, -10.0],
            "Currency": ["USD", "USD"],
        }
        df = pd.DataFrame(raw_data)
        out_excel = io.BytesIO()
        df.to_excel(out_excel, index=False)
        excel_bytes = out_excel.getvalue()

        # Test Parse
        parsed_rows = merger.parse_broker_file(excel_bytes, "pocket_option_history.xlsx")
        assert len(parsed_rows) == 2
        assert parsed_rows[0].order_id == "e384a8f6-c371-4b8f-916a-112ae0a60456"
        assert parsed_rows[0].profit == Decimal("9.2")

        # Test Merge & Analytics
        analysis = merger.merge_and_analyze(parsed_rows)
        assert analysis["total_broker_trades"] == 2
        assert analysis["matched_trades_count"] == 1
        assert analysis["match_rate_pct"] == 50.0
        assert analysis["total_broker_profit"] == -0.8

        # Strategy breakdown
        strat_breakdown = analysis["strategy_breakdown"]
        assert len(strat_breakdown) >= 1
        boll_stat = next(
            s for s in strat_breakdown if s["strategy_name"] == "Bollinger ATR Reversion"
        )
        assert boll_stat["wins"] == 1
        assert boll_stat["net_profit"] == 9.2

        # Test Export
        export_bytes = merger.export_to_excel_or_csv(analysis["merged_records"], format_type="xlsx")
        assert len(export_bytes) > 100
