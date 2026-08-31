from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from scripts.collect_s1_data import run_collector_loop
from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import BacktestConfig, StakeModel
from strat_trade.domain.entities import Candle
from strat_trade.domain.trading.market_data_store import MarketDataStore


def _generate_synthetic_s1_candles(
    count: int,
    start_ts: float = 1700000000.0,
    base_price: float = 1.0850,
) -> list[Candle]:
    """Generates continuous 1-second candles with realistic oscillation."""
    candles: list[Candle] = []
    current_price = base_price
    for i in range(count):
        ts = start_ts + i
        # Sinusoidal oscillation + gentle trend
        wave = math.sin(i / 15.0) * 0.0008
        current_price = base_price + wave
        open_p = current_price - 0.0001 * math.cos(i / 10.0)
        close_p = current_price + 0.0001 * math.cos(i / 10.0)
        high_p = max(open_p, close_p) + 0.0002
        low_p = min(open_p, close_p) - 0.0002
        candles.append(
            Candle(
                open_time=datetime.fromtimestamp(ts, tz=UTC),
                open=Decimal(str(round(open_p, 5))),
                high=Decimal(str(round(high_p, 5))),
                low=Decimal(str(round(low_p, 5))),
                close=Decimal(str(round(close_p, 5))),
                volume=Decimal("100.0"),
            )
        )
    return candles


class TestS1DataCollectionIntegration:
    @pytest.mark.asyncio
    async def test_e2e_multi_cycle_collection_and_overlapping_deduplication(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "e2e_market_data.db"
        store = MarketDataStore(db_path=db_path)

        # Total 420 seconds of continuous simulated market
        base_ts = 1700000000.0
        all_eur_candles = _generate_synthetic_s1_candles(420, start_ts=base_ts, base_price=1.0850)
        all_gold_candles = _generate_synthetic_s1_candles(420, start_ts=base_ts, base_price=2050.0)

        # Polling cycles (300 candles each, sliding by 60s):
        # Cycle 1: 0..299
        # Cycle 2: 60..359 (240 overlap)
        # Cycle 3: 120..419 (240 overlap)
        eur_batches = [
            all_eur_candles[0:300],
            all_eur_candles[60:360],
            all_eur_candles[120:420],
        ]
        gold_batches = [
            all_gold_candles[0:300],
            all_gold_candles[60:360],
            all_gold_candles[120:420],
        ]

        eur_call_idx = 0
        gold_call_idx = 0

        async def _mock_get_candles(
            asset: str,
            timeframe: int = 1,
            count: int = 300,
            **kwargs,
        ) -> list[Candle]:
            nonlocal eur_call_idx, gold_call_idx
            if asset == "EURUSD_otc":
                batch = eur_batches[min(eur_call_idx, len(eur_batches) - 1)]
                eur_call_idx += 1
                return batch
            if asset == "GOLD_otc":
                batch = gold_batches[min(gold_call_idx, len(gold_batches) - 1)]
                gold_call_idx += 1
                return batch
            return []

        mock_gateway = AsyncMock()
        mock_gateway.get_candles.side_effect = _mock_get_candles

        await run_collector_loop(
            gateway=mock_gateway,
            store=store,
            assets=["EURUSD_otc", "GOLD_otc"],
            timeframe=1,
            count=300,
            interval=0.001,
            max_cycles=3,
            throttle_delay=0.0,
        )

        # Verify exact uniqueness and row counts
        assert store.count_candles("EURUSD_otc") == 420
        assert store.count_candles("GOLD_otc") == 420
        assert store.get_total_candle_count() == 840
        assert store.get_stored_assets() == ["EURUSD_otc", "GOLD_otc"]

        # Verify chronological continuity
        eur_candles = store.get_candles("EURUSD_otc")
        for i in range(len(eur_candles) - 1):
            t_curr = eur_candles[i].open_time.timestamp()
            t_next = eur_candles[i + 1].open_time.timestamp()
            assert t_next - t_curr == 1.0, f"Gap detected at index {i}: {t_curr} -> {t_next}"

    def test_e2e_collected_s1_data_with_binary_backtest_engine(self, tmp_path: Path) -> None:
        db_path = tmp_path / "backtest_market_data.db"
        store = MarketDataStore(db_path=db_path)

        # Populate 600 S1 candles with oscillating trend
        base_ts = 1700000000.0
        candles = _generate_synthetic_s1_candles(600, start_ts=base_ts, base_price=1.0850)
        store.insert_candles("EURUSD_otc", candles)

        # Retrieve DataFrame ready for BinaryBacktestEngine
        df = store.get_candles_df("EURUSD_otc")
        assert len(df) == 600
        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
        assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])

        # Configure time-based backtester on S1 data with 60s expiration
        config = BacktestConfig(
            asset="EURUSD_otc",
            strategy_name="support_resistance_bounce",
            strategy_params={"pivot_period": 10, "touch_tolerance": 0.0003},
            timeframe_seconds=1,
            expiration_seconds=60,
            payout_rate=Decimal("0.85"),
            initial_deposit=Decimal("1000.0"),
            stake_model=StakeModel.FLAT,
            stake_amount=Decimal("10.0"),
        )

        engine = BinaryBacktestEngine(config=config)
        summary = engine.run(df)

        assert summary is not None
        assert summary.asset == "EURUSD_otc"
        assert summary.timeframe_seconds == 1
        assert summary.total_trades >= 0
        assert summary.final_balance > 0
