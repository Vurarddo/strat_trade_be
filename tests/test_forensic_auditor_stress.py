from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from strat_trade.domain.entities import Candle
from strat_trade.domain.trading.bot_engine import LiveDemoBotEngine
from strat_trade.domain.trading.correlation import (
    extract_currency_pair,
    get_portfolio_currency_exposure,
    is_correlated_conflict,
    normalize_symbol,
)
from strat_trade.domain.trading.entities import (
    BotStatus,
    IndicatorSnapshot,
    LiveTradeRecord,
    PreTradingPlan,
    StrategyAssignment,
)
from strat_trade.domain.trading.trade_store import TradeStore


def _make_mock_candles(count: int = 100, trend: float = 0.0001) -> list[Candle]:
    base_time = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    candles = []
    price = 1.1000
    for i in range(count):
        price += trend
        candles.append(
            Candle(
                open_time=base_time + timedelta(minutes=i),
                open=Decimal(str(round(price - 0.0001, 5))),
                high=Decimal(str(round(price + 0.0003, 5))),
                low=Decimal(str(round(price - 0.0003, 5))),
                close=Decimal(str(round(price, 5))),
                volume=Decimal("100"),
            )
        )
    return candles


def test_adversarial_symbol_normalization_and_extraction():
    """Stress tests strange, malformed, exotic, and edge-case asset symbols."""
    # Exotic OTC and standard formats
    assert normalize_symbol("EURUSD_otc") == "EURUSD"
    assert normalize_symbol("   eur-usd (OTC)  ") == "EURUSD"
    assert normalize_symbol("USD/CHF OTC") == "USDCHF"
    assert normalize_symbol("NZD_CAD_OTC") == "NZDCAD"
    assert normalize_symbol("BTC-USD-OTC") == "BTCUSD"
    assert normalize_symbol("ETH/USD (OTC)") == "ETHUSD"

    # Non-forex / Commodities / Equities
    assert extract_currency_pair("XAUUSD_otc") == ("XAU", "USD")
    assert extract_currency_pair("XAGUSD_otc") == ("XAG", "USD")
    assert extract_currency_pair("US500_otc") is None
    assert extract_currency_pair("AAPL") is None
    assert extract_currency_pair("TSLA_otc") is None
    assert extract_currency_pair("EUR") is None
    assert extract_currency_pair("EURUSDD") is None
    assert extract_currency_pair("EUR123") is None
    assert extract_currency_pair("USDEUR") == ("USD", "EUR")
    assert extract_currency_pair("USDUSD") is None  # base == quote rejected
    assert extract_currency_pair(None) is None
    assert extract_currency_pair("") is None


def test_adversarial_correlation_directional_matrix():
    """Verifies exposure conflict matrix across 4 major currencies (EUR, USD, GBP, JPY)."""
    # 1. EURUSD CALL (Long EUR, Short USD)
    trade_eurusd_call = {"asset": "EURUSD_otc", "action": "CALL"}

    # Candidates vs EURUSD CALL:
    # GBPUSD CALL: Long GBP, Short USD -> Double Short USD -> CONFLICT
    c, r = is_correlated_conflict("GBPUSD_otc", "CALL", [trade_eurusd_call])
    assert c is True and "Double Short USD" in r

    # GBPUSD PUT: Long USD, Short GBP -> No Double Long/Short
    c, r = is_correlated_conflict("GBPUSD_otc", "PUT", [trade_eurusd_call])
    assert c is False

    # USDCHF CALL: Long USD, Short CHF -> No Double Long/Short
    c, r = is_correlated_conflict("USDCHF_otc", "CALL", [trade_eurusd_call])
    assert c is False

    # USDCHF PUT: Long CHF, Short USD -> Double Short USD -> CONFLICT
    c, r = is_correlated_conflict("USDCHF_otc", "PUT", [trade_eurusd_call])
    assert c is True and "Double Short USD" in r

    # EURGBP CALL: Long EUR, Short GBP -> Double Long EUR -> CONFLICT
    c, r = is_correlated_conflict("EURGBP_otc", "CALL", [trade_eurusd_call])
    assert c is True and "Double Long EUR" in r

    # EURGBP PUT: Long GBP, Short EUR -> No Double Long/Short
    c, r = is_correlated_conflict("EURGBP_otc", "PUT", [trade_eurusd_call])
    assert c is False


def test_portfolio_exposure_net_zero_hedging():
    """Verifies portfolio aggregation under balanced currency loads."""
    trades = [
        {"asset": "EURUSD_otc", "action": "CALL"},  # +1 EUR, -1 USD
        {"asset": "EURUSD_otc", "action": "PUT"},  # -1 EUR, +1 USD
        {"asset": "GBPUSD_otc", "action": "CALL"},  # +1 GBP, -1 USD
        {"asset": "GBPJPY_otc", "action": "PUT"},  # +1 JPY, -1 GBP
    ]
    exp = get_portfolio_currency_exposure(trades)
    assert exp["EUR"] == 0
    assert exp["USD"] == -1
    assert exp["GBP"] == 0
    assert exp["JPY"] == 1


@pytest.mark.asyncio
async def test_drawdown_calculation_precision_and_recovery():
    """Stress tests peak drawdown when balance reaches new peaks and drops."""
    engine = LiveDemoBotEngine(trade_store=MagicMock(spec=TradeStore))
    plan = PreTradingPlan(
        assignments=[],
        total_assets=0,
        initial_deposit=Decimal("1000.00"),
        stake_model="flat",
        stake_amount=Decimal("10.00"),
        stake_percent=1.0,
        expiration_seconds=60,
        daily_stop_loss_pct=0.50,
        stop_loss_amount=Decimal("500.00"),
        max_concurrent_trades=3,
        min_payout_rate=0.80,
        max_drawdown_pct_limit=0.10,  # 10% limit
        bar_edge_guard_seconds=0.0,
    )
    gateway = AsyncMock()
    await engine.start(plan, gateway)

    # Initial: balance 1000, peak 1000, dd 0.0
    assert engine.peak_balance == Decimal("1000.00")
    assert engine.current_drawdown_pct == 0.0

    # Win sequence: grow balance to 1500.00
    engine.current_balance = Decimal("1500.00")
    engine.peak_balance = Decimal("1500.00")
    await engine._check_circuit_breakers()
    assert engine.status == BotStatus.RUNNING

    # Drop to 1400.00 -> Drawdown = (1500 - 1400) / 1500 = 6.67%
    engine.current_balance = Decimal("1400.00")
    await engine._check_circuit_breakers()
    assert engine.status == BotStatus.RUNNING
    assert round(engine.current_drawdown_pct, 2) == 6.67

    # Drop to 1340.00 -> Drawdown = (1500 - 1340) / 1500 = 10.67% -> Breach!
    engine.current_balance = Decimal("1340.00")
    await engine._check_circuit_breakers()
    assert engine.status == BotStatus.HALTED_BY_CIRCUIT_BREAKER
    assert round(engine.current_drawdown_pct, 2) == 10.67


@pytest.mark.asyncio
async def test_consecutive_losses_draw_does_not_reset_streak():
    """Verifies that a DRAW trade does not reset consecutive_losses counter."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = PreTradingPlan(
        assignments=[],
        total_assets=0,
        initial_deposit=Decimal("1000.00"),
        stake_model="flat",
        stake_amount=Decimal("10.00"),
        stake_percent=1.0,
        expiration_seconds=60,
        daily_stop_loss_pct=0.50,
        stop_loss_amount=Decimal("500.00"),
        max_concurrent_trades=3,
        min_payout_rate=0.80,
        max_consecutive_losses=3,
        bar_edge_guard_seconds=0.0,
    )
    gateway = AsyncMock()
    await engine.start(plan, gateway)
    engine.consecutive_losses = 2

    # Settle DRAW trade
    now = datetime.now(UTC)
    trade_draw = LiveTradeRecord(
        trade_id="t_draw",
        asset="EURUSD_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=now - timedelta(seconds=60),
        expiration_seconds=60,
        open_price=Decimal("1.1000"),
        strategy_id="s",
        strategy_name="s",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )
    engine.active_trades["t_draw"] = trade_draw
    candle_draw = Candle(
        open_time=now,
        open=Decimal("1.1000"),
        high=Decimal("1.1005"),
        low=Decimal("1.0995"),
        close=Decimal("1.1000"),  # Close price equals open price -> DRAW
        volume=Decimal("10"),
    )
    gateway.get_candles.return_value = [candle_draw]
    await engine._check_active_trades()

    # Consecutive losses should still be 2
    assert engine.consecutive_losses == 2
    assert engine.status == BotStatus.RUNNING


@pytest.mark.asyncio
async def test_concurrent_global_cooldown_execution_lock():
    """Verifies that concurrent async tasks calling _execute_order serialize under _order_lock."""
    store = MagicMock(spec=TradeStore)
    engine = LiveDemoBotEngine(trade_store=store)
    plan = PreTradingPlan(
        assignments=[
            StrategyAssignment(
                asset="EURUSD_otc",
                strategy_id="s1",
                strategy_name="S1",
                category="c",
                parameters={},
                estimated_win_rate_pct=60,
                estimated_profit_factor=1.5,
                estimated_trades_count=10,
                quantum_score=80,
            ),
            StrategyAssignment(
                asset="NZDUSD_otc",
                strategy_id="s2",
                strategy_name="S2",
                category="c",
                parameters={},
                estimated_win_rate_pct=60,
                estimated_profit_factor=1.5,
                estimated_trades_count=10,
                quantum_score=80,
            ),
        ],
        total_assets=2,
        initial_deposit=Decimal("1000.00"),
        stake_model="flat",
        stake_amount=Decimal("10.00"),
        stake_percent=1.0,
        expiration_seconds=60,
        daily_stop_loss_pct=0.50,
        stop_loss_amount=Decimal("500.00"),
        max_concurrent_trades=5,
        min_payout_rate=0.80,
        global_cooldown_seconds=30,
        bar_edge_guard_seconds=0.0,
    )
    gateway = AsyncMock()
    gateway.open_trade.return_value = ("broker-123", {"percentProfit": 92})
    await engine.start(plan, gateway)

    candles = _make_mock_candles(count=50)

    # Launch 2 simultaneous order executions at the exact same millisecond
    tasks = [
        engine._execute_order(plan.assignments[0], "CALL", 0.8, "test", candles, 0.92),
        engine._execute_order(plan.assignments[1], "CALL", 0.8, "test", candles, 0.92),
    ]
    await asyncio.gather(*tasks)

    # Due to global_cooldown_seconds=30 and _order_lock, only the first order must succeed!
    assert len(engine.active_trades) == 1
    await engine.stop()
