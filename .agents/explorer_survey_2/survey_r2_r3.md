# Architectural Survey: Requirements R2 & R3
**Project**: Pocket Option AutoTrader Pro (`strat_trade_be`)  
**Investigator**: Explorer 2 (UI Expiration & Dynamic Noise Filtering Architecture)  
**Date**: 2026-08-23  
**Status**: Investigation Complete — Ready for Implementation  

---

## Executive Summary

This architectural survey provides an exhaustive forensic investigation of the codebase for:
1. **Requirement R2 (UI Expiration Simplification & Automated Strategy-Driven Expiration)**: Removing manual expiration inputs from the live bot configuration dock in `src/strat_trade/web/templates/index.html` and JavaScript payload builders, while embedding optimal calibrated expiration durations (180s / 3 bars on M1) into backend strategy parameter definitions (`Support & Resistance Pin-Bar`, `RSI + Stoch Extreme Scalp`, `EMA Ribbon Trend Pullback`, etc.).
2. **Requirement R3 (Dynamic Regime & Micro-Tick Noise Filtering)**: Replacing the rigid 6-pair whitelist with dynamic asset qualification based on statistical microstructure metrics (flat-bar ratio, price quantization entropy, micro-whipsaw sign-flip frequency, and minimum ATR threshold) to block erratic step-tick assets (e.g. crypto OTC and illiquid exotics) while permitting all liquid continuous OTC and Forex pairs, coupled with a minimum 3-5 minute per-asset anti-whipsaw post-settlement cooldown in the trading engine.

---

## 1. Requirement R2: UI Expiration Simplification & Automated Strategy-Driven Expiration

### 1.1 Current Codebase Flow & Findings

#### A. Frontend Template (`src/strat_trade/web/templates/index.html`)
- **Dock Markup (Lines 226–239)**:
  ```html
  <!-- Expiration & Stop-Loss -->
  <div class="grid grid-cols-2 gap-3">
    <div>
      <label class="text-xs text-gray-400 block mb-1">Час експірації</label>
      <select id="botCfgExpiration" class="w-full glass-input text-xs rounded-lg px-2.5 py-2">
        <option value="60">60 сек (M1)</option>
        <option value="180" selected>180 сек (M3)</option>
        <option value="300">300 сек (M5)</option>
      </select>
    </div>
    <div>
      <label class="text-xs text-gray-400 block mb-1">Сесійний Stop-Loss (%)</label>
      <input type="number" id="botCfgStopLoss" value="5" min="1" max="50" step="1" class="w-full glass-input text-xs rounded-lg px-2.5 py-2" />
    </div>
  </div>
  ```
  - **Issue**: Manual dropdown allows the user to override optimal strategy execution with sub-optimal durations (e.g. 60s on Pin-Bar or Extreme Scalp, which requires 180s / 3 bars to allow price to fully reject and reverse).
  - **Remedy**: Cleanly remove `#botCfgExpiration`. Combine `#botCfgStopLoss` with `#botCfgMinPayout` into a clean, balanced 2-column grid (`grid grid-cols-2 gap-3`).

- **JavaScript Payload Construction (Lines 1785–1795)**:
  ```javascript
  const payload = {
    assets: selectedAssets,
    initial_deposit: parseFloat(document.getElementById('botCfgDeposit').value),
    stake_model: document.getElementById('botCfgStakeModel').value,
    stake_amount: parseFloat(document.getElementById('botCfgStakeAmount').value),
    stake_percent: parseFloat(document.getElementById('botCfgStakePercent').value),
    expiration_seconds: parseInt(document.getElementById('botCfgExpiration').value),
    daily_stop_loss_pct: parseFloat(document.getElementById('botCfgStopLoss').value) / 100.0,
    max_concurrent_trades: parseInt(document.getElementById('botCfgMaxConcurrent').value),
    min_payout_rate: parseFloat(document.getElementById('botCfgMinPayout').value) / 100.0,
  };
  ```
  - **Remedy**: Remove `expiration_seconds: parseInt(...)` from `prepareLiveBotLaunch()`. Backend Pydantic schema `AutoAssignRequest` defaults `expiration_seconds = 180` and derives exact expiration bars directly from the assigned strategy's parameter definition.

#### B. Backend API Route & Schema Handling
- **`src/strat_trade/api/schemas.py`**:
  - `AutoAssignRequest` (line 709): `expiration_seconds: int = Field(180, ge=5, le=86400, description="Trade duration in seconds")` is already defaulted to 180.
  - `PreTradingPlanResponse` (line 751): Returns `expiration_seconds: int` (180).
- **`src/strat_trade/api/routes/bot.py`**:
  - Line 46: `expiration_seconds=req.expiration_seconds` (defaults to 180 when omitted).
  - Line 82: `expiration_seconds=plan.expiration_seconds` in `PreTradingPlanResponse`.
  - Line 130: `expiration_seconds=req.plan.expiration_seconds` in `StartBotRequest`.

#### C. Backend Strategy Parameter Definitions & Expiration Defaults
- **`src/strat_trade/domain/strategies/support_resistance_bounce.py`**:
  - `__init__`: `base_expiration_bars: int = 3` (Lines 23, 29).
  - `get_parameter_definitions`: `ParameterDef("base_expiration_bars", "Expiration Bars", "int", 3, 1, 5, 1, description="Expiration bars")` (Lines 131–139).
  - Matches 180s (3 bars on 60s M1).
- **`src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`**:
  - `__init__`: Currently `base_expiration_bars: int = 2` (Line 27).
  - `get_parameter_definitions`: `ParameterDef("base_expiration_bars", "Expiration Bars", "int", 2, ...)` (Line 148).
  - **Calibration needed**: Update default `base_expiration_bars` to `3` (180s) to align with high-winrate dual oscillator exhaustion window.
- **`src/strat_trade/domain/strategies/ema_pullback_trend.py`**:
  - `__init__`: `base_expiration_bars: int = 3` (Line 32).
  - `get_parameter_definitions`: `ParameterDef("base_expiration_bars", "Expiration Bars", "int", 3, ...)` (Line 214).
  - Matches 180s (3 bars on 60s M1).
- **`src/strat_trade/domain/strategies/bollinger_atr_reversion.py`**:
  - `base_expiration_bars: int = 3` (Line 30).
- **`src/strat_trade/domain/strategies/supertrend_adx_momentum.py`**:
  - `base_expiration_bars: int = 3` (Line 26).

#### D. Pre-Trading Plan Strategy Assignment & Execution
- **`src/strat_trade/use_cases/auto_assign_strategies.py`**:
  - `generate_pre_trading_plan()`: Line 70 passes `expiration_bars=max(1, expiration_seconds // 60)` (default 3 bars = 180s).
- **`src/strat_trade/domain/trading/bot_engine.py`**:
  - In `_execute_order()` (lines 585 & 608): Order duration is passed as `expiration_seconds=assignment.parameters.get("base_expiration_bars", 3) * 60` or `self.plan.expiration_seconds`.

---

## 2. Requirement R3: Dynamic Regime & Micro-Tick Noise Filtering

### 2.1 Analysis of Current Asset Filtering vs Dynamic Qualification

#### A. Current Implementation (`src/strat_trade/domain/trading/asset_filter.py`)
- **Static Toxic Blacklist (`DEFAULT_TOXIC_OTC_BLACKLIST`)**: 11 symbols (`USDIDR`, `USDVND`, `BNB`, `BNBUSD`, `EURCHF`, `USDDZD`, `UAHUSD`, `USDMYR`, `USDINR`, `EURHUF`, `GBPJPY`).
- **Static Whitelist (`DEFAULT_HIGH_WINRATE_WHITELIST`)**: 6 symbols (`EURUSD`, `USDCLP`, `USDBDT`, `USDEGP`, `GOLD`, `XAUUSD`).
- **Problem**: 
  - The rigid 6-pair whitelist excludes valuable liquid continuous assets like `GBPUSD_otc`, `USDJPY_otc`, `AUDUSD_otc`, `USDCAD_otc`, `EURGBP_otc`, `EURJPY_otc`, and spot Forex pairs (`EURUSD`, `GBPUSD`, `USDJPY`, `AUDUSD`).
  - A static blacklist cannot detect newly added exotic OTC assets or crypto tokens that exhibit discrete step-ticks, low volume, or erratic micro-whipsaws.

#### B. Dynamic Statistical Microstructure Qualification Architecture
To implement dynamic asset qualification that analyzes real price action, we define quantitative metrics calculated over 30–150 recent 1-minute bars:

1. **Flat-Bar Ratio (`flat_bar_ratio`)**:
   $$\text{flat\_bar\_ratio} = \frac{\sum_{i=1}^N \mathbf{1}_{\{High_i == Low_i \text{ or } |High_i - Low_i| \le \epsilon\}}}{N}$$
   - *Continuous liquid assets* (`EURUSD_otc`, `USDJPY_otc`, `Gold_otc`): $< 5\%$.
   - *Discrete step-tick noise* (`USDIDR`, `USDVND`, dead exotics): $> 15\%-40\%$.
   - **Threshold**: Disqualify if `flat_bar_ratio > 0.15` (15%).

2. **Price Quantization Entropy / Unique Close Ratio (`unique_close_ratio`)**:
   $$\text{unique\_close\_ratio} = \frac{|\{Close_i : i=1\dots N\}|}{N}$$
   - *Continuous assets*: $> 0.40-0.70$ (price smoothly explores continuous spectrum).
   - *Quantized step-tick feeds*: $< 0.30$ (price stuck bouncing between 3-5 discrete price points).
   - **Threshold**: Disqualify if `unique_close_ratio < 0.30` (30%).

3. **Directional Alternation / Micro-Whipsaw Ratio (`sign_flip_ratio`)**:
   $$\text{sign\_flip\_ratio} = \frac{\sum_{i=2}^N \mathbf{1}_{\{\Delta p_i \cdot \Delta p_{i-1} < 0\}}}{N-1}$$
   - *Micro-whipsaw noise*: $> 80\%$ with near-zero displacement $\left(\frac{|\sum \Delta p|}{\sum |\Delta p|} < 0.05\right)$.
   - Indicates random alternating tick noise without technical support/resistance or momentum.
   - **Threshold**: Disqualify if `sign_flip_ratio > 0.80` with low directional efficiency.

4. **Minimum Normalized ATR Volatility**:
   $$\text{rel\_atr} = \frac{ATR(14, df)}{Close}$$
   - **Threshold**: Disqualify if $\text{rel\_atr} < 0.00003$ (zero-volatility dead asset).

5. **Multi-Layer Hybrid Filtering Workflow**:
   ```
   Asset Candidate
          │
          ├── Layer 1: Canonical Symbol Normalization (regex)
          │
          ├── Layer 2: Fast Static Blacklist (USDIDR, USDVND, BNB, etc.) -> REJECT
          │
          ├── Layer 3: Dynamic Microstructure Analyzer (Candles / Ticks)
          │     ├── Flat-Bar Ratio <= 15%
          │     ├── Unique Price Levels >= 30%
          │     ├── Directional Noise & Whipsaw Checks
          │     └── Minimum Relative ATR >= 0.00003
          │     └── FAIL -> REJECT with diagnostic reason
          │
          └── Layer 4: Qualified Liquid Asset (Forex OTC, Spot Forex, Liquid Commodities) -> ACCEPT
   ```

### 2.2 Anti-Whipsaw Post-Settlement Cooldown Architecture

#### A. Engine Cooldown Mechanics (`src/strat_trade/domain/trading/bot_engine.py`)
- **State Tracking**: `self._asset_cooldown_until: dict[str, datetime] = {}` (Line 48).
- **Settlement Trigger (Lines 343–358)**:
  When an open trade closes, compute cooldown:
  ```python
  cooldown_bars = self.plan.cooldown_bars if self.plan else 3
  cooldown_sec = max(180, cooldown_bars * 60)  # Hard minimum 3-5 minutes (180-300s)
  self._asset_cooldown_until[trade.asset] = now + timedelta(seconds=cooldown_sec)
  ```
- **Evaluation Filter (Lines 441–450)**:
  `_evaluate_single_asset()` checks `self._asset_cooldown_until.get(asset)` and skips scanning if active.
- **Atomic Concurrency Guard (Line 549)**:
  Add an atomic cooldown check inside `async with self._order_lock:` in `_execute_order()` to eliminate race conditions between concurrent worker loops:
  ```python
  cooldown_until = self._asset_cooldown_until.get(assignment.asset)
  if cooldown_until and now < cooldown_until:
      logger.debug("Asset %s is in post-settlement cooldown inside order lock", assignment.asset)
      return
  ```
- **Backtesting Alignment (`PortfolioBacktestEngine`)**:
  `src/strat_trade/domain/backtest/portfolio_engine.py` (lines 269–275) enforces `cooldown_bars` (default 3 bars = 180s) to prevent repeat entries during breakout whipsaws.

---

## 3. Comprehensive File Inventory & Affected Components

| Component | File Path | Scope of Changes for R2 & R3 |
| :--- | :--- | :--- |
| **Frontend UI Template** | `src/strat_trade/web/templates/index.html` | Remove `botCfgExpiration` select; clean 2-col grid for Stop-Loss & Payout; remove `expiration_seconds` from JS payload builder. |
| **Asset Filter Domain** | `src/strat_trade/domain/trading/asset_filter.py` | Add `qualify_asset_microstructure()`, `is_step_tick_noise()`, relax rigid 6-pair whitelist to support all liquid continuous pairs. |
| **Bot Engine** | `src/strat_trade/domain/trading/bot_engine.py` | Enforce hard minimum 3-min cooldown (`max(180, cooldown_sec)`), atomic cooldown check in `_execute_order`. |
| **Auto Matcher** | `src/strat_trade/domain/optimizer/auto_matcher.py` | Integrate dynamic asset qualification, assign 3-bar default expiration, update priority strategy scores. |
| **Auto Assign Use Case** | `src/strat_trade/use_cases/auto_assign_strategies.py` | Use dynamic qualification and default 180s expiration. |
| **Strategy Definitions** | `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py` | Update default `base_expiration_bars` to 3 (180s). |
| **Settings** | `src/strat_trade/settings.py` | Update default whitelist and blacklist configurations. |
| **API Schemas** | `src/strat_trade/api/schemas.py` | Ensure `AutoAssignRequest` defaults `expiration_seconds=180` and `cooldown_bars=3`. |

---

## 4. Test Suite Inventory & Verification Plan

### 4.1 Affected Test Suites
- `tests/test_strategy_curation_and_asset_filter.py`: Unit and integration tests for asset filtering, canonical key normalization, toxic blacklist, and whitelist behavior.
- `tests/test_m2_toxic_blacklist_fuzz.py`: Fuzzing tests for symbol normalization and toxic pair rejection.
- `tests/test_m2_adversarial_stress.py`: Stress tests on asset filtering and strategy execution.
- `tests/test_bot_and_audit_api.py`: REST API tests for bot auto-assignment, start, status, stop endpoints.
- `tests/test_strategy_auto_matcher.py`: Tests for strategy auto-matcher scoring and heuristic fallbacks.
- `tests/test_execution_guardrails.py`: Engine guardrails, post-trade settlement cooldown, and circuit breakers.
- `tests/test_portfolio_backtest_models_and_engine.py`: Portfolio backtest engine cooldown and expiration verification.

### 4.2 Verification Commands
```bash
# 1. Run all unit & integration tests
.venv/bin/pytest -v

# 2. Run specific asset filter & strategy curation tests
.venv/bin/pytest tests/test_strategy_curation_and_asset_filter.py tests/test_m2_toxic_blacklist_fuzz.py tests/test_bot_and_audit_api.py -v

# 3. Static type & lint checks
.venv/bin/ruff check src tests
.venv/bin/mypy src/strat_trade/domain/trading/asset_filter.py src/strat_trade/domain/trading/bot_engine.py src/strat_trade/api/schemas.py src/strat_trade/use_cases/auto_assign_strategies.py
```

---

## 5. Implementation Recommendations & Action Plan

1. **Step 1 (UI Simplification)**:
   - In `index.html`, remove `<select id="botCfgExpiration">` and update `prepareLiveBotLaunch()` to omit `expiration_seconds`.
2. **Step 2 (Strategy Expiration Calibration)**:
   - In `rsi_stochastic_extreme.py`, set default `base_expiration_bars = 3` (180s).
   - Verify `SupportResistanceBounceStrategy` and `EmaPullbackTrendStrategy` are calibrated to `base_expiration_bars = 3`.
3. **Step 3 (Dynamic Micro-Tick Noise Qualification)**:
   - Implement `qualify_asset_microstructure()` in `asset_filter.py` with flat-bar ratio ($\le 15\%$), unique price ratio ($\ge 30\%$), and micro-whipsaw sign-flip filter.
   - Update `filter_allowed_assets()` and `StrategyAutoMatcher` to apply dynamic qualification when candle data is available.
4. **Step 4 (Anti-Whipsaw Cooldown Enforcement)**:
   - In `bot_engine.py`, enforce `cooldown_sec = max(180, cooldown_bars * 60)` upon trade close and add an atomic check in `_execute_order()`.
5. **Step 5 (Full Verification)**:
   - Run complete test suite (`.venv/bin/pytest`) and static analysis (`ruff`, `mypy`).
