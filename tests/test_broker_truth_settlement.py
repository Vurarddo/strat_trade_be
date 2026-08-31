"""Regression tests for anchoring trades to the broker instead of to candles.

The 28-29.08 session exposed the failure these pin down: the candle feed serves
only closed bars, so the bot's own open price sat a median of 32 bps (5.8 ATR)
away from the broker's fill. Because the bot then judged WIN/LOSS against that
price, its verdict could disagree with the account, and every guard that learns
from the verdict -- the consecutive-loss breaker, the per-asset degradation
guard, the asset governor -- accumulated wrong statistics. Eighteen trades
opened inside windows where an asset should have been muted, and a run of 11
losses survived a cap of 3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from strat_trade.domain.entities import Candle
from strat_trade.domain.trading.bot_engine import (
    BROKER_SETTLEMENT_GRACE_SECONDS,
    LiveDemoBotEngine,
)
from strat_trade.domain.trading.entities import (
    BotStatus,
    IndicatorSnapshot,
    LiveTradeRecord,
    PreTradingPlan,
    StrategyAssignment,
    TradeOutcome,
)


def _plan(**overrides: object) -> PreTradingPlan:
    defaults: dict[str, object] = {
        "assignments": [
            StrategyAssignment(
                asset="EURUSD_otc",
                strategy_id="rsi_stochastic_extreme",
                strategy_name="RSI + Stoch Extreme Scalp",
                category="Scalping Reversal",
                parameters={"rsi_period": 14},
                estimated_win_rate_pct=60.0,
                estimated_profit_factor=1.5,
                estimated_trades_count=40,
                quantum_score=80.0,
            )
        ],
        "total_assets": 1,
        "initial_deposit": Decimal("1000.00"),
        "stake_model": "flat",
        "stake_amount": Decimal("20.00"),
        "stake_percent": 1.0,
        "expiration_seconds": 180,
        "daily_stop_loss_pct": 0.05,
        "stop_loss_amount": Decimal("500.00"),
        "max_concurrent_trades": 3,
        "min_payout_rate": 0.80,
        "bar_edge_guard_seconds": 0.0,
    }
    defaults.update(overrides)
    return PreTradingPlan(**defaults)  # type: ignore[arg-type]


def _engine() -> tuple[LiveDemoBotEngine, AsyncMock]:
    engine = LiveDemoBotEngine(trade_store=MagicMock())
    engine.plan = _plan()
    engine.status = BotStatus.RUNNING
    gateway = AsyncMock()
    engine._gateway = gateway
    return engine, gateway


def _trade(
    *,
    action: str = "CALL",
    open_price: str = "1.10000",
    age_seconds: int = 190,
    order_id: str | None = "broker-order-1",
) -> LiveTradeRecord:
    return LiveTradeRecord(
        trade_id="t1",
        broker_order_id=order_id,
        asset="EURUSD_otc",
        action=action,
        stake=Decimal("20.00"),
        open_time=datetime.now(UTC) - timedelta(seconds=age_seconds),
        expiration_seconds=180,
        open_price=Decimal(open_price),
        strategy_id="rsi_stochastic_extreme",
        strategy_name="RSI + Stoch Extreme Scalp",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )


def _candle(close: float) -> Candle:
    return Candle(
        open_time=datetime.now(UTC),
        open=Decimal(str(close)),
        high=Decimal(str(close + 0.001)),
        low=Decimal(str(close - 0.001)),
        close=Decimal(str(close)),
        volume=Decimal("100"),
    )


class TestOpenPriceComesFromTheBroker:
    @pytest.mark.asyncio
    async def test_entry_price_in_the_open_response_wins(self) -> None:
        engine, _ = _engine()
        price = await engine._broker_fill_price("o1", {"entry_price": "1.23456"})
        assert price == Decimal("1.23456")

    @pytest.mark.asyncio
    async def test_falls_back_to_querying_the_deal(self) -> None:
        engine, gateway = _engine()
        gateway.get_deal_entry_price.return_value = Decimal("1.30000")

        price = await engine._broker_fill_price("o1", {"status": "ok"})

        assert price == Decimal("1.30000")
        gateway.get_deal_entry_price.assert_awaited_once_with("o1")

    @pytest.mark.asyncio
    async def test_a_nonsense_answer_is_refused(self) -> None:
        engine, gateway = _engine()
        gateway.get_deal_entry_price.return_value = object()

        assert await engine._broker_fill_price("o1", {"entry_price": "not-a-price"}) is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [0, -1.5, None, True])
    async def test_non_positive_prices_are_refused(self, bad: object) -> None:
        engine, gateway = _engine()
        gateway.get_deal_entry_price.return_value = None

        assert await engine._broker_fill_price("o1", {"entry_price": bad}) is None


class TestSettlementUsesTheBrokerVerdict:
    @pytest.mark.asyncio
    async def test_broker_loss_overrides_a_candle_that_says_win(self) -> None:
        """The exact disagreement that corrupted every guard on 28-29.08."""
        engine, gateway = _engine()
        engine.active_trades["t1"] = _trade(action="CALL", open_price="1.10000")
        # Candles say the CALL finished well above entry, i.e. a win.
        gateway.get_candles.return_value = [_candle(1.10500)]
        # The broker, settling against its own fill, says it lost.
        gateway.get_trade_result.return_value = {
            "result": "loss",
            "profit": Decimal("-20.00"),
            "close_price": Decimal("1.09900"),
        }

        await engine._check_active_trades()

        settled = engine.recent_trades[0]
        assert settled.outcome == TradeOutcome.LOSS
        assert settled.pnl == Decimal("-20.00")
        assert settled.close_price == Decimal("1.09900")
        assert settled.settlement_source == "broker"
        assert engine.consecutive_losses == 1

    @pytest.mark.asyncio
    async def test_broker_profit_is_used_verbatim(self) -> None:
        engine, gateway = _engine()
        engine.active_trades["t1"] = _trade()
        gateway.get_candles.return_value = [_candle(1.10500)]
        gateway.get_trade_result.return_value = {
            "result": "win",
            "profit": Decimal("16.40"),  # a real 82% payout, not the assumed 92%
            "close_price": Decimal("1.10500"),
        }

        await engine._check_active_trades()

        assert engine.recent_trades[0].pnl == Decimal("16.40")
        assert engine.current_balance == Decimal("1016.40")

    @pytest.mark.asyncio
    async def test_missing_profit_falls_back_to_the_modelled_payout(self) -> None:
        engine, gateway = _engine()
        engine.active_trades["t1"] = _trade()
        gateway.get_candles.return_value = [_candle(1.10500)]
        gateway.get_trade_result.return_value = {"result": "win", "profit": None}

        await engine._check_active_trades()

        assert engine.recent_trades[0].pnl == Decimal("20.00") * Decimal("0.92")

    @pytest.mark.asyncio
    async def test_draws_are_settled_flat(self) -> None:
        engine, gateway = _engine()
        engine.active_trades["t1"] = _trade()
        gateway.get_candles.return_value = [_candle(1.10500)]
        gateway.get_trade_result.return_value = {"result": "draw", "profit": None}

        await engine._check_active_trades()

        assert engine.recent_trades[0].outcome == TradeOutcome.DRAW
        assert engine.recent_trades[0].pnl == Decimal("0.00")


class TestFallbackWhenTheBrokerIsSilent:
    @pytest.mark.asyncio
    async def test_waits_out_the_grace_window_instead_of_using_a_stale_candle(self) -> None:
        engine, gateway = _engine()
        # Just past expiry, so the broker has barely had a chance to answer.
        engine.active_trades["t1"] = _trade(age_seconds=182)
        gateway.get_candles.return_value = [_candle(1.10500)]
        gateway.get_trade_result.return_value = None

        await engine._check_active_trades()

        assert "t1" in engine.active_trades
        assert engine.active_trades["t1"].outcome == TradeOutcome.PENDING

    @pytest.mark.asyncio
    async def test_settles_from_candles_once_the_grace_window_lapses(self) -> None:
        engine, gateway = _engine()
        engine.active_trades["t1"] = _trade(age_seconds=180 + BROKER_SETTLEMENT_GRACE_SECONDS + 5)
        gateway.get_candles.return_value = [_candle(1.10500)]
        gateway.get_trade_result.return_value = None

        await engine._check_active_trades()

        settled = engine.recent_trades[0]
        assert settled.outcome == TradeOutcome.WIN
        assert settled.settlement_source == "candle"

    @pytest.mark.asyncio
    async def test_a_paper_order_settles_immediately_without_waiting(self) -> None:
        engine, gateway = _engine()
        engine.active_trades["t1"] = _trade(age_seconds=182, order_id="demo-abc123")
        gateway.get_candles.return_value = [_candle(1.10500)]

        await engine._check_active_trades()

        assert engine.recent_trades[0].settlement_source == "candle"
        gateway.get_trade_result.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_unrecognised_verdict_is_not_trusted(self) -> None:
        engine, gateway = _engine()
        engine.active_trades["t1"] = _trade(age_seconds=182)
        gateway.get_trade_result.return_value = {"result": "pending"}
        gateway.get_candles.return_value = [_candle(1.10500)]

        await engine._check_active_trades()

        assert "t1" in engine.active_trades

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("action", "close", "expected"),
        [
            ("CALL", 1.10500, TradeOutcome.WIN),
            ("CALL", 1.09500, TradeOutcome.LOSS),
            ("PUT", 1.09500, TradeOutcome.WIN),
            ("PUT", 1.10500, TradeOutcome.LOSS),
            ("CALL", 1.10000, TradeOutcome.DRAW),
            ("PUT", 1.10000, TradeOutcome.DRAW),
        ],
    )
    async def test_candle_fallback_matrix(
        self, action: str, close: float, expected: TradeOutcome
    ) -> None:
        engine, gateway = _engine()
        trade = _trade(action=action, open_price="1.10000")
        gateway.get_candles.return_value = [_candle(close)]

        outcome, _, close_price = await engine._settle_from_candles(trade)

        assert outcome is expected
        assert close_price == Decimal(str(close))


class TestSnapshotMatchesTheStrategy:
    def test_logged_rsi_uses_the_strategy_period_and_smoothing(self) -> None:
        """A 14-period simple average made 12 of 32 logged entries look invalid."""
        import pandas as pd
        import ta

        engine, _ = _engine()
        closes = [1.10 + (i % 7) * 0.0004 - (i % 3) * 0.0002 for i in range(60)]
        candles = [
            Candle(
                open_time=datetime.now(UTC) - timedelta(minutes=60 - i),
                open=Decimal(str(round(c - 0.0001, 5))),
                high=Decimal(str(round(c + 0.0003, 5))),
                low=Decimal(str(round(c - 0.0003, 5))),
                close=Decimal(str(round(c, 5))),
                volume=Decimal("100"),
            )
            for i, c in enumerate(closes)
        ]

        snapshot = engine._extract_snapshot(candles, rsi_period=9)

        expected = float(
            ta.momentum.RSIIndicator(close=pd.Series([float(c.close) for c in candles]), window=9)
            .rsi()
            .iloc[-1]
        )
        assert snapshot.rsi == pytest.approx(expected)

    def test_a_different_period_yields_a_different_number(self) -> None:
        engine, _ = _engine()
        closes = [1.10 + (i % 7) * 0.0004 - (i % 3) * 0.0002 for i in range(60)]
        candles = [
            Candle(
                open_time=datetime.now(UTC) - timedelta(minutes=60 - i),
                open=Decimal(str(round(c - 0.0001, 5))),
                high=Decimal(str(round(c + 0.0003, 5))),
                low=Decimal(str(round(c - 0.0003, 5))),
                close=Decimal(str(round(c, 5))),
                volume=Decimal("100"),
            )
            for i, c in enumerate(closes)
        ]

        assert engine._extract_snapshot(candles, 9).rsi != engine._extract_snapshot(candles, 14).rsi
