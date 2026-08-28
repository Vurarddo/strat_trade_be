"""Currency Pair Correlation & Directional Exposure Filter.

Decomposes currency pairs into base and quote currencies, extracts directional
exposure (Long/Short) based on binary option action (CALL/PUT), and detects
correlated exposure conflicts to prevent risk over-concentration across active trades.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Any


class DirectionalBias(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


# Standard currency codes commonly traded in binary options (Forex & Crypto)
KNOWN_CURRENCIES: frozenset[str] = frozenset(
    {
        "USD",
        "EUR",
        "GBP",
        "JPY",
        "AUD",
        "NZD",
        "CAD",
        "CHF",
        "CNH",
        "CNY",
        "SGD",
        "HKD",
        "SEK",
        "NOK",
        "MXN",
        "ZAR",
        "TRY",
        "PLN",
        "INR",
        "BRL",
        "KRW",
        "RUB",
        "BTC",
        "ETH",
    }
)

# Reference statistical correlation benchmark between major currency pairs
MAJOR_PAIR_CORRELATIONS: dict[frozenset[str], float] = {
    frozenset({"EURUSD", "GBPUSD"}): 0.82,
    frozenset({"EURUSD", "USDCHF"}): -0.91,
    frozenset({"AUDUSD", "NZDUSD"}): 0.85,
    frozenset({"EURUSD", "USDJPY"}): -0.45,
    frozenset({"GBPUSD", "USDCHF"}): -0.78,
    frozenset({"AUDUSD", "EURUSD"}): 0.65,
    frozenset({"USDCAD", "USDCHF"}): 0.60,
    frozenset({"EURGBP", "GBPUSD"}): -0.70,
}


def normalize_symbol(asset: str | None) -> str:
    """Normalizes asset string to canonical uppercase format (e.g., 'AUDUSD_otc' -> 'AUDUSD').

    Strips OTC tags, separators, spaces, and casing.
    """
    if not asset or not isinstance(asset, str):
        return ""
    s = asset.strip().upper()
    # Remove parenthesized notes like (OTC)
    s = re.sub(r"\(.*?\)", "", s)
    # Strip OTC suffix or word token (e.g. _OTC, -OTC, space OTC, or standalone OTC)
    s = re.sub(r"[_\-\s]?OTC\b", "", s)
    if s.endswith("OTC"):
        s = s[:-3]
    # Strip all non-alphanumeric characters
    clean = re.sub(r"[^A-Z0-9]", "", s)
    return clean


def extract_currency_pair(asset: str | None) -> tuple[str, str] | None:
    """Extracts (base, quote) currencies from asset symbol.

    Examples:
        'AUDUSD_otc'    -> ('AUD', 'USD')
        'EURUSD_otc'    -> ('EUR', 'USD')
        'USDCHF'        -> ('USD', 'CHF')
        'USD/CHF OTC'   -> ('USD', 'CHF')
        'EUR-USD'       -> ('EUR', 'USD')
        'audnzd_otc'    -> ('AUD', 'NZD')
        'BTCUSD_otc'    -> ('BTC', 'USD')
        'INVALID'       -> None
        'AAPL'          -> None

    Returns:
        tuple[str, str] representing (base_currency, quote_currency), or None if unparseable.
    """
    clean = normalize_symbol(asset)
    if len(clean) == 6 and clean.isalpha():
        base = clean[:3]
        quote = clean[3:]
        if base != quote:
            return base, quote
    return None


def get_directional_exposure(
    asset: str,
    action: str | Any,
) -> tuple[str, str] | None:
    """Calculates directional currency exposure for a binary option trade.

    Exposure rules:
    - CALL on BASE/QUOTE: Expect Base to rise vs Quote -> Long BASE, Short QUOTE
    - PUT on BASE/QUOTE:  Expect Base to fall vs Quote -> Short BASE, Long QUOTE

    Returns:
        tuple[str, str] representing (long_currency, short_currency), or None if invalid.
    """
    pair = extract_currency_pair(asset)
    if not pair:
        return None
    base, quote = pair

    act_str = action.value if hasattr(action, "value") else str(action or "").upper().strip()

    if act_str == "CALL":
        return base, quote  # Long base, Short quote
    elif act_str == "PUT":
        return quote, base  # Long quote, Short base
    return None


def _extract_trade_info(trade: Any) -> tuple[str, str] | None:
    """Helper to extract (asset, action) from LiveTradeRecord, BacktestTrade, dict, or object."""
    if isinstance(trade, dict):
        asset = trade.get("asset")
        action = trade.get("action")
    else:
        asset = getattr(trade, "asset", None)
        action = getattr(trade, "action", None)

    if not asset or not action:
        return None

    act_str = action.value if hasattr(action, "value") else str(action)
    return str(asset), act_str


def is_correlated_conflict(
    candidate_asset: str,
    candidate_action: str | Any,
    active_trades: Sequence[Any],
    *,
    check_opposing: bool = False,
) -> tuple[bool, str]:
    """Checks if candidate trade conflicts with any active trade via correlated currency exposure.

    Prevents:
    1. Double Long exposure on the same currency (e.g. CALL on AUDUSD + CALL on AUDNZD).
    2. Double Short exposure on the same currency (e.g. CALL EURUSD + CALL GBPUSD,
       or CALL EURUSD + PUT USDCHF).
    3. (Optional) Opposing exposure on the same currency if check_opposing=True.

    Args:
        candidate_asset: Symbol of candidate trade (e.g. 'AUDNZD_otc').
        candidate_action: Direction of candidate trade ('CALL' or 'PUT').
        active_trades: Collection of active trades (LiveTradeRecord, BacktestTrade, or dicts).
        check_opposing: If True, flags opposing exposures on the same currency.

    Returns:
        tuple[bool, str]: (is_conflict, reason_description)
    """
    cand_exp = get_directional_exposure(candidate_asset, candidate_action)
    if not cand_exp:
        return False, ""

    cand_long, cand_short = cand_exp

    for active in active_trades:
        trade_info = _extract_trade_info(active)
        if not trade_info:
            continue
        act_asset, act_action = trade_info
        act_exp = get_directional_exposure(act_asset, act_action)
        if not act_exp:
            continue

        act_long, act_short = act_exp

        # 1. Duplicate Long Currency Exposure (Concentration Risk)
        if cand_long == act_long:
            return True, f"Conflict: Double Long {cand_long} (active: {act_asset} {act_action})"

        # 2. Duplicate Short Currency Exposure (Concentration Risk)
        if cand_short == act_short:
            return True, f"Conflict: Double Short {cand_short} (active: {act_asset} {act_action})"

        # 3. Optional: Opposing Currency Exposure (Self-Hedging / Contradiction)
        if check_opposing:
            if cand_long == act_short:
                return (
                    True,
                    f"Conflict: Opposing {cand_long} exposure (active: {act_asset} {act_action})",
                )
            if cand_short == act_long:
                return (
                    True,
                    f"Conflict: Opposing {cand_short} exposure (active: {act_asset} {act_action})",
                )

    return False, ""


def get_portfolio_currency_exposure(active_trades: Sequence[Any]) -> dict[str, int]:
    """Computes net directional currency units across all active trades.

    Positive value indicates net Long count, negative indicates net Short count.

    Example:
        Active: [CALL EURUSD, CALL GBPUSD] -> {'EUR': 1, 'GBP': 1, 'USD': -2}
    """
    exposure: dict[str, int] = {}
    for active in active_trades:
        trade_info = _extract_trade_info(active)
        if not trade_info:
            continue
        act_asset, act_action = trade_info
        exp = get_directional_exposure(act_asset, act_action)
        if not exp:
            continue
        long_ccy, short_ccy = exp
        exposure[long_ccy] = exposure.get(long_ccy, 0) + 1
        exposure[short_ccy] = exposure.get(short_ccy, 0) - 1
    return exposure


def get_pair_correlation(pair_a: str, pair_b: str) -> float | None:
    """Returns benchmark Pearson correlation coefficient between two currency pairs if known."""
    sym_a = normalize_symbol(pair_a)
    sym_b = normalize_symbol(pair_b)
    if not sym_a or not sym_b:
        return None
    if sym_a == sym_b:
        return 1.0
    key = frozenset({sym_a, sym_b})
    return MAJOR_PAIR_CORRELATIONS.get(key)
