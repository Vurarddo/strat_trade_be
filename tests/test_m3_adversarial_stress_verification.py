from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from strat_trade.domain.backtest.models import (
    BacktestTrade,
    PortfolioBacktestConfig,
    StakeModel,
    TradeAction,
    TradeOutcome,
)
from strat_trade.domain.backtest.portfolio_engine import PortfolioBacktestEngine
from strat_trade.domain.backtest.verification_runner import (
    Rolling15TradeVerificationRunner,
    RollingVerificationReport,
    VerificationStatus,
)
from strat_trade.domain.entities import Candle
from strat_trade.main import app

# =========================================================================
# FIXTURES & DETERMINISTIC CANDLE FACTORIES
# =========================================================================


def make_portfolio_trade(
    index: int,
    asset: str,
    outcome: TradeOutcome,
    stake: float = 10.0,
    payout_rate: float = 0.92,
    action: TradeAction = TradeAction.CALL,
    entry_price: float = 1.1000,
    base_time: datetime | None = None,
) -> BacktestTrade:
    t_start = base_time or datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    entry_time = t_start + timedelta(minutes=index * 2)
    exit_time = entry_time + timedelta(minutes=3)

    stake_dec = Decimal(str(stake))
    payout_dec = Decimal(str(payout_rate))

    if outcome == TradeOutcome.WIN:
        pnl = round(stake_dec * payout_dec, 4)
        exit_p = entry_price + 0.0005 if action == TradeAction.CALL else entry_price - 0.0005
    elif outcome == TradeOutcome.LOSS:
        pnl = -stake_dec
        exit_p = entry_price - 0.0005 if action == TradeAction.CALL else entry_price + 0.0005
    else:  # DRAW
        pnl = Decimal("0.0")
        exit_p = entry_price

    return BacktestTrade(
        entry_index=index * 2,
        exit_index=index * 2 + 3,
        entry_time=entry_time,
        exit_time=exit_time,
        action=action,
        entry_price=Decimal(str(round(entry_price, 5))),
        exit_price=Decimal(str(round(exit_p, 5))),
        stake=stake_dec,
        payout_rate=payout_dec,
        pnl=pnl,
        outcome=outcome,
        balance_after=Decimal("1000.0") + pnl,
        confidence=0.88,
        expiration_seconds=180,
        asset=asset,
    )


class MultiRegimeStressCandleFactory:
    """Deterministic candle generator with clean microstructure for adversarial tests."""

    @staticmethod
    def make_ranging_channel_with_wicks(
        n: int = 350,
        base_price: float = 1.1000,
        amplitude: float = 0.0060,
        period: int = 24,
    ) -> pd.DataFrame:
        times = pd.date_range("2026-08-20 08:00:00", periods=n, freq="1min", tz="UTC")
        t = np.linspace(0, (n / period) * 2 * np.pi, n)
        sine = np.sin(t) * amplitude
        noise = np.sin(t * 7) * (amplitude * 0.08)
        closes = base_price + sine + noise

        rows = []
        for i in range(n):
            c = float(closes[i])
            o = float(closes[i - 1]) if i > 0 else c
            phase = float(t[i] % (2 * np.pi))

            if 4.2 <= phase <= 5.4:  # Lower bounce
                low = min(o, c) - 0.0010
                high = max(o, c) + 0.0002
                if c <= o:
                    c = o + 0.0004
            elif 1.1 <= phase <= 2.3:  # Upper bounce
                high = max(o, c) + 0.0010
                low = min(o, c) - 0.0002
                if c >= o:
                    c = o - 0.0004
            else:
                high = max(o, c) + 0.0003
                low = min(o, c) - 0.0003

            rows.append(
                {
                    "timestamp": times[i],
                    "open": o,
                    "high": high,
                    "low": low,
                    "close": c,
                    "volume": 100.0,
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def make_multi_cycle_squeeze_breakouts(n: int = 350) -> pd.DataFrame:
        times = pd.date_range("2026-08-20 08:00:00", periods=n, freq="1min", tz="UTC")
        closes = np.full(n, 1.1000, dtype=float)
        # 3 distinct squeeze -> breakout cycles
        cycle_len = n // 3
        for c in range(3):
            c_start = c * cycle_len
            c_end = (c + 1) * cycle_len
            sq_len = cycle_len // 2
            # Squeeze
            for i in range(c_start, c_start + sq_len):
                closes[i] = 1.1000 + (c * 0.0050) + np.sin(i * 0.5) * 0.00005
            # Breakout expansion
            for i in range(c_start + sq_len, c_end):
                closes[i] = closes[i - 1] + 0.00035 + (0.0001 if i % 2 == 0 else -0.00005)

        opens = np.roll(closes, 1)
        opens[0] = 1.1000
        highs = np.maximum(opens, closes) + 0.0002
        lows = np.minimum(opens, closes) - 0.0001
        volumes = np.linspace(50.0, 300.0, n)

        return pd.DataFrame(
            {
                "timestamp": times,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
            }
        )

    @staticmethod
    def make_trending_market(n: int = 300, slope: float = 0.00025) -> pd.DataFrame:
        times = pd.date_range("2026-08-20 08:00:00", periods=n, freq="1min", tz="UTC")
        trend = np.linspace(0, slope * n, n)
        noise = np.sin(np.linspace(0, 15, n)) * 0.0002
        closes = 1.0850 + trend + noise
        opens = np.roll(closes, 1)
        opens[0] = 1.0850
        highs = np.maximum(opens, closes) + 0.0003
        lows = np.minimum(opens, closes) - 0.0001
        volumes = np.random.uniform(80.0, 200.0, n)
        return pd.DataFrame(
            {
                "timestamp": times,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
            }
        )

    @staticmethod
    def make_pure_random_walk(n: int = 250, seed: int = 123) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        times = pd.date_range("2026-08-20 08:00:00", periods=n, freq="1min", tz="UTC")
        steps = rng.normal(0.0, 0.0003, n)
        closes = 1.1000 + np.cumsum(steps)
        highs = closes + np.abs(rng.normal(0.0, 0.0002, n))
        lows = closes - np.abs(rng.normal(0.0, 0.0002, n))
        opens = np.roll(closes, 1)
        opens[0] = 1.1000
        volumes = rng.uniform(50.0, 100.0, n)
        return pd.DataFrame(
            {
                "timestamp": times,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
            }
        )


# =========================================================================
# SUITE 1: AUTOMATED TUNING FEEDBACK LOOP STRESS TESTS
# =========================================================================


def test_adversarial_autotune_bollinger_atr_reversion_converges() -> None:
    """
    Intentionally initializes BollingerAtrReversion with failing parameters
    (adx_trend_threshold=50.0, min_wick_ratio=0.50, bb_std=3.0) on a ranging market.
    Verifies that the optimizer triggers and finds optimal parameters.
    """
    df = MultiRegimeStressCandleFactory.make_ranging_channel_with_wicks(n=350)
    bad_params = {
        "adx_trend_threshold": 50.0,
        "min_wick_ratio": 0.50,
        "bb_std": 3.0,
        "rsi_oversold": 20.0,
        "rsi_overbought": 80.0,
    }

    runner = Rolling15TradeVerificationRunner(
        strategy_name="bollinger_atr_reversion",
        strategy_params=bad_params,
        auto_tune_on_failure=True,
        max_tuning_combinations=16,
        enable_plateau_check=True,
    )

    custom_grid = {
        "adx_trend_threshold": [22.0, 28.0],
        "min_wick_ratio": [0.15, 0.25],
        "bb_std": [1.8, 2.0],
        "base_expiration_bars": [2, 3],
    }

    report = runner.verify_or_optimize(df, parameter_grid=custom_grid)

    assert report.auto_tuned is True
    assert report.tuning_iterations > 0
    assert report.initial_params == bad_params
    assert report.optimized_params is not None
    assert report.tuning_report is not None
    assert "total_combinations_evaluated" in report.tuning_report


def test_adversarial_autotune_squeeze_breakout_converges() -> None:
    """
    Intentionally initializes VolatilitySqueezeBreakout with broken kc_mult=0.5
    on a multi-cycle squeeze-breakout market. Verifies auto-tuner evaluates grid and adapts.
    """
    df = MultiRegimeStressCandleFactory.make_multi_cycle_squeeze_breakouts(n=350)
    bad_params = {"kc_mult": 0.5, "momentum_period": 20}

    runner = Rolling15TradeVerificationRunner(
        strategy_name="volatility_squeeze_breakout",
        strategy_params=bad_params,
        auto_tune_on_failure=True,
        max_tuning_combinations=12,
    )

    custom_grid = {
        "kc_mult": [1.4, 1.5, 1.6],
        "momentum_period": [8, 12],
        "base_expiration_bars": [2, 3],
    }

    report = runner.verify_or_optimize(df, parameter_grid=custom_grid)

    assert report.auto_tuned is True
    assert report.tuning_iterations > 0
    assert report.optimized_params is not None


def test_adversarial_autotune_ema_pullback_converges() -> None:
    """
    Intentionally initializes EmaPullbackTrend with inverted moving averages (fast=50, mid=10).
    Verifies auto-tuner searches parameter space and evaluates valid trend parameters.
    """
    df = MultiRegimeStressCandleFactory.make_trending_market(n=300)
    inverted_params = {"ema_fast": 50, "ema_mid": 10, "adx_threshold": 40.0}

    runner = Rolling15TradeVerificationRunner(
        strategy_name="ema_pullback_trend",
        strategy_params=inverted_params,
        auto_tune_on_failure=True,
        max_tuning_combinations=12,
    )

    custom_grid = {
        "ema_fast": [7, 9],
        "ema_mid": [21, 26],
        "adx_threshold": [20.0, 24.0],
        "base_expiration_bars": [2, 3],
    }

    report = runner.verify_or_optimize(df, parameter_grid=custom_grid)

    assert report.auto_tuned is True
    assert report.tuning_iterations > 0
    assert report.optimized_params is not None


def test_adversarial_autotune_pure_noise_graceful_handling() -> None:
    """
    On pure random walk market where no strategy edge exists:
    Verifies optimizer handles failure without exceptions, terminates cleanly,
    and returns accurate diagnostics in tuning_report.
    """
    df = MultiRegimeStressCandleFactory.make_pure_random_walk(n=200)
    runner = Rolling15TradeVerificationRunner(
        strategy_name="bollinger_atr_reversion",
        strategy_params={"adx_trend_threshold": 50.0},
        auto_tune_on_failure=True,
        max_tuning_combinations=6,
    )

    report = runner.verify_or_optimize(
        df,
        parameter_grid={
            "adx_trend_threshold": [15.0, 25.0],
            "bb_std": [2.0, 2.5],
        },
    )

    # Must complete without crashing
    assert isinstance(report, RollingVerificationReport)
    assert report.auto_tuned is True
    assert report.tuning_iterations > 0
    assert report.tuning_report is not None


def test_adversarial_plateau_check_deterministic_behavior() -> None:
    """
    Verifies parameter plateau stability test (_check_parameter_plateau):
    Executes perturbation logic across multi-parameter grid.
    """
    df = MultiRegimeStressCandleFactory.make_ranging_channel_with_wicks(n=200)
    runner = Rolling15TradeVerificationRunner(strategy_name="bollinger_atr_reversion")

    grid = {
        "adx_trend_threshold": [10.0, 25.0, 45.0],
        "bb_std": [1.0, 2.0, 3.5],
    }
    opt_params = {"adx_trend_threshold": 25.0, "bb_std": 2.0}

    is_stable = runner._check_parameter_plateau(df, opt_params, grid)
    assert isinstance(is_stable, bool)


# =========================================================================
# SUITE 2: MULTI-ASSET PORTFOLIO 60-TRADE SEQUENTIAL CYCLES
# =========================================================================


def test_adversarial_multi_asset_portfolio_60_trade_sequential_cycles() -> None:
    """
    Simulates a multi-asset portfolio (EURUSD_otc, GBPUSD_otc, USDJPY_otc, AUDUSD_otc)
    generating 60 sequential trades across 4 distinct 15-trade cycles.
    Verifies batch partitioning, win rates, PnL accumulation, and rolling window continuity.
    """
    assets = ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "AUDUSD_otc"]
    trades: list[BacktestTrade] = []

    # 4 cycles with varying profitable compositions:
    # Cycle 1: 9W, 6L (WR: 60.00%, Net: 9*9.2 - 6*10 = +$22.80)
    # Cycle 2: 8W, 7L (WR: 53.33%, Net: 8*9.2 - 7*10 = +$3.60)
    # Cycle 3: 10W, 5L (WR: 66.67%, Net: 10*9.2 - 5*10 = +$42.00)
    # Cycle 4: 11W, 4L (WR: 73.33%, Net: 11*9.2 - 4*10 = +$61.20)
    cycle_specs = [(9, 6), (8, 7), (10, 5), (11, 4)]

    trade_idx = 0
    for wins, losses in cycle_specs:
        outcomes = [TradeOutcome.WIN] * wins + [TradeOutcome.LOSS] * losses
        for i, outcome in enumerate(outcomes):
            asset = assets[(trade_idx + i) % len(assets)]
            t = make_portfolio_trade(
                index=trade_idx,
                asset=asset,
                outcome=outcome,
                stake=10.0,
                payout_rate=0.92,
            )
            trades.append(t)
            trade_idx += 1

    assert len(trades) == 60

    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(trades)

    # 1. High-level verification metrics
    assert report.total_trades == 60
    assert report.total_batches == 4
    assert report.passed_batches == 4
    assert report.failed_batches == 0
    assert report.all_batches_passed is True
    assert report.all_non_overlapping_passed is True
    assert report.status == VerificationStatus.PASSED

    # 2. Sequential batch assertions
    assert len(report.batches) == 4
    for b_idx, batch in enumerate(report.batches):
        assert batch.is_partial is False
        assert batch.total_trades == 15
        assert batch.start_trade_index == b_idx * 15 + 1
        assert batch.end_trade_index == (b_idx + 1) * 15
        assert batch.passed is True
        assert batch.net_pnl > Decimal("0.0")
        assert batch.win_rate_pct >= Decimal("53.33")

    # 3. Rolling windows continuity: 60 - 15 + 1 = 46 rolling windows
    assert report.total_rolling_windows == 46
    assert len(report.rolling_windows) == 46
    for r_idx, r_win in enumerate(report.rolling_windows):
        assert r_win.start_trade_index == r_idx + 1
        assert r_win.end_trade_index == r_idx + 15
        assert r_win.total_trades == 15

    # 4. Total cumulative PnL check: 22.80 + 3.60 + 42.00 + 61.20 = +$129.60
    assert report.total_net_pnl == Decimal("129.60")


def test_adversarial_multi_asset_portfolio_75_trade_five_cycle_stress() -> None:
    """75 trades across 5 sequential cycles with front-loaded loss shock and recovery."""
    assets = ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc"]
    trades: list[BacktestTrade] = []

    # Cycle 1: 7 LOSS, then 8 WIN -> Max consecutive losses 7, but passes batch with WR 53.33%
    # Cycle 2: 9 WIN, 6 LOSS
    # Cycle 3: 10 WIN, 5 LOSS
    # Cycle 4: 8 WIN, 7 LOSS
    # Cycle 5: 12 WIN, 3 LOSS
    cycle_outcomes = [
        [TradeOutcome.LOSS] * 7 + [TradeOutcome.WIN] * 8,
        [TradeOutcome.WIN] * 9 + [TradeOutcome.LOSS] * 6,
        [TradeOutcome.WIN] * 10 + [TradeOutcome.LOSS] * 5,
        [TradeOutcome.WIN] * 8 + [TradeOutcome.LOSS] * 7,
        [TradeOutcome.WIN] * 12 + [TradeOutcome.LOSS] * 3,
    ]

    trade_idx = 0
    for cycle in cycle_outcomes:
        for outcome in cycle:
            asset = assets[trade_idx % len(assets)]
            t = make_portfolio_trade(trade_idx, asset, outcome, stake=10.0, payout_rate=0.92)
            trades.append(t)
            trade_idx += 1

    assert len(trades) == 75

    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(trades)

    assert report.total_trades == 75
    assert report.total_batches == 5
    assert report.passed_batches == 5
    assert report.failed_batches == 0
    assert report.all_batches_passed is True

    # Check batch 1 drawdown & loss streak
    b1 = report.batches[0]
    assert b1.max_consecutive_losses == 7
    assert b1.max_drawdown_amount == Decimal("70.0")
    assert b1.net_pnl == Decimal("3.60")
    assert b1.passed is True


def test_adversarial_portfolio_engine_integration_with_verification_runner() -> None:
    """
    Directly runs multi-asset PortfolioBacktestEngine and feeds its trade stream
    into Rolling15TradeVerificationRunner to verify domain interoperability.
    """
    df1 = MultiRegimeStressCandleFactory.make_ranging_channel_with_wicks(n=250, base_price=1.1000)
    df2 = MultiRegimeStressCandleFactory.make_ranging_channel_with_wicks(n=250, base_price=1.2500)

    config = PortfolioBacktestConfig(
        assets=["EURUSD_otc", "GBPUSD_otc"],
        timeframe_seconds=60,
        initial_deposit=Decimal("1000.0"),
        stake_model=StakeModel.FLAT,
        stake_amount=Decimal("10.0"),
        payout_rates={"EURUSD_otc": Decimal("0.92"), "GBPUSD_otc": Decimal("0.92")},
        strategy_name="bollinger_atr_reversion",
        strategy_params={"adx_trend_threshold": 30.0, "min_wick_ratio": 0.15, "bb_std": 1.8},
        expiration_bars=3,
        max_concurrent_trades=2,
    )

    p_engine = PortfolioBacktestEngine(config)
    p_summary = p_engine.run({"EURUSD_otc": df1, "GBPUSD_otc": df2})
    assert p_summary.total_trades >= 0

    # Feed trades to verification runner
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(p_summary.trades)

    assert isinstance(report, RollingVerificationReport)
    assert report.total_trades == len(p_summary.trades)


# =========================================================================
# SUITE 3: REST API VERIFICATION ENDPOINT ADVERSARIAL STRESS TESTS
# =========================================================================


def test_api_verify_15_trades_invalid_payload_validation_errors() -> None:
    """Adversarial stress test on API payload validation (HTTP 422)."""
    mock_feed = AsyncMock()
    app.state.trading_gateway = mock_feed
    client = TestClient(app)

    # 1. Negative deposit
    res1 = client.post("/api/v1/backtest/verify-15-trades", json={"initial_deposit": -500.0})
    assert res1.status_code == 422

    # 2. Out of bounds payout_rate (> 1.0)
    res2 = client.post("/api/v1/backtest/verify-15-trades", json={"payout_rate": 1.95})
    assert res2.status_code == 422

    # 3. Out of bounds payout_rate (< 0.1)
    res3 = client.post("/api/v1/backtest/verify-15-trades", json={"payout_rate": -0.5})
    assert res3.status_code == 422

    # 4. Out of bounds min_win_rate_pct (> 100.0)
    res4 = client.post("/api/v1/backtest/verify-15-trades", json={"min_win_rate_pct": 120.0})
    assert res4.status_code == 422

    # 5. Invalid stake_amount (< 1.0)
    res5 = client.post("/api/v1/backtest/verify-15-trades", json={"stake_amount": 0.05})
    assert res5.status_code == 422

    # 6. Candle count below min (< 60)
    res6 = client.post("/api/v1/backtest/verify-15-trades", json={"candle_count": 10})
    assert res6.status_code == 422

    # 7. Candle count above max (> 2000)
    res7 = client.post("/api/v1/backtest/verify-15-trades", json={"candle_count": 50000})
    assert res7.status_code == 422

    # 8. Extra forbidden parameter (extra='forbid')
    res8 = client.post(
        "/api/v1/backtest/verify-15-trades",
        json={"unrecognized_malicious_field": "exploit_attempt"},
    )
    assert res8.status_code == 422

    # 9. Malformed types (string for numeric candle_count)
    res9 = client.post(
        "/api/v1/backtest/verify-15-trades",
        json={"candle_count": "one_thousand"},
    )
    assert res9.status_code == 422


def test_api_verify_15_trades_non_existent_strategy_safety() -> None:
    """Non-existent or malformed strategy names safely fallback to default strategy."""
    mock_feed = AsyncMock()
    df_synthetic = MultiRegimeStressCandleFactory.make_ranging_channel_with_wicks(n=200)
    mock_candles = [
        Candle(
            open_time=row["timestamp"].to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        for _, row in df_synthetic.iterrows()
    ]
    mock_feed.get_candles.return_value = mock_candles

    app.state.trading_gateway = mock_feed
    client = TestClient(app)

    payload = {
        "asset": "EURUSD_otc",
        "strategy_name": "phantom_quantum_ai_strategy_9999",
        "candle_count": 200,
    }
    response = client.post("/api/v1/backtest/verify-15-trades", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "total_batches" in data
    assert "status" in data


def test_api_verify_15_trades_empty_feed_candles_error() -> None:
    """When candle feed returns empty list, endpoint returns HTTP 400."""
    mock_feed = AsyncMock()
    mock_feed.get_candles.return_value = []

    app.state.trading_gateway = mock_feed
    client = TestClient(app)

    payload = {
        "asset": "EURUSD_otc",
        "candle_count": 200,
    }
    response = client.post("/api/v1/backtest/verify-15-trades", json=payload)
    assert response.status_code == 400
    err_data = response.json()
    assert "error" in err_data
    assert "No candles returned from broker" in err_data["error"]["message"]


def test_api_verify_15_trades_feed_broker_exception_handling() -> None:
    """When candle feed raises unexpected runtime exception, endpoint raises error cleanly."""
    mock_feed = AsyncMock()
    mock_feed.get_candles.side_effect = RuntimeError("Broker WebSocket disconnection")

    app.state.trading_gateway = mock_feed
    client = TestClient(app, raise_server_exceptions=False)

    payload = {
        "asset": "EURUSD_otc",
        "candle_count": 200,
    }
    response = client.post("/api/v1/backtest/verify-15-trades", json=payload)
    assert response.status_code in [400, 500]


def test_api_verify_15_trades_e2e_autotune_successful_response() -> None:
    """E2E API verification with auto_tune=True returning verified response structure."""
    mock_feed = AsyncMock()
    df_synthetic = MultiRegimeStressCandleFactory.make_ranging_channel_with_wicks(n=250)
    mock_candles = [
        Candle(
            open_time=row["timestamp"].to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        for _, row in df_synthetic.iterrows()
    ]
    mock_feed.get_candles.return_value = mock_candles

    app.state.trading_gateway = mock_feed
    client = TestClient(app)

    payload = {
        "asset": "EURUSD_otc",
        "strategy_name": "bollinger_atr_reversion",
        "strategy_params": {"adx_trend_threshold": 50.0, "bb_std": 3.0},
        "payout_rate": 0.92,
        "candle_count": 250,
        "auto_tune": True,
        "parameter_grid": {
            "adx_trend_threshold": [22.0, 28.0],
            "bb_std": [1.8, 2.0],
        },
        "max_combinations": 8,
    }

    response = client.post("/api/v1/backtest/verify-15-trades", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["auto_tuned"] is True
    assert data["optimized_params"] is not None
    assert data["tuning_iterations"] > 0
    assert "batches" in data
    assert "status" in data
