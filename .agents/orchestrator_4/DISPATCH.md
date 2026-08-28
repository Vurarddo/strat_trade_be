## 2026-08-22T13:06:02Z
You are the Project Orchestrator for Phase 3 quantitative refinements in strat_trade_be.

Your working directory is:
/Users/vlados/work/projects/startup/strat_trade_be/.agents/orchestrator_4

The authoritative user request is documented in:
/Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md

Summary of Task:
1. R1. Auto-Matcher Strategy Hierarchy & Hybrid Deprecation:
   - Remove `hybrid_multifactors` from being the default heuristic fallback in `StrategyAutoMatcher`.
   - Set default fallback strategy to `supertrend_adx_momentum` (with secondary fallback to `macd_divergence_break`).
   - Restrict `hybrid_multifactors` to only fire when ADX >= 22.0 with strict multi-indicator agreement (RSI + EMA + ADX confirmed).
2. R2. Expand Toxic OTC Asset Blacklist:
   - In `asset_filter.py`, add newly discovered high-drawdown OTC pairs to `DEFAULT_TOXIC_BLACKLIST`: `USD/DZD OTC`, `UAH/USD OTC`, `USD/MYR OTC`, `USD/INR OTC`, `EUR/HUF OTC`, `GBP/JPY OTC`.
   - Ensure all canonical variations (with/without `_otc`, slashes, spaces) are normalized and blocked in `LiveDemoBotEngine` and `StrategyAutoMatcher`.
3. R3. Verification & Rolling 15-Trade Batch Validation:
   - Execute `Rolling15TradeVerificationRunner` and run backtest sweeps across historical candle datasets and recent broker trade logs.
   - Verify portfolio achieves >= 58% overall win rate, > $1,500 Net PnL (at $100 stake / 92% payout), and positive net growth on sequential 15-trade batches.
   - Ensure 100% test pass across all unit and integration test suites (`pytest`) and 0 ruff errors.
