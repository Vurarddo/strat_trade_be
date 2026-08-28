# Empirical Stress Testing & Verification Report — Challenger 1

## Verdict: **APPROVE**

---

## 1. Observation

Adversarial stress-testing was designed and executed against the implementation across four core modules:

1. **`EmaPullbackTrendStrategy` (`src/strat_trade/domain/strategies/ema_pullback_trend.py`)**:
   - In `evaluate_bar` (lines 131–134 and lines 149–152):
     ```python
     # Bullish Pullback CALL Gate
     (sk > sd or (sk > prev_sk and sk < self.stoch_overbought))
     and rsi <= self.rsi_overbought
     and sk <= self.stoch_overbought

     # Bearish Pullback PUT Gate
     (sk < sd or (sk < prev_sk and sk > self.stoch_oversold))
     and rsi >= self.rsi_oversold
     and sk >= self.stoch_oversold
     ```
   - *Empirical Test*: Injected 60 synthetic bars with prices touching EMA fast/mid during established uptrends while spiking RSI to 82.5–91.5 and Stochastic %K to 88.0–95.0. 
   - *Observation*: **Zero (0) CALL signals generated** across all 60 overbought spike bars.
   - *Boundary Test*: Evaluated precise boundary values: $RSI=65.0, Stoch=75.0$ (CALL allowed); $RSI=65.01$ (rejected); $Stoch=75.01$ (rejected); $RSI=35.0, Stoch=25.0$ (PUT allowed); $RSI=34.99$ (rejected); $Stoch=24.99$ (rejected).

2. **`SupportResistanceBounceStrategy` (`src/strat_trade/domain/strategies/support_resistance_bounce.py`)**:
   - In `evaluate_bar` (lines 73–92):
     ```python
     # Support Bounce CALL Gate
     low <= supp * 1.0005
     and close >= supp
     and (lower_wick / range_) >= max(0.35, self.min_wick_ratio)
     and close > open_
     and ((close - low) / range_) >= 0.50

     # Resistance Rejection PUT Gate
     high >= res * 0.9995
     and close <= res
     and (upper_wick / range_) >= max(0.35, self.min_wick_ratio)
     and close < open_
     and ((high - close) / range_) >= 0.50
     ```
   - *Empirical Test*: Evaluated wick ratios $[0.00, 0.10, 0.20, 0.30, 0.34, 0.3499]$ on horizontal support. **All 6 were strictly rejected** (Signal is `None`).
   - *Confirmation Test*: Evaluated bearish close on support (`close < open` with $0.50$ wick ratio) and lower-half close (`(close - low)/range < 0.50`); both were **strictly rejected**.
   - *Breakout Test*: Bearish breakouts (`close < support`) and bullish breakouts (`close > resistance`) were **strictly rejected** from reversal signals.

3. **`is_toxic_asset` & `LiveDemoBotEngine` (`src/strat_trade/domain/trading/`)**:
   - In `asset_filter.py` and `bot_engine.py` (lines 423–429, 531–541):
   - *Empirical Test*: Tested 18 formatting variants of toxic assets including `USD/IDR OTC`, `USDIDR_otc`, `  usd / idr  otc  `, `\tUSDIDR\n`, `USD_IDR_OTC`, `USD/VND OTC`, `BNB OTC`, `bnb/usd otc`, `EUR/CHF OTC`, `EUR-CHF (OTC)`. **100% were detected as toxic**.
   - *Engine Test*: Tested `LiveDemoBotEngine` under simulated execution. Toxic asset assignments bypassed candle fetching entirely (gateway called 0 times) and were blocked inside `_execute_order` under `_order_lock` (broker `open_trade` called 0 times).

4. **`Rolling15TradeVerificationRunner` (`src/strat_trade/domain/backtest/verification_runner.py`)**:
   - *Empirical Test*: Evaluated boundary combinations:
     - 15 Losses: $0\%$ Win Rate, Net PnL $-\$1,500.00 \to$ `FAILED`.
     - 8 Wins / 7 Losses (Alternating sequence) at $92\%$ payout: $53.33\%$ Win Rate, Net PnL $+\$36.00 \to$ `PASSED` (`is_8_of_15_win`).
     - 7 Wins / 8 Losses at $92\%$ payout: $46.67\%$ Win Rate, Net PnL $-\$156.00 \to$ `FAILED`.
     - 8 Wins / 6 Losses / 1 Draw: Decisive $14$ trades, $57.14\%$ Win Rate, Net PnL $+\$136.00 \to$ `PASSED`.
     - 8 Wins / 7 Losses at $80\%$ payout: Net PnL $-\$60.00 \to$ `FAILED`.
     - 8 Wins / 7 Losses at $87.5\%$ payout (exact break-even): Net PnL $\$0.00 \to$ `FAILED` (requires strictly $> \$0.00$).
     - 8 Wins / 7 Losses at $88.0\%$ payout: Net PnL $+\$4.00 \to$ `PASSED`.
     - 4 Sequential batches (60 trades, 40W/20L): $66.67\%$ Win Rate, Net PnL $+\$1,680.00$, 0 failed batches $\to$ `PASSED`.
     - Partial batches (14 trades, 29 trades): Incomplete slices are marked `is_partial=True` and never passed.

---

## 2. Logic Chain

1. **Elimination of Spike Traps in EMA Pullback**:
   - Because `evaluate_bar` checks `rsi <= 65.0` and `sk <= 75.0` as boolean prerequisites prior to emitting `TradeAction.CALL`, any impulse spike that touches the EMA line while in overbought territory is mathematically precluded from triggering an order.
   - The test harness empirically verified that during 60 distinct overbought spike bars, exactly 0 signals were emitted.

2. **Rejection of False S&R Bounces**:
   - Enforcing `min_wick_ratio >= 0.35` together with `close > open` and `(close - low)/range >= 0.50` ensures that candles testing support must show both price rejection and directional buyer dominance before an entry is signaled.
   - The test harness empirically confirmed that sub-threshold wicks, red/bearish closes, and lower-half closes on support are 100% filtered out.

3. **Multi-Tiered Asset Blacklisting**:
   - Canonical normalization transforms symbol variants to uppercase alphanumeric tokens (`USDIDR`, `USDVND`, `BNB`, `EURCHF`, `GOLD`).
   - The engine validates assets at two distinct checkpoints (pre-evaluation and atomic execution), preventing broker order placement even under concurrent execution.

4. **15-Trade Batch Robustness**:
   - The verification runner accurately computes win rates against decisive trades (excluding draws from denominator), enforces $> \$0.00$ net PnL, tracks consecutive loss streaks and peak drawdown, and guards against premature completion on partial batches.

---

## 3. Caveats

- No caveats. All 65 stress tests in `tests/test_empirical_stress_challenger.py` and all 471 tests across the entire repository pass with 100% success rate and zero warnings/lint errors.

---

## 4. Conclusion

The implementation across Milestones 1, 2, and 3 is mathematically sound, robust against adversarial inputs, and strictly adheres to the product requirements and acceptance criteria.

**Verdict: APPROVE**.

---

## 5. Verification Method

To independently reproduce and verify all empirical findings:

```bash
# 1. Execute Challenger 1 dedicated stress test suite
.venv/bin/pytest tests/test_empirical_stress_challenger.py -v
# Expected: 65 passed in ~0.45s

# 2. Execute full repository test suite
.venv/bin/pytest -v
# Expected: 471 passed in ~9.6s

# 3. Verify code quality and formatting
.venv/bin/ruff check tests/test_empirical_stress_challenger.py
.venv/bin/ruff format --check tests/test_empirical_stress_challenger.py
# Expected: All checks passed!
```
