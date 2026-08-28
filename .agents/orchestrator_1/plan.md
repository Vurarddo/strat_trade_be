# Orchestration Plan: Strategy Curation, Asset Filtering & Rolling 15-Trade Verification

## Overview
Transform `strat_trade_be` live demo bot trading and strategy auto-matcher to eliminate loss-making strategies (`EMA Ribbon Trend Pullback`), enhance Pin-Bar rejection filters, blacklist toxic/high-slippage OTC assets, configure whitelist prioritization, and verify performance across rolling 15-trade sequential batches achieving >56% win rate and 100% test pass.

## Phases & Milestones

### Phase 0: Survey & Discovery (Explorers 1, 2, 3)
- Survey 1: Explore strategy implementations (`EMA Ribbon Trend Pullback`, `Support & Resistance Pin-Bar`, `SuperTrend + ADX Momentum`, `Гібридна Мульти-Факторна`, `RSI + Stoch Extreme Scalp`, `MACD Divergence & Cross`).
- Survey 2: Explore `LiveDemoBotEngine`, `StrategyAutoMatcher`, broker connection, and asset configuration for blacklist/whitelist enforcement.
- Survey 3: Explore `Rolling15TradeVerificationRunner`, Minimax Auto-Tuner, backtest runner, dataset paths, trade logs, and test suite structure in `tests/`.

### Milestone 1 (R1): Strategy Portfolio Curation & Loss Remediation
- Deactivate `EMA Ribbon Trend Pullback` or strictly filter 1m overbought/oversold levels ($RSI > 65$, $Stoch > 75$).
- Enhance `Support & Resistance Pin-Bar` filter (candle wick rejection ratio $\ge 0.35$ and bounce confirmation).
- Prioritize high-performing strategies in auto-matcher and bot engines.

### Milestone 2 (R2): Asset Quality Filter & Toxic Pair Blacklist
- Implement Asset Quality / Blacklist filtering in `LiveDemoBotEngine` and `StrategyAutoMatcher` to reject toxic pairs (`USD/IDR OTC`, `USD/VND OTC`, `BNB OTC`, `EUR/CHF OTC`).
- Implement configurable Asset Whitelisting favoring high-winrate pairs (`EUR/USD OTC`, `USD/CLP OTC`, `USD/BDT OTC`, `USD/EGP OTC`, `GBP/JPY OTC`, `Gold OTC`).

### Milestone 3 (R3): Rolling 15-Trade Verification & Backtest Regression
- Run `Rolling15TradeVerificationRunner` and Minimax Auto-Tuner against historical candle datasets and recent broker trade logs.
- Verify Win Rate $\ge 56\%$ and Net PnL $> \$1,500$ ($100 stake, 92% payout) with 0 negative 15-trade batches.
- Run all unit and integration tests across `tests/` ensuring 100% pass rate.

### Phase 4: Verification, Review, Challenger Stress-Testing, and Forensic Audit
- Independent Reviewers (2)
- Challengers (2)
- Forensic Auditor (1)
- Gate Synthesis & Handoff to Sentinel
