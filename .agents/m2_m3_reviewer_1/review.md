# Quality & Adversarial Review Report: Milestones M2 & M3

**Reviewer**: M2/M3 Reviewer 1 (Archetype: reviewer_critic)  
**Parent Orchestrator**: `965d505d-f351-4731-b173-775c7711e297`  
**Date**: 2026-08-23  
**Working Directory**: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m2_m3_reviewer_1`  
**Scope**: 
- `src/strat_trade/web/templates/index.html` (Requirement R2)
- `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py` (Requirement R2)
- `src/strat_trade/domain/trading/asset_filter.py` (Requirement R3)
- `src/strat_trade/domain/trading/bot_engine.py` (Requirement R3)
- `src/strat_trade/domain/optimizer/auto_matcher.py` (Requirements R1, R2, R3)

---

## 1. Review Summary

**Verdict**: **APPROVE**  
**Overall Risk Assessment**: LOW  
**Integrity Status**: PASS (Zero integrity violations; genuine mathematical and architectural implementations without mocks, facades, or hardcoded cheating).

The implementation of Milestone 2 (UI Expiration Simplification & Strategy-Driven Auto-Expiration) and Milestone 3 (Dynamic Microstructure Noise Filtering & Anti-Whipsaw Cooldown) satisfies all architectural and functional requirements defined in `PROJECT.md` and `ORIGINAL_REQUEST.md`.

---

## 2. Integrity & Anti-Cheating Audit

| Integrity Dimension | Checked Aspect | Assessment |
|---------------------|----------------|------------|
| **Hardcoded Outputs** | Source code inspection for hardcoded test results or constant spoofing | **PASS** — Strategies and engines compute dynamic metrics directly from input data. |
| **Facade Implementations** | Dummy classes/functions returning superficial success values | **PASS** — `qualify_asset_microstructure`, `filter_allowed_assets`, `bot_engine`, and `auto_matcher` contain full production logic. |
| **Task Bypasses** | External shortcuts or bypassing core requirements | **PASS** — All UI elements, parameter definitions, and statistical qualification routines are properly wired. |
| **Attestation Artifacts** | Authenticity of test results and coverage logs | **PASS** — Verified independently via full execution of pytest (840 tests passing) and ruff static analysis (0 errors). |

---

## 3. Detailed Component Review

### 3.1 Frontend & Template Dock (`src/strat_trade/web/templates/index.html`)
- **Observation**:
  - The manual `<select id="botCfgExpiration">` dropdown in the Live Bot configuration dock has been removed cleanly.
  - The form layout was rebalanced into a clean two-column grid pairing `botCfgStopLoss` with `botCfgMinPayout`.
  - In `prepareLiveBotLaunch()`, the payload definition no longer extracts `expiration_seconds`, enabling backend strategy parameter defaults to govern trade durations.
  - Global codebase search for `botCfgExpiration` across templates returns 0 occurrences.
- **Correctness & Style**: Glassmorphism UI tokens and responsive Tailwind grid structures are fully preserved.
- **Verdict**: PASS.

### 3.2 Strategy Expiration Calibration (`src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`)
- **Observation**:
  - `RsiStochasticExtremeStrategy.__init__` now defaults to `base_expiration_bars: int = 3` (180 seconds on M1 feeds).
  - `get_parameter_definitions()` defines `base_expiration_bars` with default `3`, min `1`, max `5`, step `1`.
  - Signal evaluation correctly propagates `self.base_expiration_bars` in `SignalResult.expiration_bars`.
- **Verdict**: PASS.

### 3.3 Dynamic Microstructure Noise Filtering (`src/strat_trade/domain/trading/asset_filter.py`)
- **Observation**:
  - `qualify_asset_microstructure(candles: pd.DataFrame) -> tuple[bool, str]` evaluates 4 statistical dimensions:
    1. Minimum history: $\ge 50$ bars required.
    2. `flat_bar_ratio`: proportion of bars with $High \le Low + 10^{-9}$ or $|Close - Open| \le 10^{-9}$. Rejects if $> 15\%$.
    3. `unique_price_ratio`: $\frac{|\{Close\}|}{N}$. Rejects if $< 30\%$.
    4. `whipsaw_sign_flip_ratio`: proportion of consecutive 1-bar return sign flips ($r_t \cdot r_{t-1} < 0$). Rejects if $> 80\%$.
    5. `relative_atr`: $\frac{ATR(14)}{Close}$. Rejects if $< 0.00003$ (dead/zero volatility).
  - `filter_allowed_assets()` seamlessly integrates optional `candle_data` dictionary to qualify feeds dynamically while remaining backward-compatible.
- **Verdict**: PASS.

### 3.4 Live Demo Bot Engine & Anti-Whipsaw Cooldown (`src/strat_trade/domain/trading/bot_engine.py`)
- **Observation**:
  - Line 345: Post-trade settlement cooldown enforces a hard floor: `cooldown_sec = max(180, cooldown_bars * 60)`.
  - Line 443: Cooldown is inspected prior to candle fetching in `_evaluate_single_asset()`.
  - Line 557: Atomic check inside `async with self._order_lock:` prevents race conditions when concurrent signals fire around the settlement boundary.
- **Verdict**: PASS.

### 3.5 Strategy AutoMatcher Integration (`src/strat_trade/domain/optimizer/auto_matcher.py`)
- **Observation**:
  - `PRIORITY_STRATEGIES` is constrained to `{"support_resistance_bounce", "rsi_stochastic_extreme", "ema_pullback_trend"}`.
  - Microstructure qualification check is invoked on candle data ($\ge 50$ bars). Rejected assets receive low quantum scores ($15.0$) with clear explanatory diagnostics.
  - Quantum scoring prioritizes sniper strategies ($+15.0$ bonus) and whitelisted assets ($+15.0$ bonus).
- **Verdict**: PASS.

---

## 4. Adversarial Stress-Testing & Edge Cases

| Stress Scenario | Attack / Stress Vector | Observed Behavior | Status |
|-----------------|------------------------|-------------------|--------|
| **Discrete Step-Tick Feeds** | Simulated 5-level discrete price quantization with flat bars | `qualify_asset_microstructure` rejected with `Unique price ratio 8.33% below threshold 30.00%` | **PASS** |
| **Micro-Whipsaw Noise** | Perfect alternating returns ($r_t \cdot r_{t-1} < 0$ on 100% of bars) | `qualify_asset_microstructure` rejected with `Whipsaw sign flip ratio 100.00% exceeds threshold 80.00%` | **PASS** |
| **Dead / Flatline Feeds** | $ATR(14)/Close = 0.000001 < 0.00003$ | `qualify_asset_microstructure` rejected with `Relative ATR below threshold 0.000030` | **PASS** |
| **Continuous Liquid Feeds** | Random walk + drift simulation for EURUSD, GBPUSD, USDJPY, AUDUSD, USDCLP, USDBDT, USDEGP, Gold | 100% qualification pass rate with detailed diagnostic status | **PASS** |
| **Cooldown Boundary Race** | 2 concurrent async tasks attempting order placement within 180s post-settlement | First task locks mutex, second task is atomically rejected by `_asset_cooldown_until` check inside `_order_lock` | **PASS** |
| **Missing Expiration Input** | Frontend POST `/api/v1/bot/auto-assign` payload without `expiration_seconds` | Backend defaults to 180s and assigns 3-bar strategy parameter | **PASS** |

---

## 5. Verification Results

1. **Pytest Test Suite Execution**:
   - Command: `.venv/bin/pytest`
   - Result: `840 passed, 2 warnings in 25.97s` (100% pass rate).
2. **Static Analysis & Ruff Linting**:
   - Command: `.venv/bin/ruff check src tests`
   - Result: `All checks passed!` (0 lint errors).
3. **Template Inspection**:
   - Command: `grep -rn "botCfgExpiration" src/strat_trade/web/templates/`
   - Result: 0 matches.

---

## 6. Recommendations & Handoff Note

- Work products for M2 and M3 are fully validated and production-ready.
- The pipeline is clear to proceed to Milestone 4 (E2E Verification & Rolling 15-Trade Validation across 600+ real broker trades).
