"""Asset Quality Filter & Toxic Pair Blacklist / High-Winrate Whitelist.

Provides canonical normalization, blacklist filtering for toxic OTC pairs with
high slippage / discrete quotes, and whitelist prioritization for high-winrate assets.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from strat_trade.domain.trading.correlation import normalize_symbol

logger = logging.getLogger(__name__)

# Default Canonical Toxic Assets (Discretized, high-slippage OTC pairs)
DEFAULT_TOXIC_OTC_BLACKLIST: frozenset[str] = frozenset(
    {
        "USDIDR",  # USD/IDR OTC
        "USDVND",  # USD/VND OTC
        "BNB",  # BNB OTC
        "BNBUSD",  # BNB/USD OTC
        "EURCHF",  # EUR/CHF OTC
        "USDDZD",  # USD/DZD OTC
        "UAHUSD",  # UAH/USD OTC
        "USDMYR",  # USD/MYR OTC
        "USDINR",  # USD/INR OTC
        "EURHUF",  # EUR/HUF OTC
        "GBPJPY",  # GBP/JPY OTC
        "SYPUSD",  # SYP/USD OTC (Synthetic zero-ATR micro-pip)
        "LBPUSD",  # LBP/USD OTC (Synthetic zero-ATR micro-pip)
        "USDPKR",  # USD/PKR OTC
        "AEDCNY",  # AED/CNY OTC
        "ZARUSD",  # ZAR/USD OTC
        "USDCOP",  # USD/COP OTC
        "AUDCHF",  # AUD/CHF OTC
        "USDTHB",  # USD/THB OTC
        "QARCNY",  # QAR/CNY OTC
        "USDRUB",  # USD/RUB OTC
        "EURGBP",  # EUR/GBP OTC
        "BHDCNY",  # BHD/CNY OTC
        "USDBRL",  # USD/BRL OTC
        "CHFNOK",  # CHF/NOK OTC
        "NZDJPY",  # NZD/JPY OTC
        "USDMXN",  # USD/MXN OTC
        "CHFJPY",  # CHF/JPY Spot & OTC
        "EURJPY",  # EUR/JPY OTC
        "USDSGD",  # USD/SGD OTC (High-slippage discrete jumps)
        "CADCHF",  # CAD/CHF OTC (Choppy low-volatility traps)
        "USDCHF",  # USD/CHF OTC (Choppy low-volatility traps)
        "AUDJPY",  # AUD/JPY OTC & Spot (Persistent trend runaways)
        "GBPAUD",  # GBP/AUD OTC (High-spread volatility spikes)
        "YERUSD",  # YER/USD OTC (Synthetic exotic)
        "KESUSD",  # KES/USD OTC (Synthetic exotic)
    }
)
DEFAULT_TOXIC_BLACKLIST = DEFAULT_TOXIC_OTC_BLACKLIST

# Default Canonical High-Winrate Pairs (Smooth price action, high payout)
DEFAULT_HIGH_WINRATE_WHITELIST: frozenset[str] = frozenset(
    {
        "EURUSD",  # EUR/USD OTC
        "USDCLP",  # USD/CLP OTC
        "USDBDT",  # USD/BDT OTC
        "USDEGP",  # USD/EGP OTC
        "GOLD",  # Gold OTC
        "XAUUSD",  # XAU/USD OTC
    }
)


def canonical_asset_key(asset: str | None) -> str:
    """Normalizes symbol to uppercase alphanumeric key (e.g. 'USD/IDR OTC' -> 'USDIDR')."""
    if not asset or not isinstance(asset, str):
        return ""
    clean = normalize_symbol(asset)
    if clean in ("GOLD", "XAUUSD"):
        return "GOLD"
    return clean


def is_otc_asset(asset: str | None) -> bool:
    """True for broker-synthesised OTC quotes, which trade 24/7 off-exchange."""
    if not asset or not isinstance(asset, str):
        return False
    return "OTC" in asset.upper()


def is_spot_market_closed(current_time: datetime | None = None) -> tuple[bool, str]:
    """Exchange-backed FX is closed from Fri 21:00 UTC until Sun 21:00 UTC.

    Quotes may still be served during the weekend but they are stale, so any
    spot signal formed in that window is based on a frozen tape.
    """
    now_utc = current_time or datetime.now(UTC)
    weekday = now_utc.weekday()  # Monday == 0, Sunday == 6
    mins = now_utc.hour * 60 + now_utc.minute

    is_closed = (
        weekday == 5  # Saturday
        or (weekday == 4 and mins >= 21 * 60)  # Friday after 21:00 UTC
        or (weekday == 6 and mins < 21 * 60)  # Sunday before 21:00 UTC
    )
    if is_closed:
        return True, (
            "Spot FX market is closed for the weekend "
            f"(Fri 21:00 - Sun 21:00 UTC, current: {now_utc.strftime('%a %H:%M')} UTC)"
        )
    return False, ""


def is_toxic_asset(
    asset: str | None,
    custom_blacklist: Sequence[str] | None = None,
) -> tuple[bool, str]:
    """Returns (is_toxic, reason) if asset matches toxic blacklist."""
    key = canonical_asset_key(asset)
    if not key:
        return False, ""

    if custom_blacklist:
        blacklist = {canonical_asset_key(x) for x in custom_blacklist}
    else:
        blacklist = {canonical_asset_key(x) for x in DEFAULT_TOXIC_OTC_BLACKLIST}

    if key in blacklist:
        return True, f"Asset '{asset}' ({key}) is in the toxic OTC blacklist"
    return False, ""


def is_whitelisted_asset(
    asset: str | None,
    custom_whitelist: Sequence[str] | None = None,
) -> bool:
    """Returns True if asset is in high-winrate whitelist."""
    key = canonical_asset_key(asset)
    if not key:
        return False

    if custom_whitelist:
        whitelist = {canonical_asset_key(x) for x in custom_whitelist}
    else:
        whitelist = {canonical_asset_key(x) for x in DEFAULT_HIGH_WINRATE_WHITELIST}

    return key in whitelist


def qualify_asset_microstructure(candles: pd.DataFrame) -> tuple[bool, str]:
    """Evaluates statistical price action metrics to qualify continuous liquid assets.

    Rejects quantized step-tick exotics, flat zero-volatility feeds, and micro-whipsaw noise.

    Metrics:
    - Minimum 50 candles required.
    - flat_bar_ratio: proportion of bars with high == low or zero body range
      (|close - open| <= 1e-9). Reject if > 0.15 (15%).
    - unique_price_ratio: unique close prices / total bars. Reject if < 0.30 (30%).
    - whipsaw_sign_flip_ratio: proportion of consecutive 1-bar returns flipping sign.
      Reject if > 0.80 (80%).
    - relative_atr: ATR(14) / Close. Reject if < 0.00003.

    Returns:
        (is_qualified, diagnostic_reason)
    """
    if candles is None or not isinstance(candles, pd.DataFrame) or len(candles) < 50:
        count = len(candles) if isinstance(candles, pd.DataFrame) else 0
        return False, f"Insufficient candle history ({count} < 50 bars required)"

    required_cols = ["open", "high", "low", "close"]
    for col in required_cols:
        if col not in candles.columns:
            return False, f"Missing required column '{col}'"

    df = candles[required_cols].apply(pd.to_numeric, errors="coerce")
    if df.isna().any().any():
        return False, "Candle dataframe contains NaN or non-numeric values"

    if (df["close"] <= 0).any():
        return False, "Candle dataframe contains non-positive price values"

    n_bars = len(df)

    # 1. Flat-bar ratio: high == low or zero body range (close == open)
    is_flat = (df["high"] <= df["low"] + 1e-9) | ((df["close"] - df["open"]).abs() <= 1e-9)
    flat_bar_ratio = float(is_flat.mean())
    if flat_bar_ratio > 0.15:
        return (
            False,
            f"Flat bar ratio {flat_bar_ratio:.2%} exceeds threshold 15.00% "
            "(discrete/illiquid noise)",
        )

    # 2. Unique close price ratio
    unique_closes = df["close"].nunique()
    unique_price_ratio = float(unique_closes / n_bars)
    if unique_price_ratio < 0.30:
        return (
            False,
            f"Unique price ratio {unique_price_ratio:.2%} below threshold 30.00% "
            "(discrete step-tick noise)",
        )

    # 3. Whipsaw sign flip ratio
    returns = df["close"].diff().dropna()
    prod = returns.iloc[1:].values * returns.iloc[:-1].values
    valid_pairs = len(prod)
    if valid_pairs > 0:
        sign_flips = int((prod < 0).sum())
        whipsaw_sign_flip_ratio = float(sign_flips / valid_pairs)
    else:
        whipsaw_sign_flip_ratio = 0.0

    if whipsaw_sign_flip_ratio > 0.80:
        return (
            False,
            f"Whipsaw sign flip ratio {whipsaw_sign_flip_ratio:.2%} exceeds threshold 80.00% "
            "(alternating noise)",
        )

    # 4. Relative ATR(14)
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr14 = float(tr.rolling(window=14).mean().iloc[-1])
    curr_close = float(close.iloc[-1])
    if curr_close <= 0 or np.isnan(atr14):
        return False, "Invalid price data for ATR calculation"

    if curr_close < 0.001:
        return (
            False,
            f"Price {curr_close:.8f} is below 0.001000 (ultra-micro tick synthetic asset)",
        )

    relative_atr = float(atr14 / curr_close)
    if relative_atr < 0.00003:
        return (
            False,
            f"Relative ATR {relative_atr:.6f} below threshold 0.000030 (dead/zero volatility)",
        )

    return True, "Asset microstructure qualified (continuous, liquid, valid volatility)"


def filter_allowed_assets(
    assets: Sequence[str],
    blacklist: Sequence[str] | None = None,
    whitelist: Sequence[str] | None = None,
    enforce_whitelist_only: bool = False,
    candle_data: dict[str, pd.DataFrame] | None = None,
) -> list[str]:
    """Filters out toxic assets and optionally enforces whitelist-only / microstructure."""
    out: list[str] = []
    for a in assets:
        toxic, _ = is_toxic_asset(a, blacklist)
        if toxic:
            continue
        if enforce_whitelist_only and not is_whitelisted_asset(a, whitelist):
            continue
        if candle_data and a in candle_data:
            df = candle_data[a]
            if isinstance(df, pd.DataFrame) and len(df) >= 50:
                qualified, _ = qualify_asset_microstructure(df)
                if not qualified:
                    continue
        out.append(a)
    return out


def is_asset_in_active_session(
    asset: str | None,
    current_time: datetime | None = None,
    buffer_minutes: int = 30,
) -> tuple[bool, str]:
    """Determines whether the given asset is in an active liquid trading session (UTC).

    Suppresses trading during low-liquidity transition gaps, nocturnal discrete dead zones,
    and market rollover periods for both Spot and OTC quotes.

    Session windows describe exchange liquidity, so they apply to spot quotes.
    OTC quotes are synthesised by the broker and run continuously, therefore
    they are exempt from the London/NY and Asian windows but still respect the
    exotic nocturnal dead zone and commodity rollover breaks.

    Trading Session Windows (UTC):
    - Spot FX: closed Fri 21:00 - Sun 21:00 UTC (weekend).
    - Asian / Pacific (JPY, AUD, NZD, SGD, CNH, CNY, HKD): 00:00 - 22:00 UTC
    - European / US (EUR, GBP, CHF, USD, CAD, TRY, RUB, NOK, SEK, PLN): 06:30 - 22:00 UTC
    - Commodities (GOLD, SILVER, XAU, XAG): 00:00 - 21:30 & 23:30 - 24:00 UTC
    - Exotic / LatAm / Middle East Nocturnal Dead Zone (THB, YER, BHD, NGN, MAD,
      PKR, LBP, SYP, QAR, TND, EGP, BDT, ZAR, ARS, COP, CLP, BRL, MXN):
      Active daytime window: 04:00 - 20:30 UTC. Blocked: 20:30 - 04:00 UTC.

    Returns:
        (is_active, diagnostic_reason)
    """
    if not asset or not isinstance(asset, str):
        return False, "Invalid or empty asset identifier"

    now_utc = current_time or datetime.now(UTC)
    hour = now_utc.hour
    minute = now_utc.minute
    current_mins = hour * 60 + minute
    is_otc = is_otc_asset(asset)

    clean = asset.upper().replace("/", "").replace("_OTC", "").replace(" OTC", "").replace(" ", "")

    # 0. Weekend Gate - spot instruments have no live tape outside market hours
    if not is_otc:
        closed, closed_reason = is_spot_market_closed(now_utc)
        if closed:
            return False, f"Spot asset '{asset}' blocked: {closed_reason}"

    # 1. Exotic Nocturnal Dead Zone Check
    exotics = (
        "THB",
        "YER",
        "BHD",
        "NGN",
        "MAD",
        "PKR",
        "LBP",
        "SYP",
        "QAR",
        "TND",
        "EGP",
        "BDT",
        "ZAR",
        "ARS",
        "COP",
        "CLP",
        "BRL",
        "MXN",
    )
    if any(ex in clean for ex in exotics):
        # Active window: 04:00 UTC (240m) to 20:30 UTC (1230m)
        if not (240 <= current_mins <= 1230):
            return (
                False,
                f"Exotic asset '{asset}' is in nocturnal low-liquidity/discrete dead zone "
                f"(active 04:00-20:30 UTC, current: {now_utc.strftime('%H:%M')} UTC)",
            )
        return True, f"Exotic asset '{asset}' active in daytime window (04:00-20:30 UTC)"

    # 2. Commodities (GOLD, SILVER, XAU, XAG)
    if any(c in clean for c in ("GOLD", "SILVER", "XAU", "XAG")):
        # Daily rollover break: 21:30 - 23:30 UTC
        if 1290 <= current_mins <= 1410:
            return (
                False,
                f"Commodity '{asset}' in daily rollover break "
                f"(21:30-23:30 UTC, current: {now_utc.strftime('%H:%M')} UTC)",
            )
        return True, f"Commodity '{asset}' active"

    # 2b. OTC quotes are broker-synthesised and quoted around the clock
    if is_otc:
        return True, f"OTC asset '{asset}' quoted continuously (session windows not applicable)"

    # 3. Asian / Pacific primary (JPY, AUD, NZD, SGD, CNH, CNY, HKD)
    asian_pacific = ("JPY", "AUD", "NZD", "SGD", "CNH", "CNY", "HKD")
    has_asian_component = any(ap in clean for ap in asian_pacific)

    # 4. European / American primary
    european = ("EUR", "GBP", "CHF", "TRY", "RUB", "NOK", "SEK", "PLN")
    american = ("USD", "CAD")

    has_european = any(eu in clean for eu in european)
    has_american = any(am in clean for am in american)

    # If pair contains an Asian/Pacific component
    if has_asian_component:
        # Active across Tokyo, Sydney, London, and NY sessions: 00:00 to 22:00 UTC
        if not (0 <= current_mins <= 1320):  # 22:00 UTC is 1320m
            return (
                False,
                f"Asset '{asset}' in session transition pause "
                f"(active 00:00-22:00 UTC, current: {now_utc.strftime('%H:%M')} UTC)",
            )
        return True, f"Asset '{asset}' active in Asian/Global session (00:00-22:00 UTC)"

    # Purely European / American pairs (e.g. EUR/USD, GBP/USD, EUR/GBP, USD/CAD, CAD/CHF)
    if has_european or has_american:
        start_mins = 6 * 60 + 30  # 06:30 UTC (London open with 30m buffer)
        end_mins = 22 * 60  # 22:00 UTC (NY close)
        if not (start_mins <= current_mins <= end_mins):
            return (
                False,
                f"European/US asset '{asset}' is outside active London/NY session "
                f"(active 06:30-22:00 UTC, current: {now_utc.strftime('%H:%M')} UTC)",
            )
        return True, f"European/US asset '{asset}' active in London/NY session (06:30-22:00 UTC)"

    return True, "Asset session active"
