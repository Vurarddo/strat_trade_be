# Handoff Report: Currency Correlation & Exposure Filtering Design

**Agent**: `m2_explorer_1`  
**Milestone**: Milestone 2 — Currency Correlation & Exposure Filtering  
**Date**: 2026-08-20  
**Target Module**: `src/strat_trade/domain/trading/correlation.py`  
**Target Tests**: `tests/test_currency_correlation.py`

---

## 1. Observation

1. **Current Codebase State**:
   - Grep search for `correlation.py` in `src/strat_trade/domain/trading/` showed that the file does not yet exist.
   - `LiveDemoBotEngine` (`src/strat_trade/domain/trading/bot_engine.py:270-272`):
     ```python
     # Don't open duplicate trades on the same asset if already active
     if any(t.asset == asset for t in self.active_trades.values()):
         return
     ```
     Only exact duplicate asset symbols are filtered.
   - `PortfolioBacktestEngine` (`src/strat_trade/domain/backtest/portfolio_engine.py:234-235`):
     ```python
     # Don't open multiple trades on the exact same asset simultaneously
     if any(t.asset == sig.asset for t in active_trades):
         continue
     ```
     Similarly, only identical assets are rejected during portfolio simulation.
2. **Asset Naming Variations in System**:
   - Symbols across codebase, Pocket Option gateway, and web client appear in various formats:
     - `AUDUSD_otc`, `EURUSD_otc`, `USDCHF_otc`, `GBPUSD_otc`, `USDJPY_otc` (`src/strat_trade/domain/strategies/registry.py:55, 127`, `src/strat_trade/api/routes/candles.py:36`)
     - `USD/CHF OTC`, `EUR/USD` (`tests/test_live_trade_store.py:24`, `src/strat_trade/adapters/pocket_option_gateway.py:432`)
     - Standard 6-char strings `AUDUSD`, `EURUSD`, `USDCHF` (`src/strat_trade/api/routes/candles.py:99`).
3. **Data Type Variations in Active Trades**:
   - In `LiveDemoBotEngine`, active trades are stored as `dict[str, LiveTradeRecord]`, where each `LiveTradeRecord` (`src/strat_trade/domain/trading/entities.py:121-150`) has `asset: str` and `action: str` ("CALL" or "PUT").
   - In `PortfolioBacktestEngine`, active trades are stored as `list[BacktestTrade]`, where `BacktestTrade` (`src/strat_trade/domain/backtest/models.py:47-64`) has `asset: str` and `action: TradeAction` (enum with values "CALL" and "PUT").
4. **Test Environment**:
   - Test runner is located at `.venv/bin/pytest`.
   - Running `.venv/bin/pytest` executed 165 tests in 3.79s, with 165 passing and 0 failures.

---

## 2. Logic Chain

1. **Need for Asset Normalization & Decomposition (Ref: Observation 2)**:
   - Because Pocket Option and broker data sources format symbols with `_otc`, ` OTC`, `/`, and `-`, a robust `normalize_symbol(asset: str) -> str` and `extract_currency_pair(asset: str) -> tuple[str, str] | None` must strip non-alphanumeric noise, remove OTC tags, and validate that the remaining clean string is a valid 6-character alphabetic pair $(B, Q)$ where $B \ne Q$.
2. **Directional Binary Exposure Model (Ref: Observation 1 & 2)**:
   - For any currency pair $P = B/Q$:
     - A `CALL` trade expects $P \uparrow \implies \text{Long } B, \text{ Short } Q$.
     - A `PUT` trade expects $P \downarrow \implies \text{Short } B, \text{ Long } Q$.
   - This mapping allows exact currency-level tracking regardless of whether the currency appears in the numerator ($B$) or denominator ($Q$).
3. **Correlated Conflict Detection (Ref: Observation 1)**:
   - Comparing candidate directional exposure against active trades catches:
     - **Double Long**: Candidate Long == Active Long (e.g. `CALL AUDUSD` + `CALL AUDNZD` -> Double Long AUD; `PUT EURUSD` + `CALL USDCHF` -> Double Long USD).
     - **Double Short**: Candidate Short == Active Short (e.g. `CALL EURUSD` + `CALL GBPUSD` -> Double Short USD; `CALL EURUSD` + `PUT USDCHF` -> Double Short USD).
   - This eliminates catastrophic multi-asset drawdowns caused by systemic currency moves.
4. **Polymorphic Interoperability (Ref: Observation 3)**:
   - Implementing `_extract_trade_info(trade: Any) -> tuple[str, str] | None` inside `correlation.py` allows `is_correlated_conflict` to accept `LiveTradeRecord`, `BacktestTrade`, `dict`, or any duck-typed object seamlessly, ensuring zero discrepancies between live trading and backtesting.
5. **Specification of Test Suite (Ref: Observation 4)**:
   - 12 comprehensive unit tests specified in `tests/test_currency_correlation.py` cover all normalization edge cases, directional mappings, multi-currency conflicts, inverse pairs, and portfolio exposure metrics.

---

## 3. Caveats

1. **Non-Forex Assets (Commodities / Stocks / Crypto without 3-char codes)**:
   - Assets like `GOLD`, `AAPL`, `SPX500` return `None` from `extract_currency_pair` and are bypass-cleared (no false positive rejection). Crypto pairs with 3-char codes (e.g. `BTCUSD`, `ETHUSD`) parse correctly as Base=BTC/ETH, Quote=USD.
2. **Dynamic Live Macro Volatility**:
   - Currency correlation values fluctuate during high-impact news releases (NFP, CPI). While static/directional base-quote filtering eliminates 100% of same-currency over-exposure, statistical cross-currency correlation (e.g. AUD vs NZD) uses benchmark correlation matrices.
3. **Read-Only Scope**:
   - `m2_explorer_1` is strictly read-only. The actual writing of `src/strat_trade/domain/trading/correlation.py` and `tests/test_currency_correlation.py` will be performed by the milestone implementer.

---

## 4. Conclusion

The design for `src/strat_trade/domain/trading/correlation.py` is fully formulated, mathematically rigorous, and fully specified in `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_explorer_1/analysis.md`. It provides:
1. `extract_currency_pair(asset: str) -> tuple[str, str] | None`
2. `get_directional_exposure(asset: str, action: str | Any) -> tuple[str, str] | None`
3. `is_correlated_conflict(candidate_asset: str, candidate_action: str | Any, active_trades: Sequence[Any], *, check_opposing: bool = False) -> tuple[bool, str]`
4. `get_portfolio_currency_exposure(active_trades: Sequence[Any]) -> dict[str, int]`
5. `get_pair_correlation(pair_a: str, pair_b: str) -> float | None`

The implementer can drop in the code and test suite directly.

---

## 5. Verification Method

Once implemented, the verification steps are:
1. **Unit Test Execution**:
   ```bash
   .venv/bin/pytest tests/test_currency_correlation.py -v
   ```
   Must pass 100% of the test cases defined in `tests/test_currency_correlation.py`.
2. **Full Regression Suite**:
   ```bash
   .venv/bin/pytest
   ```
   Must pass all 165 existing tests plus new correlation unit tests with 0 regressions.
3. **Inspection Verification**:
   Verify `is_correlated_conflict("AUDNZD_otc", "CALL", [_make_live_trade("AUDUSD_otc", "CALL")])` returns `(True, "Conflict: Double Long AUD ...")`.
