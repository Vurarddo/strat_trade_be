# Phase 3 Quantitative Refinements Plan

## Overview
Execute Phase 3 refinement requirements across strat_trade_be:
1. R1: Auto-Matcher strategy hierarchy (supertrend_adx_momentum default fallback, macd_divergence_break secondary fallback; restrict hybrid_multifactors to ADX >= 22.0 with strict RSI+EMA+ADX confirmation).
2. R2: Expand toxic OTC asset blacklist with newly discovered pairs (`USD/DZD OTC`, `UAH/USD OTC`, `USD/MYR OTC`, `USD/INR OTC`, `EUR/HUF OTC`, `GBP/JPY OTC`) and ensure robust canonical normalization.
3. R3: Run `Rolling15TradeVerificationRunner` and backtest sweeps to verify >=58% WR, >$1,500 net PnL, positive net growth on sequential 15-trade batches, 100% test pass, 0 ruff errors.

## Execution Sequence
1. **Phase 0: Survey**:
   - Spawn 3 Explorers to investigate current implementations in `strategy_auto_matcher.py`, `asset_filter.py`, `hybrid_multifactors.py`, `live_demo_bot_engine.py`, `rolling_15_trade_verification_runner.py`, and test suites.
2. **Decomposition & PROJECT.md**:
   - Define architectural contracts, code layout, feature inventory, and milestone schedule.
3. **Milestone 1 (R1 - Strategy Hierarchy & Hybrid Deprecation)**:
   - Explorer → Worker → Reviewers → Challengers → Auditor → Gate.
4. **Milestone 2 (R2 - Toxic OTC Asset Blacklist & Normalization)**:
   - Explorer → Worker → Reviewers → Challengers → Auditor → Gate.
5. **Milestone 3 (R3 - Rolling 15-Trade Verification & Backtest Sweeps)**:
   - Explorer → Worker → Reviewers → Challengers → Auditor → Gate.
6. **Milestone 4 (Final Full Validation & Adversarial Check)**:
   - Full pytest suite pass + ruff lint clean + final audit.
7. **Synthesis & Sentinel Reporting**.
