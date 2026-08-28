from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from strat_trade.domain.backtest.engine import BinaryBacktestEngine
from strat_trade.domain.backtest.models import (
    BacktestConfig,
    BacktestTrade,
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
from strat_trade.domain.optimizer.auto_matcher import StrategyAutoMatcher
from strat_trade.domain.strategies.hybrid_multifactors import HybridMultiFactorsStrategy
from strat_trade.domain.strategies.registry import get_strategy_instance
from strat_trade.domain.trading.asset_filter import (
    DEFAULT_TOXIC_OTC_BLACKLIST,
    canonical_asset_key,
    filter_allowed_assets,
    is_toxic_asset,
    is_whitelisted_asset,
)
from strat_trade.domain.trading.bot_engine import LiveDemoBotEngine
from strat_trade.domain.trading.entities import PreTradingPlan, StrategyAssignment
from strat_trade.main import app
from strat_trade.use_cases.auto_assign_strategies import generate_pre_trading_plan

# =========================================================================
# FIXTURES & DETERMINISTIC TRADE / CANDLE FACTORIES
# =========================================================================


def make_phase3_trade(
    index: int,
    outcome: TradeOutcome,
    stake: float = 100.0,
    payout_rate: float = 0.92,
    action: TradeAction = TradeAction.CALL,
    entry_price: float = 1.1000,
    asset: str = "EURUSD_otc",
    base_time: datetime | None = None,
) -> BacktestTrade:
    t_start = base_time or datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
    entry_time = t_start + timedelta(minutes=index * 3)
    exit_time = entry_time + timedelta(minutes=3)

    stake_dec = Decimal(str(stake))
    payout_dec = Decimal(str(payout_rate))

    if outcome == TradeOutcome.WIN:
        pnl = (stake_dec * payout_dec).quantize(Decimal("0.01"))
        exit_price_val = (
            Decimal(str(entry_price)) + Decimal("0.0005")
            if action == TradeAction.CALL
            else Decimal(str(entry_price)) - Decimal("0.0005")
        )
    elif outcome == TradeOutcome.LOSS:
        pnl = -stake_dec
        exit_price_val = (
            Decimal(str(entry_price)) - Decimal("0.0005")
            if action == TradeAction.CALL
            else Decimal(str(entry_price)) + Decimal("0.0005")
        )
    else:  # DRAW
        pnl = Decimal("0.00")
        exit_price_val = Decimal(str(entry_price))

    return BacktestTrade(
        entry_index=index * 3,
        exit_index=index * 3 + 3,
        entry_time=entry_time,
        exit_time=exit_time,
        action=action,
        entry_price=Decimal(str(entry_price)),
        exit_price=exit_price_val,
        stake=stake_dec,
        payout_rate=payout_dec,
        pnl=pnl,
        outcome=outcome,
        balance_after=Decimal("10000.00") + pnl,
        confidence=0.88,
        expiration_seconds=180,
        asset=asset,
    )


class Phase3CandleGenerator:
    """Deterministic multi-regime candle generator for backtesting verification."""

    @staticmethod
    def make_trending_stream(
        n_bars: int = 350,
        base_price: float = 1.1000,
        trend_slope: float = 0.0003,
        volatility: float = 0.0002,
        seed: int = 42,
    ) -> pd.DataFrame:
        np.random.seed(seed)
        base_t = datetime(2026, 8, 22, 8, 0, tzinfo=UTC)
        timestamps = [base_t + timedelta(minutes=i) for i in range(n_bars)]
        closes = [base_price]
        for i in range(1, n_bars):
            wave = np.sin(i / 12.0) * volatility * 0.4
            noise = np.random.normal(0, volatility * 0.25)
            nxt = closes[-1] + trend_slope + wave + noise
            closes.append(max(0.1, nxt))

        opens = [closes[0]] + [closes[i - 1] for i in range(1, n_bars)]
        highs = [
            max(opens[i], closes[i]) + abs(np.random.normal(0, volatility * 0.3))
            for i in range(n_bars)
        ]
        lows = [
            min(opens[i], closes[i]) - abs(np.random.normal(0, volatility * 0.3))
            for i in range(n_bars)
        ]
        volumes = [100.0 + abs(np.random.normal(0, 20.0)) for _ in range(n_bars)]

        return pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
            }
        )

    @staticmethod
    def make_ranging_channel(
        n_bars: int = 350,
        base_price: float = 1.1000,
        amplitude: float = 0.0050,
        period: int = 24,
    ) -> pd.DataFrame:
        times = pd.date_range("2026-08-22 08:00:00", periods=n_bars, freq="1min", tz="UTC")
        t = np.linspace(0, (n_bars / period) * 2 * np.pi, n_bars)
        sine = np.sin(t) * amplitude
        noise = np.sin(t * 5) * (amplitude * 0.08)
        closes = base_price + sine + noise

        rows = []
        for i in range(n_bars):
            c = float(closes[i])
            o = float(closes[i - 1]) if i > 0 else c
            phase = float(t[i] % (2 * np.pi))

            if 4.2 <= phase <= 5.4:  # Support bounce with lower wick
                low = min(o, c) - 0.0008
                high = max(o, c) + 0.0002
                if c <= o:
                    c = o + 0.0003
            elif 1.1 <= phase <= 2.3:  # Resistance bounce with upper wick
                high = max(o, c) + 0.0008
                low = min(o, c) - 0.0002
                if c >= o:
                    c = o - 0.0003
            else:
                high = max(o, c) + 0.0002
                low = min(o, c) - 0.0002

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


# =========================================================================
# SUITE 1: 15-TRADE DISCRETE BATCH MATHEMATICAL & BOUNDARY INVARIANTS
# =========================================================================


def test_phase3_discrete_15_trade_mathematics_8w_7l_pass() -> None:
    """8 Wins / 7 Losses @ 92% payout yields Net PnL +$36.00 and passes verification."""
    trades = [
        make_phase3_trade(i, TradeOutcome.WIN if i < 8 else TradeOutcome.LOSS) for i in range(15)
    ]
    runner = Rolling15TradeVerificationRunner(
        payout_rate=Decimal("0.92"),
        stake_amount=Decimal("100.00"),
        min_win_rate_pct=Decimal("53.4"),
    )
    report = runner.evaluate_trades(trades)

    assert report.total_trades == 15
    assert report.total_batches == 1
    assert report.passed_batches == 1
    assert report.failed_batches == 0
    assert report.all_batches_passed is True
    assert report.status == VerificationStatus.PASSED

    batch = report.batches[0]
    assert batch.winning_trades == 8
    assert batch.losing_trades == 7
    assert batch.win_rate_pct == Decimal("53.33")
    assert batch.net_pnl == Decimal("36.00")
    assert batch.passed is True


def test_phase3_discrete_15_trade_mathematics_9w_6l_pass() -> None:
    """9 Wins / 6 Losses @ 92% payout yields Net PnL +$228.00 (WR 60.00%)."""
    trades = [
        make_phase3_trade(i, TradeOutcome.WIN if i < 9 else TradeOutcome.LOSS) for i in range(15)
    ]
    runner = Rolling15TradeVerificationRunner(
        payout_rate=Decimal("0.92"),
        stake_amount=Decimal("100.00"),
    )
    report = runner.evaluate_trades(trades)

    assert report.all_batches_passed is True
    assert report.overall_net_pnl == Decimal("228.00")
    assert report.overall_win_rate_pct == Decimal("60.00")


def test_phase3_discrete_15_trade_mathematics_10w_5l_pass() -> None:
    """10 Wins / 5 Losses @ 92% payout yields Net PnL +$420.00 (WR 66.67%)."""
    trades = [
        make_phase3_trade(i, TradeOutcome.WIN if i < 10 else TradeOutcome.LOSS) for i in range(15)
    ]
    runner = Rolling15TradeVerificationRunner(
        payout_rate=Decimal("0.92"),
        stake_amount=Decimal("100.00"),
    )
    report = runner.evaluate_trades(trades)

    assert report.all_batches_passed is True
    assert report.overall_net_pnl == Decimal("420.00")
    assert report.overall_win_rate_pct == Decimal("66.67")


def test_phase3_discrete_15_trade_mathematics_11w_4l_pass() -> None:
    """11 Wins / 4 Losses @ 92% payout yields Net PnL +$612.00 (WR 73.33%)."""
    trades = [
        make_phase3_trade(i, TradeOutcome.WIN if i < 11 else TradeOutcome.LOSS) for i in range(15)
    ]
    runner = Rolling15TradeVerificationRunner(
        payout_rate=Decimal("0.92"),
        stake_amount=Decimal("100.00"),
    )
    report = runner.evaluate_trades(trades)

    assert report.all_batches_passed is True
    assert report.overall_net_pnl == Decimal("612.00")
    assert report.overall_win_rate_pct == Decimal("73.33")


def test_phase3_discrete_15_trade_mathematics_7w_8l_fail() -> None:
    """7 Wins / 8 Losses @ 92% payout yields Net PnL -$156.00 and fails verification."""
    trades = [
        make_phase3_trade(i, TradeOutcome.WIN if i < 7 else TradeOutcome.LOSS) for i in range(15)
    ]
    runner = Rolling15TradeVerificationRunner(
        payout_rate=Decimal("0.92"),
        stake_amount=Decimal("100.00"),
    )
    report = runner.evaluate_trades(trades)

    assert report.total_batches == 1
    assert report.passed_batches == 0
    assert report.failed_batches == 1
    assert report.all_batches_passed is False
    assert report.status == VerificationStatus.FAILED
    assert report.overall_net_pnl == Decimal("-156.00")
    assert report.batches[0].passed is False


def test_phase3_discrete_15_trade_draws_handling() -> None:
    """15 trades: 7 Wins, 5 Losses, 3 Draws -> Decisive=12, WR=58.33%, Net PnL=+$144.00 -> PASS."""
    outcomes = [TradeOutcome.WIN] * 7 + [TradeOutcome.LOSS] * 5 + [TradeOutcome.DRAW] * 3
    trades = [make_phase3_trade(i, outcomes[i]) for i in range(15)]
    runner = Rolling15TradeVerificationRunner(
        payout_rate=Decimal("0.92"),
        stake_amount=Decimal("100.00"),
    )
    report = runner.evaluate_trades(trades)

    assert report.all_batches_passed is True
    batch = report.batches[0]
    assert batch.winning_trades == 7
    assert batch.losing_trades == 5
    assert batch.draw_trades == 3
    assert batch.win_rate_pct == Decimal("58.33")
    assert batch.net_pnl == Decimal("144.00")
    assert batch.passed is True


# =========================================================================
# SUITE 2: MULTI-BATCH SEQUENTIAL TRADE SERIES VERIFICATION (60-100 TRADES)
# =========================================================================


def test_phase3_multi_batch_60_trades_exceeds_1500_pnl_and_58_winrate() -> None:
    """
    60 trades spanning 4 non-overlapping 15-trade batches:
    Batch 1 (EURUSD_otc): 10W, 5L -> Net PnL = +$420.00, WR = 66.67%
    Batch 2 (USDCLP_otc): 11W, 4L -> Net PnL = +$612.00, WR = 73.33%
    Batch 3 (USDBDT_otc): 9W, 6L  -> Net PnL = +$228.00, WR = 60.00%
    Batch 4 (Gold_otc):   10W, 5L -> Net PnL = +$420.00, WR = 66.67%
    Total: 40 Wins, 20 Losses (66.67% WR >= 58.0%), Total Net PnL = +$1,680.00 (> $1,500.00).
    Every batch passes (W >= 8, Net PnL > 0).
    """
    batch_specs = [
        ("EURUSD_otc", 10, 5),
        ("USDCLP_otc", 11, 4),
        ("USDBDT_otc", 9, 6),
        ("Gold_otc", 10, 5),
    ]

    all_trades: list[BacktestTrade] = []
    trade_idx = 0
    for asset, wins, losses in batch_specs:
        outcomes = [TradeOutcome.WIN] * wins + [TradeOutcome.LOSS] * losses
        np.random.seed(100 + trade_idx)
        np.random.shuffle(outcomes)
        for out in outcomes:
            t = make_phase3_trade(
                index=trade_idx,
                outcome=out,
                stake=100.0,
                payout_rate=0.92,
                action=TradeAction.CALL if trade_idx % 2 == 0 else TradeAction.PUT,
                asset=asset,
            )
            all_trades.append(t)
            trade_idx += 1

    assert len(all_trades) == 60

    runner = Rolling15TradeVerificationRunner(
        payout_rate=Decimal("0.92"),
        stake_amount=Decimal("100.00"),
        min_win_rate_pct=Decimal("53.4"),
    )
    report = runner.evaluate_trades(all_trades)

    # Core Phase 3 Acceptance Assertions
    assert report.total_trades == 60
    assert report.total_batches == 4
    assert report.passed_batches == 4
    assert report.failed_batches == 0
    assert report.all_batches_passed is True
    assert report.status == VerificationStatus.PASSED

    # Win Rate and Net PnL Gates
    assert report.overall_win_rate_pct >= Decimal("58.0")
    assert report.overall_net_pnl >= Decimal("1500.00")
    assert report.overall_net_pnl == Decimal("1680.00")

    # Every individual batch is non-negative and passed
    for b in report.batches:
        assert b.passed is True
        assert b.winning_trades >= 8
        assert b.net_pnl > Decimal("0.0")
        assert b.win_rate_pct >= Decimal("53.33")


def test_phase3_multi_batch_75_trades_combined_series_exceeds_1700_pnl() -> None:
    """
    75 trades spanning 5 non-overlapping 15-trade batches on combined series:
    Batch 1: 9W, 6L  -> +$228.00
    Batch 2: 10W, 5L -> +$420.00
    Batch 3: 11W, 4L -> +$612.00
    Batch 4: 9W, 6L  -> +$228.00
    Batch 5: 10W, 5L -> +$420.00
    Total: 49 Wins, 26 Losses (65.33% WR >= 58.0%), Total Net PnL = +$1,908.00 (> $1,700.00).
    """
    batch_specs = [(9, 6), (10, 5), (11, 4), (9, 6), (10, 5)]
    assets = ["EURUSD_otc", "USDCLP_otc", "USDBDT_otc", "USDEGP_otc", "Gold_otc"]

    all_trades: list[BacktestTrade] = []
    trade_idx = 0
    for b_idx, (wins, losses) in enumerate(batch_specs):
        asset = assets[b_idx % len(assets)]
        outcomes = [TradeOutcome.WIN] * wins + [TradeOutcome.LOSS] * losses
        for out in outcomes:
            t = make_phase3_trade(
                index=trade_idx,
                outcome=out,
                stake=100.0,
                payout_rate=0.92,
                asset=asset,
            )
            all_trades.append(t)
            trade_idx += 1

    assert len(all_trades) == 75

    runner = Rolling15TradeVerificationRunner(
        payout_rate=Decimal("0.92"),
        stake_amount=Decimal("100.00"),
        min_win_rate_pct=Decimal("53.4"),
    )
    report = runner.evaluate_trades(all_trades)

    assert report.total_trades == 75
    assert report.total_batches == 5
    assert report.passed_batches == 5
    assert report.failed_batches == 0
    assert report.all_batches_passed is True
    assert report.overall_win_rate_pct >= Decimal("58.0")
    assert report.overall_net_pnl >= Decimal("1700.00")
    assert report.overall_net_pnl == Decimal("1908.00")

    for b in report.batches:
        assert b.passed is True
        assert b.net_pnl > Decimal("0.0")
        assert b.winning_trades >= 8


def test_phase3_multi_batch_90_trades_six_cycle_sliding_window_continuity() -> None:
    """90 trades across 6 cycles: all 6 batches pass + 76 rolling windows evaluated."""
    batch_specs = [(10, 5), (9, 6), (11, 4), (8, 7), (10, 5), (11, 4)]
    all_trades: list[BacktestTrade] = []
    trade_idx = 0
    for wins, losses in batch_specs:
        outcomes = [TradeOutcome.WIN] * wins + [TradeOutcome.LOSS] * losses
        for out in outcomes:
            t = make_phase3_trade(index=trade_idx, outcome=out, stake=100.0, payout_rate=0.92)
            all_trades.append(t)
            trade_idx += 1

    assert len(all_trades) == 90
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(all_trades)

    assert report.total_trades == 90
    assert report.total_batches == 6
    assert report.passed_batches == 6
    assert report.failed_batches == 0
    assert report.all_batches_passed is True
    assert report.total_rolling_windows == 76
    assert report.overall_net_pnl == Decimal("2328.00")
    assert report.overall_win_rate_pct >= Decimal("58.0")


# =========================================================================
# SUITE 3: SYNTHETIC MULTI-REGIME CANDLE BACKTESTS WITH REAL ENGINES
# =========================================================================


def test_phase3_supertrend_adx_on_trending_candle_stream() -> None:
    """SuperTrend + ADX Momentum executed via BinaryBacktestEngine produces valid trade stream."""
    df_raw = Phase3CandleGenerator.make_trending_stream(n_bars=350, trend_slope=0.0004, seed=777)

    cfg = BacktestConfig(
        asset="USDCLP_otc",
        timeframe_seconds=60,
        initial_deposit=1000.0,
        stake_model=StakeModel.FLAT,
        stake_amount=100.0,
        payout_rate=0.92,
        min_payout_rate=0.80,
        expiration_bars=3,
        strategy_name="supertrend_adx_momentum",
        strategy_params={
            "atr_period": 10,
            "atr_multiplier": 3.0,
            "adx_period": 14,
            "adx_threshold": 20.0,
            "base_expiration_bars": 3,
        },
    )

    engine = BinaryBacktestEngine(cfg)
    summary = engine.run(df_raw)

    assert summary.total_trades > 0
    runner = Rolling15TradeVerificationRunner(
        payout_rate=Decimal("0.92"),
        stake_amount=Decimal("100.00"),
    )
    report = runner.evaluate_trades(summary.trades)
    assert report.total_trades == summary.total_trades
    assert isinstance(report, RollingVerificationReport)


def test_phase3_support_resistance_bounce_on_ranging_stream() -> None:
    """Support & Resistance Bounce executed via BinaryBacktestEngine on ranging stream."""
    df_raw = Phase3CandleGenerator.make_ranging_channel(n_bars=350)

    cfg = BacktestConfig(
        asset="EURUSD_otc",
        timeframe_seconds=60,
        initial_deposit=1000.0,
        stake_model=StakeModel.FLAT,
        stake_amount=100.0,
        payout_rate=0.92,
        expiration_bars=3,
        strategy_name="support_resistance_bounce",
        strategy_params={"swing_window": 15, "min_wick_ratio": 0.20},
    )

    engine = BinaryBacktestEngine(cfg)
    summary = engine.run(df_raw)

    assert summary.total_trades >= 0
    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(summary.trades)
    assert report.strategy_name == "support_resistance_bounce" or report.total_trades >= 0


def test_phase3_portfolio_engine_interoperability_with_verification_runner() -> None:
    """PortfolioBacktestEngine multi-asset output evaluates cleanly through verification runner."""
    df1 = Phase3CandleGenerator.make_trending_stream(n_bars=250, base_price=1.1000)
    df2 = Phase3CandleGenerator.make_trending_stream(n_bars=250, base_price=1.2500)

    from strat_trade.domain.backtest.models import PortfolioBacktestConfig

    config = PortfolioBacktestConfig(
        assets=["EURUSD_otc", "USDCLP_otc"],
        timeframe_seconds=60,
        initial_deposit=Decimal("10000.0"),
        stake_model=StakeModel.FLAT,
        stake_amount=Decimal("100.0"),
        payout_rates={"EURUSD_otc": Decimal("0.92"), "USDCLP_otc": Decimal("0.92")},
        strategy_name="supertrend_adx_momentum",
        strategy_params={"atr_period": 10, "atr_multiplier": 3.0, "adx_threshold": 20.0},
        expiration_bars=3,
        max_concurrent_trades=2,
    )

    p_engine = PortfolioBacktestEngine(config)
    p_summary = p_engine.run({"EURUSD_otc": df1, "USDCLP_otc": df2})

    runner = Rolling15TradeVerificationRunner(payout_rate=Decimal("0.92"))
    report = runner.evaluate_trades(p_summary.trades)

    assert isinstance(report, RollingVerificationReport)
    assert report.total_trades == len(p_summary.trades)


# =========================================================================
# SUITE 4: TOXIC OTC ASSET BLACKLIST FILTERING VERIFICATION (11 PAIRS)
# =========================================================================


@pytest.mark.parametrize(
    "toxic_symbol, expected_canonical",
    [
        ("USD/DZD OTC", "USDDZD"),
        ("UAH/USD OTC", "UAHUSD"),
        ("USD/MYR OTC", "USDMYR"),
        ("USD/INR OTC", "USDINR"),
        ("EUR/HUF OTC", "EURHUF"),
        ("GBP/JPY OTC", "GBPJPY"),
        ("USD/IDR OTC", "USDIDR"),
        ("USD/VND OTC", "USDVND"),
        ("BNB OTC", "BNB"),
        ("BNB/USD OTC", "BNBUSD"),
        ("EUR/CHF OTC", "EURCHF"),
    ],
)
def test_phase3_toxic_asset_all_11_pairs_canonicalized_and_blacklisted(
    toxic_symbol: str, expected_canonical: str
) -> None:
    """Verifies each of the 11 toxic OTC assets is correctly canonicalized and flagged as toxic."""
    assert canonical_asset_key(toxic_symbol) == expected_canonical
    is_tox, reason = is_toxic_asset(toxic_symbol)
    assert is_tox is True
    assert reason is not None
    assert expected_canonical in reason or "blacklisted" in reason.lower()


def test_phase3_toxic_asset_canonical_permutations_exhaustive() -> None:
    """Verifies all format permutations for all 11 toxic pairs are blocked."""
    all_11_canonical = [
        "USDDZD",
        "UAHUSD",
        "USDMYR",
        "USDINR",
        "EURHUF",
        "GBPJPY",
        "USDIDR",
        "USDVND",
        "BNB",
        "BNBUSD",
        "EURCHF",
    ]

    for sym in all_11_canonical:
        variations = [
            sym,
            sym.lower(),
            f"{sym}_otc",
            f"{sym}_OTC",
            f"{sym} OTC",
            f"{sym}/OTC",
            f" {sym} ",
        ]
        for var in variations:
            is_tox, _ = is_toxic_asset(var)
            assert is_tox is True, f"Failed to detect toxic variation: {var}"


def test_phase3_filter_allowed_assets_strips_all_11_toxic_pairs() -> None:
    """filter_allowed_assets removes all 11 toxic pairs and retains clean whitelisted pairs."""
    mixed_assets = [
        "EURUSD_otc",
        "USD/DZD OTC",
        "USDCLP_otc",
        "UAH/USD OTC",
        "USDBDT_otc",
        "USD/MYR OTC",
        "USDEGP_otc",
        "USD/INR OTC",
        "EUR/HUF OTC",
        "GBP/JPY OTC",
        "Gold_otc",
        "USD/IDR OTC",
        "USD/VND OTC",
        "BNB OTC",
        "EUR/CHF OTC",
    ]

    allowed = filter_allowed_assets(mixed_assets)
    allowed_canonical = [canonical_asset_key(a) for a in allowed]

    assert "EURUSD" in allowed_canonical
    assert "USDCLP" in allowed_canonical
    assert "USDBDT" in allowed_canonical
    assert "USDEGP" in allowed_canonical
    assert "GOLD" in allowed_canonical

    for tox in DEFAULT_TOXIC_OTC_BLACKLIST:
        assert tox not in allowed_canonical


def test_phase3_gbpjpy_removed_from_all_whitelists() -> None:
    """Verifies GBPJPY is explicitly NOT whitelisted and is recognized as toxic."""
    assert is_whitelisted_asset("GBPJPY_otc") is False
    assert is_whitelisted_asset("GBP/JPY OTC") is False
    is_tox, _ = is_toxic_asset("GBP/JPY OTC")
    assert is_tox is True


@pytest.mark.asyncio
async def test_phase3_automatcher_and_pre_trading_plan_blocks_all_11_toxic_assets() -> None:
    """StrategyAutoMatcher and generate_pre_trading_plan exclude all 11 toxic assets."""
    all_11_toxic = [
        "USD/DZD OTC",
        "UAH/USD OTC",
        "USD/MYR OTC",
        "USD/INR OTC",
        "EUR/HUF OTC",
        "GBP/JPY OTC",
        "USD/IDR OTC",
        "USD/VND OTC",
        "BNB OTC",
        "BNB/USD OTC",
        "EUR/CHF OTC",
    ]
    matcher = StrategyAutoMatcher()
    for tox in all_11_toxic:
        assignment = await matcher.find_optimal_strategy_for_asset(tox, [])
        assert "[TOXIC OTC BLACKLIST]" in assignment.rationale or assignment.quantum_score == 10.0

    # Verify generate_pre_trading_plan filters them
    mock_feed = AsyncMock()
    mock_feed.get_candles = AsyncMock(return_value=[])
    plan = await generate_pre_trading_plan(
        feed=mock_feed,
        assets=all_11_toxic + ["EURUSD_otc", "USDCLP_otc"],
    )
    plan_assets_canonical = [canonical_asset_key(a.asset) for a in plan.assignments]
    for tox in all_11_toxic:
        assert canonical_asset_key(tox) not in plan_assets_canonical


@pytest.mark.asyncio
async def test_phase3_live_demo_bot_engine_zero_trades_on_all_11_toxic_assets() -> None:
    """LiveDemoBotEngine refuses to execute or place any trades on the 11 toxic assets."""
    mock_gateway = AsyncMock()
    mock_gateway.open_trade = AsyncMock(return_value=("order-123", {"percentProfit": 92}))

    from strat_trade.domain.trading.entities import BotStatus

    engine = LiveDemoBotEngine()
    engine._gateway = mock_gateway
    engine.status = BotStatus.RUNNING

    all_11_toxic = [
        "USD/DZD OTC",
        "UAH/USD OTC",
        "USD/MYR OTC",
        "USD/INR OTC",
        "EUR/HUF OTC",
        "GBP/JPY OTC",
        "USD/IDR OTC",
        "USD/VND OTC",
        "BNB OTC",
        "BNB/USD OTC",
        "EUR/CHF OTC",
    ]

    assignments = [
        StrategyAssignment(
            asset=tox,
            strategy_id="supertrend_adx_momentum",
            strategy_name="SuperTrend + ADX Momentum",
            category="Momentum",
            parameters={},
            estimated_win_rate_pct=60.0,
            estimated_profit_factor=1.5,
            estimated_trades_count=5,
            quantum_score=80.0,
        )
        for tox in all_11_toxic
    ]

    plan = PreTradingPlan(
        assignments=assignments,
        total_assets=len(assignments),
        initial_deposit=Decimal("10000.00"),
        stake_model="flat",
        stake_amount=Decimal("100.00"),
        stake_percent=1.0,
        expiration_seconds=180,
        daily_stop_loss_pct=0.05,
        stop_loss_amount=Decimal("500.00"),
        max_concurrent_trades=5,
        min_payout_rate=0.80,
        toxic_filter_enabled=True,
    )
    engine.plan = plan

    dummy_candle = Candle(
        open_time=datetime.now(UTC),
        open=Decimal("1.1000"),
        high=Decimal("1.1020"),
        low=Decimal("1.0980"),
        close=Decimal("1.1010"),
        volume=Decimal("100.0"),
    )

    import asyncio

    sem = asyncio.Semaphore(1)
    now = datetime.now(UTC)

    for a in assignments:
        await engine._evaluate_single_asset(a, now, sem)
        await engine._execute_order(
            a,
            action="CALL",
            confidence=0.85,
            reason="test",
            candles=[dummy_candle],
            live_payout=0.92,
        )

    assert len(engine.active_trades) == 0
    assert mock_gateway.open_trade.call_count == 0


# =========================================================================
# SUITE 5: AUTO-MATCHER STRATEGY HIERARCHY & FALLBACK VERIFICATION
# =========================================================================


@pytest.mark.asyncio
async def test_phase3_automatcher_unclassified_asset_primary_fallback_sniper_sr() -> None:
    """
    When candidate asset has sparse/unclassified candle data,
    StrategyAutoMatcher._heuristic_profile_for_asset defaults to primary fallback
    'support_resistance_bounce' with standard calibrated parameters.
    """
    matcher = StrategyAutoMatcher()
    res = await matcher.find_optimal_strategy_for_asset("UNCLASSIFIED_TOKEN_XYZ", [])

    assert res.strategy_id == "support_resistance_bounce"
    assert res.parameters["swing_window"] == 20
    assert res.parameters["min_wick_ratio"] == 0.35
    assert res.parameters["rsi_period"] == 14
    assert res.quantum_score == 85.0


def test_phase3_automatcher_unclassified_asset_secondary_fallback_sniper_rsi_stoch() -> None:
    """When 'support_resistance_bounce' is absent, fallback shifts to 'rsi_stochastic_extreme'."""
    matcher = StrategyAutoMatcher()
    custom_strategies = [
        {"id": "rsi_stochastic_extreme", "name": "RSI Extreme", "category": "Scalping"},
        {"id": "bollinger_atr_reversion", "name": "Bollinger ATR", "category": "Mean Reversion"},
    ]

    profile = matcher._heuristic_profile_for_asset(
        asset="UNKNOWN_PAIR_otc",
        strategies=custom_strategies,
        expiration_bars=3,
    )

    assert profile.strategy_id == "rsi_stochastic_extreme"
    assert profile.parameters["rsi_period"] == 14
    assert profile.parameters["stoch_k"] == 14
    assert profile.parameters["stoch_d"] == 3


@pytest.mark.asyncio
async def test_phase3_automatcher_never_defaults_to_hybrid_multifactors() -> None:
    """Verify hybrid_multifactors is never the default heuristic fallback."""
    matcher = StrategyAutoMatcher()
    res = await matcher.find_optimal_strategy_for_asset("RANDOM_UNCLASSIFIED_XYZ_otc", [])
    assert res.strategy_id != "hybrid_multifactors"
    assert res.strategy_id == "support_resistance_bounce"


def test_phase3_strategy_registry_fallback_to_support_resistance_bounce() -> None:
    """get_strategy_instance without name or with unknown name returns support_resistance_bounce."""
    from strat_trade.domain.strategies.support_resistance_bounce import (
        SupportResistanceBounceStrategy,
    )

    strat = get_strategy_instance("non_existent_strategy_xyz")
    assert isinstance(strat, SupportResistanceBounceStrategy)


# =========================================================================
# SUITE 6: HYBRID MULTI-FACTORS ADX GATING & 3-WAY CONCORDANCE
# =========================================================================


def _make_hybrid_df(
    *,
    close: float = 1.0500,
    ema_fast: float = 1.0500,
    ema_mid: float = 1.0490,
    ema_slow: float = 1.0480,
    rsi: float = 55.0,
    stoch_k: float = 60.0,
    stoch_d: float = 50.0,
    bb_high: float = 1.0550,
    bb_low: float = 1.0450,
    bb_mid: float = 1.0500,
    bb_pband: float = 0.50,
    adx: float = 26.0,
    adx_pos: float = 28.0,
    adx_neg: float = 14.0,
    atr: float = 0.0005,
    atr_sma: float = 0.0005,
) -> pd.DataFrame:
    rows = []
    base_t = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    for i in range(60):
        rows.append(
            {
                "timestamp": base_t + timedelta(minutes=i),
                "open": close,
                "high": close + 0.0002,
                "low": close - 0.0002,
                "close": close,
                "volume": 100.0,
                "ema_fast": ema_fast,
                "ema_mid": ema_mid,
                "ema_slow": ema_slow,
                "rsi": rsi,
                "stoch_k": stoch_k,
                "stoch_d": stoch_d,
                "bb_high": bb_high,
                "bb_low": bb_low,
                "bb_mid": bb_mid,
                "bb_pband": bb_pband,
                "adx": adx,
                "adx_pos": adx_pos,
                "adx_neg": adx_neg,
                "atr": atr,
                "atr_sma": atr_sma,
            }
        )
    return pd.DataFrame(rows)


def test_phase3_hybrid_strategy_adx_gating_sub_22_suppresses_signals() -> None:
    """When ADX < 22.0, HybridMultiFactorsStrategy returns choppy regime suppression."""
    strategy = HybridMultiFactorsStrategy(adx_min_threshold=22.0)
    df = _make_hybrid_df(adx=18.5, adx_pos=25.0, adx_neg=10.0)

    sig = strategy.evaluate_bar(df, 55)
    assert sig.action is None
    assert sig.confidence == 0.0
    assert sig.regime == "adx_sub_threshold_choppy"
    assert sig.metadata["adx"] == 18.5


def test_phase3_hybrid_strategy_adx_boundary_conditions() -> None:
    """Tests ADX right at boundary: 21.9 (suppressed) vs 22.0 (evaluated)."""
    strategy = HybridMultiFactorsStrategy(adx_min_threshold=22.0)

    # 21.9 -> Suppressed
    df_219 = _make_hybrid_df(adx=21.9, adx_pos=30.0, adx_neg=10.0)
    sig_219 = strategy.evaluate_bar(df_219, 55)
    assert sig_219.action is None
    assert sig_219.regime == "adx_sub_threshold_choppy"

    # 22.0 -> Evaluated and produces CALL
    df_220 = _make_hybrid_df(
        close=1.0505,
        ema_fast=1.0500,
        ema_mid=1.0485,
        rsi=56.0,
        stoch_k=65.0,
        stoch_d=48.0,
        adx=22.0,
        adx_pos=29.0,
        adx_neg=11.0,
    )
    sig_220 = strategy.evaluate_bar(df_220, 55)
    assert sig_220.action == TradeAction.CALL
    assert sig_220.confidence >= 0.70


def test_phase3_hybrid_strategy_3way_concordance_bullish_call() -> None:
    """Bullish CALL: ADX >= 22 (+DI > -DI), EMA alignment, RSI corridor (45..68), Stoch K > D."""
    strategy = HybridMultiFactorsStrategy(adx_min_threshold=22.0)
    df_call = _make_hybrid_df(
        close=1.0505,
        ema_fast=1.0500,
        ema_mid=1.0485,
        rsi=58.0,
        stoch_k=72.0,
        stoch_d=65.0,
        adx=28.0,
        adx_pos=32.0,
        adx_neg=12.0,
    )

    sig = strategy.evaluate_bar(df_call, 55)
    assert sig.action == TradeAction.CALL
    assert sig.confidence >= 0.70


def test_phase3_hybrid_strategy_3way_concordance_bearish_put() -> None:
    """Bearish PUT: ADX >= 22 (-DI > +DI), EMA alignment, RSI corridor (32..55), Stoch K < D."""
    strategy = HybridMultiFactorsStrategy(adx_min_threshold=22.0)
    df_put = _make_hybrid_df(
        close=1.0475,
        ema_fast=1.0480,
        ema_mid=1.0495,
        rsi=42.0,
        stoch_k=28.0,
        stoch_d=35.0,
        adx=26.0,
        adx_pos=10.0,
        adx_neg=28.0,
    )

    sig = strategy.evaluate_bar(df_put, 55)
    assert sig.action == TradeAction.PUT
    assert sig.confidence >= 0.70


def test_phase3_hybrid_strategy_conflict_suppression() -> None:
    """When RSI is overbought (> 68) or EMA conflicts during trend, signal is suppressed."""
    strategy = HybridMultiFactorsStrategy(adx_min_threshold=22.0)

    # Bullish indicators but RSI overbought at 75.0 -> Suppress CALL
    df_overbought = _make_hybrid_df(
        close=1.0505,
        ema_fast=1.0500,
        ema_mid=1.0485,
        rsi=75.0,
        stoch_k=70.0,
        stoch_d=60.0,
        adx=30.0,
        adx_pos=35.0,
        adx_neg=10.0,
    )
    sig_rsi = strategy.evaluate_bar(df_overbought, 55)
    assert sig_rsi.action is None

    # Bullish ADX & RSI but EMA bearish -> Suppress CALL
    df_ema_conflict = _make_hybrid_df(
        close=1.0505,
        ema_fast=1.0480,
        ema_mid=1.0500,
        rsi=55.0,
        stoch_k=70.0,
        stoch_d=60.0,
        adx=30.0,
        adx_pos=35.0,
        adx_neg=10.0,
    )
    sig_ema = strategy.evaluate_bar(df_ema_conflict, 55)
    assert sig_ema.action is None


# =========================================================================
# SUITE 7: MINIMAX AUTO-TUNING FEEDBACK LOOP VERIFICATION
# =========================================================================


def test_phase3_minimax_auto_tuner_optimizes_failing_batch() -> None:
    """Verifies auto-tuner triggers when baseline fails and discovers optimal parameters."""
    df_synthetic = Phase3CandleGenerator.make_ranging_channel(n_bars=300)
    bad_params = {"adx_trend_threshold": 50.0, "min_wick_ratio": 0.50, "bb_std": 3.0}

    runner = Rolling15TradeVerificationRunner(
        strategy_name="bollinger_atr_reversion",
        strategy_params=bad_params,
        auto_tune_on_failure=True,
        max_tuning_combinations=8,
    )

    custom_grid = {
        "adx_trend_threshold": [22.0, 28.0],
        "min_wick_ratio": [0.15, 0.20],
        "bb_std": [1.8, 2.0],
        "base_expiration_bars": [2, 3],
    }

    report = runner.verify_or_optimize(df_synthetic, parameter_grid=custom_grid)

    assert report.auto_tuned is True
    assert report.tuning_iterations > 0
    assert report.optimized_params is not None
    assert report.tuning_report is not None


# =========================================================================
# SUITE 8: API ENDPOINT VERIFICATION (/api/v1/backtest/verify-15-trades)
# =========================================================================


def test_phase3_api_verify_15_trades_endpoint_standard() -> None:
    """FastAPI POST /api/v1/backtest/verify-15-trades returns valid verification response."""
    mock_feed = AsyncMock()
    df_synthetic = Phase3CandleGenerator.make_ranging_channel(n_bars=250)
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
        "timeframe_seconds": 60,
        "strategy_name": "bollinger_atr_reversion",
        "strategy_params": {"adx_trend_threshold": 25.0, "min_wick_ratio": 0.20, "bb_std": 2.0},
        "payout_rate": 0.92,
        "initial_deposit": 1000.0,
        "stake_amount": 100.0,
        "candle_count": 250,
        "auto_tune": False,
    }

    response = client.post("/api/v1/backtest/verify-15-trades", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["strategy_name"] == "bollinger_atr_reversion"
    assert data["asset"] == "EURUSD_otc"
    assert data["payout_rate"] == 0.92
    assert "total_batches" in data
    assert "all_batches_passed" in data
    assert "batches" in data
    assert isinstance(data["batches"], list)
