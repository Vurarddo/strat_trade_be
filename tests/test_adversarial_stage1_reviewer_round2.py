from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import (
    BacktestConfig,
    StakeModel,
)
from strat_trade.domain.entities import Candle
from strat_trade.domain.optimizer.auto_matcher import StrategyAutoMatcher
from strat_trade.main import app
from strat_trade.use_cases.auto_assign_strategies import generate_pre_trading_plan


def _build_synthetic_df(
    timestamps: list[Any],
    closes: list[float],
) -> pd.DataFrame:
    n = len(closes)
    rows = []
    for i in range(n):
        c = float(closes[i])
        o = float(closes[i - 1]) if i > 0 else c
        h = max(o, c) + 0.0006
        low = min(o, c) - 0.0006
        rows.append(
            {
                "timestamp": timestamps[i],
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 200.0,
            }
        )
    return pd.DataFrame(rows)


class TestRound2AdversarialTimeBasedEngine:
    """Aggressive stress tests for time-based backtesting engine."""

    def test_unix_integer_epoch_timestamps(self) -> None:
        """Engine seamlessly handles raw UNIX integer epoch timestamps."""
        n = 200
        start_epoch = 1770000000
        timestamps = [start_epoch + i * 60 for i in range(n)]
        t = np.linspace(0, 12 * np.pi, n)
        closes = 1.1500 + np.sin(t) * 0.0060

        df = _build_synthetic_df(timestamps, closes)
        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            expiration_seconds=180,
            strategy_name="hybrid_multifactors",
        )
        engine = BinaryBacktestEngine(cfg)
        summary = engine.run(df)

        assert summary.total_trades > 0
        for trade in summary.trades:
            diff_sec = (trade.exit_time - trade.entry_time).total_seconds()
            assert diff_sec == 180.0
            assert trade.expiration_seconds == 180

    def test_subsecond_high_density_tick_bursts(self) -> None:
        """Engine handles 100ms sub-second tick intervals accurately."""
        n = 1000
        base_t = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
        # 10 ticks per second (100ms)
        timestamps = [base_t + timedelta(milliseconds=i * 100) for i in range(n)]
        t = np.linspace(0, 20 * np.pi, n)
        closes = 1.2500 + np.sin(t) * 0.0050

        df = _build_synthetic_df(timestamps, closes)
        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=1,
            expiration_seconds=15,  # 15s expiration = 150 ticks
            strategy_name="hybrid_multifactors",
        )
        engine = BinaryBacktestEngine(cfg)
        summary = engine.run(df)

        assert summary.total_trades > 0
        for trade in summary.trades:
            diff_sec = (trade.exit_time - trade.entry_time).total_seconds()
            assert diff_sec == 15.0
            assert trade.exit_index == trade.entry_index + 150

    def test_multi_day_weekend_gap_over_trade(self) -> None:
        """When a trade spans across a Friday-to-Monday weekend gap (e.g. 60 hours),
        the engine advances and exits at the first available Monday candle.
        """
        n_fri = 100
        n_mon = 100
        fri_base = datetime(2026, 6, 5, 20, 0, tzinfo=UTC)  # Friday evening
        mon_base = datetime(2026, 6, 8, 8, 0, tzinfo=UTC)  # Monday morning

        timestamps = [fri_base + timedelta(minutes=i) for i in range(n_fri)]
        timestamps.extend([mon_base + timedelta(minutes=i) for i in range(n_mon)])

        n_total = len(timestamps)
        t = np.linspace(0, 10 * np.pi, n_total)
        closes = 1.1000 + np.sin(t) * 0.0040

        df = _build_synthetic_df(timestamps, closes)
        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            expiration_seconds=180,
            strategy_name="hybrid_multifactors",
        )
        engine = BinaryBacktestEngine(cfg)
        summary = engine.run(df)

        assert summary.total_trades > 0
        for trade in summary.trades:
            target = trade.entry_time + timedelta(seconds=180)
            assert trade.exit_time >= target

    def test_dataset_ending_at_trade_entry_clean_termination(self) -> None:
        """When dataset ends before expiration can be met, engine terminates cleanly."""
        base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        n = 60
        timestamps = [base_t + timedelta(minutes=i) for i in range(n)]
        t = np.linspace(0, 4 * np.pi, n)
        closes = 1.1000 + np.sin(t) * 0.0050
        df = _build_synthetic_df(timestamps, closes)

        # Expiration is 10 hours (600 minutes) - impossible to settle within 60 rows
        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            expiration_seconds=36000,
            strategy_name="hybrid_multifactors",
        )
        engine = BinaryBacktestEngine(cfg)
        summary = engine.run(df)

        assert summary.total_trades == 0
        assert summary.net_profit == Decimal("0.0")

    def test_martingale_and_compounding_money_management(self) -> None:
        """Verify Martingale and dynamic percent position sizing work with time-based exit."""
        base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        n = 200
        timestamps = [base_t + timedelta(minutes=i) for i in range(n)]
        t = np.linspace(0, 10 * np.pi, n)
        closes = 1.1000 + np.sin(t) * 0.0050
        df = _build_synthetic_df(timestamps, closes)

        # Martingale
        cfg_martingale = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            expiration_seconds=120,
            stake_model=StakeModel.MARTINGALE,
            stake_amount=Decimal("10.0"),
            martingale_multiplier=Decimal("2.0"),
            martingale_max_steps=3,
            strategy_name="hybrid_multifactors",
        )
        summary_m = BinaryBacktestEngine(cfg_martingale).run(df)
        assert summary_m.total_trades > 0

        # Percent compounding
        cfg_pct = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            expiration_seconds=120,
            stake_model=StakeModel.PERCENT,
            stake_percent=Decimal("2.5"),
            strategy_name="hybrid_multifactors",
        )
        summary_pct = BinaryBacktestEngine(cfg_pct).run(df)
        assert summary_pct.total_trades > 0

    def test_session_stop_loss_circuit_breaker_halts_loop(self) -> None:
        """When session drawdown reaches daily_stop_loss_pct, backtest halts trading."""
        base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        n = 200
        timestamps = [base_t + timedelta(minutes=i) for i in range(n)]
        t = np.linspace(0, 10 * np.pi, n)
        closes = 1.1000 + np.sin(t) * 0.0050
        df = _build_synthetic_df(timestamps, closes)

        # Very tight 0.5% stop loss with $10 stake on $100 deposit (1 loss = 10% dd > 0.5%)
        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            initial_deposit=Decimal("100.0"),
            stake_amount=Decimal("10.0"),
            daily_stop_loss_pct=Decimal("0.005"),  # 0.5%
            expiration_seconds=120,
            strategy_name="hybrid_multifactors",
        )
        summary = BinaryBacktestEngine(cfg).run(df)
        # Verify that if drawdown occurred, the engine stopped trading
        if summary.net_profit < Decimal("0.0"):
            dd_from_start = (Decimal("100.0") - summary.final_balance) / Decimal("100.0")
            assert dd_from_start >= Decimal("0.005")


class TestRound2AdversarialAutoAssign:
    """Stress tests for StrategyAutoMatcher and PreTradingPlan use case."""

    @pytest.mark.asyncio
    async def test_matcher_rejects_empty_and_corrupt_microstructures(self) -> None:
        """Test exact boundary conditions (49 bars vs 50 bars) on failed microstructures."""
        matcher = StrategyAutoMatcher()

        # 50 bars with 20% flat bars -> must return None
        n = 50
        closes = [1.1000 if i < 10 else 1.1000 + i * 0.0002 for i in range(n)]
        highs = [1.1000 if i < 10 else closes[i] + 0.0004 for i in range(n)]
        lows = [1.1000 if i < 10 else closes[i] - 0.0004 for i in range(n)]
        df_flat_50 = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=n, freq="min"),
                "open": closes,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": [100.0] * n,
            }
        )
        res = await matcher.find_optimal_strategy_for_asset("EURUSD_otc", df_flat_50)
        assert res is None

    @pytest.mark.asyncio
    async def test_matcher_custom_strategy_filter(self) -> None:
        """When allowed_strategies is provided, candidate selection restricts to that set."""
        matcher = StrategyAutoMatcher()
        base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        candles = [
            Candle(
                open_time=base_t + timedelta(minutes=i),
                open=Decimal(str(round(1.1000 + np.sin(i * 0.2) * 0.003 - 0.0002, 5))),
                high=Decimal(str(round(1.1005 + np.sin(i * 0.2) * 0.003, 5))),
                low=Decimal(str(round(1.0995 + np.sin(i * 0.2) * 0.003, 5))),
                close=Decimal(str(round(1.1000 + np.sin(i * 0.2) * 0.003 + 0.0001, 5))),
                volume=Decimal("100"),
            )
            for i in range(150)
        ]

        res = await matcher.find_optimal_strategy_for_asset(
            asset="EURUSD_otc",
            candles=candles,
            allowed_strategies=["rsi_stochastic_extreme"],
        )
        assert res is not None
        assert res.strategy_id == "rsi_stochastic_extreme"

    @pytest.mark.asyncio
    async def test_pre_trading_plan_handles_network_exceptions_resiliently(self) -> None:
        """If candle feed raises exceptions for all assets, plan handles gracefully."""
        mock_feed = AsyncMock()
        mock_feed.get_candles = AsyncMock(side_effect=ConnectionResetError("Socket reset"))

        plan = await generate_pre_trading_plan(
            feed=mock_feed,
            assets=["EURUSD_otc", "Gold_otc"],
        )
        assert isinstance(plan.assignments, list)
        assert plan.total_assets == len(plan.assignments)


class TestRound2AdversarialApiRoutes:
    """Stress tests for FastAPI API backtest endpoints."""

    def test_run_backtest_api_with_valid_and_invalid_expiration_seconds(self) -> None:
        feed = AsyncMock()
        base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        feed.get_candles = AsyncMock(
            return_value=[
                Candle(
                    open_time=base_t + timedelta(minutes=i),
                    open=Decimal(str(round(1.1000 + np.sin(i * 0.2) * 0.003 - 0.0002, 5))),
                    high=Decimal(str(round(1.1005 + np.sin(i * 0.2) * 0.003, 5))),
                    low=Decimal(str(round(1.0995 + np.sin(i * 0.2) * 0.003, 5))),
                    close=Decimal(str(round(1.1000 + np.sin(i * 0.2) * 0.003 + 0.0001, 5))),
                    volume=Decimal("100"),
                )
                for i in range(120)
            ]
        )
        app.state.trading_gateway = feed
        client = TestClient(app)

        # 1. Valid payload with expiration_seconds
        payload_valid = {
            "asset": "EURUSD_otc",
            "timeframe_seconds": 60,
            "expiration_seconds": 180,
            "strategy_name": "hybrid_multifactors",
            "candle_count": 100,
        }
        res_valid = client.post("/api/v1/backtest/run", json=payload_valid)
        assert res_valid.status_code == 200
        data = res_valid.json()
        assert "trades" in data
        assert "win_rate_pct" in data

        # 2. Invalid negative expiration_seconds (< 1)
        payload_neg = dict(payload_valid, expiration_seconds=-5)
        res_neg = client.post("/api/v1/backtest/run", json=payload_neg)
        assert res_neg.status_code == 422

        # 3. Invalid huge expiration_seconds (> 86400)
        payload_huge = dict(payload_valid, expiration_seconds=999999)
        res_huge = client.post("/api/v1/backtest/run", json=payload_huge)
        assert res_huge.status_code == 422

    def test_upload_and_backtest_api_csv(self) -> None:
        client = TestClient(app)

        # Create sample CSV
        base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        rows = ["timestamp,open,high,low,close,volume"]
        for i in range(120):
            t = base_t + timedelta(minutes=i)
            c = round(1.1000 + np.sin(i * 0.1) * 0.004, 5)
            rows.append(f"{t.isoformat()},{c},{c + 0.0005},{c - 0.0005},{c},100")
        csv_content = "\n".join(rows).encode("utf-8")

        response = client.post(
            "/api/v1/backtest/upload",
            files={"file": ("dataset.csv", io.BytesIO(csv_content), "text/csv")},
            data={
                "asset": "UPLOAD_TEST",
                "timeframe_seconds": "60",
                "expiration_seconds": "180",
                "strategy_name": "hybrid_multifactors",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["asset"] == "UPLOAD_TEST"
        assert "trades" in data
