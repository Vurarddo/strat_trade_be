# Empirical Challenge Report: Boundary & Confluence Verification (Milestone 1)

## Challenge Summary

**Overall risk assessment**: LOW

All adversarial hypotheses and boundary stress tests confirm that Milestone 1 strategy portfolio restructuring is robust, leak-free, and compliant with all Sniper Confluence specifications. Legacy indicator-spam strategies (`macd_divergence_break`, `hybrid_multifactors`, `supertrend_adx_momentum`, `volatility_squeeze_breakout`, `bollinger_atr_reversion`) are strictly quarantined and never assigned by automated strategy matching across any asset category, data shape, or fallback path.

---

## Challenges & Stress Hypotheses

### [Low Risk / Resolved] Challenge 1: Indicator Spam Leakage via Heuristic Fallback Routing
- **Assumption challenged**: Legacy failing strategies (`macd_divergence_break` and `hybrid_multifactors`) could be selected during heuristic routing when candle data is missing, insufficient (< 35 bars), or unclassified.
- **Attack scenario**: Evaluated 50+ diverse asset symbols across Commodities, Stocks, Crypto, Forex (GBP/JPY), Forex (Other), exotic unclassified tokens, and toxic blacklisted OTC assets under zero-candle and corrupt-candle conditions.
- **Observed Behavior**: Zero instances of legacy strategies allocated. Heuristic routing strictly maps:
  - Commodities (`Gold_otc`, `XAUUSD`, `GOLD`) $\rightarrow$ `support_resistance_bounce`
  - Stocks (`#AAPL_otc`, `TSLA`, `NVDA`, `INTC`, `#MSFT`, `#AMZN`) $\rightarrow$ `ema_pullback_trend`
  - Crypto (`BTCUSD_otc`, `ETHUSD_otc`, `SOLUSD_otc`, `DOGEUSD_otc`, `XRPUSD_otc`) $\rightarrow$ `rsi_stochastic_extreme`
  - Forex JPY/GBP pairs (`USDJPY_otc`, `GBPUSD_otc`, `GBPJPY_otc`, `EURGBP_otc`) $\rightarrow$ `support_resistance_bounce`
  - Forex Other pairs (`EURUSD_otc`, `AUDUSD_otc`, `NZDUSD_otc`, `USDCLP_otc`, `USDBDT_otc`) $\rightarrow$ `rsi_stochastic_extreme`
  - Unclassified / Synthetic tokens (`SYNTHETIC_INDEX_01`, `UNKNOWN_XYZ`) $\rightarrow$ `support_resistance_bounce`
- **Blast radius**: None.
- **Mitigation status**: Fully mitigated by `auto_matcher.py` lines 17–23 and 238–364.

---

### [Low Risk / Resolved] Challenge 2: Adversarially Engineered Candle Series Bypassing Candidate Filters
- **Assumption challenged**: Synthetic market data engineered specifically with strong MACD divergences or multi-factor indicator confluences might bypass candidate strategy filtering in `find_optimal_strategy_for_asset` and select `macd_divergence_break` or `hybrid_multifactors`.
- **Attack scenario**: Injected synthetic cyclical divergence series, strong trend momentum series, and high-volatility breakout series into `find_optimal_strategy_for_asset`.
- **Observed Behavior**: `candidate_strategies = [s for s in strategies if s["id"] in PRIORITY_STRATEGIES]` in `auto_matcher.py` (lines 422–424) strictly prevents legacy strategies from being backtested or evaluated. The optimal strategy returned was strictly one of the Sniper Trio (`support_resistance_bounce`, `rsi_stochastic_extreme`, `ema_pullback_trend`).
- **Blast radius**: None.
- **Mitigation status**: Fully verified in `tests/test_m1_challenger_2_boundary_confluence.py::TestAdversarialMarketDataAutoMatching`.

---

### [Low Risk / Resolved] Challenge 3: Registry Fallback Precedence & Type Coercion Safety
- **Assumption challenged**: Passing corrupt names, `None`, empty strings, whitespace, or invalid types to `get_strategy_instance()` might trigger unexpected exceptions or fall back to legacy strategies.
- **Attack scenario**: Fuzzed `get_strategy_instance()` with uppercase, mixed-case, whitespace-padded, `None`, non-string objects (`12345`, `{}`, `[]`, `object()`), and non-existent strategy IDs.
- **Observed Behavior**: In all invalid/unknown cases, `get_strategy_instance()` safely returns an instance of `SupportResistanceBounceStrategy` conforming to `BaseStrategy`. Legacy names (`macd_divergence_break`, `hybrid_multifactors`) remain instantiable by direct ID for historical backtest compatibility.
- **Blast radius**: None.
- **Mitigation status**: Fully verified in `TestRegistryFallbackSafety`.

---

### [Low Risk / Resolved] Challenge 4: End-to-End Multi-Asset Plan Generation Concurrency
- **Assumption challenged**: Asynchronous concurrency in `generate_pre_trading_plan` across 20+ mixed asset classes might produce race conditions or assign deactivated strategies.
- **Attack scenario**: Executed `generate_pre_trading_plan` with 16 concurrent assets across all market sectors.
- **Observed Behavior**: 100% of plan assignments were allocated exclusively to `PRIORITY_STRATEGIES` with valid parameters (`base_expiration_bars = 3`), positive quantum scores, and estimated win rates $\ge 50\%$.
- **Blast radius**: None.
- **Mitigation status**: Fully verified in `TestPreTradingPlanIntegration`.

---

## Stress Test Results

| # | Test Scenario | Expected Behavior | Actual Behavior | Result |
|---|---------------|-------------------|-----------------|--------|
| 1 | `PRIORITY_STRATEGIES` membership test | Strict set of 3 Sniper strategies | `{"support_resistance_bounce", "rsi_stochastic_extreme", "ema_pullback_trend"}` | **PASS** |
| 2 | Deactivated strategies exclusion test | 0 legacy strategies in priority set | All 5 legacy strategies absent | **PASS** |
| 3 | Commodities heuristic routing (6 assets) | Routed to `support_resistance_bounce` | Routed to `support_resistance_bounce` | **PASS** |
| 4 | Stocks heuristic routing (11 assets) | Routed to `ema_pullback_trend` | Routed to `ema_pullback_trend` | **PASS** |
| 5 | Crypto heuristic routing (9 assets) | Routed to `rsi_stochastic_extreme` | Routed to `rsi_stochastic_extreme` | **PASS** |
| 6 | Forex JPY/GBP heuristic routing (9 assets) | Routed to `support_resistance_bounce` | Routed to `support_resistance_bounce` | **PASS** |
| 7 | Forex other heuristic routing (12 assets) | Routed to `rsi_stochastic_extreme` | Routed to `rsi_stochastic_extreme` | **PASS** |
| 8 | Unclassified tokens heuristic routing (5 assets)| Routed to `support_resistance_bounce` | Routed to `support_resistance_bounce` | **PASS** |
| 9 | MACD divergence synthetic candle series | Strict Sniper Trio winner | `rsi_stochastic_extreme` allocated (MACD never evaluated) | **PASS** |
| 10 | Strong trend momentum synthetic series | Strict Sniper Trio winner | `ema_pullback_trend` allocated | **PASS** |
| 11 | Candle length boundaries (0, 1, 10, 34, 35, 36, 100, 200 bars) | Graceful handling without crashes | Correct fallback (<35) or backtest (>=35) | **PASS** |
| 12 | Corrupt / NaN / Inf DataFrame handling | Graceful fallback without crash | S&R Bounce fallback allocated | **PASS** |
| 13 | Registry direct instantiation of legacy strategies | Accessible for backwards compatibility | Correct classes instantiated | **PASS** |
| 14 | Registry unknown / invalid / None fallback | Fallback to S&R Bounce | `SupportResistanceBounceStrategy` instance | **PASS** |
| 15 | Registry case insensitivity & whitespace trim | Correct strategy class | Correct strategy class | **PASS** |
| 16 | End-to-end `generate_pre_trading_plan` (16 assets) | 100% Sniper Trio assignments | 100% Sniper Trio assignments | **PASS** |
| 17 | Full test suite execution (`pytest`) | 828 passing tests, 0 failures | 828 passed in 22.55s | **PASS** |
| 18 | Static lint verification (`ruff check src tests`) | 0 violations | All checks passed! | **PASS** |

---

## Unchallenged Areas

- Dynamic microstructure noise filtering (`qualify_asset_microstructure` in `asset_filter.py`) and post-settlement cooldown enforcement (`LiveDemoBotEngine`) — scheduled for Milestone 3.
- UI template removal of `#botCfgExpiration` select — scheduled for Milestone 2.
- 600+ trade rolling 15-trade backtest validation — scheduled for Milestone 4.
