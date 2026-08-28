"""Regression tests for the fixes derived from the 24-28.08 live loss analysis.

Each test pins one measured failure mode so it cannot silently return:

* entries placed on a bar boundary (20% of trades, 97% of the net loss);
* indicators computed on a still-forming candle;
* a substituted strategy silently running on defaults while the trade log
  recorded the assigned strategy's tuned parameters;
* OTC risked at full stake despite a win rate below its break-even;
* spot instruments evaluated on a frozen weekend tape.
"""

from __future__ import annotations

import asyncio
import math
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from strat_trade.api.http_errors import register_domain_exception_handlers
from strat_trade.api.routes.bot import router as bot_router
from strat_trade.domain.entities import Candle
from strat_trade.domain.strategies.registry import split_strategy_params
from strat_trade.domain.trading.asset_filter import (
    is_asset_in_active_session,
    is_otc_asset,
    is_spot_market_closed,
)
from strat_trade.domain.trading.asset_governor import (
    AssetGovernor,
    AssetGovernorConfig,
    AssetTier,
    break_even_win_rate,
    wilson_lower_bound,
    wilson_upper_bound,
)
from strat_trade.domain.trading.bot_engine import LiveDemoBotEngine
from strat_trade.domain.trading.entities import (
    BotStatus,
    IndicatorSnapshot,
    LiveTradeRecord,
    PreTradingPlan,
    StrategyAssignment,
    TradeOutcome,
)
from strat_trade.domain.trading.execution_gates import (
    is_bar_edge_blocked,
    seconds_into_bar,
    select_closed_candles,
)
from strat_trade.domain.trading.trade_store import TradeStore
from strat_trade.use_cases.manage_live_bot import get_bot_engine

MID_BAR = datetime(2026, 8, 26, 14, 30, 30, tzinfo=UTC)  # Wednesday, London/NY open


class _FakeGateway:
    """Minimal broker stand-in for the API round-trip tests."""

    async def get_candles(
        self, asset: str, timeframe: int | str, *, count: int, end_time: datetime | None = None
    ) -> list[Candle]:
        return _tradable_history(datetime.now(UTC), bars=150)[-count:]

    async def get_assets(self) -> list[dict]:
        return [{"symbol": "EURUSD_otc", "name": "EUR/USD OTC", "payout": 92, "is_otc": True}]

    async def open_trade(
        self, asset: str, action: str, amount: float, expiration_seconds: int
    ) -> tuple[str, dict]:
        return "test-order", {"status": "ok"}


def _assignment(asset: str) -> StrategyAssignment:
    return StrategyAssignment(
        asset=asset,
        strategy_id="rsi_stochastic_extreme",
        strategy_name="RSI + Stoch Extreme Scalp",
        category="Scalping Reversal",
        parameters={"rsi_period": 14},
        estimated_win_rate_pct=60.0,
        estimated_profit_factor=1.5,
        estimated_trades_count=40,
        quantum_score=80.0,
    )


def _plan(asset: str, **overrides: object) -> PreTradingPlan:
    defaults: dict[str, object] = {
        "assignments": [_assignment(asset)],
        "total_assets": 1,
        "initial_deposit": Decimal("1000.00"),
        "stake_model": "flat",
        "stake_amount": Decimal("20.00"),
        "stake_percent": 1.0,
        "expiration_seconds": 60,
        "daily_stop_loss_pct": 0.05,
        "stop_loss_amount": Decimal("50.00"),
        "max_concurrent_trades": 3,
        "min_payout_rate": 0.80,
        "cooldown_bars": 0,
        "global_cooldown_seconds": 0,
        "toxic_filter_enabled": False,
        "correlation_filter_enabled": False,
    }
    defaults.update(overrides)
    return PreTradingPlan(**defaults)  # type: ignore[arg-type]


def _tradable_history(end: datetime, bars: int = 100) -> list[Candle]:
    """Candles with enough variation to clear the microstructure filter."""
    start = end.replace(second=0, microsecond=0) - timedelta(minutes=bars - 1)
    out = []
    for i in range(bars):
        price = 1.1000 + math.sin(i / 3.0) * 0.0015 + i * 0.00002
        out.append(
            Candle(
                open_time=start + timedelta(minutes=i),
                open=Decimal(str(round(price - 0.0002, 5))),
                high=Decimal(str(round(price + 0.0004, 5))),
                low=Decimal(str(round(price - 0.0004, 5))),
                close=Decimal(str(round(price, 5))),
                volume=Decimal("100"),
            )
        )
    return out


def _engine_with_signal(asset: str, now: datetime, **plan_overrides: object):
    """Engine primed with a gateway and a strategy that always fires CALL."""
    engine = LiveDemoBotEngine(trade_store=MagicMock())
    engine.plan = _plan(asset, **plan_overrides)
    engine.status = BotStatus.RUNNING

    gateway = AsyncMock()
    gateway.get_asset_payout.return_value = 0.92
    gateway.get_candles.return_value = _tradable_history(now)
    gateway.open_trade.return_value = ("order-1", {"percentProfit": 92})
    engine._gateway = gateway

    signal = MagicMock()
    signal.action.value = "CALL"
    signal.confidence = 0.85
    signal.metadata = {"reason": "test"}
    signal.regime = "ranging"
    strategy = MagicMock()
    strategy.evaluate_candles.return_value = signal
    engine._strategy_instances[asset] = strategy

    return engine, gateway, strategy


def _candle(open_time: datetime, close: float = 1.1) -> Candle:
    return Candle(
        open_time=open_time,
        open=Decimal(str(close)),
        high=Decimal(str(close + 0.001)),
        low=Decimal(str(close - 0.001)),
        close=Decimal(str(close)),
        volume=Decimal("100"),
    )


class TestBarEdgeGate:
    @pytest.mark.parametrize("second", [0, 1, 2])
    def test_blocks_entries_inside_the_guard_window(self, second: int) -> None:
        now = datetime(2026, 8, 28, 12, 30, second, tzinfo=UTC)
        blocked, reason = is_bar_edge_blocked(now, guard_seconds=3.0)
        assert blocked is True
        assert "Bar-edge guard" in reason

    @pytest.mark.parametrize("second", [3, 4, 30, 59])
    def test_allows_entries_once_the_bar_has_settled(self, second: int) -> None:
        now = datetime(2026, 8, 28, 12, 30, second, tzinfo=UTC)
        blocked, _ = is_bar_edge_blocked(now, guard_seconds=3.0)
        assert blocked is False

    def test_zero_guard_disables_the_gate(self) -> None:
        now = datetime(2026, 8, 28, 12, 30, 0, tzinfo=UTC)
        assert is_bar_edge_blocked(now, guard_seconds=0.0)[0] is False

    def test_seconds_into_bar_tracks_sub_second_precision(self) -> None:
        now = datetime(2026, 8, 28, 12, 30, 2, 500_000, tzinfo=UTC)
        assert seconds_into_bar(now) == pytest.approx(2.5)

    def test_naive_datetimes_are_treated_as_utc(self) -> None:
        naive = datetime(2026, 8, 28, 12, 30, 1)
        assert is_bar_edge_blocked(naive, guard_seconds=3.0)[0] is True


class TestClosedBarSelection:
    def test_drops_the_currently_forming_bar(self) -> None:
        base = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
        candles = [_candle(base + timedelta(minutes=i)) for i in range(5)]
        now = base + timedelta(minutes=4, seconds=20)

        closed = select_closed_candles(candles, now)

        assert len(closed) == 4
        assert closed[-1].open_time == base + timedelta(minutes=3)

    def test_keeps_every_bar_when_all_have_completed(self) -> None:
        base = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
        candles = [_candle(base + timedelta(minutes=i)) for i in range(5)]
        now = base + timedelta(minutes=5, seconds=1)

        assert len(select_closed_candles(candles, now)) == 5

    def test_drops_the_last_bar_when_timestamps_are_unavailable(self) -> None:
        class Bare:
            close = 1.1

        candles = [Bare(), Bare(), Bare()]
        assert len(select_closed_candles(candles, datetime.now(UTC))) == 2

    def test_empty_input_is_safe(self) -> None:
        assert select_closed_candles([], datetime.now(UTC)) == []


class TestGovernorStatistics:
    def test_break_even_matches_pocket_option_payouts(self) -> None:
        assert break_even_win_rate(0.92) == pytest.approx(0.5208, abs=1e-4)
        assert break_even_win_rate(0.80) == pytest.approx(0.5556, abs=1e-4)

    def test_wilson_bound_is_conservative_on_small_samples(self) -> None:
        # Same 60% point estimate, but ten trades cannot justify the same confidence.
        assert wilson_lower_bound(6, 10) < wilson_lower_bound(600, 1000)
        assert wilson_lower_bound(600, 1000) < 0.60

    def test_wilson_bound_handles_degenerate_input(self) -> None:
        assert wilson_lower_bound(0, 0) == 0.0
        assert wilson_lower_bound(0, 25) == 0.0
        assert wilson_upper_bound(0, 0) == 1.0

    def test_bounds_bracket_the_point_estimate(self) -> None:
        lower = wilson_lower_bound(45, 100)
        upper = wilson_upper_bound(45, 100)
        assert lower < 0.45 < upper

    def test_upper_bound_is_the_correct_test_for_muting(self) -> None:
        # A 71% win rate over 21 trades must never look like evidence of failure,
        # yet at 95% confidence its lower bound still sits under the 52.08%
        # break-even. Muting on the lower bound would therefore kill good assets.
        assert wilson_lower_bound(15, 21, 1.96) < break_even_win_rate(0.92)
        assert wilson_upper_bound(15, 21, 1.96) > break_even_win_rate(0.92)


class TestAssetGovernor:
    def test_otc_starts_on_probation_with_a_reduced_stake(self) -> None:
        gov = AssetGovernor(AssetGovernorConfig(otc_stake_multiplier=0.25))
        verdict = gov.evaluate("EUR/USD OTC")

        assert verdict.tier is AssetTier.PROBATION
        assert verdict.stake_multiplier == pytest.approx(0.25)
        assert verdict.is_tradable is True

    def test_spot_trades_at_full_stake(self) -> None:
        gov = AssetGovernor()
        verdict = gov.evaluate("EUR/USD")

        assert verdict.tier is AssetTier.NORMAL
        assert verdict.stake_multiplier == pytest.approx(1.0)

    def test_otc_requires_a_higher_payout_floor_than_spot(self) -> None:
        gov = AssetGovernor(
            AssetGovernorConfig(otc_min_payout_rate=0.90, spot_min_payout_rate=0.80)
        )
        assert gov.evaluate("EUR/USD OTC").min_payout_rate == pytest.approx(0.90)
        assert gov.evaluate("EUR/USD").min_payout_rate == pytest.approx(0.80)

    def test_losing_asset_is_muted_once_it_is_statistically_below_break_even(self) -> None:
        gov = AssetGovernor(AssetGovernorConfig(min_trades_for_mute=20))
        now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

        for i in range(20):
            verdict = gov.record_outcome("USD/RUB OTC", is_win=i < 6, payout_rate=0.92, now=now)

        assert verdict.tier is AssetTier.MUTED
        assert verdict.stake_multiplier == 0.0
        assert verdict.is_tradable is False

    def test_asset_is_not_muted_before_the_minimum_sample(self) -> None:
        gov = AssetGovernor(AssetGovernorConfig(min_trades_for_mute=20))
        now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

        for _ in range(10):
            verdict = gov.record_outcome("USD/RUB OTC", is_win=False, payout_rate=0.92, now=now)

        assert verdict.is_tradable is True

    def test_a_winning_asset_survives_the_mute_check(self) -> None:
        gov = AssetGovernor(AssetGovernorConfig(min_trades_for_mute=20))
        now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

        for i in range(40):
            verdict = gov.record_outcome("EUR/USD", is_win=i % 4 != 0, payout_rate=0.92, now=now)

        assert verdict.tier is AssetTier.NORMAL

    @staticmethod
    def _play_45_percent(gov: AssetGovernor, trades: int) -> object:
        """Feeds a repeating 9-win / 11-loss cycle, i.e. exactly 45% win rate."""
        now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
        verdict = gov.evaluate("AUD/CAD OTC", now)
        for i in range(trades):
            verdict = gov.record_outcome(
                "AUD/CAD OTC", is_win=i % 20 < 9, payout_rate=0.92, now=now
            )
        return verdict

    def test_a_marginal_asset_is_not_muted_on_an_inconclusive_sample(self) -> None:
        # 45% is below the 52.08% break-even, but 40 trades cannot prove it.
        gov = AssetGovernor(AssetGovernorConfig(min_trades_for_mute=20))
        verdict = self._play_45_percent(gov, trades=40)

        assert gov.stats_for("AUD/CAD OTC").win_rate == pytest.approx(0.45)
        assert verdict.is_tradable is True

    def test_the_same_marginal_asset_is_muted_once_the_sample_grows(self) -> None:
        gov = AssetGovernor(AssetGovernorConfig(min_trades_for_mute=20))
        verdict = self._play_45_percent(gov, trades=120)

        assert verdict.is_tradable is False

    def test_mute_expiry_starts_a_fresh_measurement_window(self) -> None:
        gov = AssetGovernor(AssetGovernorConfig(min_trades_for_mute=20, mute_duration_minutes=60))
        start = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
        for i in range(20):
            gov.record_outcome("USD/RUB OTC", is_win=i < 6, payout_rate=0.92, now=start)
        assert gov.evaluate("USD/RUB OTC", start).is_tradable is False

        later = start + timedelta(minutes=61)
        verdict = gov.record_outcome("USD/RUB OTC", is_win=True, payout_rate=0.92, now=later)

        assert verdict.is_tradable is True
        assert gov.stats_for("USD/RUB OTC").decided == 1

    def test_repeat_offenders_are_muted_for_longer(self) -> None:
        gov = AssetGovernor(AssetGovernorConfig(min_trades_for_mute=20, mute_duration_minutes=60))
        start = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
        for i in range(20):
            gov.record_outcome("USD/RUB OTC", is_win=i < 6, payout_rate=0.92, now=start)
        first_mute_end = gov.stats_for("USD/RUB OTC").muted_until

        resume = start + timedelta(minutes=61)
        for i in range(20):
            gov.record_outcome("USD/RUB OTC", is_win=i < 6, payout_rate=0.92, now=resume)
        second_mute_end = gov.stats_for("USD/RUB OTC").muted_until

        assert first_mute_end is not None and second_mute_end is not None
        assert (second_mute_end - resume) > (first_mute_end - start)

    def test_sustained_edge_promotes_otc_to_a_larger_stake(self) -> None:
        gov = AssetGovernor(
            AssetGovernorConfig(
                otc_stake_multiplier=0.25, promotion_min_trades=400, min_trades_for_mute=100000
            )
        )
        now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
        for i in range(400):
            verdict = gov.record_outcome(
                "EUR/USD OTC", is_win=i % 5 != 0, payout_rate=0.92, now=now
            )

        assert gov.stats_for("EUR/USD OTC").promoted is True
        assert verdict.stake_multiplier == pytest.approx(0.5)

    def test_draws_never_reach_the_governor_counters(self) -> None:
        gov = AssetGovernor()
        assert gov.stats_for("EUR/USD OTC").decided == 0


class TestSessionAndWeekendGates:
    @pytest.mark.parametrize(
        "asset,expected",
        [
            ("EUR/USD OTC", True),
            ("EURUSD_otc", True),
            ("EUR/USD", False),
            ("", False),
            (None, False),
        ],
    )
    def test_otc_detection(self, asset: str | None, expected: bool) -> None:
        assert is_otc_asset(asset) is expected

    @pytest.mark.parametrize(
        "moment,closed",
        [
            (datetime(2026, 8, 29, 12, 0, tzinfo=UTC), True),  # Saturday
            (datetime(2026, 8, 28, 22, 0, tzinfo=UTC), True),  # Friday after 21:00
            (datetime(2026, 8, 30, 12, 0, tzinfo=UTC), True),  # Sunday morning
            (datetime(2026, 8, 30, 22, 0, tzinfo=UTC), False),  # Sunday reopen
            (datetime(2026, 8, 28, 12, 0, tzinfo=UTC), False),  # Friday session
        ],
    )
    def test_spot_is_closed_across_the_weekend(self, moment: datetime, closed: bool) -> None:
        assert is_spot_market_closed(moment)[0] is closed

    def test_spot_asset_is_rejected_on_saturday(self) -> None:
        saturday = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
        active, reason = is_asset_in_active_session("EUR/USD", saturday)

        assert active is False
        assert "weekend" in reason.lower()

    def test_otc_asset_is_accepted_on_saturday(self) -> None:
        saturday = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
        active, _ = is_asset_in_active_session("EUR/USD OTC", saturday)
        assert active is True

    def test_otc_is_exempt_from_the_london_session_window(self) -> None:
        early = datetime(2026, 8, 26, 3, 0, tzinfo=UTC)  # Wednesday, before London
        assert is_asset_in_active_session("EUR/USD OTC", early)[0] is True
        assert is_asset_in_active_session("EUR/USD", early)[0] is False

    def test_otc_exotics_still_respect_the_nocturnal_dead_zone(self) -> None:
        night = datetime(2026, 8, 29, 2, 0, tzinfo=UTC)  # Saturday night
        active, reason = is_asset_in_active_session("YER/USD OTC", night)

        assert active is False
        assert "dead zone" in reason.lower()


class TestStrategyParameterIntegrity:
    def test_rejected_parameters_are_reported_not_silently_dropped(self) -> None:
        accepted, rejected = split_strategy_params(
            "rsi_stochastic_extreme", {"rsi_period": 9, "supertrend_multiplier": 3.0}
        )

        assert "rsi_period" in accepted
        assert "supertrend_multiplier" in rejected

    def test_matching_parameters_are_fully_accepted(self) -> None:
        accepted, rejected = split_strategy_params("rsi_stochastic_extreme", {"rsi_period": 9})

        assert accepted == {"rsi_period": 9}
        assert rejected == []

    def test_empty_parameters_are_handled(self) -> None:
        assert split_strategy_params("ema_pullback_trend", None) == ({}, [])


class TestTradeStoreForensics:
    def _record(self, **overrides: object) -> LiveTradeRecord:
        base = {
            "trade_id": "t-1",
            "asset": "EUR/USD OTC",
            "action": "CALL",
            "stake": Decimal("5.00"),
            "open_time": datetime(2026, 8, 29, 12, 0, 7, tzinfo=UTC),
            "expiration_seconds": 60,
            "open_price": Decimal("1.10000"),
            "strategy_id": "rsi_stochastic_extreme",
            "strategy_name": "RSI + Stoch Extreme Scalp",
            "strategy_params": {"rsi_period": 14, "supertrend_multiplier": 3.0},
            "indicator_snapshot": IndicatorSnapshot(rsi=22.0, adx=31.5),
            "confidence": 0.72,
            "reason": "oversold",
            "payout_rate": Decimal("0.92"),
            "outcome": TradeOutcome.PENDING,
            "pnl": Decimal("0.00"),
            "executed_params": {"rsi_period": 14},
            "asset_tier": "PROBATION",
            "stake_multiplier": 0.25,
            "entry_second": 7,
            "is_otc": True,
        }
        base.update(overrides)
        return LiveTradeRecord(**base)  # type: ignore[arg-type]

    def test_forensics_columns_survive_a_round_trip(self, tmp_path) -> None:
        store = TradeStore(db_path=tmp_path / "trades.db")
        store.save_trade(self._record())

        loaded = store.get_trade_by_id("t-1")

        assert loaded is not None
        assert loaded.executed_params == {"rsi_period": 14}
        assert loaded.strategy_params != loaded.executed_params
        assert loaded.asset_tier == "PROBATION"
        assert loaded.stake_multiplier == pytest.approx(0.25)
        assert loaded.entry_second == 7
        assert loaded.is_otc is True
        assert loaded.indicator_snapshot.adx == pytest.approx(31.5)

    def test_legacy_database_is_migrated_in_place(self, tmp_path) -> None:
        db_path = tmp_path / "legacy.db"
        legacy_columns = """
            trade_id TEXT PRIMARY KEY, broker_order_id TEXT, asset TEXT NOT NULL,
            action TEXT NOT NULL, stake TEXT NOT NULL, open_time TEXT NOT NULL,
            expiration_seconds INTEGER NOT NULL, open_price TEXT NOT NULL, close_time TEXT,
            close_price TEXT, strategy_id TEXT NOT NULL, strategy_name TEXT NOT NULL,
            strategy_params TEXT NOT NULL, indicator_snapshot TEXT NOT NULL,
            confidence REAL NOT NULL, reason TEXT NOT NULL, payout_rate TEXT NOT NULL,
            outcome TEXT NOT NULL, pnl TEXT NOT NULL, balance_after TEXT,
            is_merged_with_broker INTEGER DEFAULT 0, broker_profit TEXT, slippage TEXT,
            created_at TEXT NOT NULL
        """
        with sqlite3.connect(db_path) as conn:
            conn.execute(f"CREATE TABLE trades ({legacy_columns})")
            conn.commit()

        store = TradeStore(db_path=db_path)
        store.save_trade(self._record(trade_id="t-legacy"))
        loaded = store.get_trade_by_id("t-legacy")

        assert loaded is not None
        assert loaded.asset_tier == "PROBATION"
        assert loaded.entry_second == 7


class TestBotEngineWiring:
    """The gates above are only useful if the engine actually consults them."""

    @pytest.mark.asyncio
    async def test_engine_does_not_even_fetch_candles_on_a_bar_edge(self) -> None:
        edge = MID_BAR.replace(second=1)
        engine, gateway, _ = _engine_with_signal("EUR/USD OTC", edge)

        await engine._evaluate_single_asset(engine.plan.assignments[0], edge, asyncio.Semaphore(1))

        gateway.get_candles.assert_not_called()
        assert engine.active_trades == {}

    @pytest.mark.asyncio
    async def test_engine_hides_the_forming_bar_from_the_strategy(self) -> None:
        engine, gateway, strategy = _engine_with_signal("EUR/USD OTC", MID_BAR)
        full_history = gateway.get_candles.return_value

        await engine._evaluate_single_asset(
            engine.plan.assignments[0], MID_BAR, asyncio.Semaphore(1)
        )

        seen = strategy.evaluate_candles.call_args.args[0]
        assert len(seen) == len(full_history) - 1
        assert seen[-1].open_time == full_history[-2].open_time

    @pytest.mark.asyncio
    async def test_engine_prices_the_order_off_the_live_bar_not_the_closed_one(self) -> None:
        engine, gateway, _ = _engine_with_signal("EUR/USD OTC", MID_BAR)
        live_close = gateway.get_candles.return_value[-1].close

        await engine._evaluate_single_asset(
            engine.plan.assignments[0], MID_BAR, asyncio.Semaphore(1)
        )

        opened = next(iter(engine.active_trades.values()))
        assert opened.open_price == live_close

    @pytest.mark.asyncio
    async def test_engine_haircuts_otc_stake_but_not_spot(self) -> None:
        otc_engine, otc_gateway, _ = _engine_with_signal("EUR/USD OTC", MID_BAR)
        await otc_engine._evaluate_single_asset(
            otc_engine.plan.assignments[0], MID_BAR, asyncio.Semaphore(1)
        )

        spot_engine, spot_gateway, _ = _engine_with_signal("EUR/USD", MID_BAR)
        await spot_engine._evaluate_single_asset(
            spot_engine.plan.assignments[0], MID_BAR, asyncio.Semaphore(1)
        )

        assert otc_gateway.open_trade.call_args.kwargs["amount"] == 5.0
        assert spot_gateway.open_trade.call_args.kwargs["amount"] == 20.0

    @pytest.mark.asyncio
    async def test_engine_rejects_otc_when_the_payout_is_below_its_floor(self) -> None:
        engine, gateway, _ = _engine_with_signal("EUR/USD OTC", MID_BAR)
        # Clears the plan-wide 80% floor but not the 90% OTC floor.
        gateway.get_asset_payout.return_value = 0.85

        await engine._evaluate_single_asset(
            engine.plan.assignments[0], MID_BAR, asyncio.Semaphore(1)
        )

        gateway.open_trade.assert_not_called()

    @pytest.mark.asyncio
    async def test_engine_obeys_a_governor_mute(self) -> None:
        engine, gateway, _ = _engine_with_signal("EUR/USD OTC", MID_BAR)
        engine.asset_governor.stats_for("EUR/USD OTC").muted_until = MID_BAR + timedelta(hours=1)

        await engine._evaluate_single_asset(
            engine.plan.assignments[0], MID_BAR, asyncio.Semaphore(1)
        )

        gateway.get_candles.assert_not_called()

    @pytest.mark.asyncio
    async def test_engine_keeps_the_assigned_strategy_when_switching_is_off(self) -> None:
        engine, _, strategy = _engine_with_signal("EUR/USD OTC", MID_BAR)

        await engine._evaluate_single_asset(
            engine.plan.assignments[0], MID_BAR, asyncio.Semaphore(1)
        )

        strategy.evaluate_candles.assert_called_once()
        assert {sid for _, sid in engine._dynamic_strategy_pool} == {"rsi_stochastic_extreme"}

    @pytest.mark.asyncio
    async def test_engine_records_the_parameters_the_strategy_actually_used(self) -> None:
        engine, _, _ = _engine_with_signal("EUR/USD OTC", MID_BAR)
        engine.plan.assignments[0].parameters = {"rsi_period": 9, "supertrend_multiplier": 3.0}

        await engine._evaluate_single_asset(
            engine.plan.assignments[0], MID_BAR, asyncio.Semaphore(1)
        )

        opened = next(iter(engine.active_trades.values()))
        assert opened.executed_params == {"rsi_period": 9}
        assert "supertrend_multiplier" in opened.strategy_params
        assert opened.entry_second == 30
        assert opened.is_otc is True

    @pytest.mark.asyncio
    async def test_settled_trades_feed_the_governor(self) -> None:
        engine, gateway, _ = _engine_with_signal("EUR/USD OTC", MID_BAR)
        await engine._evaluate_single_asset(
            engine.plan.assignments[0], MID_BAR, asyncio.Semaphore(1)
        )
        opened = next(iter(engine.active_trades.values()))
        opened.open_time = datetime.now(UTC) - timedelta(seconds=120)
        # Settle above the entry so the CALL resolves decisively rather than as a
        # draw, which carries no information and is deliberately not counted.
        gateway.get_candles.return_value = [_candle(MID_BAR, float(opened.open_price) + 0.005)]

        await engine._check_active_trades()

        stats = engine.asset_governor.stats_for("EUR/USD OTC")
        assert stats.decided == 1
        assert stats.wins == 1


class TestGovernanceConfigSurvivesTheApiRoundTrip:
    """The UI posts a config, gets a plan back, then posts that plan to /start.

    If any governance field is dropped by a schema on that path the bot silently
    runs on defaults, which is how the previous settings blacklist became dead
    code in the first place.
    """

    @staticmethod
    def _client() -> TestClient:
        app = FastAPI()
        register_domain_exception_handlers(app)
        app.state.trading_gateway = _FakeGateway()
        app.include_router(bot_router, prefix="/api/v1")
        return TestClient(app)

    def test_custom_governance_settings_reach_the_running_engine(self) -> None:
        client = self._client()
        overrides = {
            "bar_edge_guard_seconds": 5.0,
            "use_closed_bar_only": True,
            "dynamic_strategy_switching_enabled": False,
            "otc_stake_multiplier": 0.1,
            "otc_min_payout_rate": 0.92,
            "governor_min_trades_for_mute": 30,
        }
        res = client.post(
            "/api/v1/bot/auto-assign",
            json={"assets": ["EURUSD_otc"], "initial_deposit": 1000.0, **overrides},
        )
        assert res.status_code == 200
        plan_data = res.json()
        for key, value in overrides.items():
            assert plan_data[key] == value, f"{key} lost in the auto-assign response"

        assert client.post("/api/v1/bot/start", json={"plan": plan_data}).status_code == 200
        try:
            engine = get_bot_engine()
            assert engine.plan is not None
            assert engine.plan.bar_edge_guard_seconds == 5.0
            assert engine.plan.otc_stake_multiplier == 0.1
            assert engine.asset_governor.config.otc_stake_multiplier == 0.1
            assert engine.asset_governor.config.min_trades_for_mute == 30
            assert engine._governor_verdict(
                "EURUSD_otc", datetime.now(UTC)
            ).stake_multiplier == pytest.approx(0.1)
        finally:
            client.post("/api/v1/bot/stop")

    def test_defaults_apply_when_the_client_sends_nothing(self) -> None:
        client = self._client()
        res = client.post(
            "/api/v1/bot/auto-assign", json={"assets": ["EURUSD_otc"], "initial_deposit": 1000.0}
        )

        plan_data = res.json()
        assert plan_data["bar_edge_guard_seconds"] == 3.0
        assert plan_data["use_closed_bar_only"] is True
        assert plan_data["dynamic_strategy_switching_enabled"] is False
        assert plan_data["otc_stake_multiplier"] == 0.25
        assert plan_data["otc_min_payout_rate"] == 0.90
