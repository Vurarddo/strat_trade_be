# BRIEFING — 2026-08-20T17:48:30Z

## Mission
Investigate historical candle data storage/loaders and design the architecture for `Rolling15TradeVerificationRunner` for Milestone 3 (R3).

## 🔒 My Identity
- Archetype: explorer
- Roles: investigation, synthesis
- Working directory: /Users/vlados/work/projects/startup/strat_trade_be/.agents/m3_explorer_1
- Original parent: b5bec36a-db84-436e-98e2-3b5605cf7864
- Milestone: Milestone 3: Automated Iterative Verification & Optimization Loop (R3)

## 🔒 Key Constraints
- Read-only investigation — do NOT implement directly in `src/` (write reports and proposed designs in agent directory)
- Rigorous evidence chain with file paths, line numbers, and exact code models
- Adhere strictly to 5-component handoff report protocol

## Current Parent
- Conversation ID: b5bec36a-db84-436e-98e2-3b5605cf7864
- Updated: 2026-08-20T17:48:30Z

## Investigation State
- **Explored paths**:
  - `src/strat_trade/domain/backtest/models.py`
  - `src/strat_trade/domain/backtest/data_loader.py`
  - `src/strat_trade/domain/backtest/engine.py`
  - `src/strat_trade/domain/backtest/portfolio_engine.py`
  - `src/strat_trade/domain/optimizer/grid_search.py`
  - `src/strat_trade/domain/optimizer/auto_matcher.py`
  - `src/strat_trade/domain/binary_options_metrics.py`
  - `src/strat_trade/use_cases/run_backtest.py`
  - `src/strat_trade/use_cases/optimize_strategy.py`
  - `src/strat_trade/api/routes/backtest.py`
  - `src/strat_trade/api/schemas.py`
  - `data/trades.db`
  - Test fixtures in `tests/test_backtest_models_and_engine.py`
- **Key findings**:
  - Standard DataFrame canonical format: `["timestamp", "open", "high", "low", "close", "volume"]` with UTC datetimes.
  - CSV/JSON parsing normalized via `parse_candles_csv_or_json`.
  - Payout mathematics: at 92% broker payout, break-even is 52.083%; 8 wins in 15 trades achieves WR=53.33% (~53.4%) and net profit +$3.60 on $10 stake.
  - Verification runner architecture designed with non-overlapping 15-trade batches ($M = N // 15$) and rolling 15-trade sliding windows ($K = N - 15 + 1$).
  - Full metrics suite: total trades, wins, losses, draws, win rate %, gross profit, gross loss, net PnL, ROI %, profit factor, max consecutive losses/wins, drawdown.
  - Automated feedback loop integration designed connecting `Rolling15TradeVerificationRunner` with `StrategyOptimizerEngine`.
- **Unexplored areas**: None for Explorer 1 scope.

## Key Decisions Made
- `Rolling15TradeVerificationRunner` should support both executing fresh backtests on DataFrames/candles and evaluating pre-computed `BacktestSummary` objects.
- Configurable `min_win_rate_pct` (default `Decimal("53.4")` or `Decimal("53.33")`) with unit-tested handling of 8 wins / 7 losses.
- Standalone verification data models (`BatchEvaluationResult`, `VerificationReport`) structured for easy JSON/REST serialization and automated optimization feedback.

## Artifact Index
- DISPATCH.md — incoming instructions
- BRIEFING.md — persistent state and identity
- progress.md — liveness heartbeat
- handoff.md — final handoff report
