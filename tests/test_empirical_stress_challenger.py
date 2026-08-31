"""Empirical Adversarial Stress Testing Suite — Challenger 1.

Verifies mathematical boundary conditions, edge cases, and robustness across:
1. EmaPullbackTrendStrategy: Zero CALL signals on overbought spikes; Zero PUT on oversold dips.
2. SupportResistanceBounceStrategy: Strict rejection of small wicks (<0.35) and wrong closes.
3. Asset Quality & Toxic Blacklist Filter: Canonical key matching and engine order blocking.
4. Rolling15TradeVerificationRunner: Batch partitioning, ties, streaks, and payout thresholds.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from strat_trade.domain.backtest.models import (
    BacktestTrade,
    TradeAction,
    TradeOutcome,
)
from strat_trade.domain.backtest.verification_runner import (
    Rolling15TradeVerificationRunner,
    VerificationStatus,
)
from strat_trade.domain.entities import Candle
from strat_trade.domain.strategies.ema_pullback_trend import EmaPullbackTrendStrategy
from strat_trade.domain.strategies.support_resistance_bounce import (
    SupportResistanceBounceStrategy,
)
from strat_trade.domain.trading.asset_filter import (
    canonical_asset_key,
    filter_allowed_assets,
    is_toxic_asset,
    is_whitelisted_asset,
)
from strat_trade.domain.trading.bot_engine import LiveDemoBotEngine
from strat_trade.domain.trading.entities import (
    BotStatus,
    PreTradingPlan,
    StrategyAssignment,
)

# ============================================================================
# 1. EMA PULLBACK TREND STRATEGY EMPIRICAL STRESS TESTS
# ============================================================================


class TestEmaPullbackEmpiricalStress:
    """Adversarial stress-testing of EMA Ribbon Pullback signal generation."""

    def _generate_trending_dataframe(
        self,
        n_bars: int = 150,
        trend: str = "bullish",
        base_price: float = 1.1000,
    ) -> pd.DataFrame:
        """Generates synthetic trend data with strong ADX and EMAs."""
        np.random.seed(42)
        timestamps = [
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC) + timedelta(minutes=i) for i in range(n_bars)
        ]
        prices = [base_price]
        step = 0.0003 if trend == "bullish" else -0.0003

        for _ in range(1, n_bars):
            noise = np.random.normal(0, 0.00005)
            prices.append(prices[-1] + step + noise)

        df_dict = {
            "timestamp": timestamps,
            "open": [],
            "high": [],
            "low": [],
            "close": [],
            "volume": [1000] * n_bars,
        }

        for p in prices:
            df_dict["open"].append(p - 0.0001)
            df_dict["high"].append(p + 0.0002)
            df_dict["low"].append(p - 0.0002)
            df_dict["close"].append(p + 0.0001)

        df = pd.DataFrame(df_dict)
        return df

    def test_ema_pullback_zero_calls_on_overbought_rsi_stoch_spikes(self) -> None:
        """Adversarially injects extreme overbought RSI (>80) and Stochastic (>85)

        spikes during an established uptrend, and verifies that ZERO CALL signals are generated.
        """
        strat = EmaPullbackTrendStrategy(
            ema_fast=9,
            ema_mid=21,
            ema_slow=50,
            adx_threshold=25.0,
            rsi_overbought=65.0,
            stoch_overbought=75.0,
        )

        df = self._generate_trending_dataframe(n_bars=150, trend="bullish")
        df = strat.prepare_dataframe(df)

        # Confirm uptrend indicators are initialized
        assert "ema_f" in df.columns
        assert "rsi" in df.columns
        assert "stoch_k" in df.columns

        # Adversarially manipulate the last 30 bars to have low price touching EMA_f/EMA_m,
        # but with extreme overbought RSI (80 to 95) and Stoch (85 to 98).
        overbought_eval_indices = []
        for idx in range(80, 140):
            ema_f_val = df.loc[idx, "ema_f"]
            # Price touches EMA
            df.loc[idx, "low"] = ema_f_val * 0.9999
            df.loc[idx, "close"] = ema_f_val * 1.0002
            df.loc[idx, "open"] = ema_f_val * 1.0001
            df.loc[idx, "high"] = ema_f_val * 1.0005

            # Extreme overbought momentum
            df.loc[idx, "rsi"] = 82.5 + (idx % 10)  # 82.5 to 91.5
            df.loc[idx, "stoch_k"] = 88.0 + (idx % 8)  # 88.0 to 95.0
            df.loc[idx, "stoch_d"] = 85.0
            df.loc[idx, "adx"] = 35.0
            df.loc[idx, "adx_pos"] = 30.0
            df.loc[idx, "adx_neg"] = 10.0
            overbought_eval_indices.append(idx)

        # Evaluate every single overbought bar
        call_signals_count = 0
        for idx in overbought_eval_indices:
            signal = strat.evaluate_bar(df, idx)
            if signal.action == TradeAction.CALL:
                call_signals_count += 1

        # EMPIRICAL ASSERTION: Zero CALL signals during overbought conditions
        assert call_signals_count == 0, (
            f"Expected 0 CALL signals during RSI/Stoch overbought spikes, got {call_signals_count}"
        )

    def test_ema_pullback_zero_puts_on_oversold_rsi_stoch_dips(self) -> None:
        """Adversarially injects extreme oversold RSI (<20) and Stochastic (<15)

        dips during an established downtrend, and verifies that ZERO PUT signals are generated.
        """
        strat = EmaPullbackTrendStrategy(
            ema_fast=9,
            ema_mid=21,
            ema_slow=50,
            adx_threshold=25.0,
            rsi_oversold=35.0,
            stoch_oversold=25.0,
        )

        df = self._generate_trending_dataframe(n_bars=150, trend="bearish")
        df = strat.prepare_dataframe(df)

        oversold_eval_indices = []
        for idx in range(80, 140):
            ema_f_val = df.loc[idx, "ema_f"]
            # Price touches EMA
            df.loc[idx, "high"] = ema_f_val * 1.0001
            df.loc[idx, "close"] = ema_f_val * 0.9998
            df.loc[idx, "open"] = ema_f_val * 0.9999
            df.loc[idx, "low"] = ema_f_val * 0.9995

            # Extreme oversold momentum
            df.loc[idx, "rsi"] = 18.0 - (idx % 8)  # 11.0 to 18.0
            df.loc[idx, "stoch_k"] = 12.0 - (idx % 6)  # 7.0 to 12.0
            df.loc[idx, "stoch_d"] = 15.0
            df.loc[idx, "adx"] = 35.0
            df.loc[idx, "adx_pos"] = 10.0
            df.loc[idx, "adx_neg"] = 30.0
            oversold_eval_indices.append(idx)

        put_signals_count = 0
        for idx in oversold_eval_indices:
            signal = strat.evaluate_bar(df, idx)
            if signal.action == TradeAction.PUT:
                put_signals_count += 1

        # EMPIRICAL ASSERTION: Zero PUT signals during oversold conditions
        assert put_signals_count == 0, (
            f"Expected 0 PUT signals during RSI/Stoch oversold dips, got {put_signals_count}"
        )

    @pytest.mark.parametrize(
        ("rsi", "stoch_k", "expected_call"),
        [
            (65.0, 75.0, True),  # Exact boundary: allowed
            (65.01, 75.0, False),  # RSI 0.01 above overbought: strictly rejected
            (65.0, 75.01, False),  # Stoch 0.01 above overbought: strictly rejected
            (70.0, 60.0, False),  # High RSI: rejected
            (50.0, 80.0, False),  # High Stoch: rejected
            (55.0, 60.0, True),  # Well within limits: allowed
        ],
    )
    def test_ema_pullback_boundary_conditions(
        self, rsi: float, stoch_k: float, expected_call: bool
    ) -> None:
        """Verifies sharp mathematical boundaries for RSI (<=65.0) and Stoch (<=75.0)."""
        strat = EmaPullbackTrendStrategy(
            ema_fast=9,
            ema_mid=21,
            ema_slow=50,
            adx_threshold=25.0,
            rsi_overbought=65.0,
            stoch_overbought=75.0,
        )
        df = self._generate_trending_dataframe(n_bars=100, trend="bullish")
        df = strat.prepare_dataframe(df)

        idx = 80
        ema_f_val = 1.1500
        df.loc[idx, "ema_f"] = ema_f_val
        df.loc[idx, "ema_m"] = ema_f_val - 0.0010
        df.loc[idx, "ema_s"] = ema_f_val - 0.0020
        df.loc[idx, "adx"] = 30.0
        df.loc[idx, "adx_pos"] = 28.0
        df.loc[idx, "adx_neg"] = 12.0
        df.loc[idx, "open"] = ema_f_val
        df.loc[idx, "low"] = ema_f_val * 0.9999
        df.loc[idx, "high"] = ema_f_val + 0.0005
        df.loc[idx, "close"] = ema_f_val + 0.0003

        df.loc[idx - 1, "stoch_k"] = stoch_k - 5.0
        df.loc[idx - 1, "stoch_d"] = stoch_k
        df.loc[idx, "stoch_k"] = stoch_k
        df.loc[idx, "stoch_d"] = stoch_k - 2.0  # Bullish cross (sk > sd)
        df.loc[idx, "rsi"] = rsi

        signal = strat.evaluate_bar(df, idx)
        if expected_call:
            assert signal.action == TradeAction.CALL, f"Expected CALL at RSI={rsi}, Stoch={stoch_k}"
        else:
            assert signal.action is None, (
                f"Expected None at RSI={rsi}, Stoch={stoch_k}, got {signal.action}"
            )


# ============================================================================
# 2. SUPPORT & RESISTANCE BOUNCE STRATEGY EMPIRICAL STRESS TESTS
# ============================================================================


class TestSupportResistanceBounceEmpiricalStress:
    """Adversarial stress-testing of Support/Resistance Bounce & Pin-Bar filter."""

    def _setup_sr_dataframe(
        self,
        support_level: float = 1.1000,
        resistance_level: float = 1.1200,
        n_bars: int = 50,
    ) -> pd.DataFrame:
        """Sets up dataframe with predetermined rolling support and resistance."""
        timestamps = [
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC) + timedelta(minutes=i) for i in range(n_bars)
        ]
        df = pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [1.1100] * n_bars,
                "high": [1.1150] * n_bars,
                "low": [1.1050] * n_bars,
                "close": [1.1100] * n_bars,
                "volume": [1000] * n_bars,
                "sr_support": [support_level] * n_bars,
                "sr_resistance": [resistance_level] * n_bars,
                "rsi": [35.0] * n_bars,
            }
        )
        return df

    @pytest.mark.parametrize("wick_ratio", [0.00, 0.10, 0.20, 0.30, 0.34, 0.3499])
    def test_sr_support_rejects_sub_threshold_wicks(self, wick_ratio: float) -> None:
        """Verifies that candles with lower wick ratio < 0.35 on support are STRICTLY rejected."""
        strat = SupportResistanceBounceStrategy(
            swing_window=20,
            min_wick_ratio=0.35,
        )
        df = self._setup_sr_dataframe(support_level=1.1000)
        idx = 35

        # Candle testing support (low <= support)
        # Total range = 0.0010 (10 pips)
        # Lower wick = wick_ratio * 0.0010
        total_range = 0.0010
        low = 1.1000
        high = low + total_range
        lower_wick = wick_ratio * total_range
        open_ = low + lower_wick
        close = high - 0.0001  # Bullish close

        df.loc[idx, "open"] = open_
        df.loc[idx, "high"] = high
        df.loc[idx, "low"] = low
        df.loc[idx, "close"] = close
        df.loc[idx, "rsi"] = 35.0

        signal = strat.evaluate_bar(df, idx)
        assert signal.action is None, (
            f"False bounce allowed with sub-threshold wick ratio {wick_ratio:.4f}!"
        )

    def test_sr_support_rejects_bearish_close_on_support(self) -> None:
        """Verifies that a candle with a long lower wick but a BEARISH close (close < open)

        is rejected (no bounce confirmation).
        """
        strat = SupportResistanceBounceStrategy(
            swing_window=20,
            min_wick_ratio=0.35,
        )
        df = self._setup_sr_dataframe(support_level=1.1000)
        idx = 35

        # Candle has huge lower wick (0.45 ratio), but closes RED (close < open)
        low = 1.1000
        high = 1.1020  # Range = 0.0020
        open_ = 1.1015
        close = 1.1010  # close < open!

        df.loc[idx, "open"] = open_
        df.loc[idx, "high"] = high
        df.loc[idx, "low"] = low
        df.loc[idx, "close"] = close
        df.loc[idx, "rsi"] = 35.0

        signal = strat.evaluate_bar(df, idx)
        assert signal.action is None, "Bearish candle on support was falsely accepted!"

    def test_sr_support_rejects_close_in_lower_half(self) -> None:
        """Verifies that a candle with close in the lower 50% of the range is rejected."""
        strat = SupportResistanceBounceStrategy(
            swing_window=20,
            min_wick_ratio=0.35,
        )
        df = self._setup_sr_dataframe(support_level=1.1000)
        idx = 35

        # Candle: range = 0.0020, close - low = 0.0008 (40% < 50%)
        low = 1.1000
        high = 1.1020
        open_ = 1.1005
        close = 1.1008  # close > open, but (close - low) / range = 0.0008 / 0.0020 = 0.40

        df.loc[idx, "open"] = open_
        df.loc[idx, "high"] = high
        df.loc[idx, "low"] = low
        df.loc[idx, "close"] = close

        signal = strat.evaluate_bar(df, idx)
        assert signal.action is None, (
            "Candle closing in lower 50% was falsely accepted as support bounce!"
        )

    def test_sr_valid_support_bounce_acceptance(self) -> None:
        """Verifies genuine pin-bar with >=35% lower wick, bullish close, upper 50% close."""
        strat = SupportResistanceBounceStrategy(
            swing_window=20,
            min_wick_ratio=0.35,
        )
        df = self._setup_sr_dataframe(support_level=1.1000)
        idx = 35

        # Pin-bar: Low tests 1.1000, High 1.1020, Open 1.1010, Close 1.1018
        low = 1.1000
        high = 1.1020
        open_ = 1.1010
        close = 1.1018

        df.loc[idx, "open"] = open_
        df.loc[idx, "high"] = high
        df.loc[idx, "low"] = low
        df.loc[idx, "close"] = close
        df.loc[idx, "rsi"] = 35.0

        signal = strat.evaluate_bar(df, idx)
        assert signal.action == TradeAction.CALL
        assert signal.confidence >= 0.75

    def test_sr_resistance_rejects_bullish_close_and_small_wicks(self) -> None:
        """Verifies resistance rejection: small upper wicks and bullish closes are rejected."""
        strat = SupportResistanceBounceStrategy(
            swing_window=20,
            min_wick_ratio=0.35,
        )
        df = self._setup_sr_dataframe(resistance_level=1.1200)
        idx = 35

        # 1. Bullish close on resistance with long upper wick
        df.loc[idx, "low"] = 1.1180
        df.loc[idx, "high"] = 1.1200
        df.loc[idx, "open"] = 1.1185
        df.loc[idx, "close"] = 1.1190  # close > open (Bullish!)
        df.loc[idx, "rsi"] = 65.0

        signal = strat.evaluate_bar(df, idx)
        assert signal.action is None, (
            "Bullish close on resistance was falsely accepted as PUT bounce!"
        )

        # 2. Bearish close but tiny upper wick (0.20 ratio < 0.35)
        df.loc[idx, "low"] = 1.1180
        df.loc[idx, "high"] = 1.1200  # Range = 0.0020
        df.loc[idx, "open"] = 1.1196  # upper wick = 1.1200 - 1.1196 = 0.0004 (20%)
        df.loc[idx, "close"] = 1.1185  # close < open
        df.loc[idx, "rsi"] = 65.0

        signal = strat.evaluate_bar(df, idx)
        assert signal.action is None, "Sub-threshold upper wick was falsely accepted as PUT bounce!"

        # 3. Valid shooting star pin-bar on resistance
        df.loc[idx, "open"] = 1.1190
        df.loc[idx, "high"] = 1.1200  # upper wick = 1.1200 - 1.1190 = 0.0010 (50%)
        df.loc[idx, "low"] = 1.1180
        df.loc[idx, "close"] = 1.1182  # close < open & (high - close)/range = 0.90
        df.loc[idx, "rsi"] = 65.0

        signal = strat.evaluate_bar(df, idx)
        assert signal.action == TradeAction.PUT
        assert signal.confidence >= 0.75


# ============================================================================
# 3. ASSET QUALITY FILTER & LIVE BOT ENGINE ADVERSARIAL STRESS TESTS
# ============================================================================


class TestAssetFilterAndBotEngineEmpiricalStress:
    """Adversarial stress-testing of Asset Quality Filter and LiveDemoBotEngine."""

    @pytest.mark.parametrize(
        "toxic_input",
        [
            "USD/IDR OTC",
            "USDIDR_otc",
            "usdidr_otc",
            "USD-IDR (OTC)",
            "  usd / idr  otc  ",
            "\tUSDIDR\n",
            "USD_IDR_OTC",
            "USD/VND OTC",
            "USDVND_otc",
            "usdvnd_otc",
            "  USD-VND (otc)  ",
            "BNB OTC",
            "bnb_otc",
            "BNBUSD_otc",
            "bnb/usd otc",
            "EUR/CHF OTC",
            "EURCHF_otc",
            "eurchf_otc",
            "EUR-CHF (OTC)",
            # Newly discovered toxic OTC pairs permutations
            "USD/DZD OTC",
            "USDDZD_otc",
            "usddzd_otc",
            "USD_DZD_OTC",
            "USDDZDOTC",
            "  USD-DZD (OTC)  ",
            "UAH/USD OTC",
            "UAHUSD_otc",
            "uah_usd_otc",
            "UAH_USD_OTC",
            "UAHUSDOTC",
            "  UAH-USD (OTC)  ",
            "USD/MYR OTC",
            "USDMYR_otc",
            "usdmyr_otc",
            "USD_MYR_OTC",
            "USDMYROTC",
            "  USD-MYR (OTC)  ",
            "USD/INR OTC",
            "USDINR_otc",
            "usdinr_otc",
            "USD_INR_OTC",
            "USDINROTC",
            "  USD-INR (OTC)  ",
            "EUR/HUF OTC",
            "EURHUF_otc",
            "eurhuf_otc",
            "EUR_HUF_OTC",
            "EURHUFOTC",
            "  EUR-HUF (OTC)  ",
            "GBP/JPY OTC",
            "GBPJPY_otc",
            "gbpjpy_otc",
            "GBP_JPY_OTC",
            "GBPJPYOTC",
            "  GBP-JPY (OTC)  ",
        ],
    )
    def test_toxic_asset_exhaustive_variations_rejected(self, toxic_input: str) -> None:
        """Verifies casing, whitespace, and delimiter variants of toxic assets are rejected."""
        is_toxic, reason = is_toxic_asset(toxic_input)
        assert is_toxic is True, f"Toxic asset '{toxic_input}' was NOT detected as toxic!"
        assert "toxic OTC blacklist" in reason

    @pytest.mark.parametrize(
        ("whitelist_input", "expected_canonical"),
        [
            ("EUR/USD OTC", "EURUSD"),
            ("eurusd_otc", "EURUSD"),
            ("USD/CLP OTC", "USDCLP"),
            ("usdbdt_otc", "USDBDT"),
            ("USD/EGP OTC", "USDEGP"),
            ("Gold OTC", "GOLD"),
            ("XAUUSD_otc", "GOLD"),
            ("XAU/USD OTC", "GOLD"),
        ],
    )
    def test_whitelisted_assets_canonicalization(
        self, whitelist_input: str, expected_canonical: str
    ) -> None:
        """Verifies high-winrate whitelisted assets are canonicalized and identified."""
        key = canonical_asset_key(whitelist_input)
        assert key == expected_canonical
        assert is_whitelisted_asset(whitelist_input) is True
        is_toxic, _ = is_toxic_asset(whitelist_input)
        assert is_toxic is False

    @pytest.mark.parametrize(
        "malformed_input",
        [
            "",
            "   ",
            None,
            "123456",
            "INVALID_PAIR_ZZZZZZ",
            "!!!@@@###$$$",
            "\n\r\t",
        ],
    )
    def test_filter_edge_cases_and_malformed_strings(self, malformed_input: Any) -> None:
        """Ensures asset filter gracefully handles malformed, None, or empty inputs."""
        key = canonical_asset_key(malformed_input)
        assert isinstance(key, str)
        is_toxic, _ = is_toxic_asset(malformed_input)
        assert is_toxic is False  # Unknown garbage is not in toxic blacklist
        assert is_whitelisted_asset(malformed_input) is False

    def test_filter_allowed_assets_mechanics(self) -> None:
        """Tests filter_allowed_assets with toxic, whitelisted, and regular assets."""
        pool = [
            "USD/IDR OTC",  # Toxic
            "EUR/USD OTC",  # Whitelist
            "USD/VND OTC",  # Toxic
            "GBP/USD OTC",  # Regular (non-toxic, not in default whitelist)
            "BNB OTC",  # Toxic
            "USD/CLP OTC",  # Whitelist
        ]

        # 1. Standard filter (toxic removed, regular allowed)
        filtered = filter_allowed_assets(pool, enforce_whitelist_only=False)
        assert filtered == ["EUR/USD OTC", "GBP/USD OTC", "USD/CLP OTC"]

        # 2. Strict Whitelist-only filter (toxic removed, only whitelist allowed)
        whitelisted_only = filter_allowed_assets(pool, enforce_whitelist_only=True)
        assert whitelisted_only == ["EUR/USD OTC", "USD/CLP OTC"]

    @pytest.mark.asyncio
    async def test_live_demo_bot_engine_blocks_toxic_assets(self) -> None:
        """Adversarial test ensuring LiveDemoBotEngine rejects toxic assets."""
        bot = LiveDemoBotEngine()
        assignment_toxic = StrategyAssignment(
            asset="USD/IDR OTC",
            strategy_id="hybrid_multifactors",
            strategy_name="Hybrid Multi-Factor",
            category="reversion",
            parameters={},
            estimated_win_rate_pct=60.0,
            estimated_profit_factor=1.5,
            estimated_trades_count=20,
            quantum_score=80.0,
            rationale="Test toxic assignment",
        )
        assignment_clean = StrategyAssignment(
            asset="EUR/USD OTC",
            strategy_id="hybrid_multifactors",
            strategy_name="Hybrid Multi-Factor",
            category="reversion",
            parameters={},
            estimated_win_rate_pct=60.0,
            estimated_profit_factor=1.5,
            estimated_trades_count=20,
            quantum_score=80.0,
            rationale="Test clean assignment",
        )

        plan = PreTradingPlan(
            assignments=[assignment_toxic, assignment_clean],
            total_assets=2,
            initial_deposit=Decimal("1000.00"),
            stake_model="flat",
            stake_amount=Decimal("10.00"),
            stake_percent=1.0,
            expiration_seconds=180,
            daily_stop_loss_pct=0.05,
            stop_loss_amount=Decimal("50.00"),
            max_concurrent_trades=3,
            min_payout_rate=0.80,
            toxic_filter_enabled=True,
            bar_edge_guard_seconds=0.0,
        )

        gateway_mock = AsyncMock()
        gateway_mock.get_candles = AsyncMock(return_value=[])
        gateway_mock.open_trade = AsyncMock(return_value=("order_123", {"percentProfit": 92}))

        await bot.start(plan, gateway_mock)
        assert bot.status == BotStatus.RUNNING

        # 1. Run single asset evaluation for toxic pair
        sem = asyncio.Semaphore(1)
        now = datetime.now(UTC)
        await bot._evaluate_single_asset(assignment_toxic, now, sem)

        # Gateway candles should NEVER be requested for toxic asset
        assert gateway_mock.get_candles.call_count == 0

        # 2. Attempt direct order execution with toxic asset under _order_lock
        dummy_candle = Candle(
            open_time=datetime.now(UTC),
            open=Decimal("1.10"),
            high=Decimal("1.11"),
            low=Decimal("1.09"),
            close=Decimal("1.10"),
            volume=Decimal("100"),
        )
        await bot._execute_order(
            assignment=assignment_toxic,
            action="CALL",
            confidence=0.85,
            reason="Stress Test",
            candles=[dummy_candle],
            live_payout=0.92,
        )

        # Broker open_trade should NEVER be called for toxic asset
        assert gateway_mock.open_trade.call_count == 0
        assert len(bot.active_trades) == 0

        await bot.stop()


# ============================================================================
# 4. ROLLING 15-TRADE VERIFICATION RUNNER EMPIRICAL STRESS TESTS
# ============================================================================


class TestRolling15TradeVerificationEmpiricalStress:
    """Adversarial stress-testing of Rolling15TradeVerificationRunner."""

    def _create_mock_trades(
        self,
        outcomes: list[TradeOutcome],
        stake: Decimal = Decimal("100.0"),
        payout_rate: Decimal = Decimal("0.92"),
    ) -> list[BacktestTrade]:
        """Creates deterministic sequence of BacktestTrade objects."""
        trades = []
        base_time = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        balance = Decimal("1000.0")

        for i, out in enumerate(outcomes):
            entry_t = base_time + timedelta(minutes=i * 3)
            exit_t = entry_t + timedelta(minutes=3)
            if out == TradeOutcome.WIN:
                pnl = stake * payout_rate
            elif out == TradeOutcome.LOSS:
                pnl = -stake
            else:  # DRAW
                pnl = Decimal("0.0")

            balance += pnl
            trade = BacktestTrade(
                entry_index=i,
                exit_index=i + 1,
                entry_time=entry_t,
                exit_time=exit_t,
                action=TradeAction.CALL,
                entry_price=Decimal("1.1000"),
                exit_price=(Decimal("1.1005") if out == TradeOutcome.WIN else Decimal("1.0995")),
                stake=stake,
                payout_rate=payout_rate,
                pnl=pnl,
                outcome=out,
                balance_after=balance,
                confidence=0.80,
                expiration_seconds=180,
                asset="EURUSD_otc",
                metadata={},
            )
            trades.append(trade)
        return trades

    def test_all_loss_batch_evaluation(self) -> None:
        """15 consecutive losses: Win Rate 0%, Net PnL -$1500 -> STRICT FAILED."""
        runner = Rolling15TradeVerificationRunner(batch_size=15, min_win_rate_pct=Decimal("53.4"))
        outcomes = [TradeOutcome.LOSS] * 15
        trades = self._create_mock_trades(outcomes)

        report = runner.evaluate_trades(trades)
        assert report.status == VerificationStatus.FAILED
        assert report.total_batches == 1
        assert report.passed_batches == 0
        assert report.failed_batches == 1
        assert report.all_batches_passed is False

        batch = report.batches[0]
        assert batch.winning_trades == 0
        assert batch.losing_trades == 15
        assert batch.win_rate_pct == Decimal("0.00")
        assert batch.net_pnl == Decimal("-1500.00")
        assert batch.max_consecutive_losses == 15
        assert batch.passed is False

    def test_minimal_8_wins_15_trades_pass_boundary(self) -> None:
        """8 wins / 7 losses at 92% payout: Net PnL = 8 * 92 - 7 * 100 = +$36 -> STRICT PASSED."""
        runner = Rolling15TradeVerificationRunner(batch_size=15, min_win_rate_pct=Decimal("53.4"))
        # Alternating W, L, W, L, W, L, W, L, W, L, W, L, W, L, W (8W, 7L)
        outcomes = [
            TradeOutcome.WIN,
            TradeOutcome.LOSS,
            TradeOutcome.WIN,
            TradeOutcome.LOSS,
            TradeOutcome.WIN,
            TradeOutcome.LOSS,
            TradeOutcome.WIN,
            TradeOutcome.LOSS,
            TradeOutcome.WIN,
            TradeOutcome.LOSS,
            TradeOutcome.WIN,
            TradeOutcome.LOSS,
            TradeOutcome.WIN,
            TradeOutcome.LOSS,
            TradeOutcome.WIN,
        ]
        trades = self._create_mock_trades(outcomes)

        report = runner.evaluate_trades(trades)
        assert report.status == VerificationStatus.PASSED
        assert report.total_batches == 1
        assert report.passed_batches == 1
        assert report.failed_batches == 0

        batch = report.batches[0]
        assert batch.winning_trades == 8
        assert batch.losing_trades == 7
        assert batch.win_rate_pct == Decimal("53.33")
        assert batch.net_pnl == Decimal("36.00")
        assert batch.max_consecutive_losses == 1
        assert batch.passed is True

    def test_7_wins_8_losses_failure_boundary(self) -> None:
        """7 wins / 8 losses at 92% payout: Net PnL = 7 * 92 - 8 * 100 = -$156 -> STRICT FAILED."""
        runner = Rolling15TradeVerificationRunner(batch_size=15, min_win_rate_pct=Decimal("53.4"))
        outcomes = [TradeOutcome.WIN] * 7 + [TradeOutcome.LOSS] * 8
        trades = self._create_mock_trades(outcomes)

        report = runner.evaluate_trades(trades)
        assert report.status == VerificationStatus.FAILED
        batch = report.batches[0]
        assert batch.winning_trades == 7
        assert batch.losing_trades == 8
        assert batch.win_rate_pct == Decimal("46.67")
        assert batch.net_pnl == Decimal("-156.00")
        assert batch.passed is False

    def test_tie_draw_trades_mechanics(self) -> None:
        """Verifies that DRAW trades (pnl=0) correctly calculate decisive trade win rate."""
        runner = Rolling15TradeVerificationRunner(batch_size=15, min_win_rate_pct=Decimal("53.4"))
        # 8 Wins, 6 Losses, 1 Draw -> Total = 15, Decisive = 14
        # Win rate = 8 / 14 = 57.14%
        # Net PnL = 8 * 92 - 6 * 100 + 0 = +$136.00
        outcomes = [TradeOutcome.WIN] * 8 + [TradeOutcome.LOSS] * 6 + [TradeOutcome.DRAW] * 1
        trades = self._create_mock_trades(outcomes)

        report = runner.evaluate_trades(trades)
        assert report.status == VerificationStatus.PASSED
        batch = report.batches[0]
        assert batch.winning_trades == 8
        assert batch.losing_trades == 6
        assert batch.draw_trades == 1
        assert batch.win_rate_pct == Decimal("57.14")
        assert batch.net_pnl == Decimal("136.00")
        assert batch.passed is True

    def test_low_payout_rejection(self) -> None:
        """At 80% payout, 8 wins / 7 losses yields -$60 (Negative PnL) -> MUST FAIL."""
        runner = Rolling15TradeVerificationRunner(
            batch_size=15,
            payout_rate=Decimal("0.80"),
            min_win_rate_pct=Decimal("53.4"),
        )
        outcomes = [TradeOutcome.WIN] * 8 + [TradeOutcome.LOSS] * 7
        trades = self._create_mock_trades(outcomes, payout_rate=Decimal("0.80"))

        report = runner.evaluate_trades(trades)
        assert report.status == VerificationStatus.FAILED
        batch = report.batches[0]
        assert batch.net_pnl == Decimal("-60.00")
        assert batch.passed is False  # Fails net PnL check!

    def test_multi_batch_sequential_verification(self) -> None:
        """Verifies 4 sequential non-overlapping 15-trade batches (60 trades).

        Batch 1: 10W/5L (+420) -> PASS
        Batch 2: 9W/6L  (+228) -> PASS
        Batch 3: 11W/4L (+612) -> PASS
        Batch 4: 10W/5L (+420) -> PASS
        Overall: 40W/20L (66.67% WR), Total PnL = +$1,680.00, All batches passed -> STATUS PASSED.
        """
        runner = Rolling15TradeVerificationRunner(batch_size=15, min_win_rate_pct=Decimal("53.4"))
        b1 = [TradeOutcome.WIN] * 10 + [TradeOutcome.LOSS] * 5
        b2 = [TradeOutcome.WIN] * 9 + [TradeOutcome.LOSS] * 6
        b3 = [TradeOutcome.WIN] * 11 + [TradeOutcome.LOSS] * 4
        b4 = [TradeOutcome.WIN] * 10 + [TradeOutcome.LOSS] * 5

        all_outcomes = b1 + b2 + b3 + b4
        trades = self._create_mock_trades(all_outcomes)

        report = runner.evaluate_trades(trades)
        assert report.status == VerificationStatus.PASSED
        assert report.total_trades == 60
        assert report.total_batches == 4
        assert report.passed_batches == 4
        assert report.failed_batches == 0
        assert report.all_batches_passed is True
        assert report.overall_passed is True
        assert report.total_net_pnl == Decimal("1680.00")
        assert report.overall_win_rate_pct == Decimal("66.67")
        assert len(report.rolling_windows) == 60 - 15 + 1  # 46 sliding windows

    def test_exact_breakeven_payout_boundary_rejection(self) -> None:
        """At 87.5% payout, 8 wins / 7 losses gives 8 * 87.5 - 7 * 100 = 0.00 (Zero PnL).

        The rule strictly requires net_pnl > 0.0, so this MUST FAIL.
        """
        runner = Rolling15TradeVerificationRunner(
            batch_size=15,
            payout_rate=Decimal("0.875"),
            min_win_rate_pct=Decimal("53.4"),
        )
        outcomes = [TradeOutcome.WIN] * 8 + [TradeOutcome.LOSS] * 7
        trades = self._create_mock_trades(outcomes, payout_rate=Decimal("0.875"))

        report = runner.evaluate_trades(trades)
        assert report.status == VerificationStatus.FAILED
        batch = report.batches[0]
        assert batch.net_pnl == Decimal("0.00")
        assert batch.passed is False

        # Now test 88% payout (8 * 88 - 7 * 100 = +$4.00) -> MUST PASS
        runner_88 = Rolling15TradeVerificationRunner(
            batch_size=15,
            payout_rate=Decimal("0.88"),
            min_win_rate_pct=Decimal("53.4"),
        )
        trades_88 = self._create_mock_trades(outcomes, payout_rate=Decimal("0.88"))
        report_88 = runner_88.evaluate_trades(trades_88)
        assert report_88.status == VerificationStatus.PASSED
        assert report_88.batches[0].net_pnl == Decimal("4.00")
        assert report_88.batches[0].passed is True

    def test_partial_batch_never_marked_passed(self) -> None:
        """Verifies that incomplete batches (e.g. 14 or 29 trades) are NEVER marked as passed."""
        runner = Rolling15TradeVerificationRunner(batch_size=15)
        # 14 trades (all wins!)
        trades_14 = self._create_mock_trades([TradeOutcome.WIN] * 14)
        report_14 = runner.evaluate_trades(trades_14)
        assert report_14.status == VerificationStatus.INSUFFICIENT_TRADES
        assert len(report_14.batches) == 1
        assert report_14.batches[0].is_partial is True
        assert report_14.batches[0].passed is False

        # 29 trades (1 full batch of 15W, 1 partial batch of 14W)
        trades_29 = self._create_mock_trades([TradeOutcome.WIN] * 29)
        report_29 = runner.evaluate_trades(trades_29)
        assert report_29.status == VerificationStatus.PASSED
        assert report_29.total_non_overlapping_batches == 1
        assert len(report_29.batches) == 2
        assert report_29.batches[0].passed is True
        assert report_29.batches[1].is_partial is True
        assert report_29.batches[1].passed is False


# ============================================================================
# 5. ADDITIONAL DEEP BOUNDARY & FAILURE MODE STRESS TESTS
# ============================================================================


class TestDeepAdversarialEdgeCases:
    """Additional extreme stress tests for flat bars, breakouts, and AutoMatcher scoring."""

    def test_sr_flat_bar_zero_range_rejection(self) -> None:
        """When high == low (zero price movement), strategy must return flat_bar regime."""
        strat = SupportResistanceBounceStrategy(swing_window=20)
        timestamps = [
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC) + timedelta(minutes=i) for i in range(50)
        ]
        df = pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [1.1000] * 50,
                "high": [1.1000] * 50,
                "low": [1.1000] * 50,
                "close": [1.1000] * 50,
                "volume": [0] * 50,
                "sr_support": [1.1000] * 50,
                "sr_resistance": [1.1000] * 50,
            }
        )
        signal = strat.evaluate_bar(df, 30)
        assert signal.action is None
        assert signal.regime == "flat_bar"

    def test_sr_breakouts_rejected_not_treated_as_bounces(self) -> None:
        """Support breakout (close < support) and Resistance breakout must be rejected."""
        strat = SupportResistanceBounceStrategy(swing_window=20)
        timestamps = [
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC) + timedelta(minutes=i) for i in range(50)
        ]
        df = pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [1.1050] * 50,
                "high": [1.1100] * 50,
                "low": [1.1000] * 50,
                "close": [1.1050] * 50,
                "volume": [1000] * 50,
                "sr_support": [1.1000] * 50,
                "sr_resistance": [1.1200] * 50,
                "rsi": [30.0] * 50,
            }
        )

        idx = 35
        # 1. Bearish breakout below support: low = 1.0950, close = 1.0970 (< 1.1000 support)
        df.loc[idx, "open"] = 1.0990
        df.loc[idx, "high"] = 1.1000
        df.loc[idx, "low"] = 1.0950
        df.loc[idx, "close"] = 1.0970  # close < support!

        signal = strat.evaluate_bar(df, idx)
        assert signal.action is None

        # 2. Bullish breakout above resistance: high = 1.1250, close = 1.1230 (> 1.1200 resistance)
        df.loc[idx, "open"] = 1.1190
        df.loc[idx, "high"] = 1.1250
        df.loc[idx, "low"] = 1.1180
        df.loc[idx, "close"] = 1.1230  # close > resistance!
        df.loc[idx, "rsi"] = 70.0

        signal = strat.evaluate_bar(df, idx)
        assert signal.action is None
