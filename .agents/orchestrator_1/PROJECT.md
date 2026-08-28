# Project: Strategy Portfolio Curation, Toxic Pair Blacklisting & Rolling Verification

## Architecture
- Backend binary options trading system (`strat_trade_be`)
- Strategy registry and individual strategy signal generators (`src/strat_trade/domain/strategies/`)
- `LiveDemoBotEngine` (`src/strat_trade/domain/trading/bot_engine.py`) & `StrategyAutoMatcher` (`src/strat_trade/domain/optimizer/auto_matcher.py`)
- Dedicated Asset Filter module (`src/strat_trade/domain/trading/asset_filter.py`)
- `Rolling15TradeVerificationRunner` & Minimax Auto-Tuner (`src/strat_trade/domain/backtest/verification_runner.py`)
- Pytest suite in `tests/` (471 total tests passing 100%)

## Feature Inventory
| # | Feature | Description | Milestone | Source | Status |
|---|---------|-------------|-----------|--------|--------|
| 1 | EMA Ribbon Deactivation/Filtering | Add strict 1m RSI/Stoch overbought/oversold filtering ($RSI \le 65 / Stoch \le 75$ for CALL, $RSI \ge 35 / Stoch \ge 25$ for PUT) and remove as fallback | M1 | ORIGINAL_REQUEST §R1 | DONE |
| 2 | S&R Pin-Bar Rejection & Bounce Filter | Enforce candle wick rejection ratio >= 0.35 and directional bounce confirmation (bullish close & upper 50% for CALL, bearish close & lower 50% for PUT) | M1 | ORIGINAL_REQUEST §R1 | DONE |
| 3 | Strategy Prioritization | Prioritize SuperTrend+ADX, Hybrid Multi-Factor, RSI+Stoch Extreme Scalp, MACD Divergence (+15 quantum score, Hybrid Multi-Factor as default fallback) | M1 | ORIGINAL_REQUEST §R1 | DONE |
| 4 | Asset Blacklisting | Implement `asset_filter.py` and enforce rejection of toxic/discrete OTC pairs (USD/IDR OTC, USD/VND OTC, BNB OTC, EUR/CHF OTC) in `LiveDemoBotEngine`, `StrategyAutoMatcher`, `generate_pre_trading_plan` | M2 | ORIGINAL_REQUEST §R2 | DONE |
| 5 | Asset Whitelisting | Implement configurable Asset Whitelisting favoring high-winrate pairs (EUR/USD OTC, USD/CLP OTC, USD/BDT OTC, USD/EGP OTC, GBP/JPY OTC, Gold OTC) with scoring priority | M2 | ORIGINAL_REQUEST §R2 | DONE |
| 6 | Rolling 15-Trade Verification | Validate >= 56% winrate, positive net PnL (> $1500), 0 negative batches across rolling sequential 15-trade batches | M3 | ORIGINAL_REQUEST §R3 | DONE |
| 7 | Full Test Suite 100% Pass | All unit/integration tests passing in tests/ with 0 regressions and dedicated verification tests | M3 | ORIGINAL_REQUEST §R3 | DONE |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 0 | Survey & Architecture Mapping | Survey strategies, execution engines, asset filters, verification runners | none | DONE |
| 1 | R1 Strategy Portfolio Curation | Deactivate/filter EMA Ribbon, enhance Pin-Bar rejection & bounce, prioritize top strategies | M0 | DONE |
| 2 | R2 Asset Quality & Blacklist Filter | Blacklist toxic OTC assets, configure whitelist in LiveDemoBot, AutoMatcher, Settings | M0 | DONE |
| 3 | R3 Rolling Verification & Regression | Execute Rolling15TradeVerificationRunner, verify >=56% WR, >$1500 PnL, test suite pass | M1, M2 | DONE |
| 4 | Multi-Agent Review & Forensic Audit | 2x Reviewers, 2x Challengers, Forensic Auditor pass | M3 | DONE |

## Interface Contracts
### Strategy Signal Generation (`src/strat_trade/domain/strategies/`)
- `EmaPullbackTrendStrategy`: Calculates `rsi`, checks `rsi <= rsi_overbought (65)` & `stoch_k <= stoch_overbought (75)` for CALL; `rsi >= rsi_oversold (35)` & `stoch_k >= stoch_oversold (25)` for PUT.
- `SupportResistanceBounceStrategy`: Enforces `min_wick_ratio >= 0.35` and directional candlestick bounce confirmation (`close > open` & `(close - low)/range >= 0.50` for CALL; `close < open` & `(high - close)/range >= 0.50` for PUT).
- `StrategyAutoMatcher`: Grants +15.0 quantum bonus to top strategies (`supertrend_adx_momentum`, `hybrid_multifactors`, `rsi_stochastic_extreme`, `macd_divergence_break`); sets `hybrid_multifactors` as fallback.

### Asset Filter & Engine Integration (`src/strat_trade/domain/trading/`)
- `src/strat_trade/domain/trading/asset_filter.py`: Provides `is_toxic_asset`, `is_whitelisted_asset`, `filter_allowed_assets`, `canonical_asset_key`.
- `LiveDemoBotEngine`: In `_evaluate_single_asset` and `_execute_order`, rejects blacklisted toxic pairs.
- `StrategyAutoMatcher`: Penalizes/rejects toxic pairs, boosts whitelisted pairs.
- `PreTradingPlan` & Settings: Configurable `toxic_asset_blacklist` and `high_winrate_asset_whitelist`.

## Code Layout
- `src/strat_trade/domain/strategies/`: Strategy implementations
- `src/strat_trade/domain/optimizer/auto_matcher.py`: Strategy auto-matching and ranking
- `src/strat_trade/domain/trading/asset_filter.py`: Asset quality and blacklist/whitelist filtering
- `src/strat_trade/domain/trading/bot_engine.py`: Live demo bot execution engine
- `src/strat_trade/domain/backtest/verification_runner.py`: Rolling 15-trade verification & minimax tuner
- `tests/`: Unit and integration test suites (471 tests)
