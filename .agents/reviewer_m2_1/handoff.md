# Milestone 2 Review Report: Risk Governance, Circuit Breakers & UI Telemetry

**Reviewer**: Reviewer 1 (Reviewer & Adversarial Critic)  
**Date**: 2026-08-24  
**Verdict**: **APPROVE**  
**Project**: `strat_trade_be`  
**Milestone**: Milestone 2 — Risk Governance & Telemetry UI  

---

## 1. Observation

Direct observations from codebase inspection, verification commands, and static analysis:

1. **Global Consecutive-Loss Circuit Breaker (15-Minute Lockout)**:
   - File: `src/strat_trade/domain/trading/bot_engine.py` (lines 41-49, 134-154, 212-222, 360-384).
   - `LiveDemoBotEngine` tracks `consecutive_losses` atomically.
   - Upon encountering `TradeOutcome.LOSS`, if `consecutive_losses >= max_consecutive_losses` (default 3), status transitions to `BotStatus.PAUSED` and sets `paused_until = now + timedelta(minutes=15)` (900 seconds global pause across all assets).
   - In `_run_loop()`, when `datetime.now(UTC) >= self.paused_until`, the bot auto-resumes to `BotStatus.RUNNING`, resets `paused_until = None`, and resets `consecutive_losses = 0`.
   - In `resume()`, manual resumption resets status to `BotStatus.RUNNING`, clears `paused_until = None`, and resets `consecutive_losses = 0`.
   - In `_check_active_trades()`, any `TradeOutcome.WIN` resets `consecutive_losses = 0`.
   - In `_evaluate_signals_and_trade()`, `_evaluate_single_asset()`, and `_execute_order()`, trade scanning and execution are strictly blocked while in `BotStatus.PAUSED`.

2. **Portfolio Backtest Parity**:
   - File: `src/strat_trade/domain/backtest/portfolio_engine.py` (lines 187-200, 254-283).
   - `PortfolioBacktestEngine` mirrors live risk governance with exact mathematical parity: 3 consecutive losses set `paused_until_time = t.exit_time + timedelta(minutes=15)`.
   - All candidate signals during the pause window are skipped (`sig.entry_time < paused_until_time`), and once expired (`sig.entry_time >= paused_until_time`), `paused_until_time` is cleared and `consecutive_losses` is reset to 0.

3. **Anti-Whipsaw Cooldown ($\ge 180$s / 3 min post-settlement)**:
   - File: `src/strat_trade/domain/trading/bot_engine.py` (lines 343-358, 442-451, 557-566).
   - Sets `cooldown_sec = max(180, cooldown_bars * 60)` upon trade settlement, populating `self._asset_cooldown_until[trade.asset]`.
   - Enforced both at initial candidate evaluation (`_evaluate_single_asset`) and atomically under `_order_lock` before placing an order (`_execute_order`).
   - File: `src/strat_trade/domain/backtest/portfolio_engine.py` (lines 270-277).
   - Aligned post-settlement cooldown calculation: `cooldown_sec = max(180, self.config.cooldown_bars * self.config.timeframe_seconds)`.

4. **Asset Microstructure Qualification & Noise Filtering**:
   - File: `src/strat_trade/domain/trading/asset_filter.py` (lines 96-195).
   - `qualify_asset_microstructure(candles: pd.DataFrame) -> tuple[bool, str]` validates 4 quantitative metrics:
     1. `flat_bar_ratio <= 0.15` (15%)
     2. `unique_price_ratio >= 0.30` (30%)
     3. `whipsaw_sign_flip_ratio <= 0.80` (80%)
     4. `relative_atr >= 0.000030` (0.003% of price)
   - Guards against `< 50` bars, NaNs, missing columns, and non-positive prices.

5. **UI Telemetry & Controls**:
   - File: `src/strat_trade/web/templates/index.html` (lines 1885-2048).
   - Dedicated `PAUSED (COOLDOWN)` amber warning badge with pulse animation.
   - Local 1-second interval ticker (`startPauseCountdownTicker()`) dynamically calculating countdown timer (`MM:SS`) from `data.paused_until`.
   - Consecutive loss indicators in bot status headers and KPI ribbon cards (`(3L streak)` / `Streak: 3/3`).
   - Manual `Відновити` (Resume) button wired to `POST /api/v1/bot/resume`.

6. **Test Suite Verification**:
   - `tests/test_risk_governance_circuit_breaker.py`: 10 passed in 0.59s.
   - Full pytest test suite: 975 passed in 26.19s with 0 failures.
   - `ruff check src`: All checks passed with 0 errors.
   - `ruff check tests/test_risk_governance_circuit_breaker.py`: All checks passed with 0 errors.

---

## 2. Logic Chain

```
[Observation: bot_engine.py tracks consecutive_losses & sets paused_until = now + 15m upon 3 losses]
                                 │
                                 ▼
[Observation: bot_engine.py resets streak on WIN, on expiry in _run_loop, and on resume()]
                                 │
                                 ▼
[Observation: portfolio_engine.py mirrors identical 15m pause & 180s per-asset cooldown parity]
                                 │
                                 ▼
[Observation: qualify_asset_microstructure implements genuine 4-metric statistical filtering]
                                 │
                                 ▼
[Observation: index.html receives paused_until & consecutive_losses via /api/v1/bot/status]
                                 │
                                 ▼
[Observation: test_risk_governance_circuit_breaker.py passes all 10 tests & full suite passes 975/975]
                                 │
                                 ▼
[Conclusion: Milestone 2 risk governance and UI telemetry are fully implemented and verified.]
```

---

## 3. Findings

### [Minor] Finding 1: Ruff Lint Cleanups in Challenger Test Files
- **What**: 32 ruff lint errors (unused imports, line too long, unused variables) exist in `tests/test_m2_challenger_1_empirical_stress.py` and `tests/test_m2_challenger_2_empirical_verification.py`.
- **Where**: `tests/test_m2_challenger_1_empirical_stress.py` and `tests/test_m2_challenger_2_empirical_verification.py`.
- **Why**: Challenger test files created during development contained minor stylistic/lint issues. Note that `src/` and `tests/test_risk_governance_circuit_breaker.py` are 100% clean.
- **Suggestion**: Run `ruff check --fix tests` or format lines in challenger test files before final milestone signoff.

---

## 4. Adversarial Stress-Testing & Integrity Assessment

### Integrity Checks
- **No hardcoded results**: All calculations (streaks, pause intervals, ATR, unique prices, sign flips) are computed dynamically from live inputs and market data.
- **No facade implementations**: The bot engine, portfolio engine, and microstructure filters contain full production logic with defensive error handling and asyncio locks.
- **No shortcut delegations**: Verification suite runs real tests against real domain models and FastAPI routes.

### Stress-Test Scenarios Evaluated
1. **Multi-Asset Loss Cascade**: When 3 different assets lose in sequence (EURUSD -> GBPUSD -> USDJPY), the global circuit breaker triggers immediately, pausing all trading for 15 minutes.
2. **Double-Checked Locking for Cooldowns**: Post-settlement cooldown is evaluated both before signal generation and atomically under `_order_lock`, eliminating race conditions between concurrent asset tasks.
3. **Auto-Resume & Expiry Timing**: Simulated clock progression past `paused_until` properly transitions bot to RUNNING and resets streak to 0.
4. **Isolated Loss Resilience**: Alternating loss-win sequences (e.g. L-L-W-L-L-W) never trigger false positive circuit breaker pauses.
5. **Extreme Microstructure Feeds**: Flatlines, discrete 5-step ladders, zero-volatility feeds, and 100% whipsaw sign-flips are reliably rejected with clear diagnostic reasons.

---

## 5. Caveats

- **No Active WebSockets for UI Telemetry**: UI status is polled every 3000ms via REST while the JavaScript ticker interpolates countdown seconds locally every 1000ms. This provides smooth UX without requiring full WebSocket infrastructure.
- **No caveats** regarding core risk governance, streak tracking, anti-whipsaw cooldowns, or microstructure qualification.

---

## 6. Conclusion

**Verdict: APPROVE**

Milestone 2 backend risk governance changes meet all functional, architectural, and quality requirements:
- 15-minute global pause after 3 consecutive losses across assets.
- Streak tracking reset on WIN, on auto-resume expiry, and on manual resume.
- Per-asset anti-whipsaw cooldown ($\ge 180$s) enforced under order lock.
- 4-metric microstructure noise filtering in `qualify_asset_microstructure`.
- UI telemetry with amber badge, live countdown timer, and loss streak display.
- 100% test pass (975/975 tests passing).

---

## 7. Verification Method

To independently verify:

1. **Targeted Risk Governance Tests**:
   ```bash
   .venv/bin/pytest tests/test_risk_governance_circuit_breaker.py -v
   ```
   *Result*: 10 passed in 0.59s.

2. **Full Regression Suite**:
   ```bash
   .venv/bin/pytest
   ```
   *Result*: 975 passed in 26.19s.

3. **Linter on Core Code**:
   ```bash
   .venv/bin/ruff check src tests/test_risk_governance_circuit_breaker.py
   ```
   *Result*: `All checks passed!`
