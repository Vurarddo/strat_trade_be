# Original User Request

## Initial Request — 2026-08-23T08:43:56Z

<USER_REQUEST>
Transform `strat_trade_be` into a high-conviction Sniper Confluence Trading System: deactivate failing indicator-spam strategies (`MACD Divergence & Cross`, `hybrid_multifactors`), center active trading on proven high-winrate alpha (`Support & Resistance Pin-Bar`, `RSI + Stoch Extreme Scalp`, `EMA Ribbon Trend Pullback`), remove manual expiration input from the UI control panel in favor of strategy-calibrated optimal execution, and enforce multi-factor noise filters across all assets.

Working directory: `/Users/vlados/work/projects/startup/strat_trade_be`
Integrity mode: development

## Requirements

### R1. Strategy Portfolio Restructuring (Sniper Edge)
- Deactivate `MACD Divergence & Cross` and `hybrid_multifactors` from default active live bot assignments in `StrategyAutoMatcher` and `bot_engine` to eliminate counter-trend whipsaws and signal spam.
- Focus primary strategy allocation and fallback routing on proven profitable strategies:
  - `Support & Resistance Pin-Bar` (57.6% WR in live broker tests, price-action rejection at key swings)
  - `RSI + Stoch Extreme Scalp` (71.4% WR in live broker tests, dual-oscillator exhaustion)
  - `EMA Ribbon Trend Pullback` (60.0% WR with calibrated overbought/oversold guards)
- Enforce multi-factor confluence and higher-timeframe alignment so trades fire on high-probability setups (Sniper mode, 10-25 high-quality signals/day) rather than high-frequency spam.

### R2. UI Expiration Simplification & Automated Strategy-Driven Expiration
- Remove the manual "Час експірації" (`botCfgExpiration`) dropdown from the bot configuration dock in `src/strat_trade/web/templates/index.html` and JavaScript payload builders.
- Set optimal expiration duration automatically within backend strategy parameter definitions (e.g. 180s / 3 bars for Pin-Bar & Extreme Scalp) so the user does not need to manually configure expiration times.

### R3. Dynamic Regime & Micro-Tick Noise Filtering
- Rather than a rigid 6-pair whitelist, implement dynamic asset qualification that blocks extreme noise/step-tick assets (like crypto OTC and erratic discrete exotics) while allowing all standard liquid OTC and Forex assets that exhibit continuous price action.
- Implement an anti-whipsaw cooldown (minimum 3-5 minutes per asset after trade settlement) to prevent repeat entries during volatile breakouts.

### R4. Automated Verification & Rolling 15-Trade Validation
- Run `Rolling15TradeVerificationRunner` across historical candles and multi-session broker datasets (combining all 600+ real broker trades).
- Verify that under the refined Sniper strategy pool, overall win rate exceeds 58% and every sequential 15-trade validation batch yields positive net balance growth.
- Ensure 100% test pass across all unit and integration test suites (`pytest`).

## Acceptance Criteria

### Strategy & Engine Safety
- [ ] `MACD Divergence & Cross` and uncalibrated hybrid strategies do not open trades in live demo bot mode.
- [ ] `Support & Resistance Pin-Bar`, `RSI + Stoch Extreme Scalp`, and `EMA Ribbon Trend Pullback` receive top allocation priority.
- [ ] Minimum cooldown prevents consecutive entries on the same asset within 3 minutes of completion.

### UI / UX
- [ ] The "Час експірації" input is cleanly removed from the UI bot configuration form in `index.html`.
- [ ] Pre-trading plan generation automatically assigns strategy-calibrated optimal expiration bars without requiring user input.

### Quantitative Profitability Metric
- [ ] Verified backtest on the combined real broker trade logs yields $\ge 58\%$ Win Rate and positive net PnL across rolling 15-trade batches.
- [ ] 100% test pass across all tests in `tests/` with 0 ruff errors.
</USER_REQUEST>

## Follow-up — 2026-08-24T13:40:55Z

<USER_REQUEST>
Implement a Global Consecutive-Loss Circuit Breaker (15-minute cooldown after 3 consecutive losses) and a Runaway Momentum Filter in `strat_trade_be` to eliminate 5-8 loss streaks during sudden market volatility sweeps while preserving winning streaks.

Working directory: `/Users/vlados/work/projects/startup/strat_trade_be`
Integrity mode: development

## Requirements

### R1. Global Portfolio Consecutive-Loss Circuit Breaker (15-Min Lockout)
- In `LiveDemoBotEngine` and risk governance (`RiskManager`), maintain an atomic counter of consecutive closed trade outcomes across all assets.
- If **3 consecutive trades** close in `LOSS` across the portfolio, automatically activate a global **15-minute trading pause (900 seconds)** (`global_cooldown_until`).
- Reset the consecutive loss counter to zero on any `WIN` or upon cooldown expiration.
- Broadcast an informative telemetry event over WebSocket to the UI notifying the user of the active cooldown and remaining seconds.

### R2. Runaway Momentum & Consecutive Candle Filter for Mean Reversion
- Enhance entry guards in `SupportResistanceBounceStrategy` and `RsiStochasticExtremeStrategy` to detect runaway trend momentum.
- Suppress counter-trend reversal entries when the preceding 3-4 consecutive M1 candles close aggressively in the trend direction with expanding bodies and minimal wicks (preventing "catching a falling knife" during news/volatility sweeps).

### R3. Automated Verification & Streak Stress-Testing
- Execute verification benchmarks on multi-session broker datasets and synthetic volatility sweep candle streams.
- Verify that the 15-minute circuit breaker eliminates multi-trade loss cascades ($\ge 4$ consecutive losses) while preserving positive deposit growth on winning streaks.
- Ensure 100% test pass across all unit and integration tests (`pytest`) with 0 ruff violations.

## Acceptance Criteria

### Execution & Safety Guardrails
- [ ] Any sequence of 3 consecutive closed losses triggers a hard 15-minute global pause across all assets.
- [ ] Counter-trend reversal signals are suppressed during 3+ candle runaway momentum bursts.
- [ ] Winning streaks continue uninterrupted without artificial entry limits.

### Quantitative & Test Integrity
- [ ] Stress-test simulation on the August 24 trade dataset proves elimination of the 7-loss cascade.
- [ ] 100% test pass across all test suites in `tests/` with 0 ruff lint errors.
</USER_REQUEST>

## Follow-up — 2026-08-31T14:26:28Z

<USER_REQUEST>
This project implements Stage 1 of the quantitative improvements for the Pocket Option AutoTrader Pro: fixing the time-based backtester evaluation and cleaning up the auto-assign toxic asset logic. This is a single self-contained refactor; keep it small and focused.

Working directory: `/Users/vlados/work/projects/startup/strat_trade_be`
Integrity mode: development

## Requirements

### R1. Time-Based Backtester Execution
Modify `src/strat_trade/domain/backtest/engine.py` (`BinaryBacktestEngine`) to evaluate trade outcomes based on exact time rather than bar index offset. 
- Instead of using `exit_idx = i + exp_bars`, the engine should calculate `target_exit_time = entry_time + pd.Timedelta(seconds=expiration_seconds)`.
- It should search forward in the dataframe for the first row where `timestamp >= target_exit_time` to use as the exit price.
- Update `BacktestConfig` to accept `expiration_seconds` explicitly, ensuring it derives the target time correctly even if the dataframe contains sub-minute (S1/S5) or tick data.

### R2. Auto-Assign Logic Cleanup
Modify `src/strat_trade/domain/optimizer/auto_matcher.py` (`StrategyAutoMatcher`) and `src/strat_trade/use_cases/auto_assign_strategies.py`.
- If an asset fails the toxic check (`is_toxic`) or the microstructure check (`qualify_asset_microstructure`), `find_optimal_strategy_for_asset` should return `None` instead of generating a heuristic profile.
- In `auto_assign_strategies.py`, filter out any `None` assignments from the gathered tasks so that rejected assets do not appear in the final `PreTradingPlan`.

## Acceptance Criteria

### Backtest Engine
- [ ] `BinaryBacktestEngine` determines the exit price by matching `timestamp >= target_exit_time` instead of strict integer row offset.
- [ ] `BinaryBacktestEngine` correctly handles scenarios where the exact `target_exit_time` falls between available data points (e.g., using the next available row's close or open).
- [ ] `pytest` tests pass successfully without breaking the regression suites.

### Auto-Assign
- [ ] `StrategyAutoMatcher.find_optimal_strategy_for_asset` returns `None` for assets failing the microstructure or toxicity filters.
- [ ] `generate_pre_trading_plan` successfully filters out `None` values and builds a valid `PreTradingPlan` containing only accepted assets.
- [ ] `pytest` tests related to auto-assign pass successfully.
</USER_REQUEST>

## Follow-up — 2026-08-31T15:45:40Z

<USER_REQUEST>
This project implements Stage 2 of the quantitative improvements for the Pocket Option AutoTrader Pro: building a standalone data collector script that fetches 1-second (S1) candles using the existing Pocket Option gateway and saves them to a SQLite database. This data will fuel the time-based backtester.

Working directory: `/Users/vlados/work/projects/startup/strat_trade_be`
Integrity mode: development

## Requirements

### R1. Database Schema for Market Data
Create a module `src/strat_trade/domain/trading/market_data_store.py` (or handle it directly in the script) that connects to a new SQLite database at `data/market_data.db`.
- It must create a table `candles_s1` with columns: `asset` (TEXT), `timestamp` (INTEGER or REAL for epoch UTC), `open` (REAL), `high` (REAL), `low` (REAL), `close` (REAL), `volume` (REAL).
- It must enforce a `UNIQUE(asset, timestamp)` constraint to prevent duplicate records.

### R2. Data Collection Script
Create a standalone executable script `scripts/collect_s1_data.py`.
- It must instantiate the existing `PocketOptionTradingGateway` from `src/strat_trade/adapters/pocket_option_gateway.py` (you can use dummy/env credentials like `SSID=demo` since the gateway supports it).
- It should run in an infinite `asyncio` loop, iterating over a hardcoded list of target assets (e.g., `["EURUSD_otc", "GOLD_otc", "AUDNZD_otc"]`).
- For each asset, it calls `gateway.get_candles(asset, timeframe=1, count=300)` (which fetches the last 300 1-second candles).
- It must sleep for an appropriate interval (e.g., 60-120 seconds) between fetches to avoid spamming the broker.
- It must gracefully catch exceptions (like timeouts or `BrokerUnavailableError`) and continue the loop rather than crashing.

### R3. Safe Upsert Logic
The script must insert the fetched candles into `data/market_data.db` using `INSERT OR IGNORE` (or `INSERT OR REPLACE`). Because the script polls every 60 seconds and fetches 300 seconds of history, the data will overlap. The unique constraint and upsert logic must ensure no duplicate rows are created.

## Acceptance Criteria

### Schema & Database
- [ ] A local SQLite database `data/market_data.db` is successfully created when the script runs.
- [ ] The `UNIQUE(asset, timestamp)` constraint accurately prevents duplicate rows when the same data is inserted twice.

### Collector Script
- [ ] `scripts/collect_s1_data.py` runs continuously without crashing when encountering simulated network errors or timeouts.
- [ ] The script successfully fetches `timeframe=1` data via `PocketOptionTradingGateway` and stores it.
- [ ] Running the script manually for a few iterations produces a verifiable `data/market_data.db` file populated with S1 candles.
</USER_REQUEST>
