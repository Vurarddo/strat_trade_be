## 2026-08-31T15:13:42Z
Conduct an independent post-victory audit for Stage 1 of the quantitative improvements for Pocket Option AutoTrader Pro:
<original_task>
Implement Stage 1 of the quantitative improvements for Pocket Option AutoTrader Pro:
1. Time-Based Backtester Execution in `src/strat_trade/domain/backtest/engine.py` (`BinaryBacktestEngine`) and `BacktestConfig`:
   - Calculate `target_exit_time = entry_time + pd.Timedelta(seconds=expiration_seconds)`.
   - Search forward in the dataframe for the first row where `timestamp >= target_exit_time` for exit price.
   - Accept `expiration_seconds` explicitly in `BacktestConfig` and derive target time correctly even with sub-minute/tick data.
2. Auto-Assign Logic Cleanup in `src/strat_trade/domain/optimizer/auto_matcher.py` (`StrategyAutoMatcher`) and `src/strat_trade/use_cases/auto_assign_strategies.py`:
   - Return `None` from `find_optimal_strategy_for_asset` if asset fails `is_toxic` or `qualify_asset_microstructure`.
   - Filter out `None` assignments in `auto_assign_strategies.py` so rejected assets do not appear in `PreTradingPlan`.
3. Ensure all pytest tests pass cleanly with 0 ruff errors.
</original_task>
