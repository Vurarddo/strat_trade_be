# Handoff Report: Toxic OTC Asset Blacklist & Canonical Asset Filtering (R2)

## 1. Observation

### 1.1 Current Blacklist & Whitelist Implementation in `asset_filter.py`
In `src/strat_trade/domain/trading/asset_filter.py` (lines 14–35):
```python
# Default Canonical Toxic Assets (Discretized, high-slippage OTC pairs)
DEFAULT_TOXIC_OTC_BLACKLIST: frozenset[str] = frozenset(
    {
        "USDIDR",  # USD/IDR OTC
        "USDVND",  # USD/VND OTC
        "BNB",  # BNB OTC
        "BNBUSD",  # BNB/USD OTC
        "EURCHF",  # EUR/CHF OTC
    }
)

# Default Canonical High-Winrate Pairs (Smooth price action, high payout)
DEFAULT_HIGH_WINRATE_WHITELIST: frozenset[str] = frozenset(
    {
        "EURUSD",  # EUR/USD OTC
        "USDCLP",  # USD/CLP OTC
        "USDBDT",  # USD/BDT OTC
        "USDEGP",  # USD/EGP OTC
        "GBPJPY",  # GBP/JPY OTC  <-- CRITICAL: Currently present in whitelist!
        "GOLD",  # Gold OTC
        "XAUUSD",  # XAU/USD OTC
    }
)
```

### 1.2 Canonical Symbol Normalization Logic
In `src/strat_trade/domain/trading/correlation.py` (lines 64–80):
```python
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
```
And in `src/strat_trade/domain/trading/asset_filter.py` (lines 38–46):
```python
def canonical_asset_key(asset: str | None) -> str:
    """Normalizes symbol to uppercase alphanumeric key (e.g. 'USD/IDR OTC' -> 'USDIDR')."""
    if not asset or not isinstance(asset, str):
        return ""
    clean = normalize_symbol(asset)
    if clean in ("GOLD", "XAUUSD"):
        return "GOLD"
    return clean
```

### 1.3 Normalization Formatting Verification
Tracing all variations of the 6 newly discovered high-drawdown pairs through `canonical_asset_key()`:
| Input Format Variation | `normalize_symbol` Intermediate | `canonical_asset_key` Output |
|---|---|---|
| `"USD/DZD OTC"` | `"USD/DZD"` -> `"USDDZD"` | `"USDDZD"` |
| `"USD_DZD_OTC"` | `"USD_DZD"` -> `"USDDZD"` | `"USDDZD"` |
| `"USDDZDOTC"` | `endswith("OTC")` -> `"USDDZD"` | `"USDDZD"` |
| `"USD/DZD"` | `"USDDZD"` | `"USDDZD"` |
| `"USD_DZD"` | `"USDDZD"` | `"USDDZD"` |
| `"USDDZD_otc"` | `"USDDZD"` | `"USDDZD"` |
| `"usddzd_otc"` | `"USDDZD"` | `"USDDZD"` |
| `"USD-DZD (OTC)"` | `\(.*?\)` stripped -> `"USD-DZD"` -> `"USDDZD"` | `"USDDZD"` |
| `"  USD/DZD (otc)  "` | `"USDDZD"` | `"USDDZD"` |
| `"UAH/USD OTC"` | `"UAH/USD"` -> `"UAHUSD"` | `"UAHUSD"` |
| `"uah_usd_otc"` | `"UAHUSD"` | `"UAHUSD"` |
| `"USD/MYR OTC"` | `"USD/MYR"` -> `"USDMYR"` | `"USDMYR"` |
| `"usdmyr_otc"` | `"USDMYR"` | `"USDMYR"` |
| `"USD/INR OTC"` | `"USD/INR"` -> `"USDINR"` | `"USDINR"` |
| `"usdinr_otc"` | `"USDINR"` | `"USDINR"` |
| `"EUR/HUF OTC"` | `"EUR/HUF"` -> `"EURHUF"` | `"EURHUF"` |
| `"eurhuf_otc"` | `"EURHUF"` | `"EURHUF"` |
| `"GBP/JPY OTC"` | `"GBP/JPY"` -> `"GBPJPY"` | `"GBPJPY"` |
| `"gbpjpy_otc"` | `"GBPJPY"` | `"GBPJPY"` |

All variations cleanly map to unique 6-character canonical keys (`USDDZD`, `UAHUSD`, `USDMYR`, `USDINR`, `EURHUF`, `GBPJPY`).

### 1.4 Enforcement in `LiveDemoBotEngine`
In `src/strat_trade/domain/trading/bot_engine.py`:
1. **Pre-Evaluation Check** (lines 428–436 in `_evaluate_single_asset`):
   ```python
   asset = assignment.asset
   # 1. Asset Quality & Toxic Blacklist Filter Check
   if getattr(self.plan, "toxic_filter_enabled", True):
       is_toxic, toxic_reason = is_toxic_asset(
           asset, custom_blacklist=getattr(self.plan, "asset_blacklist", None)
       )
       if is_toxic:
           logger.warning("Skipping %s: %s", asset, toxic_reason)
           return
   ```
2. **Atomic Execution Check** (lines 536–548 in `_execute_signal` under `self._order_lock`):
   ```python
   # Atomic Toxic Blacklist Check inside order lock
   if getattr(self.plan, "toxic_filter_enabled", True):
       is_toxic, toxic_reason = is_toxic_asset(
           assignment.asset, custom_blacklist=getattr(self.plan, "asset_blacklist", None)
       )
       if is_toxic:
           logger.error(
               "Blocked execution on blacklisted toxic asset: %s (%s)",
               assignment.asset,
               toxic_reason,
           )
           return
   ```

### 1.5 Enforcement in `StrategyAutoMatcher`
In `src/strat_trade/domain/optimizer/auto_matcher.py` (lines 365–371 in `find_optimal_strategy_for_asset`):
```python
# Check toxic OTC asset blacklist
is_toxic, toxic_reason = is_toxic_asset(asset)
if is_toxic:
    profile = self._heuristic_profile_for_asset(asset, strategies, expiration_bars)
    profile.quantum_score = 10.0
    profile.rationale = f"[TOXIC OTC BLACKLIST] {toxic_reason}"
    return profile
```

### 1.6 Default Settings and Use Case Fallbacks
- `src/strat_trade/settings.py` (lines 94–116):
  `toxic_asset_blacklist` default factory has `["USD/IDR OTC", "USD/VND OTC", "BNB OTC", "EUR/CHF OTC"]`.
  `high_winrate_asset_whitelist` default factory has `["EUR/USD OTC", "USD/CLP OTC", "USD/BDT OTC", "USD/EGP OTC", "GBP/JPY OTC", "Gold OTC"]`.
- `src/strat_trade/use_cases/auto_assign_strategies.py` (lines 49–58):
  `generate_pre_trading_plan` fallback `target_assets` includes `"GBPJPY_otc"`.
- `src/strat_trade/api/routes/candles.py` (lines 182–188):
  `_CURATED_ASSETS` contains `"symbol": "GBPJPY_otc"`.

---

## 2. Logic Chain

1. **Toxic Pair Identification (Phase 3 empirical findings)**:
   - Recent live broker data identified 6 OTC assets causing severe portfolio drawdowns:
     - `USD/DZD OTC` (33.3% WR)
     - `UAH/USD OTC` (28.6% WR)
     - `USD/MYR OTC` (33.3% WR)
     - `USD/INR OTC` (25.0% WR)
     - `EUR/HUF OTC` (0.0% WR)
     - `GBP/JPY OTC` (0.0% WR)
2. **Canonical Mapping & Set Expansion**:
   - `canonical_asset_key` deterministically maps each pair to `USDDZD`, `UAHUSD`, `USDMYR`, `USDINR`, `EURHUF`, and `GBPJPY`.
   - Expanding `DEFAULT_TOXIC_OTC_BLACKLIST` (and defining the alias `DEFAULT_TOXIC_BLACKLIST = DEFAULT_TOXIC_OTC_BLACKLIST`) in `asset_filter.py` automatically blocks these keys across any caller of `is_toxic_asset` and `filter_allowed_assets`.
3. **Reconciliation of `GBPJPY` in Whitelists**:
   - `GBPJPY` was previously categorized in `DEFAULT_HIGH_WINRATE_WHITELIST` in Phase 2.
   - Now that `GBP/JPY OTC` is empirically toxic (0.0% WR), keeping `GBPJPY` in any whitelist or curated list creates a direct semantic and logical contradiction.
   - `GBPJPY` must be removed from `DEFAULT_HIGH_WINRATE_WHITELIST` (`asset_filter.py`), `high_winrate_asset_whitelist` (`settings.py`), `generate_pre_trading_plan` fallback (`auto_assign_strategies.py`), and `_CURATED_ASSETS` (`candles.py`).
4. **Multi-Layer Defensive Propagation**:
   - `StrategyAutoMatcher.find_optimal_strategy_for_asset` calls `is_toxic_asset(asset)`: any blacklisted asset immediately receives `quantum_score = 10.0` and `rationale = "[TOXIC OTC BLACKLIST]..."`.
   - `LiveDemoBotEngine._evaluate_single_asset` calls `is_toxic_asset(asset)`: skips candle fetching and indicator evaluation.
   - `LiveDemoBotEngine._execute_signal` acquires `_order_lock` and calls `is_toxic_asset(assignment.asset)`: prevents order placement even under race conditions or external assignment tampering.
   - `generate_pre_trading_plan` calls `filter_allowed_assets`: completely removes blacklisted assets during plan compilation.

---

## 3. Caveats

1. **Custom Blacklist Override vs Extension**:
   - In `is_toxic_asset`:
     ```python
     if custom_blacklist:
         blacklist = {canonical_asset_key(x) for x in custom_blacklist}
     else:
         blacklist = {canonical_asset_key(x) for x in DEFAULT_TOXIC_OTC_BLACKLIST}
     ```
     When a user provides a custom `asset_blacklist` in API requests or settings, `custom_blacklist` replaces `DEFAULT_TOXIC_OTC_BLACKLIST`. Therefore, `settings.py:toxic_asset_blacklist` default factory MUST include the complete 11-asset toxic list.
2. **Existing Whitelist Assertions in Tests**:
   - Several existing unit tests (`test_strategy_curation_and_asset_filter.py`, `test_m4_empirical_challenger_2.py`, `test_empirical_stress_challenger.py`) explicitly assert that `"GBPJPY_otc"` is whitelisted and not toxic. Updating `GBPJPY` to toxic will require updating those assertions to reflect the new state.

---

## 4. Conclusion & Actionable Modifications Required for R2

### 4.1 Source Code Changes

#### 1. `src/strat_trade/domain/trading/asset_filter.py`
- Expand `DEFAULT_TOXIC_OTC_BLACKLIST` and add `DEFAULT_TOXIC_BLACKLIST`:
  ```python
  DEFAULT_TOXIC_OTC_BLACKLIST: frozenset[str] = frozenset(
      {
          "USDIDR",  # USD/IDR OTC
          "USDVND",  # USD/VND OTC
          "BNB",  # BNB OTC
          "BNBUSD",  # BNB/USD OTC
          "EURCHF",  # EUR/CHF OTC
          "USDDZD",  # USD/DZD OTC (33.3% WR)
          "UAHUSD",  # UAH/USD OTC (28.6% WR)
          "USDMYR",  # USD/MYR OTC (33.3% WR)
          "USDINR",  # USD/INR OTC (25.0% WR)
          "EURHUF",  # EUR/HUF OTC (0.0% WR)
          "GBPJPY",  # GBP/JPY OTC (0.0% WR)
      }
  )
  DEFAULT_TOXIC_BLACKLIST = DEFAULT_TOXIC_OTC_BLACKLIST
  ```
- Remove `"GBPJPY"` from `DEFAULT_HIGH_WINRATE_WHITELIST`:
  ```python
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
  ```

#### 2. `src/strat_trade/settings.py`
- Update `toxic_asset_blacklist`:
  ```python
  toxic_asset_blacklist: list[str] = Field(
      default_factory=lambda: [
          "USD/IDR OTC",
          "USD/VND OTC",
          "BNB OTC",
          "EUR/CHF OTC",
          "USD/DZD OTC",
          "UAH/USD OTC",
          "USD/MYR OTC",
          "USD/INR OTC",
          "EUR/HUF OTC",
          "GBP/JPY OTC",
      ],
      ...
  )
  ```
- Remove `"GBP/JPY OTC"` from `high_winrate_asset_whitelist`:
  ```python
  high_winrate_asset_whitelist: list[str] = Field(
      default_factory=lambda: [
          "EUR/USD OTC",
          "USD/CLP OTC",
          "USD/BDT OTC",
          "USD/EGP OTC",
          "Gold OTC",
      ],
      ...
  )
  ```

#### 3. `src/strat_trade/use_cases/auto_assign_strategies.py`
- In `generate_pre_trading_plan` lines 50–57, remove `"GBPJPY_otc"` from default fallback assets when `target_assets` is empty:
  ```python
  if not target_assets:
      target_assets = [
          "EURUSD_otc",
          "USDCLP_otc",
          "USDBDT_otc",
          "USDEGP_otc",
          "Gold_otc",
      ]
  ```

#### 4. `src/strat_trade/api/routes/candles.py`
- Remove `"GBPJPY_otc"` from `_CURATED_ASSETS` (lines 182–188).

### 4.2 Test Suite Updates

1. **`tests/test_strategy_curation_and_asset_filter.py`**:
   - In `test_canonical_asset_key_normalization`: add tests for all 6 new pairs and their permutations.
   - In `test_is_toxic_asset_detection`: add the 6 new pairs to `toxic_assets`, remove `"GBPJPY_otc"` from `clean_assets`.
   - In `test_is_whitelisted_asset`: remove `"GBP/JPY OTC"` and `"GBPJPY_otc"` from `whitelist_pairs`, add to `non_whitelist`.
   - In `test_filter_allowed_assets`: update `raw_list` expectations so `"GBPJPY_otc"` is filtered out.
2. **`tests/test_empirical_stress_challenger.py`**:
   - In `test_toxic_asset_exhaustive_variations_rejected`: add permutations of `USD/DZD`, `UAH/USD`, `USD/MYR`, `USD/INR`, `EUR/HUF`, `GBP/JPY`.
   - In `test_whitelisted_assets_canonicalization`: remove `GBP/JPY OTC`.
3. **`tests/test_m4_empirical_challenger_2.py`**:
   - In `test_generate_pre_trading_plan_all_toxic_fallback`: update expected plan asset count to 5.
   - In `test_generate_pre_trading_plan_custom_whitelist_and_blacklist_enforcement`: replace `GBPJPY_otc` with `USDBDT_otc`.

---

## 5. Verification Method

### 5.1 Unit & Integration Test Execution
Run the asset filter and bot engine test suites:
```bash
.venv/bin/pytest tests/test_strategy_curation_and_asset_filter.py \
                 tests/test_empirical_stress_challenger.py \
                 tests/test_m4_empirical_challenger_2.py \
                 tests/test_rolling_15_regression.py -v
```

### 5.2 Full Regression Test Suite
Run complete pytest test suite (472+ items):
```bash
.venv/bin/pytest
```

### 5.3 Lint and Type Checks
```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src/strat_trade/domain/trading/asset_filter.py \
               src/strat_trade/settings.py \
               src/strat_trade/use_cases/auto_assign_strategies.py \
               src/strat_trade/domain/optimizer/auto_matcher.py \
               src/strat_trade/domain/trading/bot_engine.py
```

### 5.4 Invalidation Conditions
The solution is invalid if:
1. Any variation of `USD/DZD`, `UAH/USD`, `USD/MYR`, `USD/INR`, `EUR/HUF`, `GBP/JPY` passes `is_toxic_asset()` as non-toxic (`False`).
2. `LiveDemoBotEngine` or `generate_pre_trading_plan` allows any of these 6 pairs to be executed or assigned.
3. `GBPJPY` remains in `DEFAULT_HIGH_WINRATE_WHITELIST` while simultaneously residing in `DEFAULT_TOXIC_OTC_BLACKLIST`.
