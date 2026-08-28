# Forensic Audit Report: Milestone 2 (R2 - Toxic OTC Asset Blacklist Expansion & Canonical Normalization)

## Forensic Audit Report

**Work Product**: Milestone 2 (`asset_filter.py`, `settings.py`, `auto_assign_strategies.py`, `candles.py`, and test suites)  
**Profile**: General Project  
**Integrity Mode**: Development (from `ORIGINAL_REQUEST.md`)  
**Verdict**: **CLEAN**

---

### Phase Results
- **Hardcoded test results check**: PASS — Zero hardcoded constants or fabricated returns detected. All classification is computed dynamically via canonical normalizers and frozensets.
- **Facade implementation check**: PASS — Every domain function (`canonical_asset_key`, `is_toxic_asset`, `is_whitelisted_asset`, `filter_allowed_assets`) contains genuine logic.
- **Pre-populated artifact detection**: PASS — Workspace scanned; no stale or pre-populated log/result artifacts present.
- **Toxic OTC Blacklist expansion verification**: PASS — `DEFAULT_TOXIC_OTC_BLACKLIST` (and `DEFAULT_TOXIC_BLACKLIST`) contains all 11 canonical pairs (`USDIDR`, `USDVND`, `BNB`, `BNBUSD`, `EURCHF`, `USDDZD`, `UAHUSD`, `USDMYR`, `USDINR`, `EURHUF`, `GBPJPY`).
- **Whitelist purity & GBPJPY removal verification**: PASS — `GBPJPY` is completely absent from `DEFAULT_HIGH_WINRATE_WHITELIST`, `settings.py:high_winrate_asset_whitelist`, `auto_assign_strategies.py:target_assets`, and `candles.py:_CURATED_ASSETS`.
- **Test execution & Static verification**: PASS — Full test suite (569 tests) passes in 14.15s, targeted M2 suites (191 tests) pass in 4.69s, `ruff check` reports 0 errors.

---

## 1. Observation

1. **Source Code Inspection**:
   - `src/strat_trade/domain/trading/asset_filter.py` (lines 14–29):
     ```python
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
         }
     )
     DEFAULT_TOXIC_BLACKLIST = DEFAULT_TOXIC_OTC_BLACKLIST
     ```
   - `src/strat_trade/domain/trading/asset_filter.py` (lines 32–41):
     `DEFAULT_HIGH_WINRATE_WHITELIST` contains `{"EURUSD", "USDCLP", "USDBDT", "USDEGP", "GOLD", "XAUUSD"}`. `GBPJPY` has been removed.
   - `src/strat_trade/settings.py` (lines 94–126):
     - `toxic_asset_blacklist` default factory contains all 10 raw pairs including `"USD/DZD OTC"`, `"UAH/USD OTC"`, `"USD/MYR OTC"`, `"USD/INR OTC"`, `"EUR/HUF OTC"`, `"GBP/JPY OTC"`.
     - `high_winrate_asset_whitelist` contains `["EUR/USD OTC", "USD/CLP OTC", "USD/BDT OTC", "USD/EGP OTC", "Gold OTC"]`. `"GBP/JPY OTC"` is removed.
   - `src/strat_trade/use_cases/auto_assign_strategies.py` (lines 50–56):
     Fallback `target_assets` is `["EURUSD_otc", "USDCLP_otc", "USDBDT_otc", "USDEGP_otc", "Gold_otc"]`. `"GBPJPY_otc"` is removed.
   - `src/strat_trade/api/routes/candles.py` (lines 13–196):
     `_CURATED_ASSETS` contains 26 active pairs; `GBPJPY_otc` is removed.

2. **Empirical Independent Python Stress Test Results**:
   ```
   === 1. DEFAULT CONSTANTS CHECK ===
   DEFAULT_TOXIC_OTC_BLACKLIST: ['BNB', 'BNBUSD', 'EURCHF', 'EURHUF', 'GBPJPY', 'UAHUSD', 'USDDZD', 'USDIDR', 'USDINR', 'USDMYR', 'USDVND']
   DEFAULT_HIGH_WINRATE_WHITELIST: ['EURUSD', 'GOLD', 'USDBDT', 'USDCLP', 'USDEGP', 'XAUUSD']

   === 2. CANONICAL NORMALIZATION & PERMUTATION TEST ===
   All toxic permutation checks PASSED.

   === 3. WHITELIST PURITY TEST ===
   All whitelist permutation checks PASSED.

   === 4. SETTINGS DEFAULTS ===
   Settings toxic_asset_blacklist: ['USD/IDR OTC', 'USD/VND OTC', 'BNB OTC', 'EUR/CHF OTC', 'USD/DZD OTC', 'UAH/USD OTC', 'USD/MYR OTC', 'USD/INR OTC', 'EUR/HUF OTC', 'GBP/JPY OTC']
   Settings high_winrate_asset_whitelist: ['EUR/USD OTC', 'USD/CLP OTC', 'USD/BDT OTC', 'USD/EGP OTC', 'Gold OTC']

   === 5. CANDLES ROUTE CURATED ASSETS ===
   Curated assets count: 26
   Candles curated assets check PASSED.
   ```

3. **Tool & Test Execution**:
   - `.venv/bin/pytest`: 569 passed in 14.15s (0 failures).
   - `.venv/bin/pytest tests/test_strategy_curation_and_asset_filter.py tests/test_empirical_stress_challenger.py tests/test_m4_empirical_challenger_2.py tests/test_m2_adversarial_stress.py -v`: 191 passed in 4.69s.
   - `.venv/bin/ruff check src tests`: "All checks passed!" (0 errors).

---

## 2. Logic Chain

1. **Empirical Justification**: Broker trade analysis revealed 6 toxic OTC pairs with win rates between 0.0% and 33.3% (`USD/DZD OTC`, `UAH/USD OTC`, `USD/MYR OTC`, `USD/INR OTC`, `EUR/HUF OTC`, `GBP/JPY OTC`).
2. **Canonical Mapping & Enforcement**: Adding canonical forms `USDDZD`, `UAHUSD`, `USDMYR`, `USDINR`, `EURHUF`, `GBPJPY` to `DEFAULT_TOXIC_OTC_BLACKLIST` and `DEFAULT_TOXIC_BLACKLIST` ensures all delimiter, case, and OTC notation variations are deterministically rejected by `canonical_asset_key` and `is_toxic_asset()`.
3. **Disambiguation of Whitelist**: Previously, `GBPJPY` was listed in the high-winrate whitelist. Retaining it would create a contradiction. Removing `GBPJPY` across `asset_filter.py`, `settings.py`, `auto_assign_strategies.py`, and `candles.py` guarantees total whitelist purity and eliminates toxic execution leaks.
4. **Authenticity & Integrity**: All assertions test dynamic execution through domain models, bot order locks, and auto-matcher profiling. No facade code, bypasses, or hardcoded return tricks were found.

---

## 3. Caveats

- **Custom Blacklist Overrides**: If an external caller explicitly passes a custom blacklist to `is_toxic_asset(asset, custom_blacklist=...)`, the custom blacklist takes precedence for that specific call. Default configurations and domain constants remain fully populated with all 11 toxic pairs.
- No other caveats.

---

## 4. Conclusion

**Verdict: CLEAN**

Milestone 2 (R2) changes strictly satisfy all integrity and quantitative requirements:
- All 6 new toxic OTC pairs (`USDDZD`, `UAHUSD`, `USDMYR`, `USDINR`, `EURHUF`, `GBPJPY`) alongside the 5 existing pairs are authentically mapped, normalized, and blacklisted.
- `GBPJPY` has been removed from all whitelist configurations and curated listings.
- Zero integrity violations, zero facades, zero bypass logic.
- Full test suite (569 tests) and targeted test suites (191 tests) pass with 0 lint violations.

---

## 5. Verification Method

To independently verify this audit:

1. **Run Full Regression Suite**:
   ```bash
   .venv/bin/pytest
   ```
2. **Run Targeted M2 Test Suites**:
   ```bash
   .venv/bin/pytest tests/test_strategy_curation_and_asset_filter.py \
                    tests/test_empirical_stress_challenger.py \
                    tests/test_m4_empirical_challenger_2.py \
                    tests/test_m2_adversarial_stress.py -v
   ```
3. **Run Static Linting**:
   ```bash
   .venv/bin/ruff check src tests
   ```

### Invalidation Conditions
- Any variation of `USD/DZD`, `UAH/USD`, `USD/MYR`, `USD/INR`, `EUR/HUF`, or `GBP/JPY` passes `is_toxic_asset()` as `(False, "")`.
- `GBPJPY` appears in `DEFAULT_HIGH_WINRATE_WHITELIST` or `high_winrate_asset_whitelist`.
- Any test fails or linter produces errors.
