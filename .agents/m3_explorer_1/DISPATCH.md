## 2026-08-20T13:46:31Z

You are Explorer 1 for Milestone 3: Automated Iterative Verification & Optimization Loop (R3).
Your working directory is: /Users/vlados/work/projects/startup/strat_trade_be/.agents/m3_explorer_1/

Read:
- /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md
- /Users/vlados/work/projects/startup/strat_trade_be/PROJECT.md
- /Users/vlados/work/projects/startup/strat_trade_be/TEST_INFRA.md

Investigate:
1. Historical candle data storage, formats, and loaders in `src/strat_trade/domain/backtest/` and `data/` or fixture generators.
2. Design and architecture for `Rolling15TradeVerificationRunner` in `src/strat_trade/domain/backtest/verification_runner.py`:
   - Input: strategy instance or config, candle dataframe/historical dataset, payout rate (default 0.92), batch size (default 15).
   - Execution: Backtests strategy on the candle dataset, partitions sequential executed trades into non-overlapping 15-trade batches (and rolling 15-trade windows).
   - Metrics per batch: total trades, wins, losses, win rate pct, net PnL (with +0.92 on win and -1.00 on loss per unit stake), max consecutive losses, return on investment.
   - Validation criteria: every batch must satisfy `win_rate_pct >= 53.4` and `net_pnl > 0.0`.
3. Provide concrete code architecture and implementation specifications.

Write your report to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/m3_explorer_1/handoff.md` and send a completion message.
