"""Exhaustive Combinatorial Fuzz Matrix for Milestone 2 Toxic Blacklist Verification.

Generates and executes thousands of permutations for all 6 new toxic OTC pairs,
existing toxic pairs, whitelisted clean pairs, and adversarial edge cases.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest

from strat_trade.api.routes.candles import _CURATED_ASSETS
from strat_trade.domain.entities import Candle
from strat_trade.domain.trading.asset_filter import (
    DEFAULT_HIGH_WINRATE_WHITELIST,
    DEFAULT_TOXIC_BLACKLIST,
    DEFAULT_TOXIC_OTC_BLACKLIST,
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
from strat_trade.settings import Settings
from strat_trade.use_cases.auto_assign_strategies import generate_pre_trading_plan

# 6 New toxic pairs + 5 existing toxic pairs
NEW_TOXIC_PAIRS = [
    ("USD", "DZD", "USDDZD"),
    ("UAH", "USD", "UAHUSD"),
    ("USD", "MYR", "USDMYR"),
    ("USD", "INR", "USDINR"),
    ("EUR", "HUF", "EURHUF"),
    ("GBP", "JPY", "GBPJPY"),
]

EXISTING_TOXIC_PAIRS = [
    ("USD", "IDR", "USDIDR"),
    ("USD", "VND", "USDVND"),
    ("BNB", "", "BNB"),
    ("BNB", "USD", "BNBUSD"),
    ("EUR", "CHF", "EURCHF"),
]

ALL_TOXIC_PAIRS = NEW_TOXIC_PAIRS + EXISTING_TOXIC_PAIRS

WHITELISTED_PAIRS = [
    ("EUR", "USD", "EURUSD"),
    ("USD", "CLP", "USDCLP"),
    ("USD", "BDT", "USDBDT"),
    ("USD", "EGP", "USDEGP"),
]

DELIMITERS = ["", "/", "-", "_", " ", ".", " / ", " - ", " _ "]
OTC_SUFFIXES = [
    "",
    " OTC",
    " otc",
    " Otc",
    " (OTC)",
    " (otc)",
    "(OTC)",
    "(otc)",
    "_OTC",
    "_otc",
    "-OTC",
    "-otc",
    "OTC",
    "otc",
    " [OTC]",
    " - OTC",
]
PADDINGS = ["", "  ", "\t", "   "]


def _casing_variants(s: str) -> list[str]:
    if not s:
        return [""]
    variants = {
        s.upper(),
        s.lower(),
        s.capitalize(),
        "".join(c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(s)),
        "".join(c.lower() if i % 2 == 0 else c.upper() for i, c in enumerate(s)),
    }
    return list(variants)


def generate_asset_fuzz_matrix(base: str, quote: str) -> list[str]:
    """Generates all combinations of casing, delimiters, OTC suffixes, and padding."""
    base_cases = _casing_variants(base)
    quote_cases = _casing_variants(quote) if quote else [""]

    variations = set()
    for b in base_cases:
        for q in quote_cases:
            for delim in DELIMITERS:
                core = b if not q else f"{b}{delim}{q}"
                for otc in OTC_SUFFIXES:
                    for pad in PADDINGS:
                        variations.add(f"{pad}{core}{otc}{pad}")
    return list(variations)


def test_constants_and_settings_consistency():
    """Verify blacklist and whitelist consistency across domain, settings, and routes."""
    # 1. Domain Constants
    assert DEFAULT_TOXIC_OTC_BLACKLIST == DEFAULT_TOXIC_BLACKLIST
    expected_toxic_keys = {
        "USDIDR",
        "USDVND",
        "BNB",
        "BNBUSD",
        "EURCHF",
        "USDDZD",
        "UAHUSD",
        "USDMYR",
        "USDINR",
        "EURHUF",
        "GBPJPY",
    }
    assert DEFAULT_TOXIC_OTC_BLACKLIST.issuperset(expected_toxic_keys)

    expected_whitelist_keys = {
        "EURUSD",
        "USDCLP",
        "USDBDT",
        "USDEGP",
        "GOLD",
        "XAUUSD",
    }
    assert DEFAULT_HIGH_WINRATE_WHITELIST == expected_whitelist_keys

    # GBPJPY must NEVER be in whitelist
    assert "GBPJPY" not in DEFAULT_HIGH_WINRATE_WHITELIST

    # 2. Settings defaults
    s = Settings()
    toxic_settings_canonical = {canonical_asset_key(a) for a in s.toxic_asset_blacklist}
    assert toxic_settings_canonical == {
        "USDIDR",
        "USDVND",
        "BNB",
        "EURCHF",
        "USDDZD",
        "UAHUSD",
        "USDMYR",
        "USDINR",
        "EURHUF",
        "GBPJPY",
    }

    whitelist_settings_canonical = {canonical_asset_key(a) for a in s.high_winrate_asset_whitelist}
    assert whitelist_settings_canonical == {"EURUSD", "USDCLP", "USDBDT", "USDEGP", "GOLD"}
    assert "GBPJPY" not in whitelist_settings_canonical

    # 3. Curated assets routes
    curated_symbols = [c["symbol"] for c in _CURATED_ASSETS]
    assert "GBPJPY_otc" not in curated_symbols
    assert "gbpjpy_otc" not in [s.lower() for s in curated_symbols]


def test_exhaustive_fuzz_toxic_rejection_matrix():
    """Combinatorially fuzzes all 11 toxic asset pairs (including all 6 new pairs).

    Verifies 100% rejection rate across canonical_asset_key, is_toxic_asset,
    and filter_allowed_assets.
    """
    total_tested = 0
    failures = []

    for base, quote, expected_canonical in ALL_TOXIC_PAIRS:
        fuzz_samples = generate_asset_fuzz_matrix(base, quote)
        for raw in fuzz_samples:
            total_tested += 1

            # 1. Canonical Key
            key = canonical_asset_key(raw)
            if key != expected_canonical:
                failures.append(
                    f"Canonical mismatch: '{raw}' -> '{key}' (exp '{expected_canonical}')"
                )
                continue

            # 2. is_toxic_asset detection
            is_toxic, reason = is_toxic_asset(raw)
            if not is_toxic or "toxic OTC blacklist" not in reason:
                failures.append(f"Toxic detection failed: '{raw}' -> {is_toxic}, '{reason}'")
                continue

            # 3. is_whitelisted_asset must be False
            if is_whitelisted_asset(raw):
                failures.append(f"Toxic asset incorrectly whitelisted: '{raw}'")
                continue

            # 4. filter_allowed_assets must strip toxic asset
            allowed_standard = filter_allowed_assets([raw], enforce_whitelist_only=False)
            if allowed_standard:
                failures.append(f"filter_allowed_assets (standard) failed to reject: '{raw}'")
                continue

            allowed_strict = filter_allowed_assets([raw], enforce_whitelist_only=True)
            if allowed_strict:
                failures.append(f"filter_allowed_assets (strict) failed to reject: '{raw}'")
                continue

    assert len(failures) == 0, (
        f"Encountered {len(failures)} failures out of {total_tested} test cases:\n"
        + "\n".join(failures[:20])
    )
    assert total_tested >= 20000, f"Expected at least 20,000 fuzz variations, got {total_tested}"


def test_exhaustive_fuzz_whitelisted_assets_matrix():
    """Combinatorially fuzzes all whitelisted assets to ensure zero false positives."""
    total_tested = 0
    failures = []

    for base, quote, expected_canonical in WHITELISTED_PAIRS:
        fuzz_samples = generate_asset_fuzz_matrix(base, quote)
        for raw in fuzz_samples:
            total_tested += 1

            # 1. Canonical Key
            key = canonical_asset_key(raw)
            if key != expected_canonical:
                failures.append(
                    f"Whitelist canonical mismatch: '{raw}' -> '{key}' (exp '{expected_canonical}')"
                )
                continue

            # 2. is_toxic_asset must be False
            is_toxic, reason = is_toxic_asset(raw)
            if is_toxic:
                failures.append(f"Clean asset flagged as toxic: '{raw}', reason: {reason}")
                continue

            # 3. is_whitelisted_asset must be True
            if not is_whitelisted_asset(raw):
                failures.append(f"Whitelisted asset failed detection: '{raw}'")
                continue

            # 4. filter_allowed_assets must preserve clean whitelisted asset
            allowed_standard = filter_allowed_assets([raw], enforce_whitelist_only=False)
            if allowed_standard != [raw]:
                failures.append(f"filter_allowed_assets (standard) dropped clean asset: '{raw}'")
                continue

            allowed_strict = filter_allowed_assets([raw], enforce_whitelist_only=True)
            if allowed_strict != [raw]:
                failures.append(f"filter_allowed_assets (strict) dropped clean asset: '{raw}'")
                continue

    # Gold & XAUUSD variations
    gold_samples = [
        "Gold OTC",
        "gold otc",
        "GOLD_OTC",
        "Gold_otc",
        "GOLD (OTC)",
        "gold",
        "GOLD",
        "XAU/USD OTC",
        "xau/usd otc",
        "XAUUSD_otc",
        "xauusd_otc",
        "XAU-USD (OTC)",
        "  Gold OTC  ",
    ]
    for raw in gold_samples:
        total_tested += 1
        key = canonical_asset_key(raw)
        assert key == "GOLD"
        is_toxic, _ = is_toxic_asset(raw)
        assert is_toxic is False
        assert is_whitelisted_asset(raw) is True
        assert filter_allowed_assets([raw]) == [raw]

    assert len(failures) == 0, (
        f"Encountered {len(failures)} failures out of {total_tested} test cases:\n"
        + "\n".join(failures[:20])
    )
    assert total_tested >= 8000


def test_adversarial_malformed_and_boundary_cases():
    """Adversarial stress-testing of malformed strings, nulls, special characters."""
    adversarial_inputs: list[Any] = [
        None,
        "",
        "   ",
        "\t\n\r",
        12345,
        3.14159,
        True,
        False,
        [],
        {},
        "USD/DZD\x00OTC",
        "UAH\uff0fUSD OTC",
        "USD_MYR\u200bOTC",
        "USD\u00a0INR OTC",
        "EUR/HUF\tOTC\n",
        "!!!GBPJPY???",
        "USD/DZD/EXTRA/PARTS",
        "__USDDZD__",
        "--GBPJPY--",
    ]

    for item in adversarial_inputs:
        key = canonical_asset_key(item)
        assert isinstance(key, str)

        is_toxic, reason = is_toxic_asset(item)
        assert isinstance(is_toxic, bool)
        assert isinstance(reason, str)

        whitelisted = is_whitelisted_asset(item)
        assert isinstance(whitelisted, bool)


def test_mixed_portfolio_filtering_and_fallback():
    """Verifies mixed portfolio filtering containing all new toxic pairs alongside valid pairs."""
    mixed_portfolio = [
        "USD/DZD OTC",  # Toxic 1
        "EUR/USD OTC",  # Whitelist
        "UAH/USD OTC",  # Toxic 2
        "GBP/USD OTC",  # Regular allowed
        "USD/MYR OTC",  # Toxic 3
        "USD/CLP OTC",  # Whitelist
        "USD/INR OTC",  # Toxic 4
        "USD/JPY OTC",  # Regular allowed
        "EUR/HUF OTC",  # Toxic 5
        "USD/BDT OTC",  # Whitelist
        "GBP/JPY OTC",  # Toxic 6
        "USD/EGP OTC",  # Whitelist
        "Gold OTC",  # Whitelist
    ]

    # Standard filter: toxic removed, regular and whitelist preserved
    standard_filtered = filter_allowed_assets(mixed_portfolio, enforce_whitelist_only=False)
    assert standard_filtered == [
        "EUR/USD OTC",
        "GBP/USD OTC",
        "USD/CLP OTC",
        "USD/JPY OTC",
        "USD/BDT OTC",
        "USD/EGP OTC",
        "Gold OTC",
    ]

    # Strict whitelist filter: toxic and regular removed, only whitelist preserved
    strict_filtered = filter_allowed_assets(mixed_portfolio, enforce_whitelist_only=True)
    assert strict_filtered == [
        "EUR/USD OTC",
        "USD/CLP OTC",
        "USD/BDT OTC",
        "USD/EGP OTC",
        "Gold OTC",
    ]


@pytest.mark.asyncio
async def test_generate_pre_trading_plan_all_toxic_fallback():
    """When all input assets are toxic, fallback provides 5 curated non-toxic assets."""
    feed = AsyncMock()
    feed.get_recent_candles = AsyncMock(
        return_value=[
            Candle(
                open_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC) + timedelta(minutes=i),
                open=Decimal("1.1000"),
                high=Decimal("1.1010"),
                low=Decimal("1.0990"),
                close=Decimal("1.1005"),
                volume=Decimal("100"),
            )
            for i in range(150)
        ]
    )

    toxic_assets = [
        "USD/DZD OTC",
        "UAH/USD OTC",
        "USD/MYR OTC",
        "USD/INR OTC",
        "EUR/HUF OTC",
        "GBP/JPY OTC",
    ]

    plan = await generate_pre_trading_plan(feed, assets=toxic_assets, toxic_filter_enabled=True)
    assert len(plan.assignments) == 5
    assigned_assets = [a.asset for a in plan.assignments]
    assert assigned_assets == ["EURUSD_otc", "USDCLP_otc", "USDBDT_otc", "USDEGP_otc", "Gold_otc"]
    for a in assigned_assets:
        is_toxic, _ = is_toxic_asset(a)
        assert is_toxic is False


@pytest.mark.asyncio
async def test_bot_engine_rejection_of_all_new_toxic_pairs():
    """Verifies that LiveDemoBotEngine rejects signals and orders for all 6 new toxic pairs."""
    bot = LiveDemoBotEngine()
    assignments = [
        StrategyAssignment(
            asset=f"{canonical}_otc",
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
        for _, _, canonical in NEW_TOXIC_PAIRS
    ]

    plan = PreTradingPlan(
        assignments=assignments,
        total_assets=len(assignments),
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
    )

    gateway_mock = AsyncMock()
    gateway_mock.get_candles = AsyncMock(return_value=[])
    gateway_mock.open_trade = AsyncMock(return_value=("order_123", {"percentProfit": 92}))

    await bot.start(plan, gateway_mock)
    assert bot.status == BotStatus.RUNNING

    sem = asyncio.Semaphore(1)
    now = datetime.now(UTC)
    dummy_candle = Candle(
        open_time=now,
        open=Decimal("1.10"),
        high=Decimal("1.11"),
        low=Decimal("1.09"),
        close=Decimal("1.10"),
        volume=Decimal("100"),
    )

    for assignment in assignments:
        # 1. Single asset evaluation check
        await bot._evaluate_single_asset(assignment, now, sem)
        assert gateway_mock.get_candles.call_count == 0

        # 2. Direct order execution check under mutex
        await bot._execute_order(
            assignment=assignment,
            action="CALL",
            confidence=0.85,
            reason="Stress Test",
            candles=[dummy_candle],
            live_payout=0.92,
        )
        assert gateway_mock.open_trade.call_count == 0

    assert len(bot.active_trades) == 0
    await bot.stop()
