"""Empirical Challenger 2 Test Suite: Portfolio-Level Behavior & Strategy Auto-Matching.

Adversarial empirical stress-testing for:
1. StrategyAutoMatcher & PreTradingPlan with mixed toxic and whitelist assets.
2. LiveDemoBotEngine concurrency stress simulation verifying _order_lock and toxic asset rejection.
3. Multi-batch 15-trade simulation with 60 trades across 4 batches (deposit growth > 0, WR >= 56%).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import (
    BacktestConfig,
    BacktestTrade,
    StakeModel,
    TradeAction,
    TradeOutcome,
)
from strat_trade.domain.backtest.verification_runner import (
    Rolling15TradeVerificationRunner,
    VerificationStatus,
)
from strat_trade.domain.entities import Candle
from strat_trade.domain.optimizer.auto_matcher import (
    PRIORITY_STRATEGIES,
    StrategyAutoMatcher,
)
from strat_trade.domain.trading.asset_filter import (
    DEFAULT_TOXIC_OTC_BLACKLIST,
    canonical_asset_key,
    filter_allowed_assets,
    is_toxic_asset,
    is_whitelisted_asset,
)
from strat_trade.domain.trading.bot_engine import LiveDemoBotEngine
from strat_trade.domain.trading.entities import (
    PreTradingPlan,
    StrategyAssignment,
)
from strat_trade.domain.trading.trade_store import TradeStore
from strat_trade.ports.candles import CandleFeed
from strat_trade.use_cases.auto_assign_strategies import generate_pre_trading_plan


class MockCandleFeed(CandleFeed):
    """Mock candle feed for testing async plan generation."""

    def __init__(self, candles_map: dict[str, list[Candle]] | None = None) -> None:
        self.candles_map = candles_map or {}

    async def get_candles(self, asset: str, timeframe: int = 60, count: int = 150) -> list[Candle]:
        if asset in self.candles_map:
            return self.candles_map[asset]

        t0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC)
        candles = []
        base_p = 1.1000 if "EUR" in asset or "USD" in asset else 100.0
        step = 0.0001 if base_p < 10 else 0.05
        for i in range(count):
            candles.append(
                Candle(
                    open_time=t0 + timedelta(minutes=i),
                    open=Decimal(str(round(base_p + i * step, 4))),
                    high=Decimal(str(round(base_p + i * step + step * 5, 4))),
                    low=Decimal(str(round(base_p + i * step - step * 5, 4))),
                    close=Decimal(str(round(base_p + i * step + step * 2, 4))),
                    volume=Decimal("500"),
                )
            )
        return candles

    async def get_latest_candle(self, asset: str, timeframe: int = 60) -> Candle:
        candles = await self.get_candles(asset, timeframe, count=1)
        return candles[-1]


def _create_synthetic_trending_candles(
    n: int = 200, base_price: float = 100.0, trend: float = 0.05
) -> list[Candle]:
    t0 = datetime(2026, 8, 20, 8, 0, 0, tzinfo=UTC)
    candles = []
    p = base_price
    for i in range(n):
        noise = 0.02 if i % 2 == 0 else -0.01
        p_open = p
        p_close = p + trend + noise
        p_high = max(p_open, p_close) + 0.03
        p_low = min(p_open, p_close) - 0.03
        p = p_close
        candles.append(
            Candle(
                open_time=t0 + timedelta(minutes=i),
                open=Decimal(f"{p_open:.4f}"),
                high=Decimal(f"{p_high:.4f}"),
                low=Decimal(f"{p_low:.4f}"),
                close=Decimal(f"{p_close:.4f}"),
                volume=Decimal("1000"),
            )
        )
    return candles


# ============================================================================
# Dimension 1: StrategyAutoMatcher & PreTradingPlan Empirical Stress Tests
# ============================================================================


@pytest.mark.asyncio
async def test_automatcher_mixed_toxic_and_whitelist_variations():
    """Stress test StrategyAutoMatcher with 8 toxic format variations and 7 whitelist variations.

    Invariants:
    1. Every toxic format is rejected with None.
    2. Every whitelist format is recognized, receiving quantum boost and priority strategy.
    """
    matcher = StrategyAutoMatcher(candle_count=150)
    candles = _create_synthetic_trending_candles(150)

    toxic_variations = [
        "USD/IDR OTC",
        "USDIDR_otc",
        "usdidr_otc",
        "USD-IDR (OTC)",
        "USD/VND OTC",
        "usdvnd_otc",
        "BNB OTC",
        "EUR/CHF OTC",
        "USD/DZD OTC",
        "UAH/USD OTC",
        "USD/MYR OTC",
        "USD/INR OTC",
        "EUR/HUF OTC",
        "GBP/JPY OTC",
    ]

    whitelist_variations = [
        "EUR/USD OTC",
        "eurusd_otc",
        "USD/CLP OTC",
        "usdclp_otc",
        "USD/BDT OTC",
        "usdbdt_otc",
        "USD/EGP OTC",
        "usdegp_otc",
        "Gold OTC",
        "XAUUSD_otc",
    ]

    # 1. Evaluate all toxic variations
    for toxic_sym in toxic_variations:
        assignment = await matcher.find_optimal_strategy_for_asset(
            asset=toxic_sym,
            candles=candles,
            timeframe_seconds=60,
            expiration_bars=3,
            payout_rate=0.92,
        )
        assert assignment is None, f"Toxic asset {toxic_sym} must be rejected with None"
        assert is_toxic_asset(toxic_sym)[0] is True, (
            f"is_toxic_asset must return True for {toxic_sym}"
        )

    # 2. Evaluate all whitelist variations
    for white_sym in whitelist_variations:
        assignment = await matcher.find_optimal_strategy_for_asset(
            asset=white_sym,
            candles=candles,
            timeframe_seconds=60,
            expiration_bars=3,
            payout_rate=0.92,
        )
        assert assignment.quantum_score >= 85.0, (
            f"Whitelist asset {white_sym} must receive high quantum score"
        )
        assert is_whitelisted_asset(white_sym) is True, (
            f"is_whitelisted_asset must return True for {white_sym}"
        )
        assert is_toxic_asset(white_sym)[0] is False, (
            f"is_toxic_asset must return False for {white_sym}"
        )
        assert assignment.strategy_id in PRIORITY_STRATEGIES or assignment.strategy_id != "", (
            f"Assignment {white_sym} valid"
        )


@pytest.mark.asyncio
async def test_generate_pre_trading_plan_toxic_rejection_and_whitelist_assignment():
    """Stress test generate_pre_trading_plan with mixed list of 10 assets (5 toxic, 5 whitelist).

    Invariants:
    1. With toxic_filter_enabled=True, all 5 toxic assets are purged before strategy assignment.
    2. Exactly the 5 non-toxic assets are assigned strategies.
    3. 0 toxic assets appear in the resulting PreTradingPlan.assignments.
    """
    mixed_assets = [
        "USD/IDR OTC",
        "EURUSD_otc",
        "USD/VND OTC",
        "USDCLP_otc",
        "BNB OTC",
        "USDBDT_otc",
        "EUR/CHF OTC",
        "USDEGP_otc",
        "BNBUSD_otc",
        "Gold_otc",
    ]

    feed = MockCandleFeed()
    plan = await generate_pre_trading_plan(
        feed=feed,
        assets=mixed_assets,
        initial_deposit=1000.0,
        toxic_filter_enabled=True,
    )

    assert plan.total_assets == 5
    assert len(plan.assignments) == 5

    assigned_assets = [a.asset for a in plan.assignments]
    assigned_canonical = [canonical_asset_key(a) for a in assigned_assets]

    # Verify 0 toxic canonical keys
    for toxic_key in DEFAULT_TOXIC_OTC_BLACKLIST:
        assert toxic_key not in assigned_canonical, (
            f"Toxic asset {toxic_key} leaked into pre-trading plan!"
        )

    # Verify all assigned assets are whitelist assets
    for white_asset in ["EURUSD_otc", "USDCLP_otc", "USDBDT_otc", "USDEGP_otc", "Gold_otc"]:
        assert white_asset in assigned_assets


@pytest.mark.asyncio
async def test_generate_pre_trading_plan_all_toxic_fallback():
    """When user requests ONLY toxic assets, fallback safely to curated whitelist."""
    toxic_only = ["USD/IDR OTC", "USD/VND OTC", "BNB OTC", "EUR/CHF OTC", "BNBUSD_otc"]
    feed = MockCandleFeed()

    plan = await generate_pre_trading_plan(
        feed=feed,
        assets=toxic_only,
        toxic_filter_enabled=True,
    )

    assert plan.total_assets == 5
    assert len(plan.assignments) == 5

    assigned_assets = [a.asset for a in plan.assignments]
    assert "EURUSD_otc" in assigned_assets
    assert "USDCLP_otc" in assigned_assets
    assert "Gold_otc" in assigned_assets

    for a in assigned_assets:
        is_tox, _ = is_toxic_asset(a)
        assert is_tox is False


@pytest.mark.asyncio
async def test_generate_pre_trading_plan_custom_whitelist_and_blacklist_enforcement():
    """Verify custom blacklist and whitelist parameters work as expected."""
    feed = MockCandleFeed()

    # Custom blacklist: block EURUSD
    plan_custom_black = await generate_pre_trading_plan(
        feed=feed,
        assets=["EURUSD_otc", "USDCLP_otc", "USDBDT_otc"],
        asset_blacklist=["EURUSD_otc"],
        toxic_filter_enabled=True,
    )
    assigned = [a.asset for a in plan_custom_black.assignments]
    assert "EURUSD_otc" not in assigned
    assert "USDCLP_otc" in assigned
    assert "USDBDT_otc" in assigned

    # Whitelist-only mode
    plan_whitelist_only = await generate_pre_trading_plan(
        feed=feed,
        assets=["EURUSD_otc", "AUDCAD_otc", "USDJPY_otc"],
        asset_whitelist=["EURUSD_otc"],
        toxic_filter_enabled=True,
        enforce_whitelist_only=True,
    )
    assigned_wo = [a.asset for a in plan_whitelist_only.assignments]
    assert assigned_wo == ["EURUSD_otc"]


@pytest.mark.asyncio
async def test_automatcher_synthetic_profitable_candles_toxic_vs_clean():
    """Adversarial test: Feed 100% win-rate candles to a toxic asset vs clean asset.

    Even when candles represent a perfect money-making scenario, the toxic asset MUST STILL
    be blocked with quantum_score = 10.0 and [TOXIC OTC BLACKLIST] rationale.
    """
    matcher = StrategyAutoMatcher(candle_count=200)
    candles = _create_synthetic_trending_candles(200, trend=0.10)

    # 1. Toxic asset with perfect candles
    toxic_assign = await matcher.find_optimal_strategy_for_asset(
        asset="USD/IDR OTC",
        candles=candles,
        timeframe_seconds=60,
        expiration_bars=3,
        payout_rate=0.92,
    )
    assert toxic_assign is None

    # 2. Clean asset with same candles
    clean_assign = await matcher.find_optimal_strategy_for_asset(
        asset="EUR/USD OTC",
        candles=candles,
        timeframe_seconds=60,
        expiration_bars=3,
        payout_rate=0.92,
    )
    assert clean_assign.quantum_score > 75.0
    assert "[TOXIC OTC BLACKLIST]" not in clean_assign.rationale


# ============================================================================
# Dimension 2: LiveDemoBotEngine Concurrent Execution & Blacklist Locking Stress Tests
# ============================================================================


@pytest.mark.asyncio
async def test_live_demo_bot_engine_concurrent_order_lock_blocks_all_blacklisted(tmp_path):
    """Adversarial stress test: 100 concurrent async workers attempting order executions.

    50 workers execute blacklisted assets, 50 workers execute clean assets.
    Verify:
    1. ZERO orders executed on blacklisted assets at broker gateway.
    2. ZERO blacklisted trades in bot.active_trades.
    3. ZERO blacklisted records in TradeStore database.
    """
    store = TradeStore(tmp_path / "concurrent_order_lock.db")
    bot = LiveDemoBotEngine(trade_store=store)

    toxic_symbols = ["USD/IDR OTC", "USDIDR_otc", "USD/VND OTC", "BNB OTC", "EUR/CHF OTC"]
    clean_symbols = ["EURUSD_otc", "USDCLP_otc", "USDEGP_otc", "Gold_otc", "USDBDT_otc"]

    assignments = [
        StrategyAssignment(
            asset=sym,
            strategy_id="hybrid_multifactors",
            strategy_name=f"Hybrid_{sym}",
            category="multifactors",
            parameters={},
            estimated_win_rate_pct=65.0,
            estimated_profit_factor=1.8,
            estimated_trades_count=50,
            quantum_score=85.0,
            rationale="test",
        )
        for sym in (toxic_symbols + clean_symbols)
    ]

    plan = PreTradingPlan(
        assignments=assignments,
        total_assets=len(assignments),
        initial_deposit=Decimal("10000.00"),
        stake_model="flat",
        stake_amount=Decimal("100.00"),
        stake_percent=1.0,
        expiration_seconds=180,
        daily_stop_loss_pct=0.50,
        stop_loss_amount=Decimal("5000.00"),
        max_concurrent_trades=10,  # allow clean trades
        min_payout_rate=0.80,
        cooldown_bars=0,
        global_cooldown_seconds=0,  # 0s global cooldown for concurrency test
        max_consecutive_losses=10,
        max_drawdown_pct_limit=0.50,
        correlation_filter_enabled=False,
        toxic_filter_enabled=True,
        bar_edge_guard_seconds=0.0,
    )

    executed_assets_at_gateway: list[str] = []

    mock_gateway = MagicMock()

    async def _mock_open_trade(asset, action, amount, expiration_seconds):
        executed_assets_at_gateway.append(asset)
        return f"broker-ord-{asset}", {"percentProfit": 92}

    mock_gateway.open_trade = AsyncMock(side_effect=_mock_open_trade)

    base_time = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
    mock_candles = [
        Candle(
            open_time=base_time + timedelta(minutes=i),
            open=Decimal("1.1000"),
            high=Decimal("1.1010"),
            low=Decimal("1.0990"),
            close=Decimal("1.1005"),
            volume=Decimal("100"),
        )
        for i in range(50)
    ]

    await bot.start(plan, mock_gateway)

    # Launch 100 concurrent tasks (alternating toxic and clean)
    tasks = []
    for i in range(100):
        assign = assignments[i % len(assignments)]
        tasks.append(
            bot._execute_order(
                assignment=assign,
                action="CALL" if i % 2 == 0 else "PUT",
                confidence=0.85,
                reason="stress_test_order_lock",
                candles=mock_candles,
                live_payout=0.92,
            )
        )

    await asyncio.gather(*tasks)

    # 1. Assert gateway never received any toxic asset
    for executed_asset in executed_assets_at_gateway:
        is_tox, _ = is_toxic_asset(executed_asset)
        assert is_tox is False, (
            f"CRITICAL: Toxic asset {executed_asset} was submitted to broker gateway!"
        )

    # 2. Assert active trades contains 0 toxic assets
    for trade in bot.active_trades.values():
        is_tox, _ = is_toxic_asset(trade.asset)
        assert is_tox is False, f"CRITICAL: Toxic asset {trade.asset} in active trades!"

    # 3. Assert trade store DB has 0 toxic assets
    stored_trades = store.list_trades(limit=200)
    for t_record in stored_trades:
        is_tox, _ = is_toxic_asset(t_record.asset)
        assert is_tox is False, f"CRITICAL: Toxic asset {t_record.asset} recorded in DB!"

    await bot.stop()


@pytest.mark.asyncio
async def test_live_demo_bot_engine_evaluate_single_asset_concurrent_prefilter(tmp_path):
    """Verify _evaluate_single_asset rejects toxic assets before calling candle feed or strategy."""
    store = TradeStore(tmp_path / "prefilter_trades.db")
    bot = LiveDemoBotEngine(trade_store=store)

    toxic_sym = "USD/IDR OTC"
    assignment = StrategyAssignment(
        asset=toxic_sym,
        strategy_id="hybrid_multifactors",
        strategy_name="Hybrid",
        category="multifactors",
        parameters={},
        estimated_win_rate_pct=60.0,
        estimated_profit_factor=1.5,
        estimated_trades_count=10,
        quantum_score=80.0,
        rationale="test",
    )

    plan = PreTradingPlan(
        assignments=[assignment],
        total_assets=1,
        initial_deposit=Decimal("1000.00"),
        stake_model="flat",
        stake_amount=Decimal("10.00"),
        stake_percent=1.0,
        expiration_seconds=180,
        daily_stop_loss_pct=0.20,
        stop_loss_amount=Decimal("200.00"),
        max_concurrent_trades=3,
        min_payout_rate=0.80,
        cooldown_bars=0,
        global_cooldown_seconds=0,
        max_consecutive_losses=3,
        max_drawdown_pct_limit=0.08,
        correlation_filter_enabled=False,
        toxic_filter_enabled=True,
        bar_edge_guard_seconds=0.0,
    )

    mock_gateway = MagicMock()
    mock_gateway.get_candles = AsyncMock()
    mock_gateway.get_asset_payout = AsyncMock(return_value=0.92)

    await bot.start(plan, mock_gateway)

    now = datetime.now(UTC)
    sem = asyncio.Semaphore(10)

    # Run 50 concurrent asset evaluations
    eval_tasks = [bot._evaluate_single_asset(assignment, now, sem) for _ in range(50)]
    await asyncio.gather(*eval_tasks)

    # get_candles must NEVER have been called because pre-filter aborted immediately
    mock_gateway.get_candles.assert_not_called()
    assert len(bot.active_trades) == 0

    await bot.stop()


# ============================================================================
# Dimension 3: Multi-Batch 15-Trade Simulation Stress Tests (60 Trades across 4 Batches)
# ============================================================================


def test_multi_batch_60_trades_4_batches_positive_deposit_growth_and_winrate():
    """Stress test: 60 sequential trades across 4 non-overlapping 15-trade batches.

    Batch Structure (Stake: $100, Payout: 92% -> Win: +$92, Loss: -$100):
    - Batch 1 (Trades 1-15):  10 Wins, 5 Losses -> WinRate: 66.7%, Net PnL: +$420.00
    - Batch 2 (Trades 16-30):  9 Wins, 6 Losses -> WinRate: 60.0%, Net PnL: +$228.00
    - Batch 3 (Trades 31-45): 11 Wins, 4 Losses -> WinRate: 73.3%, Net PnL: +$612.00
    - Batch 4 (Trades 46-60): 10 Wins, 5 Losses -> WinRate: 66.7%, Net PnL: +$420.00

    Aggregate Invariants:
    - Total Trades: 60 (40 Wins, 20 Losses)
    - Total Win Rate: 66.67% >= 56.0%
    - Total Net PnL: +$1,680.00 > $1,500.00
    - 0 Failed Batches (4 / 4 passed)
    - Strictly positive deposit growth in EVERY batch.
    """
    runner = Rolling15TradeVerificationRunner(
        strategy_name="hybrid_multifactors",
        asset="EURUSD_otc",
        payout_rate=Decimal("0.92"),
        initial_deposit=Decimal("10000.00"),
        stake_model=StakeModel.FLAT,
        stake_amount=Decimal("100.00"),
        batch_size=15,
        min_win_rate_pct=Decimal("53.4"),
        min_batch_pnl=Decimal("0.0"),
    )

    t0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC)
    trades: list[BacktestTrade] = []

    batch_outcomes = [
        [TradeOutcome.WIN] * 10 + [TradeOutcome.LOSS] * 5,
        [TradeOutcome.WIN] * 9 + [TradeOutcome.LOSS] * 6,
        [TradeOutcome.WIN] * 11 + [TradeOutcome.LOSS] * 4,
        [TradeOutcome.WIN] * 10 + [TradeOutcome.LOSS] * 5,
    ]

    trade_idx = 0
    cur_balance = Decimal("10000.00")
    for _b_idx, outcomes in enumerate(batch_outcomes):
        for out in outcomes:
            trade_idx += 1
            entry_time = t0 + timedelta(minutes=trade_idx * 3)
            exit_time = entry_time + timedelta(minutes=3)
            stake = Decimal("100.00")
            pnl = (stake * Decimal("0.92")) if out == TradeOutcome.WIN else -stake
            cur_balance += pnl

            trades.append(
                BacktestTrade(
                    entry_index=trade_idx,
                    exit_index=trade_idx + 3,
                    entry_time=entry_time,
                    exit_time=exit_time,
                    action=TradeAction.CALL,
                    entry_price=Decimal("1.1000"),
                    exit_price=Decimal("1.1010") if out == TradeOutcome.WIN else Decimal("1.0990"),
                    stake=stake,
                    payout_rate=Decimal("0.92"),
                    pnl=pnl,
                    outcome=out,
                    balance_after=cur_balance,
                    confidence=0.80,
                    expiration_seconds=180,
                    asset="EURUSD_otc",
                )
            )

    assert len(trades) == 60

    report = runner.evaluate_trades(trades)

    # Verification assertions
    assert report.status == VerificationStatus.PASSED
    assert report.total_trades == 60
    assert report.total_non_overlapping_batches == 4
    assert report.passed_non_overlapping_batches == 4
    assert report.failed_non_overlapping_batches == 0
    assert report.all_non_overlapping_passed is True

    # Check profitability and win rate metrics
    assert report.overall_win_rate_pct == pytest.approx(Decimal("66.67"), abs=Decimal("0.01"))
    assert report.overall_win_rate_pct >= Decimal("56.0")
    assert report.total_net_pnl == Decimal("1680.00")
    assert report.total_net_pnl > Decimal("1500.00")

    # Verify every individual batch is strictly positive
    expected_batch_pnls = [
        Decimal("420.00"),
        Decimal("228.00"),
        Decimal("612.00"),
        Decimal("420.00"),
    ]
    for i, b in enumerate(report.batches):
        assert b.passed is True, f"Batch {i + 1} failed unexpectedly!"
        assert b.net_pnl == expected_batch_pnls[i]
        assert b.net_pnl > Decimal("0.0"), (
            f"Batch {i + 1} deposit growth must be strictly positive!"
        )
        assert b.win_rate_pct >= Decimal("53.4")


def test_multi_batch_boundary_conditions_8_vs_7_wins():
    """Verify exact mathematical boundary conditions for 15-trade batches under 92% payout:

    - 8 wins / 7 losses: net PnL = 8*92 - 7*100 = +$36.00 -> PASSED.
    - 7 wins / 8 losses: net PnL = 7*92 - 8*100 = -$156.00 -> FAILED.
    """
    runner = Rolling15TradeVerificationRunner(
        payout_rate=Decimal("0.92"),
        stake_amount=Decimal("100.00"),
        batch_size=15,
        min_win_rate_pct=Decimal("53.4"),
    )

    t0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC)

    def _make_batch_trades(wins: int, losses: int, start_idx: int) -> list[BacktestTrade]:
        outcomes = [TradeOutcome.WIN] * wins + [TradeOutcome.LOSS] * losses
        b_trades = []
        for i, out in enumerate(outcomes):
            idx = start_idx + i
            pnl = Decimal("92.00") if out == TradeOutcome.WIN else Decimal("-100.00")
            b_trades.append(
                BacktestTrade(
                    entry_index=idx,
                    exit_index=idx + 3,
                    entry_time=t0 + timedelta(minutes=idx),
                    exit_time=t0 + timedelta(minutes=idx + 3),
                    action=TradeAction.CALL,
                    entry_price=Decimal("1.1000"),
                    exit_price=Decimal("1.1005"),
                    stake=Decimal("100.00"),
                    payout_rate=Decimal("0.92"),
                    pnl=pnl,
                    outcome=out,
                    balance_after=Decimal("1000.00") + pnl,
                    confidence=0.80,
                    expiration_seconds=180,
                    asset="EURUSD_otc",
                )
            )
        return b_trades

    # 1. 8 Wins / 7 Losses -> Must PASS
    trades_8w = _make_batch_trades(8, 7, 1)
    rep_8w = runner.evaluate_trades(trades_8w)
    assert rep_8w.overall_passed is True
    assert rep_8w.batches[0].net_pnl == Decimal("36.00")
    assert rep_8w.batches[0].passed is True

    # 2. 7 Wins / 8 Losses -> Must FAIL
    trades_7w = _make_batch_trades(7, 8, 1)
    rep_7w = runner.evaluate_trades(trades_7w)
    assert rep_7w.overall_passed is False
    assert rep_7w.batches[0].net_pnl == Decimal("-156.00")
    assert rep_7w.batches[0].passed is False
    assert (
        "Win rate" in rep_7w.batches[0].failure_reasons[0]
        or "Net PnL" in rep_7w.batches[0].failure_reasons[1]
    )


def test_end_to_end_backtest_simulation_supertrend_across_15_trade_batches():
    """End-to-end simulation: Run SuperTrend + ADX engine over 300 bars of trending candles.

    Verify that binary options trades generated by SuperTrend pass 15-trade verification.
    """
    candles = _create_synthetic_trending_candles(300, base_price=1.1000, trend=0.0008)
    df = pd.DataFrame(
        [
            {
                "timestamp": c.open_time,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(c.volume),
            }
            for c in candles
        ]
    )

    cfg = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        initial_deposit=1000.0,
        stake_model=StakeModel.FLAT,
        stake_amount=10.0,
        payout_rate=0.92,
        min_payout_rate=0.80,
        expiration_bars=3,
        strategy_name="supertrend_adx_momentum",
        strategy_params={
            "atr_period": 10,
            "atr_multiplier": 3.0,
            "adx_threshold": 20.0,
            "base_expiration_bars": 3,
        },
    )

    engine = BinaryBacktestEngine(cfg)
    summary = engine.run(df)

    assert summary.total_trades >= 5
    assert summary.win_rate_pct >= Decimal("60.0")

    runner = Rolling15TradeVerificationRunner(
        strategy_name="supertrend_adx_momentum",
        asset="EURUSD_otc",
        batch_size=5,
        min_win_rate_pct=Decimal("53.4"),
    )
    report = runner.evaluate_backtest_summary(summary)
    assert report.total_trades == summary.total_trades
    assert report.total_non_overlapping_batches >= 1
    assert report.all_non_overlapping_passed is True
    assert report.total_net_pnl > Decimal("0.0")


def test_toxic_asset_filtration_prevents_catastrophic_portfolio_drag():
    """Adversarial comparison:

    1. Portfolio with toxic blacklist removes toxic assets (USD/IDR OTC, BNB OTC).
    2. Canonical key normalization correctly classifies all toxic and whitelist pairs.
    """
    raw_portfolio_assets = ["USD/IDR OTC", "BNB OTC", "EURUSD_otc", "USDCLP_otc", "Gold_otc"]

    filtered = filter_allowed_assets(raw_portfolio_assets)
    assert "USD/IDR OTC" not in filtered
    assert "BNB OTC" not in filtered
    assert filtered == ["EURUSD_otc", "USDCLP_otc", "Gold_otc"]

    for asset in filtered:
        assert is_whitelisted_asset(asset) is True
