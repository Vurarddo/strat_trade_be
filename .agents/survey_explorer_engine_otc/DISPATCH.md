## 2026-08-28T11:44:02Z
You are Explorer 2 (Engine Architecture & OTC Microstructure Analyst) for the Pocket Option AutoTrader Pro stress-test.
Your working directory is: /Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_engine_otc/
Create your directory and maintain your BRIEFING.md, progress.md, analysis.md, and handoff.md inside it.

MANDATORY INPUTS:
- Read /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md
- Read domain skill: /Users/vlados/work/projects/startup/strat_trade_be/.agents/skills/market-analyst/SKILL.md

SCOPE & TASKS:
1. Deeply inspect and analyze:
   - `src/strat_trade/domain/trading/bot_engine.py` (932 lines: full trading loop, 11-step signal evaluation pipeline, settlement logic, circuit breakers, order execution, tick loop timing)
   - `src/strat_trade/domain/trading/entities.py` (all domain models)
   - `src/strat_trade/domain/trading/regime_detector.py` (regime classification, ADX, EMA ribbon, ATR, transition zone blind spots e.g. ADX ≈ 24)
   - `src/strat_trade/domain/trading/asset_filter.py` (microstructure quality gate: flat_bar_ratio, unique_price_ratio, whipsaw_sign_flip_ratio, relative_atr; toxic blacklist; session filter)
   - `src/strat_trade/domain/trading/correlation.py` (currency correlation & directional exposure filter, currency basket gaps)
   - `src/strat_trade/domain/trading/trade_store.py` (SQLite WAL persistence, concurrency, locking under multi-trade settlements)
   - `src/strat_trade/adapters/pocket_option_gateway.py` (WebSocket ingestion, latency, tick processing)
2. Address Axis 3: OTC Algorithmic Spike Vulnerability & Engine Gaps:
   - OTC broker synthetic pricing vs real interbank markets: discrete price steps (0 range bars), artificial wicks/pin bars, synthetic snap-back reversals, step-function breakouts.
   - Evaluate the 11-step signal evaluation pipeline in `bot_engine.py`: check every single gate for bypasses, race conditions, or logic gaps.
   - Evaluate whether the 4 microstructure metrics are sufficient to catch broker manipulation or let toxic synthetic feeds pass.
   - Identify missing OTC-specific filters (e.g. tick velocity filters, spread/payout mismatch filters, candle integrity checks).
   - Circuit breaker edge cases: rapid oscillation between PAUSED and RUNNING, consecutive loss tracking reset logic.
   - Post-settlement cooldown gaps: is `max(180s, cooldown_bars * 60s)` correct or flawed?
   - Regime detector blind spots: behavior when ADX is hovering at 23-26, EMA ribbons crossing erratically on M1.
   - SQLite concurrency & transaction integrity.
3. Enumerate all engine and OTC vulnerabilities with severity, win rate impact, and technical remediation specifications.

Output your comprehensive, rigorous analysis report to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_engine_otc/analysis.md` and complete handoff.md, then send a message back to orchestrator.
