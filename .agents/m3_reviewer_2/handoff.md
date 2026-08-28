# Milestone 3 Review & Adversarial Critic Report (R3)

**Reviewer:** Reviewer 2 (`m3_reviewer_2`)  
**Roles:** reviewer, critic  
**Target:** Milestone 3 — Automated Iterative Verification & Optimization Loop  
**Working Directory:** `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m3_reviewer_2/`  
**Date:** 2026-08-20  
**Verdict:** **APPROVE**

---

## 1. Observation

1. **Test & Static Analysis Execution**:
   - Pytest: `.venv/bin/pytest -v` executed with **321 passed, 0 failures, 2 benign third-party library warnings** in 6.79s.
   - Dedicated benchmark suite: `.venv/bin/pytest -v tests/test_rolling_15_trade_verification.py` executed with **43 passed, 0 failures** in 1.44s.
   - Ruff Linter: `.venv/bin/ruff check src/ tests/` output: `All checks passed! 0 linting errors`.

2. **Source Code & Architecture Inspected**:
   - `src/strat_trade/domain/backtest/verification_runner.py`:
     - Implements `Rolling15TradeVerificationRunner` for evaluating candidate strategies across sequential non-overlapping batches ($[0:15], [15:30], \dots$) and sliding rolling windows ($[0:15], [1:16], \dots$) under binary broker payouts (+92% / -100% / 0%).
     - Implements `TradeBatchResult` and `RollingVerificationReport` with `Decimal` precision for all financial and rate metrics.
     - Implements minimax multi-batch parameter auto-tuning optimizer evaluating candidate fitness:
       $$F(\theta) = 3.0 \cdot \text{min\_wr} + 1.0 \cdot \text{mean\_wr} + 0.5 \cdot \text{pnl} - 1.5 \cdot \sigma(\text{wr}) - 500.0 \cdot \text{failed\_batches}$$
     - Implements 70% in-sample / 30% out-of-sample holdout validation and parameter plateau neighborhood stability check ($\pm 1$ step perturbation).
   - `src/strat_trade/use_cases/verify_strategy.py`:
     - Implements `execute_rolling_15_verification` orchestrating live candle fetching or custom file parsing (`parse_candles_csv_or_json`) and executing verification/optimization.
   - `src/strat_trade/api/schemas.py`:
     - Implements `TradeBatchResultResponse`, `RollingVerificationRequest`, and `RollingVerificationResponse` with `ConfigDict(extra="forbid")` for strict OpenAPI schema enforcement.
   - `src/strat_trade/api/routes/backtest.py`:
     - Exposes `POST /api/v1/backtest/verify-15-trades` mapped cleanly via `_verification_report_to_response`.
   - `tests/test_rolling_15_trade_verification.py`:
     - 43 tests covering Unit Math, Boundary Partitioning, Multi-Regime Fixtures, Auto-Tuning Loop, Real-World Continuous Benchmarks, and FastAPI endpoint tests.

3. **Integrity & Authenticity Audit**:
   - Checked for hardcoded test results, facade implementations, dummy return values, or bypassed calculations: **NONE FOUND**.
   - Verified that `BinaryBacktestEngine` runs real strategy evaluation against OHLCV candles, generating real indicator signals and calculating real trade PnL.

---

## 2. Logic Chain

1. **Mathematical Validation of Binary Options Payoffs**:
   - At 92% broker payout with stake $S = \$10.00$:
     - 8 wins / 7 losses ($WR = 53.33\%$):
       $$\text{Net PnL} = 8 \times \$9.20 - 7 \times \$10.00 = \$73.60 - \$70.00 = +\$3.60 > 0 \quad (\textbf{PASS})$$
     - 7 wins / 8 losses ($WR = 46.67\%$):
       $$\text{Net PnL} = 7 \times \$9.20 - 8 \times \$10.00 = \$64.40 - \$80.00 = -\$15.60 < 0 \quad (\textbf{FAIL})$$
     - 15 wins / 0 losses ($WR = 100.00\%$):
       $$\text{Net PnL} = 15 \times \$9.20 = +\$138.00 > 0, \quad \text{PF} = 99.99 \quad (\textbf{PASS})$$
     - 0 wins / 15 losses ($WR = 0.00\%$):
       $$\text{Net PnL} = -\$150.00 < 0, \quad \text{PF} = 0.00 \quad (\textbf{FAIL})$$
     - 15 draws / 0 wins / 0 losses:
       $$\text{Decisive} = 0, \quad WR = 0.00\%, \quad \text{Net PnL} = \$0.00 \ngtr 0 \quad (\textbf{FAIL})$$
   - `Rolling15TradeVerificationRunner._evaluate_single_slice` handles discrete integer boundary conditions with exact precision:
     `(win_rate_pct >= min_win_rate_pct or (wins >= 8 and cnt == 15 and net_pnl > 0)) and net_pnl > min_batch_pnl and not is_partial`.

2. **Adversarial Stress Testing & Boundary Analysis**:
   - **Empty Trades List ($N = 0$)**: Evaluates to `status = VerificationStatus.INSUFFICIENT_TRADES`, `total_batches = 0`, `all_batches_passed = False` with zero uncaught exceptions.
   - **Undersized Trades ($1 \le N < 15$)**: Returns `status = VerificationStatus.INSUFFICIENT_TRADES`, `total_batches = 0`, and 1 partial remainder batch with diagnostics.
   - **Exact Multiples ($N = 15, 30, 45, 60$)**: Evaluates into exact disjoint partitions with 0 remainder batches.
   - **Variable Broker Payouts (80%, 85%, 92%, 95%)**: Correctly enforces the higher win counts required at lower payout rates (e.g. 9 wins needed at 80% payout).

3. **Performance & Complexity**:
   - Full grid optimization employs uniform step sampling when combinatorial explosion exceeds `max_combinations` (capped at 200).
   - In-sample / Out-of-sample split (70/30) evaluates training fitness quickly before re-evaluating top candidates against the full dataset.
   - Entire 43-test verification suite completes in under 1.5 seconds.

---

## 3. Findings

### [Minor] Finding 1: Type Coercion for Candle List with `volume=None`

- **What**: In `verification_runner.py` (line 678) and `engine.py` (line 54), converting a Python list of `Candle` entities to DataFrame uses `"volume": float(getattr(c, "volume", 0.0))`.
- **Where**: `src/strat_trade/domain/backtest/verification_runner.py:678` and `src/strat_trade/domain/backtest/engine.py:54`.
- **Why**: Since `Candle.volume` default is `None`, `getattr(c, "volume", 0.0)` returns `None` when `volume` is set to `None`, causing `float(None)` to raise `TypeError`.
- **Impact**: Low / Minor. In practice, data is supplied as `pd.DataFrame` or parsed via `parse_candles_csv_or_json` / `verify_strategy.py` (which explicitly handles `if c.volume is not None else 0.0`).
- **Suggestion**: In a future refactoring cleanup, adjust to:
  `"volume": float(c.volume) if getattr(c, "volume", None) is not None else 0.0`.

---

## 4. Caveats

- Backtest verification operates on historical candle close data with deterministic execution. Real-world broker execution slippage and WebSocket jitter (~50-200ms) are evaluated separately in live trading audit engine.
- No other caveats.

---

## 5. Conclusion

The Milestone 3 implementation delivers a robust, mathematically rigorous, and high-performance verification benchmark and auto-tuning feedback loop meeting all requirements in `ORIGINAL_REQUEST.md (§R3)` and `PROJECT.md`. Zero regressions across the 321-test project suite and zero linter violations.

**Verdict**: **APPROVE**

---

## 6. Verification Method

To reproduce and independently verify this review:

```bash
# 1. Run dedicated rolling 15-trade verification test suite
.venv/bin/pytest -v tests/test_rolling_15_trade_verification.py

# 2. Run full test suite across entire project
.venv/bin/pytest

# 3. Verify static code analysis
.venv/bin/ruff check src/ tests/
```
