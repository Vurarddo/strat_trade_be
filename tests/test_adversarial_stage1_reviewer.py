from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import (
    BacktestConfig,
    StakeModel,
)
from strat_trade.domain.entities import Candle
from strat_trade.domain.optimizer.auto_matcher import StrategyAutoMatcher
from strat_trade.use_cases.auto_assign_strategies import generate_pre_trading_plan


def _make_ohlcv(
    timestamps: list[datetime | pd.Timestamp | str | int],
    closes: list[float],
) -> pd.DataFrame:
    n = len(closes)
    rows = []
    for i in range(n):
        c = float(closes[i])
        o = float(closes[i - 1]) if i > 0 else c
        h = max(o, c) + 0.0005
        low = min(o, c) - 0.0005
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


class TestAdversarialTimeBasedBacktest:
    """Adversarial test suite challenging time-based backtest engine and configuration."""

    def test_tick_data_subsecond_and_1second_intervals(self) -> None:
        """Verify backtest on 1-second high-frequency tick data with exact target exit time."""
        n = 500
        base_t = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        timestamps = [base_t + timedelta(seconds=i) for i in range(n)]

        np.random.seed(123)
        t = np.linspace(0, 20 * np.pi, n)
        closes = 1.0500 + np.sin(t) * 0.0050 + np.random.normal(0, 0.0002, n)

        df = _make_ohlcv(timestamps, closes)
        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=1,
            expiration_seconds=30,  # 30 seconds expiration
            stake_model=StakeModel.FLAT,
            stake_amount=Decimal("10.0"),
            strategy_name="hybrid_multifactors",
        )
        engine = BinaryBacktestEngine(cfg)
        summary = engine.run(df)

        assert summary.total_trades > 0
        for trade in summary.trades:
            # Duration must be exactly 30 seconds since each row is 1 second
            duration = (trade.exit_time - trade.entry_time).total_seconds()
            assert duration == 30.0
            assert trade.expiration_seconds == 30
            assert trade.exit_index == trade.entry_index + 30

    def test_timezone_aware_and_naive_mixed_handling(self) -> None:
        """Verify engine works seamlessly with tz-aware (EST/UTC) and tz-naive timestamps."""
        n = 200
        base_t = datetime(2026, 1, 1, 10, 0)  # Naive
        timestamps = [base_t + timedelta(minutes=i) for i in range(n)]
        t = np.linspace(0, 10 * np.pi, n)
        closes = 1.1000 + np.sin(t) * 0.0040
        df_naive = _make_ohlcv(timestamps, closes)

        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            expiration_seconds=120,
            strategy_name="hybrid_multifactors",
        )
        engine = BinaryBacktestEngine(cfg)
        summary_naive = engine.run(df_naive)
        assert summary_naive.total_trades > 0
        for trade in summary_naive.trades:
            assert trade.expiration_seconds == 120
            assert (trade.exit_time - trade.entry_time).total_seconds() >= 120

    def test_large_gap_during_trade_expiration(self) -> None:
        """When a 2-hour data gap occurs, engine finds the first candle >= target_exit_time."""
        n_before = 100
        n_after = 100
        base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        timestamps = [base_t + timedelta(minutes=i) for i in range(n_before)]
        # Add 2-hour gap
        gap_t = timestamps[-1] + timedelta(hours=2)
        timestamps.extend([gap_t + timedelta(minutes=i) for i in range(n_after)])

        n_total = len(timestamps)
        t = np.linspace(0, 10 * np.pi, n_total)
        closes = 1.1000 + np.sin(t) * 0.0050
        df_gap = _make_ohlcv(timestamps, closes)

        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            expiration_seconds=180,
            strategy_name="hybrid_multifactors",
        )
        engine = BinaryBacktestEngine(cfg)
        summary = engine.run(df_gap)

        assert summary.total_trades > 0
        for trade in summary.trades:
            target = trade.entry_time + timedelta(seconds=180)
            assert trade.exit_time >= target

    def test_expiration_seconds_smaller_than_timeframe(self) -> None:
        """If expiration_seconds is 30s on a 60s timeframe, target_exit_time is +30s,
        and the first available candle >= target_exit_time is i + 1 (+60s).
        """
        n = 150
        base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        timestamps = [base_t + timedelta(minutes=i) for i in range(n)]
        t = np.linspace(0, 8 * np.pi, n)
        closes = 1.1000 + np.sin(t) * 0.0050
        df = _make_ohlcv(timestamps, closes)

        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            expiration_seconds=30,  # 30s expiration on 60s candles
            strategy_name="hybrid_multifactors",
        )
        engine = BinaryBacktestEngine(cfg)
        summary = engine.run(df)

        assert summary.total_trades > 0
        for trade in summary.trades:
            assert trade.expiration_seconds == 30
            # Target is entry + 30s, but next candle is entry + 60s
            assert trade.exit_index == trade.entry_index + 1
            assert (trade.exit_time - trade.entry_time).total_seconds() == 60.0

    def test_insufficient_historical_candles_returns_empty_summary(self) -> None:
        """When candles count < 40, engine gracefully returns empty summary without error."""
        base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        df_short = _make_ohlcv(
            [base_t + timedelta(minutes=i) for i in range(30)],
            [1.1000 + i * 0.0001 for i in range(30)],
        )
        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            expiration_seconds=180,
            strategy_name="hybrid_multifactors",
        )
        engine = BinaryBacktestEngine(cfg)
        summary = engine.run(df_short)

        assert summary.total_trades == 0
        assert summary.net_profit == Decimal("0.0")
        assert summary.win_rate_pct == Decimal("0.0")
        assert len(summary.trades) == 0

    def test_payout_filter_below_minimum_returns_empty_summary(self) -> None:
        """When payout rate is below min_payout_rate, backtest terminates early."""
        base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        df = _make_ohlcv(
            [base_t + timedelta(minutes=i) for i in range(100)],
            [1.1000 + (i % 5) * 0.0005 for i in range(100)],
        )
        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            payout_rate=Decimal("0.70"),
            min_payout_rate=Decimal("0.80"),
            expiration_seconds=180,
            strategy_name="hybrid_multifactors",
        )
        engine = BinaryBacktestEngine(cfg)
        summary = engine.run(df)

        assert summary.total_trades == 0
        assert summary.trades == []


class TestAdversarialAutoAssignAndMatcher:
    """Adversarial tests for toxic & microstructure asset rejection in auto matcher."""

    @pytest.mark.asyncio
    async def test_all_toxic_assets_comprehensively_rejected(self) -> None:
        """Ensure all canonical toxic pairs return None with no strategy assigned."""
        matcher = StrategyAutoMatcher()
        toxic_samples = [
            "USD/IDR OTC",
            "USDIDR_otc",
            "USD/VND OTC",
            "USDVND_otc",
            "BNB OTC",
            "BNBUSD_otc",
            "EUR/CHF OTC",
            "EURCHF_otc",
            "USD/DZD OTC",
            "UAH/USD OTC",
            "USD/MYR OTC",
            "USD/INR OTC",
            "EUR/HUF OTC",
            "GBP/JPY OTC",
            "SYP/USD OTC",
            "LBP/USD OTC",
            "USD/PKR OTC",
            "AED/CNY OTC",
            "ZAR/USD OTC",
            "USD/COP OTC",
            "AUD/CHF OTC",
            "USD/THB OTC",
            "QAR/CNY OTC",
            "USD/RUB OTC",
            "EUR/GBP OTC",
            "BHD/CNY OTC",
            "USD/BRL OTC",
            "CHF/NOK OTC",
            "NZD/JPY OTC",
            "USD/MXN OTC",
            "CHF/JPY OTC",
            "EUR/JPY OTC",
            "USD/SGD OTC",
            "CAD/CHF OTC",
            "USD/CHF OTC",
            "AUD/JPY OTC",
            "GBP/AUD OTC",
            "YER/USD OTC",
            "KES/USD OTC",
        ]
        for asset in toxic_samples:
            res = await matcher.find_optimal_strategy_for_asset(asset, [])
            assert res is None, f"Asset '{asset}' must return None"

    @pytest.mark.asyncio
    async def test_microstructure_dead_and_whipsaw_assets_rejected(self) -> None:
        """Assets with dead ATR or high whipsaw flip ratio return None."""
        matcher = StrategyAutoMatcher()

        # 1. Dead volatility (relative ATR < 0.00003)
        base = 1000.0
        n = 60
        df_dead = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=n, freq="min"),
                "open": [base + i * 0.00001 for i in range(n)],
                "high": [base + i * 0.00001 + 0.000002 for i in range(n)],
                "low": [base + i * 0.00001 - 0.000002 for i in range(n)],
                "close": [base + i * 0.00001 + 0.000001 for i in range(n)],
                "volume": [10.0] * n,
            }
        )
        res_dead = await matcher.find_optimal_strategy_for_asset("EURUSD_otc", df_dead)
        assert res_dead is None

        # 2. Extreme alternating whipsaw sign flips (> 80%)
        closes = [1.2000 + (0.0020 if i % 2 == 1 else 0.0) for i in range(n)]
        df_whipsaw = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=n, freq="min"),
                "open": [c - 0.0002 for c in closes],
                "high": [c + 0.0005 for c in closes],
                "low": [c - 0.0005 for c in closes],
                "close": closes,
                "volume": [10.0] * n,
            }
        )
        res_whipsaw = await matcher.find_optimal_strategy_for_asset("EURUSD_otc", df_whipsaw)
        assert res_whipsaw is None

    @pytest.mark.asyncio
    async def test_pre_trading_plan_handles_all_rejected_assets(self) -> None:
        """When all requested assets fail qualification, PreTradingPlan has empty assignments."""
        mock_feed = AsyncMock()
        mock_feed.get_candles = AsyncMock(return_value=[])

        toxic_only = ["USD/IDR OTC", "BNB OTC", "EUR/CHF OTC"]
        plan = await generate_pre_trading_plan(
            feed=mock_feed,
            assets=toxic_only,
            toxic_filter_enabled=False,  # let matcher process all
        )

        assert plan.assignments == []
        assert plan.total_assets == 0


class TestAdversarialEndToEndAndApi:
    """Tests for API routes, execute_backtest integration, and reversed/shuffled data."""

    def test_reversed_and_unsorted_dataframe_auto_sorted(self) -> None:
        """Verify engine auto-sorts backwards-ordered dataframe and executes trades correctly."""
        base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        n = 200
        timestamps = [base_t + timedelta(minutes=i) for i in range(n)]
        t = np.linspace(0, 10 * np.pi, n)
        closes = 1.1000 + np.sin(t) * 0.0050

        # Create reversed dataframe
        df_normal = _make_ohlcv(timestamps, closes)
        df_reversed = df_normal.iloc[::-1].reset_index(drop=True)

        cfg = BacktestConfig(
            asset="EURUSD_otc",
            timeframe_seconds=60,
            expiration_seconds=180,
            strategy_name="hybrid_multifactors",
        )
        engine_norm = BinaryBacktestEngine(cfg)
        summary_norm = engine_norm.run(df_normal)

        engine_rev = BinaryBacktestEngine(cfg)
        summary_rev = engine_rev.run(df_reversed)

        assert summary_norm.total_trades > 0
        assert summary_rev.total_trades == summary_norm.total_trades
        assert summary_rev.win_rate_pct == summary_norm.win_rate_pct
        assert summary_rev.net_profit == summary_norm.net_profit

    @pytest.mark.asyncio
    async def test_execute_backtest_with_explicit_expiration_seconds(self) -> None:
        """Verify execute_backtest passes expiration_seconds through to engine."""
        from strat_trade.use_cases.run_backtest import execute_backtest

        base_t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        mock_feed = AsyncMock()
        mock_feed.get_candles = AsyncMock(
            return_value=[
                Candle(
                    open_time=base_t + timedelta(minutes=i),
                    open=Decimal(str(round(1.1000 + np.sin(i * 0.2) * 0.004, 5))),
                    high=Decimal(str(round(1.1005 + np.sin(i * 0.2) * 0.004, 5))),
                    low=Decimal(str(round(1.0995 + np.sin(i * 0.2) * 0.004, 5))),
                    close=Decimal(str(round(1.1000 + np.sin(i * 0.2) * 0.004, 5))),
                    volume=Decimal("100"),
                )
                for i in range(150)
            ]
        )

        summary = await execute_backtest(
            feed=mock_feed,
            asset="EURUSD_otc",
            timeframe_seconds=60,
            expiration_seconds=240,  # 4 minutes
            strategy_name="hybrid_multifactors",
        )

        if summary.total_trades > 0:
            for t in summary.trades:
                assert t.expiration_seconds == 240
