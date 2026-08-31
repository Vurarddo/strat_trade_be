from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import BacktestConfig, StakeModel
from strat_trade.domain.entities import Candle
from strat_trade.domain.optimizer.auto_matcher import StrategyAutoMatcher
from strat_trade.use_cases.auto_assign_strategies import generate_pre_trading_plan


def _generate_synthetic_candles(n: int = 250, interval_seconds: int = 60) -> pd.DataFrame:
    base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    timestamps = [base_t + timedelta(seconds=i * interval_seconds) for i in range(n)]

    np.random.seed(42)
    t = np.linspace(0, 16 * np.pi, n)
    sine = np.sin(t) * 0.0080
    noise = np.random.normal(0, 0.0003, n)
    closes = 1.1000 + sine + noise

    rows = []
    for i in range(n):
        c = float(closes[i])
        o = float(closes[i - 1]) if i > 0 else c
        h = max(o, c) + 0.0004
        low = min(o, c) - 0.0004
        rows.append(
            {
                "timestamp": timestamps[i],
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 100.0,
            }
        )
    return pd.DataFrame(rows)


class TestTimeBasedBacktestEngine:
    """Test suite for time-based backtester execution and BacktestConfig."""

    def test_backtest_config_explicit_expiration_seconds(self) -> None:
        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            expiration_seconds=180,
            expiration_bars=3,
        )
        assert cfg.expiration_seconds == 180
        assert cfg.expiration_bars == 3

    def test_time_based_exit_standard_m1(self) -> None:
        df = _generate_synthetic_candles(250, interval_seconds=60)
        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            expiration_seconds=180,
            stake_model=StakeModel.FLAT,
            stake_amount=Decimal("10.0"),
            strategy_name="hybrid_multifactors",
        )
        engine = BinaryBacktestEngine(cfg)
        summary = engine.run(df)

        assert summary.total_trades > 0
        for trade in summary.trades:
            # Trade duration should match expiration_seconds
            diff_sec = (trade.exit_time - trade.entry_time).total_seconds()
            assert diff_sec >= 180
            assert trade.expiration_seconds == 180
            assert trade.exit_index > trade.entry_index

    def test_time_based_exit_subminute_s5(self) -> None:
        """Verify backtester works on sub-minute 5s data with expiration_seconds = 60s."""
        df = _generate_synthetic_candles(n=600, interval_seconds=5)
        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=5,
            expiration_seconds=60,
            stake_model=StakeModel.FLAT,
            stake_amount=Decimal("10.0"),
            strategy_name="hybrid_multifactors",
        )
        engine = BinaryBacktestEngine(cfg)
        summary = engine.run(df)

        assert summary.total_trades > 0
        for trade in summary.trades:
            diff_sec = (trade.exit_time - trade.entry_time).total_seconds()
            assert diff_sec >= 60
            assert trade.expiration_seconds == 60
            # On 5s data with 60s expiration, exit_index should be >= entry_index + 12
            assert trade.exit_index >= trade.entry_index + 12

    def test_gapped_irregular_timestamps_fallback(self) -> None:
        """When data has irregular gaps, engine finds the first row with
        timestamp >= target_exit_time.
        """
        base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        timestamps = []
        cur_t = base_t
        for i in range(250):
            timestamps.append(cur_t)
            cur_t += timedelta(seconds=30 if i % 2 == 0 else 90)

        np.random.seed(42)
        t = np.linspace(0, 16 * np.pi, 250)
        closes = 1.1000 + np.sin(t) * 0.0080

        rows = []
        for i in range(250):
            c = float(closes[i])
            o = float(closes[i - 1]) if i > 0 else c
            h = max(o, c) + 0.0004
            low = min(o, c) - 0.0004
            rows.append(
                {
                    "timestamp": timestamps[i],
                    "open": o,
                    "high": h,
                    "low": low,
                    "close": c,
                    "volume": 100.0,
                }
            )
        df_gapped = pd.DataFrame(rows)

        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            expiration_seconds=180,
            strategy_name="hybrid_multifactors",
        )
        engine = BinaryBacktestEngine(cfg)
        summary = engine.run(df_gapped)

        assert summary.total_trades > 0
        for trade in summary.trades:
            # Exit time must be >= entry_time + 180s
            target = trade.entry_time + timedelta(seconds=180)
            assert trade.exit_time >= target


class TestAutoAssignToxicAndMicrostructureRejection:
    """Test suite for AutoMatcher and PreTradingPlan rejection of toxic & dead assets."""

    @pytest.mark.asyncio
    async def test_matcher_returns_none_for_toxic_assets(self) -> None:
        matcher = StrategyAutoMatcher()
        toxic_pairs = [
            "USD/IDR OTC",
            "USDIDR_otc",
            "USD/VND OTC",
            "BNB OTC",
            "EUR/CHF OTC",
            "USD/DZD OTC",
            "UAH/USD OTC",
            "USD/MYR OTC",
            "USD/INR OTC",
            "EUR/HUF OTC",
            "GBP/JPY OTC",
        ]
        for pair in toxic_pairs:
            res = await matcher.find_optimal_strategy_for_asset(pair, [])
            assert res is None, f"Toxic pair {pair} must return None"

    @pytest.mark.asyncio
    async def test_matcher_returns_none_for_failed_microstructure(self) -> None:
        matcher = StrategyAutoMatcher()
        # 1. Flat candles
        df_flat = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=60, freq="min"),
                "open": [1.1000] * 60,
                "high": [1.1000] * 60,
                "low": [1.1000] * 60,
                "close": [1.1000] * 60,
                "volume": [0.0] * 60,
            }
        )
        res_flat = await matcher.find_optimal_strategy_for_asset("EURUSD_otc", df_flat)
        assert res_flat is None

        # 2. Corrupt with NaN
        df_nan = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=60, freq="min"),
                "open": [1.10] * 60,
                "high": [np.nan] * 60,
                "low": [1.08] * 60,
                "close": [1.09] * 60,
            }
        )
        res_nan = await matcher.find_optimal_strategy_for_asset("EURUSD_otc", df_nan)
        assert res_nan is None

    @pytest.mark.asyncio
    async def test_pre_trading_plan_filters_none_assignments(self) -> None:
        """When feed returns mixture of clean and toxic/microstructure-rejected assets,
        PreTradingPlan contains only accepted assets.
        """
        mock_feed = AsyncMock()

        # Generate good candles for clean assets
        base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        good_candles = [
            Candle(
                open_time=base_t + timedelta(minutes=i),
                open=Decimal(str(round(1.1000 + i * 0.0001, 5))),
                high=Decimal(str(round(1.1010 + i * 0.0001, 5))),
                low=Decimal(str(round(1.0990 + i * 0.0001, 5))),
                close=Decimal(str(round(1.1005 + i * 0.0001, 5))),
                volume=Decimal("100"),
            )
            for i in range(150)
        ]
        mock_feed.get_candles = AsyncMock(return_value=good_candles)

        assets = [
            "EURUSD_otc",  # Clean
            "USD/IDR OTC",  # Toxic
            "USDCLP_otc",  # Clean
            "BNB OTC",  # Toxic
            "Gold_otc",  # Clean
        ]

        plan = await generate_pre_trading_plan(
            feed=mock_feed,
            assets=assets,
            toxic_filter_enabled=False,  # let matcher evaluate all
        )

        # Only the 3 clean assets should be present
        assert len(plan.assignments) == 3
        assert plan.total_assets == 3
        assigned_symbols = [a.asset for a in plan.assignments]
        assert "EURUSD_otc" in assigned_symbols
        assert "USDCLP_otc" in assigned_symbols
        assert "Gold_otc" in assigned_symbols
        assert "USD/IDR OTC" not in assigned_symbols
        assert "BNB OTC" not in assigned_symbols
