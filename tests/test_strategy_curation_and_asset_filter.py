from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from strat_trade.domain.backtest.models import TradeAction
from strat_trade.domain.entities import Candle
from strat_trade.domain.optimizer.auto_matcher import StrategyAutoMatcher
from strat_trade.domain.strategies.ema_pullback_trend import EmaPullbackTrendStrategy
from strat_trade.domain.strategies.support_resistance_bounce import SupportResistanceBounceStrategy
from strat_trade.domain.trading.asset_filter import (
    canonical_asset_key,
    filter_allowed_assets,
    is_toxic_asset,
    is_whitelisted_asset,
    qualify_asset_microstructure,
)
from strat_trade.domain.trading.bot_engine import LiveDemoBotEngine
from strat_trade.domain.trading.entities import PreTradingPlan, StrategyAssignment
from strat_trade.use_cases.auto_assign_strategies import generate_pre_trading_plan

# =====================================================================
# 1. Asset Quality Filter & Toxic Pair Blacklist Unit Tests
# =====================================================================


def test_canonical_asset_key_normalization():
    """Verify various string formats resolve to identical canonical uppercase keys."""
    assert canonical_asset_key("USD/IDR OTC") == "USDIDR"
    assert canonical_asset_key("USDIDR_otc") == "USDIDR"
    assert canonical_asset_key("usdidr_otc") == "USDIDR"
    assert canonical_asset_key("USD-IDR (OTC)") == "USDIDR"
    assert canonical_asset_key("USD/VND OTC") == "USDVND"
    assert canonical_asset_key("BNB OTC") == "BNB"
    assert canonical_asset_key("BNB/USD OTC") == "BNBUSD"
    assert canonical_asset_key("EUR/CHF OTC") == "EURCHF"

    # Expanded toxic assets canonical normalization permutations
    assert canonical_asset_key("USD/DZD OTC") == "USDDZD"
    assert canonical_asset_key("USD_DZD_OTC") == "USDDZD"
    assert canonical_asset_key("USDDZDOTC") == "USDDZD"
    assert canonical_asset_key("usddzd_otc") == "USDDZD"
    assert canonical_asset_key("USD-DZD (OTC)") == "USDDZD"

    assert canonical_asset_key("UAH/USD OTC") == "UAHUSD"
    assert canonical_asset_key("UAH_USD_OTC") == "UAHUSD"
    assert canonical_asset_key("UAHUSDOTC") == "UAHUSD"
    assert canonical_asset_key("uah_usd_otc") == "UAHUSD"
    assert canonical_asset_key("UAH-USD (OTC)") == "UAHUSD"

    assert canonical_asset_key("USD/MYR OTC") == "USDMYR"
    assert canonical_asset_key("USD_MYR_OTC") == "USDMYR"
    assert canonical_asset_key("USDMYROTC") == "USDMYR"
    assert canonical_asset_key("usdmyr_otc") == "USDMYR"
    assert canonical_asset_key("USD-MYR (OTC)") == "USDMYR"

    assert canonical_asset_key("USD/INR OTC") == "USDINR"
    assert canonical_asset_key("USD_INR_OTC") == "USDINR"
    assert canonical_asset_key("USDINROTC") == "USDINR"
    assert canonical_asset_key("usdinr_otc") == "USDINR"
    assert canonical_asset_key("USD-INR (OTC)") == "USDINR"

    assert canonical_asset_key("EUR/HUF OTC") == "EURHUF"
    assert canonical_asset_key("EUR_HUF_OTC") == "EURHUF"
    assert canonical_asset_key("EURHUFOTC") == "EURHUF"
    assert canonical_asset_key("eurhuf_otc") == "EURHUF"
    assert canonical_asset_key("EUR-HUF (OTC)") == "EURHUF"

    assert canonical_asset_key("GBP/JPY OTC") == "GBPJPY"
    assert canonical_asset_key("GBP_JPY_OTC") == "GBPJPY"
    assert canonical_asset_key("GBPJPYOTC") == "GBPJPY"
    assert canonical_asset_key("gbpjpy_otc") == "GBPJPY"
    assert canonical_asset_key("GBP-JPY (OTC)") == "GBPJPY"

    # Whitelist canonical keys
    assert canonical_asset_key("EUR/USD OTC") == "EURUSD"
    assert canonical_asset_key("USD/CLP OTC") == "USDCLP"
    assert canonical_asset_key("USD/BDT OTC") == "USDBDT"
    assert canonical_asset_key("USD/EGP OTC") == "USDEGP"

    # Gold & XAUUSD alias mapping
    assert canonical_asset_key("Gold OTC") == "GOLD"
    assert canonical_asset_key("Gold_otc") == "GOLD"
    assert canonical_asset_key("XAUUSD_otc") == "GOLD"
    assert canonical_asset_key("XAU/USD OTC") == "GOLD"

    # Empty or None
    assert canonical_asset_key(None) == ""
    assert canonical_asset_key("") == ""


def test_is_toxic_asset_detection():
    """Verify toxic OTC assets are flagged with reason and valid assets pass."""
    toxic_assets = [
        "USD/IDR OTC",
        "USDIDR_otc",
        "USD/VND OTC",
        "USDVND_otc",
        "BNB OTC",
        "BNB_otc",
        "BNBUSD_otc",
        "EUR/CHF OTC",
        "EURCHF_otc",
        "USD/DZD OTC",
        "USDDZD_otc",
        "UAH/USD OTC",
        "UAHUSD_otc",
        "USD/MYR OTC",
        "USDMYR_otc",
        "USD/INR OTC",
        "USDINR_otc",
        "EUR/HUF OTC",
        "EURHUF_otc",
        "GBP/JPY OTC",
        "GBPJPY_otc",
    ]
    for asset in toxic_assets:
        is_toxic, reason = is_toxic_asset(asset)
        assert is_toxic is True, f"Asset {asset} should be recognized as toxic"
        assert "toxic OTC blacklist" in reason

    clean_assets = [
        "EUR/USD OTC",
        "EURUSD_otc",
        "USD/CLP OTC",
        "USDCLP_otc",
        "USDBDT_otc",
        "USDEGP_otc",
        "Gold OTC",
        "BTCUSD_otc",
    ]
    for asset in clean_assets:
        is_toxic, reason = is_toxic_asset(asset)
        assert is_toxic is False, f"Asset {asset} should NOT be toxic"
        assert reason == ""


def test_is_whitelisted_asset():
    """Verify curated high-winrate assets are recognized in whitelist."""
    whitelist_pairs = [
        "EUR/USD OTC",
        "EURUSD_otc",
        "USD/CLP OTC",
        "USDCLP_otc",
        "USD/BDT OTC",
        "USDBDT_otc",
        "USD/EGP OTC",
        "USDEGP_otc",
        "Gold OTC",
        "Gold_otc",
        "XAUUSD_otc",
    ]
    for asset in whitelist_pairs:
        assert is_whitelisted_asset(asset) is True, f"{asset} should be whitelisted"

    non_whitelist = [
        "USD/IDR OTC",
        "USDCAD_otc",
        "RandomCoin_otc",
        "GBP/JPY OTC",
        "GBPJPY_otc",
        "USD/DZD OTC",
        "EUR/HUF OTC",
    ]
    for asset in non_whitelist:
        assert is_whitelisted_asset(asset) is False, f"{asset} should not be whitelisted"


def test_filter_allowed_assets():
    """Verify filtering removes blacklisted toxic assets and supports whitelist-only."""
    raw_list = [
        "EURUSD_otc",
        "USD/IDR OTC",
        "USDCLP_otc",
        "USD/VND OTC",
        "GBPJPY_otc",
        "EURCHF_otc",
        "BTCUSD_otc",
    ]
    allowed = filter_allowed_assets(raw_list)
    assert "USD/IDR OTC" not in allowed
    assert "USD/VND OTC" not in allowed
    assert "EURCHF_otc" not in allowed
    assert "GBPJPY_otc" not in allowed
    assert "EURUSD_otc" in allowed
    assert "USDCLP_otc" in allowed
    assert "BTCUSD_otc" in allowed

    # Whitelist-only enforcement
    whitelist_only = filter_allowed_assets(raw_list, enforce_whitelist_only=True)
    assert "BTCUSD_otc" not in whitelist_only
    assert "GBPJPY_otc" not in whitelist_only
    assert set(whitelist_only) == {"EURUSD_otc", "USDCLP_otc"}


# =====================================================================
# 2. EMA Ribbon Overbought / Oversold Remediation Tests
# =====================================================================


def test_ema_pullback_trend_overbought_call_suppression():
    """Verify CALL is suppressed when RSI > 65 or Stoch_K > 75 in strong uptrend."""
    strat = EmaPullbackTrendStrategy(
        ema_fast=9,
        ema_mid=21,
        ema_slow=50,
        rsi_overbought=65.0,
        rsi_oversold=35.0,
        stoch_overbought=75.0,
        stoch_oversold=25.0,
    )

    # Build uptrend DataFrame where price pulled back to EMA fast/mid
    n = 60
    base_price = 1.1000
    df = pd.DataFrame(
        {
            "timestamp": [1000 + i * 60 for i in range(n)],
            "open": [base_price + i * 0.0005 for i in range(n)],
            "high": [base_price + i * 0.0005 + 0.0004 for i in range(n)],
            "low": [base_price + i * 0.0005 - 0.0001 for i in range(n)],
            "close": [base_price + i * 0.0005 + 0.0003 for i in range(n)],
            "volume": [100.0] * n,
        }
    )

    prepared = strat.prepare_dataframe(df)

    # Force simulated overbought indicators on bar 55
    prepared.loc[55, "ema_f"] = 1.1200
    prepared.loc[55, "ema_m"] = 1.1150
    prepared.loc[55, "ema_s"] = 1.1100
    prepared.loc[55, "adx"] = 30.0
    prepared.loc[55, "adx_pos"] = 28.0
    prepared.loc[55, "adx_neg"] = 12.0
    prepared.loc[55, "low"] = 1.1200  # Touches EMA Fast
    prepared.loc[55, "close"] = 1.1210
    prepared.loc[55, "open"] = 1.1202
    prepared.loc[55, "stoch_k"] = 82.0  # Overbought (> 75)
    prepared.loc[55, "stoch_d"] = 78.0
    prepared.loc[55, "rsi"] = 72.0  # Overbought (> 65)

    sig_overbought = strat.evaluate_bar(prepared, 55)
    assert sig_overbought.action is None, (
        "CALL must be rejected when RSI > 65 and Stoch > 75 on uptrend pullback"
    )

    # Reset RSI and Stoch to safe levels (RSI = 55 <= 65, Stoch = 60 <= 75)
    prepared.loc[55, "rsi"] = 55.0
    prepared.loc[55, "stoch_k"] = 60.0
    prepared.loc[55, "stoch_d"] = 55.0
    prepared.loc[54, "stoch_k"] = 50.0
    prepared.loc[54, "stoch_d"] = 52.0

    sig_valid = strat.evaluate_bar(prepared, 55)
    assert sig_valid.action == TradeAction.CALL, (
        "CALL must be triggered when RSI and Stoch are within safe bounds"
    )
    assert sig_valid.confidence >= 0.70


def test_ema_pullback_trend_oversold_put_suppression():
    """Verify PUT is suppressed when RSI < 35 or Stoch_K < 25 in strong downtrend."""
    strat = EmaPullbackTrendStrategy(
        ema_fast=9,
        ema_mid=21,
        ema_slow=50,
        rsi_overbought=65.0,
        rsi_oversold=35.0,
        stoch_overbought=75.0,
        stoch_oversold=25.0,
    )

    n = 60
    base_price = 1.2000
    df = pd.DataFrame(
        {
            "timestamp": [1000 + i * 60 for i in range(n)],
            "open": [base_price - i * 0.0005 for i in range(n)],
            "high": [base_price - i * 0.0005 + 0.0001 for i in range(n)],
            "low": [base_price - i * 0.0005 - 0.0004 for i in range(n)],
            "close": [base_price - i * 0.0005 - 0.0003 for i in range(n)],
            "volume": [100.0] * n,
        }
    )

    prepared = strat.prepare_dataframe(df)

    # Force simulated oversold indicators on bar 55
    prepared.loc[55, "ema_f"] = 1.1700
    prepared.loc[55, "ema_m"] = 1.1750
    prepared.loc[55, "ema_s"] = 1.1800
    prepared.loc[55, "adx"] = 32.0
    prepared.loc[55, "adx_pos"] = 10.0
    prepared.loc[55, "adx_neg"] = 30.0
    prepared.loc[55, "high"] = 1.1700  # Touches EMA Fast
    prepared.loc[55, "close"] = 1.1690
    prepared.loc[55, "open"] = 1.1698
    prepared.loc[55, "stoch_k"] = 18.0  # Oversold (< 25)
    prepared.loc[55, "stoch_d"] = 22.0
    prepared.loc[55, "rsi"] = 28.0  # Oversold (< 35)

    sig_oversold = strat.evaluate_bar(prepared, 55)
    assert sig_oversold.action is None, (
        "PUT must be rejected when RSI < 35 and Stoch < 25 on downtrend pullback"
    )

    # Reset RSI and Stoch to safe levels (RSI = 45 >= 35, Stoch = 40 >= 25)
    prepared.loc[55, "rsi"] = 45.0
    prepared.loc[55, "stoch_k"] = 40.0
    prepared.loc[55, "stoch_d"] = 45.0
    prepared.loc[54, "stoch_k"] = 50.0
    prepared.loc[54, "stoch_d"] = 48.0

    sig_valid = strat.evaluate_bar(prepared, 55)
    assert sig_valid.action == TradeAction.PUT, (
        "PUT must be triggered when RSI and Stoch are within safe bounds"
    )
    assert sig_valid.confidence >= 0.70


# =====================================================================
# 3. Support & Resistance Rejection Pin-Bar & Bounce Confirmation Tests
# =====================================================================


def test_sr_bounce_wick_ratio_and_directional_confirmation():
    """Verify S&R rejects wick ratio < 0.35 and non-bounce / opposing candles."""
    strat = SupportResistanceBounceStrategy(swing_window=20, min_wick_ratio=0.35)

    n = 40
    df = pd.DataFrame(
        {
            "timestamp": [1000 + i * 60 for i in range(n)],
            "open": [1.1000] * n,
            "high": [1.1020] * n,
            "low": [1.0980] * n,
            "close": [1.1000] * n,
            "volume": [100.0] * n,
        }
    )
    prepared = strat.prepare_dataframe(df)

    # Support level = 1.0950
    prepared.loc[35, "sr_support"] = 1.0950
    prepared.loc[35, "sr_resistance"] = 1.1050

    # Case A: Low tests support, but lower wick is too small (< 0.35)
    # Range = 0.0042, Lower wick = 0.0012 -> ratio = 0.285 (< 0.35)
    prepared.loc[35, "low"] = 1.0948
    prepared.loc[35, "high"] = 1.0990
    prepared.loc[35, "open"] = 1.0960
    prepared.loc[35, "close"] = 1.0980
    prepared.loc[35, "rsi"] = 35.0

    sig_small_wick = strat.evaluate_bar(prepared, 35)
    assert sig_small_wick.action is None, "CALL must be rejected when lower wick ratio < 0.35"

    # Case B: Wick is long (0.42), but candle closed bearish (breakdown attempt)
    # close < open_ (Bearish candle on support)
    prepared.loc[35, "low"] = 1.0948
    prepared.loc[35, "high"] = 1.1000
    prepared.loc[35, "open"] = 1.0980
    prepared.loc[35, "close"] = 1.0970
    prepared.loc[35, "rsi"] = 35.0

    sig_bearish_on_supp = strat.evaluate_bar(prepared, 35)
    assert sig_bearish_on_supp.action is None, (
        "CALL must be rejected when candle is bearish (close < open)"
    )

    # Case C: Genuine Bullish Pin-Bar bounce off support
    # Range = 0.0052, Lower wick = 0.0027 -> ratio = 0.519 (>= 0.35), close in upper 50%
    prepared.loc[35, "low"] = 1.0948
    prepared.loc[35, "high"] = 1.1000
    prepared.loc[35, "open"] = 1.0975
    prepared.loc[35, "close"] = 1.0995
    prepared.loc[35, "rsi"] = 38.0

    sig_confirmed_call = strat.evaluate_bar(prepared, 35)
    assert sig_confirmed_call.action == TradeAction.CALL, (
        "CALL must trigger on confirmed bullish pin-bar support bounce"
    )
    assert sig_confirmed_call.confidence >= 0.75

    # Case D: Genuine Bearish Pin-Bar rejection off resistance
    # Range = 0.0052, Upper wick = 0.0027 -> ratio = 0.519 (>= 0.35), close in lower 50%
    prepared.loc[35, "low"] = 1.1000
    prepared.loc[35, "high"] = 1.1052
    prepared.loc[35, "open"] = 1.1025
    prepared.loc[35, "close"] = 1.1005
    prepared.loc[35, "rsi"] = 65.0

    sig_confirmed_put = strat.evaluate_bar(prepared, 35)
    assert sig_confirmed_put.action == TradeAction.PUT, (
        "PUT must trigger on confirmed bearish pin-bar resistance bounce"
    )
    assert sig_confirmed_put.confidence >= 0.75


# =====================================================================
# 4. Strategy AutoMatcher Prioritization & Fallback Tests
# =====================================================================


@pytest.mark.asyncio
async def test_auto_matcher_toxic_asset_rejection_and_whitelist_boost():
    """Verify AutoMatcher rejects toxic OTC pairs and boosts whitelist pairs."""
    matcher = StrategyAutoMatcher(candle_count=150)

    # Toxic asset profiling
    toxic_res = await matcher.find_optimal_strategy_for_asset("USD/IDR OTC", [])
    assert toxic_res is None

    # Whitelist asset profiling fallback check
    white_res = await matcher.find_optimal_strategy_for_asset("Gold_otc", [])
    assert white_res.strategy_id == "support_resistance_bounce"
    assert white_res.quantum_score >= 80.0

    # Fallback for generic unclassified asset
    fallback_res = await matcher.find_optimal_strategy_for_asset("RANDOM_SYNTHETIC", [])
    assert fallback_res.strategy_id == "support_resistance_bounce"
    assert fallback_res.parameters["min_wick_ratio"] == 0.35


# =====================================================================
# 5. Pre-Trading Plan & Bot Engine Integration Tests
# =====================================================================


@pytest.mark.asyncio
async def test_generate_pre_trading_plan_filters_toxic_assets():
    """Verify generate_pre_trading_plan strips toxic pairs and builds clean plan."""
    mock_feed = AsyncMock()
    mock_feed.get_candles = AsyncMock(return_value=[])

    raw_assets = ["USD/IDR OTC", "EURUSD_otc", "USD/VND OTC", "USDCLP_otc", "EURCHF_otc"]
    plan = await generate_pre_trading_plan(feed=mock_feed, assets=raw_assets)

    assigned_assets = [a.asset for a in plan.assignments]
    assert "USD/IDR OTC" not in assigned_assets
    assert "USD/VND OTC" not in assigned_assets
    assert "EURCHF_otc" not in assigned_assets
    assert "EURUSD_otc" in assigned_assets
    assert "USDCLP_otc" in assigned_assets
    assert plan.toxic_filter_enabled is True


@pytest.mark.asyncio
async def test_live_demo_bot_engine_rejects_toxic_execution():
    """Verify LiveDemoBotEngine blocks evaluation and order placement on toxic pairs."""
    engine = LiveDemoBotEngine()
    mock_gateway = AsyncMock()
    mock_gateway.open_trade = AsyncMock(return_value=("order-123", {"percentProfit": 92}))

    plan = PreTradingPlan(
        assignments=[
            StrategyAssignment(
                asset="USD/IDR OTC",
                strategy_id="supertrend_adx_momentum",
                strategy_name="SuperTrend + ADX Momentum",
                category="Momentum",
                parameters={},
                estimated_win_rate_pct=60.0,
                estimated_profit_factor=1.5,
                estimated_trades_count=5,
                quantum_score=80.0,
            )
        ],
        total_assets=1,
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

    # 1. Evaluation check
    sem = asyncio.Semaphore(1)
    engine.plan = plan
    engine.status = engine.status.__class__.RUNNING
    engine._gateway = mock_gateway

    await engine._evaluate_single_asset(plan.assignments[0], datetime.now(UTC), sem)
    assert len(engine.active_trades) == 0

    # 2. Direct order execution check under order lock
    dummy_candle = Candle(
        open_time=datetime.now(UTC),
        open=Decimal("1.1000"),
        high=Decimal("1.1020"),
        low=Decimal("1.0980"),
        close=Decimal("1.1010"),
        volume=Decimal("100.0"),
    )
    await engine._execute_order(
        plan.assignments[0],
        action="CALL",
        confidence=0.80,
        reason="test",
        candles=[dummy_candle],
        live_payout=0.92,
    )
    assert len(engine.active_trades) == 0
    mock_gateway.open_trade.assert_not_called()


# =====================================================================
# 5. Requirement R2: Strategy-Calibrated Auto-Expiration Verification
# =====================================================================


def test_rsi_stochastic_extreme_default_expiration_calibration():
    """Verify RSI + Stochastic Extreme strategy defaults to 3 bars (180s) optimal calibration."""
    from strat_trade.domain.strategies.rsi_stochastic_extreme import RsiStochasticExtremeStrategy

    strat = RsiStochasticExtremeStrategy()
    assert strat.base_expiration_bars == 3

    param_defs = {p.name: p for p in strat.get_parameter_definitions()}
    assert "base_expiration_bars" in param_defs
    exp_def = param_defs["base_expiration_bars"]
    assert exp_def.default_value == 3
    assert exp_def.min_value == 1
    assert exp_def.max_value >= 4


def test_auto_assign_request_default_expiration():
    """Verify AutoAssignRequest defaults expiration_seconds to 180s without client input."""
    from strat_trade.api.schemas import AutoAssignRequest

    # Payload mimicking client without expiration_seconds
    req = AutoAssignRequest(
        assets=["EURUSD_otc", "USDCLP_otc"],
        initial_deposit=1000.0,
        stake_model="flat",
        stake_amount=10.0,
        stake_percent=1.0,
        daily_stop_loss_pct=0.05,
        max_concurrent_trades=3,
        min_payout_rate=0.80,
    )
    assert req.expiration_seconds == 180


@pytest.mark.asyncio
async def test_generate_pre_trading_plan_auto_expiration():
    """Verify pre-trading plan generation assigns 180s expiration and 3-bar strategy params."""
    mock_feed = AsyncMock()
    mock_feed.get_candles = AsyncMock(return_value=[])

    plan = await generate_pre_trading_plan(
        assets=["EURUSD_otc", "USDCLP_otc"],
        initial_deposit=1000.0,
        stake_model="flat",
        stake_amount=10.0,
        stake_percent=1.0,
        expiration_seconds=180,
        feed=mock_feed,
    )

    assert plan.expiration_seconds == 180
    for assignment in plan.assignments:
        assert assignment.parameters.get("base_expiration_bars") == 3


# =====================================================================
# 6. Requirement R3: Dynamic Microstructure Noise Filter & Cooldown Tests
# =====================================================================


def test_qualify_asset_microstructure_insufficient_or_malformed_data():
    """Verify qualify_asset_microstructure rejects < 50 candles, None, NaNs, missing cols."""
    # 1. None or empty
    qual, reason = qualify_asset_microstructure(None)  # type: ignore[arg-type]
    assert qual is False
    assert "Insufficient candle history" in reason

    qual, reason = qualify_asset_microstructure(pd.DataFrame())
    assert qual is False
    assert "0 < 50 bars required" in reason

    # 2. 49 bars (under 50 threshold)
    df_49 = pd.DataFrame(
        {
            "open": [1.1000] * 49,
            "high": [1.1010] * 49,
            "low": [1.0990] * 49,
            "close": [1.1005] * 49,
        }
    )
    qual, reason = qualify_asset_microstructure(df_49)
    assert qual is False
    assert "49 < 50 bars required" in reason

    # 3. Missing column
    df_missing = pd.DataFrame(
        {
            "open": [1.1000] * 55,
            "high": [1.1010] * 55,
            "close": [1.1005] * 55,
        }
    )
    qual, reason = qualify_asset_microstructure(df_missing)
    assert qual is False
    assert "Missing required column 'low'" in reason

    # 4. NaNs
    df_nan = pd.DataFrame(
        {
            "open": [1.1000] * 55,
            "high": [1.1010] * 55,
            "low": [1.0990] * 55,
            "close": [1.1005] * 54 + [float("nan")],
        }
    )
    qual, reason = qualify_asset_microstructure(df_nan)
    assert qual is False
    assert "NaN or non-numeric values" in reason

    # 5. Non-positive price
    df_neg = pd.DataFrame(
        {
            "open": [1.1000] * 55,
            "high": [1.1010] * 55,
            "low": [1.0990] * 55,
            "close": [1.1005] * 54 + [-0.05],
        }
    )
    qual, reason = qualify_asset_microstructure(df_neg)
    assert qual is False
    assert "non-positive price" in reason


def test_qualify_asset_microstructure_flat_bar_ratio():
    """Verify rejection when flat bar ratio > 0.15 (15%)."""
    n = 60
    # 20 flat bars out of 60 (33.3% > 15%)
    opens = [1.1000 + i * 0.0002 for i in range(n)]
    highs = [op + 0.0004 for op in opens]
    lows = [op - 0.0004 for op in opens]
    closes = [op + 0.0001 for op in opens]
    for i in range(20):
        highs[i] = opens[i]
        lows[i] = opens[i]
        closes[i] = opens[i]

    df_flat = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})
    qual, reason = qualify_asset_microstructure(df_flat)
    assert qual is False
    assert "Flat bar ratio" in reason
    assert "exceeds threshold 15.00%" in reason


def test_qualify_asset_microstructure_unique_price_ratio():
    """Verify rejection when unique close price ratio < 0.30 (30%) (discrete noise)."""
    n = 60
    # 5 discrete prices with 0 flat bars (body range > 0, high > low)
    # unique closes = 5 / 60 = 8.33% (< 30%)
    discrete_closes = [100.10, 100.20, 100.30, 100.40, 100.50]
    closes = [discrete_closes[i % 5] for i in range(n)]
    opens = [c - 0.03 for c in closes]
    highs = [c + 0.05 for c in closes]
    lows = [c - 0.05 for c in closes]

    df_discrete = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})
    qual, reason = qualify_asset_microstructure(df_discrete)
    assert qual is False
    assert "Unique price ratio" in reason
    assert "below threshold 30.00%" in reason


def test_qualify_asset_microstructure_whipsaw_sign_flip_ratio():
    """Verify rejection when whipsaw sign flip ratio > 0.80 (80%)."""
    n = 60
    # Unique close prices on every bar, but alternating positive/negative returns
    # closes: 1.2000, 1.2015, 1.2002, 1.2017, 1.2004, ...
    # returns: +0.0015, -0.0013, +0.0015, -0.0013, ... -> 100% sign flips
    closes = [1.2000 + i * 0.0001 + (0.0015 if i % 2 == 1 else 0.0) for i in range(n)]
    opens = [c - 0.0003 for c in closes]
    highs = [c + 0.0005 for c in closes]
    lows = [c - 0.0005 for c in closes]

    df_whipsaw = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})
    qual, reason = qualify_asset_microstructure(df_whipsaw)
    assert qual is False
    assert "Whipsaw sign flip ratio" in reason
    assert "exceeds threshold 80.00%" in reason


def test_qualify_asset_microstructure_relative_atr():
    """Verify rejection when relative ATR < 0.00003 (zero/dead volatility)."""
    n = 60
    # High close = 1000.0, but bar spread is 0.000001 -> relative ATR is < 0.00003
    base = 1000.0
    opens = [base + i * 0.00001 for i in range(n)]
    highs = [op + 0.000002 for op in opens]
    lows = [op - 0.000002 for op in opens]
    closes = [op + 0.000001 for op in opens]

    df_dead = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})
    qual, reason = qualify_asset_microstructure(df_dead)
    assert qual is False
    assert "Relative ATR" in reason
    assert "below threshold 0.000030" in reason


def test_qualify_asset_microstructure_continuous_liquid_assets():
    """Verify liquid OTC and Forex assets pass dynamic microstructure qualification."""
    import numpy as np

    np.random.seed(42)
    assets = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCLP", "USDBDT", "USDEGP", "Gold"]
    base_prices = {
        "EURUSD": 1.0850,
        "GBPUSD": 1.2650,
        "USDJPY": 154.20,
        "AUDUSD": 0.6550,
        "USDCLP": 920.0,
        "USDBDT": 110.0,
        "USDEGP": 48.5,
        "Gold": 2350.0,
    }

    n = 100
    for asset in assets:
        p0 = base_prices[asset]
        steps = np.random.normal(loc=0.00002 * p0, scale=0.0005 * p0, size=n)
        prices = p0 + np.cumsum(steps)
        highs = prices + np.abs(np.random.normal(loc=0.0003 * p0, scale=0.0001 * p0, size=n))
        lows = prices - np.abs(np.random.normal(loc=0.0003 * p0, scale=0.0001 * p0, size=n))
        opens = prices - steps * 0.5
        closes = prices

        df_liquid = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})
        qual, reason = qualify_asset_microstructure(df_liquid)
        assert qual is True, f"Liquid asset {asset} failed qualification: {reason}"
        assert "qualified" in reason


def test_filter_allowed_assets_with_microstructure_candle_data():
    """Verify filter_allowed_assets removes assets failing microstructure qualification."""
    import numpy as np

    np.random.seed(42)

    # Valid EURUSD data
    p = 1.0850 + np.cumsum(np.random.normal(0, 0.0003, 80))
    df_valid = pd.DataFrame(
        {
            "open": p - 0.0001,
            "high": p + 0.0004,
            "low": p - 0.0004,
            "close": p + 0.0001,
        }
    )

    # Dead zero-volatility asset
    df_dead = pd.DataFrame(
        {
            "open": [1.1000] * 80,
            "high": [1.1000] * 80,
            "low": [1.1000] * 80,
            "close": [1.1000] * 80,
        }
    )

    candle_data = {
        "EURUSD_otc": df_valid,
        "DEAD_ASSET_otc": df_dead,
    }

    raw = ["EURUSD_otc", "DEAD_ASSET_otc", "USD/IDR OTC"]
    filtered = filter_allowed_assets(raw, candle_data=candle_data)
    assert "EURUSD_otc" in filtered
    assert "DEAD_ASSET_otc" not in filtered
    assert "USD/IDR OTC" not in filtered


@pytest.mark.asyncio
async def test_bot_engine_anti_whipsaw_3min_cooldown_and_atomic_check():
    """Verify LiveDemoBotEngine enforces minimum 180s cooldown and atomic check in execution."""
    from datetime import timedelta

    from strat_trade.domain.trading.entities import IndicatorSnapshot, LiveTradeRecord, TradeOutcome

    engine = LiveDemoBotEngine()
    mock_gateway = AsyncMock()
    mock_gateway.open_trade = AsyncMock(return_value=("order-123", {"percentProfit": 92}))

    plan = PreTradingPlan(
        assignments=[
            StrategyAssignment(
                asset="EURUSD_otc",
                strategy_id="support_resistance_bounce",
                strategy_name="S&R Bounce",
                category="Price Action",
                parameters={},
                estimated_win_rate_pct=65.0,
                estimated_profit_factor=1.6,
                estimated_trades_count=5,
                quantum_score=85.0,
            )
        ],
        total_assets=1,
        initial_deposit=Decimal("1000.00"),
        stake_model="flat",
        stake_amount=Decimal("10.00"),
        stake_percent=1.0,
        expiration_seconds=180,
        daily_stop_loss_pct=0.05,
        stop_loss_amount=Decimal("50.00"),
        max_concurrent_trades=3,
        min_payout_rate=0.80,
        cooldown_bars=1,  # User requests 1 bar (60s), system enforces min 180s (3 min)
        bar_edge_guard_seconds=0.0,
    )

    engine.plan = plan
    engine.status = engine.status.__class__.RUNNING
    engine._gateway = mock_gateway

    # 1. Simulate trade settlement
    trade = LiveTradeRecord(
        trade_id="t-1",
        asset="EURUSD_otc",
        action="CALL",
        stake=Decimal("10.00"),
        open_time=datetime.now(UTC) - timedelta(seconds=180),
        expiration_seconds=180,
        open_price=Decimal("1.0850"),
        strategy_id="support_resistance_bounce",
        strategy_name="S&R Bounce",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
        outcome=TradeOutcome.PENDING,
    )
    engine.active_trades["t-1"] = trade

    # Settle trade
    await engine._check_active_trades()

    # Verify cooldown is at least 180s (3 minutes) despite cooldown_bars = 1
    cooldown_until = engine._asset_cooldown_until.get("EURUSD_otc")
    assert cooldown_until is not None
    now = datetime.now(UTC)
    remaining_sec = (cooldown_until - now).total_seconds()
    assert remaining_sec >= 170.0, f"Expected at least ~180s cooldown, got {remaining_sec}"

    # 2. Verify atomic order execution rejects repeat entry during active cooldown
    dummy_candle = Candle(
        open_time=datetime.now(UTC),
        open=Decimal("1.0850"),
        high=Decimal("1.0860"),
        low=Decimal("1.0840"),
        close=Decimal("1.0855"),
        volume=Decimal("100.0"),
    )
    await engine._execute_order(
        plan.assignments[0],
        action="CALL",
        confidence=0.85,
        reason="breakout",
        candles=[dummy_candle],
        live_payout=0.92,
    )
    # Order should be blocked by atomic cooldown check
    assert len(engine.active_trades) == 0
    mock_gateway.open_trade.assert_not_called()
