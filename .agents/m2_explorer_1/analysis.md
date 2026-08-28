# Analysis: Currency Pair Correlation & Directional Exposure Filter

**Date**: 2026-08-20  
**Author**: `m2_explorer_1`  
**Milestone**: Milestone 2 — Bot Engine Guardrails & Anti-Whipsaw (R2)  
**Target Module**: `src/strat_trade/domain/trading/correlation.py`  
**Target Test Suite**: `tests/test_currency_correlation.py`

---

## 1. Executive Summary & Problem Formulation

In high-frequency binary options multi-asset trading, running autonomous strategy assignments across multiple currency pairs simultaneously introduces catastrophic **unintended directional risk concentration** if correlated pairs are treated as independent instruments.

### Core Failure Modes Observed in Baseline:
1. **Shared Base Currency Over-Concentration (e.g., AUD Pairs)**:
   - Firing simultaneous `CALL` signals on `AUDUSD_otc` and `AUDNZD_otc` puts the portfolio in a **Double Long AUD** stance. Any systemic AUD macroeconomic event or sudden OTC microstructural down-spike triggers a simultaneous double loss.
2. **Shared Quote Currency Over-Concentration (e.g., USD Pairs)**:
   - Firing simultaneous `CALL` signals on `EURUSD_otc`, `GBPUSD_otc`, and `AUDUSD_otc` creates a **Triple Short USD** stance ($3\times$ unhedged exposure against the US Dollar).
3. **Inverse Pair Contradiction (e.g., EUR/USD vs USD/CHF)**:
   - `EURUSD` and `USDCHF` exhibit strong inverse correlation ($\rho \approx -0.91$).
   - Firing `CALL` on `EURUSD_otc` (Long EUR, Short USD) and `PUT` on `USDCHF_otc` (Short USD, Long CHF) is a redundant **Double Short USD** bet.
   - Firing `CALL` on `EURUSD_otc` (Short USD) and `CALL` on `USDCHF_otc` (Long USD) creates an opposing self-hedging contradiction that pays broker fees/spreads on both sides.

To solve this, `src/strat_trade/domain/trading/correlation.py` provides a mathematical currency decomposition and directional exposure verification engine.

---

## 2. Mathematical Foundation of Directional Exposure

In binary options, every currency pair contract $P$ trades the exchange rate of the **Base Currency** ($B$) relative to the **Quote Currency** ($Q$):

$$P = \frac{\text{Base Currency } (B)}{\text{Quote Currency } (Q)}$$

When a binary option order is opened:
- **`CALL` Option**: The trader bets that $P$ will increase ($P_{t+\Delta t} > P_t$). This requires Base currency appreciation and/or Quote currency depreciation:
  $$\text{Exposure}(\text{CALL}) \implies \mathbf{Long}(B), \; \mathbf{Short}(Q)$$
- **`PUT` Option**: The trader bets that $P$ will decrease ($P_{t+\Delta t} < P_t$). This requires Base currency depreciation and/or Quote currency appreciation:
  $$\text{Exposure}(\text{PUT}) \implies \mathbf{Short}(B), \; \mathbf{Long}(Q)$$

### Complete Exposure Mapping Matrix
| Asset Symbol | Action | Decomposed Base ($B$) | Decomposed Quote ($Q$) | Long Currency ($\mathcal{C}_{\text{long}}$) | Short Currency ($\mathcal{C}_{\text{short}}$) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `AUDUSD_otc` | `CALL` | `AUD` | `USD` | **`AUD`** | **`USD`** |
| `AUDUSD_otc` | `PUT` | `AUD` | `USD` | **`USD`** | **`AUD`** |
| `AUDNZD_otc` | `CALL` | `AUD` | `NZD` | **`AUD`** | **`NZD`** |
| `AUDNZD_otc` | `PUT` | `AUD` | `NZD` | **`NZD`** | **`AUD`** |
| `EURUSD_otc` | `CALL` | `EUR` | `USD` | **`EUR`** | **`USD`** |
| `EURUSD_otc` | `PUT` | `EUR` | `USD` | **`USD`** | **`EUR`** |
| `GBPUSD_otc` | `CALL` | `GBP` | `USD` | **`GBP`** | **`USD`** |
| `GBPUSD_otc` | `PUT` | `GBP` | `USD` | **`USD`** | **`GBP`** |
| `USDCHF_otc` | `CALL` | `USD` | `CHF` | **`USD`** | **`CHF`** |
| `USDCHF_otc` | `PUT` | `USD` | `CHF` | **`CHF`** | **`USD`** |
| `USDJPY_otc` | `CALL` | `USD` | `JPY` | **`USD`** | **`JPY`** |
| `USDJPY_otc` | `PUT` | `USD` | `JPY` | **`JPY`** | **`USD`** |

---

## 3. Conflict Detection Algorithm

Let the candidate trade be $(\mathcal{A}_{\text{cand}}, \text{Act}_{\text{cand}})$, with decomposed directional exposures:
$$\mathcal{E}_{\text{cand}} = (\mathcal{C}_{\text{long}}^{\text{cand}}, \; \mathcal{C}_{\text{short}}^{\text{cand}})$$

Let the set of currently active open trades be $\mathcal{T}_{\text{active}} = \{(\mathcal{A}_1, \text{Act}_1), \dots, (\mathcal{A}_k, \text{Act}_k)\}$, with exposures:
$$\mathcal{E}_i = (\mathcal{C}_{\text{long}}^i, \; \mathcal{C}_{\text{short}}^i) \quad \text{for } i \in \{1, \dots, k\}$$

The candidate trade is **rejected for correlation conflict** if:
1. **Duplicate Long Concentration**:
   $$\exists i : \mathcal{C}_{\text{long}}^{\text{cand}} = \mathcal{C}_{\text{long}}^i \implies \text{Conflict: Double Long } \mathcal{C}_{\text{long}}^{\text{cand}}$$
2. **Duplicate Short Concentration**:
   $$\exists i : \mathcal{C}_{\text{short}}^{\text{cand}} = \mathcal{C}_{\text{short}}^i \implies \text{Conflict: Double Short } \mathcal{C}_{\text{short}}^{\text{cand}}$$
3. **(Optional) Opposing Hedging Contradiction** (when `check_opposing=True`):
   $$\exists i : \left(\mathcal{C}_{\text{long}}^{\text{cand}} = \mathcal{C}_{\text{short}}^i\right) \lor \left(\mathcal{C}_{\text{short}}^{\text{cand}} = \mathcal{C}_{\text{long}}^i\right) \implies \text{Conflict: Opposing exposure on } \mathcal{C}$$

---

## 4. Exact Implementation Design (`src/strat_trade/domain/trading/correlation.py`)

```python
"""
Currency Pair Correlation & Directional Exposure Filter.

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
        "USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF",
        "CNH", "CNY", "SGD", "HKD", "SEK", "NOK", "MXN", "ZAR",
        "TRY", "PLN", "INR", "BRL", "KRW", "RUB", "BTC", "ETH",
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


def normalize_symbol(asset: str) -> str:
    """
    Normalizes asset string to canonical uppercase format (e.g., 'AUDUSD_otc' -> 'AUDUSD').
    Strips OTC tags, separators, spaces, and casing.
    """
    if not asset or not isinstance(asset, str):
        return ""
    s = asset.strip().upper()
    # Remove parenthesized notes like (OTC)
    s = re.sub(r"\(.*?\)", "", s)
    # Strip OTC word tokens
    s = re.sub(r"\bOTC\b", "", s)
    # Strip all non-alphanumeric characters
    clean = re.sub(r"[^A-Z0-9]", "", s)
    return clean


def extract_currency_pair(asset: str) -> tuple[str, str] | None:
    """
    Extracts (base, quote) currencies from asset symbol.

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
    """
    Calculates directional currency exposure for a binary option trade.

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

    act_str = (
        action.value
        if hasattr(action, "value")
        else str(action or "").upper().strip()
    )

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
    """
    Checks if candidate trade conflicts with any active trade via correlated currency exposure.

    Prevents:
    1. Double Long exposure on the same currency (e.g. CALL on AUDUSD + CALL on AUDNZD).
    2. Double Short exposure on the same currency (e.g. CALL on EURUSD + CALL on GBPUSD, or CALL on EURUSD + PUT on USDCHF).
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
    cand_act_str = (
        candidate_action.value
        if hasattr(candidate_action, "value")
        else str(candidate_action).upper().strip()
    )

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
                return True, f"Conflict: Opposing {cand_long} exposure (active: {act_asset} {act_action})"
            if cand_short == act_long:
                return True, f"Conflict: Opposing {cand_short} exposure (active: {act_asset} {act_action})"

    return False, ""


def get_portfolio_currency_exposure(active_trades: Sequence[Any]) -> dict[str, int]:
    """
    Computes net directional currency units across all active trades.
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
```

---

## 5. Specification of Unit Tests (`tests/test_currency_correlation.py`)

The test suite covers full branch coverage, normalization robustness, edge cases, and multi-asset conflicts:

```python
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from strat_trade.domain.backtest.models import BacktestTrade, TradeAction, TradeOutcome
from strat_trade.domain.trading.correlation import (
    extract_currency_pair,
    get_directional_exposure,
    get_pair_correlation,
    get_portfolio_currency_exposure,
    is_correlated_conflict,
    normalize_symbol,
)
from strat_trade.domain.trading.entities import IndicatorSnapshot, LiveTradeRecord


def _make_live_trade(asset: str, action: str) -> LiveTradeRecord:
    return LiveTradeRecord(
        trade_id="t-mock",
        asset=asset,
        action=action,
        stake=Decimal("10.00"),
        open_time=datetime.now(UTC),
        expiration_seconds=180,
        open_price=Decimal("1.0000"),
        strategy_id="mock_strat",
        strategy_name="Mock Strategy",
        strategy_params={},
        indicator_snapshot=IndicatorSnapshot(),
        confidence=0.8,
        reason="test",
        payout_rate=Decimal("0.92"),
    )


def test_normalize_symbol():
    assert normalize_symbol("AUDUSD_otc") == "AUDUSD"
    assert normalize_symbol("EUR/USD (OTC)") == "EURUSD"
    assert normalize_symbol("usd/chf-otc") == "USDCHF"
    assert normalize_symbol("GBP-USD") == "GBPUSD"
    assert normalize_symbol("") == ""
    assert normalize_symbol(None) == ""


def test_extract_currency_pair_standard_and_otc():
    assert extract_currency_pair("EURUSD") == ("EUR", "USD")
    assert extract_currency_pair("EURUSD_otc") == ("EUR", "USD")
    assert extract_currency_pair("USDCHF_otc") == ("USD", "CHF")
    assert extract_currency_pair("AUDNZD_otc") == ("AUD", "NZD")
    assert extract_currency_pair("USD/CHF OTC") == ("USD", "CHF")
    assert extract_currency_pair("eur/usd") == ("EUR", "USD")
    assert extract_currency_pair("GBP-USD_otc") == ("GBP", "USD")
    assert extract_currency_pair("BTCUSD_otc") == ("BTC", "USD")


def test_extract_currency_pair_invalid_symbols():
    assert extract_currency_pair("AAPL") is None
    assert extract_currency_pair("GOLD") is None
    assert extract_currency_pair("USDUSD") is None
    assert extract_currency_pair("") is None
    assert extract_currency_pair(None) is None
    assert extract_currency_pair("123456") is None


def test_directional_exposure_call_put():
    # CALL on EURUSD -> Long EUR, Short USD
    assert get_directional_exposure("EURUSD_otc", "CALL") == ("EUR", "USD")
    # PUT on EURUSD -> Long USD, Short EUR
    assert get_directional_exposure("EURUSD_otc", "PUT") == ("USD", "EUR")
    # CALL on USDCHF -> Long USD, Short CHF
    assert get_directional_exposure("USDCHF", "CALL") == ("USD", "CHF")
    # PUT on USDCHF -> Long CHF, Short USD
    assert get_directional_exposure("USDCHF", "PUT") == ("CHF", "USD")
    # Invalid action or asset
    assert get_directional_exposure("EURUSD_otc", "HOLD") is None
    assert get_directional_exposure("AAPL", "CALL") is None


def test_same_base_correlated_conflict_aud():
    # Active trade: CALL on AUDUSD (Long AUD, Short USD)
    active = [_make_live_trade("AUDUSD_otc", "CALL")]

    # Candidate: CALL on AUDNZD (Long AUD, Short NZD) -> Double Long AUD
    conflict, reason = is_correlated_conflict("AUDNZD_otc", "CALL", active)
    assert conflict is True
    assert "Double Long AUD" in reason

    # Candidate: PUT on AUDCAD (Long CAD, Short AUD) -> No double long or short
    conflict, reason = is_correlated_conflict("AUDCAD_otc", "PUT", active)
    assert conflict is False


def test_same_quote_correlated_conflict_usd():
    # Active trade: CALL on EURUSD (Long EUR, Short USD)
    active = [_make_live_trade("EURUSD_otc", "CALL")]

    # Candidate: CALL on GBPUSD (Long GBP, Short USD) -> Double Short USD
    conflict, reason = is_correlated_conflict("GBPUSD_otc", "CALL", active)
    assert conflict is True
    assert "Double Short USD" in reason

    # Candidate: CALL on AUDUSD (Long AUD, Short USD) -> Double Short USD
    conflict, reason = is_correlated_conflict("AUDUSD_otc", "CALL", active)
    assert conflict is True
    assert "Double Short USD" in reason


def test_inverse_pair_correlated_conflict_eurusd_usdchf():
    # Active trade: CALL on EURUSD (Long EUR, Short USD)
    active = [_make_live_trade("EURUSD_otc", "CALL")]

    # Candidate: PUT on USDCHF (Long CHF, Short USD) -> Double Short USD
    conflict, reason = is_correlated_conflict("USDCHF_otc", "PUT", active)
    assert conflict is True
    assert "Double Short USD" in reason

    # Active trade: PUT on EURUSD (Long USD, Short EUR)
    active_put = [_make_live_trade("EURUSD_otc", "PUT")]

    # Candidate: CALL on USDCHF (Long USD, Short CHF) -> Double Long USD
    conflict, reason = is_correlated_conflict("USDCHF_otc", "CALL", active_put)
    assert conflict is True
    assert "Double Long USD" in reason


def test_uncorrelated_diversified_trades():
    # Active trade: CALL on EURUSD (Long EUR, Short USD)
    active = [_make_live_trade("EURUSD_otc", "CALL")]

    # Candidate: CALL on AUDNZD (Long AUD, Short NZD) -> No common currencies
    conflict, reason = is_correlated_conflict("AUDNZD_otc", "CALL", active)
    assert conflict is False
    assert reason == ""


def test_polymorphic_trade_inputs():
    # BacktestTrade instance
    bt_trade = BacktestTrade(
        entry_index=10,
        exit_index=13,
        entry_time=datetime.now(UTC),
        exit_time=datetime.now(UTC),
        action=TradeAction.CALL,
        entry_price=Decimal("1.0"),
        exit_price=Decimal("1.0"),
        stake=Decimal("10.0"),
        payout_rate=Decimal("0.92"),
        pnl=Decimal("0.0"),
        outcome=TradeOutcome.DRAW,
        balance_after=Decimal("1000.0"),
        confidence=0.8,
        expiration_seconds=180,
        asset="EURUSD_otc",
    )
    conflict, reason = is_correlated_conflict("GBPUSD_otc", "CALL", [bt_trade])
    assert conflict is True
    assert "Double Short USD" in reason

    # Dict input
    dict_trade = {"asset": "EURUSD_otc", "action": "CALL"}
    conflict, reason = is_correlated_conflict("GBPUSD_otc", "CALL", [dict_trade])
    assert conflict is True
    assert "Double Short USD" in reason


def test_opposing_exposure_flag():
    active = [_make_live_trade("EURUSD_otc", "CALL")]  # Short USD
    # Candidate: CALL on USDCHF (Long USD)
    # Default: check_opposing=False -> No double concentration conflict
    conflict_def, _ = is_correlated_conflict("USDCHF_otc", "CALL", active, check_opposing=False)
    assert conflict_def is False

    # check_opposing=True -> Flags opposing USD
    conflict_opp, reason_opp = is_correlated_conflict("USDCHF_otc", "CALL", active, check_opposing=True)
    assert conflict_opp is True
    assert "Opposing USD" in reason_opp


def test_portfolio_currency_exposure_aggregation():
    active = [
        _make_live_trade("EURUSD_otc", "CALL"),  # Long EUR, Short USD
        _make_live_trade("GBPUSD_otc", "CALL"),  # Long GBP, Short USD
        _make_live_trade("USDJPY_otc", "PUT"),   # Long JPY, Short USD
    ]
    exp = get_portfolio_currency_exposure(active)
    assert exp["EUR"] == 1
    assert exp["GBP"] == 1
    assert exp["JPY"] == 1
    assert exp["USD"] == -3


def test_get_pair_correlation():
    assert get_pair_correlation("EURUSD_otc", "GBPUSD_otc") == 0.82
    assert get_pair_correlation("EURUSD", "USDCHF") == -0.91
    assert get_pair_correlation("EURUSD", "EURUSD") == 1.0
    assert get_pair_correlation("EURUSD", "UNKNOWN_PAIR") is None
```

---

## 6. Integration Points with Other Modules

1. **`LiveDemoBotEngine` (`src/strat_trade/domain/trading/bot_engine.py`)**:
   - In `_evaluate_single_asset()`:
     ```python
     if self.plan and getattr(self.plan, "correlation_filter_enabled", True):
         is_conflict, reason = is_correlated_conflict(
             asset,
             act_str,
             list(self.active_trades.values()),
         )
         if is_conflict:
             logger.info("Signal rejected for %s (%s): %s", asset, act_str, reason)
             return
     ```
2. **`PortfolioBacktestEngine` (`src/strat_trade/domain/backtest/portfolio_engine.py`)**:
   - In trade dispatch loop before appending to `active_trades`:
     ```python
     if self.config.correlation_filter_enabled:
         is_conflict, _ = is_correlated_conflict(sig.asset, sig.action, active_trades)
         if is_conflict:
             continue
     ```
3. **PreTradingPlan & REST API (`entities.py`, `schemas.py`)**:
   - `PreTradingPlan.correlation_filter_enabled: bool = True`
   - `StartBotRequest.correlation_filter_enabled: bool = True`
