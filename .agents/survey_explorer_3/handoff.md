# Handoff Report — survey_explorer_3

**Author**: survey_explorer_3  
**Target Milestone**: Strategy Enhancement, Verification Benchmark, & Execution Guardrails  
**Working Directory**: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_3`  
**Full Report**: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_3/survey_report.md`  

---

## 1. Observation

1. **Backtesting Framework & Engines**:
   - `BinaryBacktestEngine` (`src/strat_trade/domain/backtest/engine.py:21-321`): Evaluates OHLCV bars starting at bar 50 (`for i in range(50, n - 1):`). Implements non-overlapping position locking per asset (`if i < next_available_idx: continue`, `next_available_idx = exit_idx`). Evaluates forward expiration settlement at `exit_idx = i + exp_bars`.
   - `PortfolioBacktestEngine` (`src/strat_trade/domain/backtest/portfolio_engine.py:39-338`): Multi-asset chronological simulation with shared deposit, `max_concurrent_trades` cap, per-asset payout rates, and leaderboard breakdown.
   - Vectorized metrics: `compute_binary_options_signal_metrics` (`src/strat_trade/domain/binary_options_metrics.py:9-75`).
   - Data ingestion: `parse_candles_csv_or_json` (`src/strat_trade/domain/backtest/data_loader.py:11-106`).
2. **Payout & PnL Settlement**:
   - Payoff structure: Win PnL $= \text{Stake} \times \text{Payout Rate}$ (e.g. $+0.92 \times \text{Stake}$ for 92% payout); Loss PnL $= -\text{Stake} \times 1.00$; Draw PnL $= 0.00$.
   - Break-even win rate: $WR_{BE} = \frac{1}{1 + 0.92} \approx 52.083\%$.
3. **Strategy Defects**:
   - `VolatilitySqueezeBreakoutStrategy` (`src/strat_trade/domain/strategies/volatility_squeeze_breakout.py:84`):
     ```python
     squeeze_fired = (sq_prev and not sq_now) or (not sq_now and abs(mom) > 0)
     ```
     `(not sq_now and abs(mom) > 0)` triggers trades on every non-squeeze bar rather than transitions.
   - `BollingerAtrReversionStrategy` (`src/strat_trade/domain/strategies/bollinger_atr_reversion.py:101-122`):
     Fires even when price closes outside bands and lacks $ADX$ trend suppression filter.
4. **Bot Guardrails**:
   - `LiveDemoBotEngine` (`src/strat_trade/domain/trading/bot_engine.py:270-277`): Only hardcoded 30-second per-asset cooldown; missing bar cooldowns, correlation matrix filtering, and consecutive-loss circuit breakers.
5. **Optimization Framework**:
   - `StrategyOptimizerEngine` (`src/strat_trade/domain/optimizer/grid_search.py:42-170`): Cartesian grid search and ranking score formula: `(wr * pf * dd_factor) + (net * 0.1)`.
   - `StrategyAutoMatcher` (`src/strat_trade/domain/optimizer/auto_matcher.py:17-401`): Multi-strategy parameter sweep and heuristic profiling.
6. **Test Suite Execution**:
   - Command: `.venv/bin/pytest`
   - Result: **66 passed** across 22 test files in 3.23s.
   - Linter: `.venv/bin/ruff check src tests` passed with 0 errors.

---

## 2. Logic Chain

1. From `src/strat_trade/domain/backtest/engine.py:174-194`, binary options settlement is fixed:
   $$\text{Win} = +0.92 S, \quad \text{Loss} = -1.00 S, \quad \text{Draw} = 0$$
2. For a 15-trade sample with flat stake $S = \$10$:
   - If $k = 8$ wins and $7$ losses:
     $$\text{PnL} = 8 \times (9.20) - 7 \times (10.00) = 73.60 - 70.00 = +\$3.60 > 0$$
     $$\text{Win Rate} = \frac{8}{15} = 53.33\% \approx 53.4\%$$
   - If $k = 7$ wins and $8$ losses:
     $$\text{PnL} = 7 \times (9.20) - 8 \times (10.00) = 64.40 - 80.00 = -\$15.60 < 0$$
3. Therefore, enforcing Win Rate $\ge 53.4\%$ across sequential non-overlapping 15-trade batches is mathematically sufficient and necessary to guarantee positive Net Growth ($>0$) at 92% broker payout.
4. By combining `BinaryBacktestEngine` trade series generation with sequential 15-trade slicing and `StrategyOptimizerEngine` grid tuning, an automated verification loop can iteratively benchmark, test, and tune strategy parameters until all rolling 15-trade windows achieve profitability without overfitting.

---

## 3. Caveats

- In live execution, broker payouts on OTC pairs fluctuate (typically between 80% and 92%). When payout drops below 92% (e.g. 85%), 8 wins out of 15 trades is no longer profitable (requires 9 wins / 60% WR). The system already has `min_payout_rate` (default 0.80 or 0.92) to filter out sub-optimal assets.
- Historical data in `data/trades.db` contains 80 recorded live/demo trades. For backtesting verification, synthetic candle generation or historical broker dumps (CSV/JSON) provide sample sizes of $\ge 200\text{--}500$ bars.

---

## 4. Conclusion

The backtesting, optimization, and test architecture of `strat_trade_be` is highly modular, robust, and well-tested (66 unit/integration tests passing).

To fulfill the requirements of `ORIGINAL_REQUEST.md`:
1. **R1**: Fix `VolatilitySqueezeBreakoutStrategy` line 84 to fire strictly on squeeze transitions (`sq_prev and not sq_now`), and enhance `BollingerAtrReversionStrategy` with candle close confirmation and ADX trend suppression ($ADX \le 25$).
2. **R2**: Implement configurable cooldown timers ($N$ bars/seconds), correlated currency pair exposure filtering, and consecutive-loss circuit breakers in `LiveDemoBotEngine`.
3. **R3**: Implement the `Rolling15TradeVerificationRunner` and automated parameter tuning loop, verifying that all sequential 15-trade windows achieve $WR \ge 53.4\%$ and Net Growth $> 0$.

---

## 5. Verification Method

To independently verify these findings:
1. Run the test suite:
   ```bash
   .venv/bin/pytest
   ```
2. Run code style checks:
   ```bash
   .venv/bin/ruff check src tests
   ```
3. Inspect the detailed survey report:
   ```bash
   cat .agents/survey_explorer_3/survey_report.md
   ```
