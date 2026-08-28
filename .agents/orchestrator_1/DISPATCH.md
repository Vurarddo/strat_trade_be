## 2026-08-21T12:58:09Z

You are the Project Orchestrator for the task defined in /Users/vlados/work/projects/startup/strat_trade_be/ORIGINAL_REQUEST.md.

Your working directory is /Users/vlados/work/projects/startup/strat_trade_be/.agents/orchestrator_1/
Please create your working directory, initialize your BRIEFING.md and plan.md, and decompose and execute the project:

1. R1: Strategy Portfolio Curation & Loss Remediation:
   - Deactivate `EMA Ribbon Trend Pullback` from default live bot trading and auto-matcher active pool, or refactor its signal trigger to strictly prevent buying into overbought / selling into oversold levels (RSI > 65, Stoch > 75 on 1m).
   - Enhance `Support & Resistance Pin-Bar` filters to enforce candle wick rejection ratio (>= 0.35) and bounce confirmation before execution.
   - Prioritize high-performing strategies (`SuperTrend + ADX Momentum`, `Гібридна Мульти-Факторна`, `RSI + Stoch Extreme Scalp`, `MACD Divergence & Cross`).

2. R2: Asset Quality Filter & Toxic Pair Blacklist:
   - Implement an explicit Asset Quality / Blacklist filter in `LiveDemoBotEngine` and `StrategyAutoMatcher` to reject high-slippage/discrete OTC pairs (such as `USD/IDR OTC`, `USD/VND OTC`, `BNB OTC`, `EUR/CHF OTC`).
   - Provide configurable Asset Whitelisting favoring high-winrate pairs (`EUR/USD OTC`, `USD/CLP OTC`, `USD/BDT OTC`, `USD/EGP OTC`, `GBP/JPY OTC`, `Gold OTC`).

3. R3: Automated Rolling 15-Trade Verification & Backtest Regression:
   - Run `Rolling15TradeVerificationRunner` and Minimax Auto-Tuner against historical candle datasets and recent broker trade logs.
   - Verify that with the new strategy curation and asset filters, overall win rate exceeds 56% with positive net PnL across all sequential 15-trade validation batches.
   - Ensure 100% test pass across all unit and integration tests in `tests/`.

Maintain continuous progress updates in your `progress.md`.
When all implementation, testing, and verification are complete, notify the Sentinel with a full summary of results.
