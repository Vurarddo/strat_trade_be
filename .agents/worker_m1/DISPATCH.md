## 2026-08-24T17:46:53Z
You are Worker 1 for Milestone 1 of strat_trade_be.
Your working directory: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/worker_m1`.
Project root: `/Users/vlados/work/projects/startup/strat_trade_be`.
Original request file: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md`.
Project file: `/Users/vlados/work/projects/startup/strat_trade_be/PROJECT.md`.
Explorer Survey Report: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_survey_1/handoff.md`.

You MUST read `/Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md` before starting work.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Skill file to reference: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/skills/trading-systems-developer/SKILL.md`.

Your Mission for Milestone 1:
1. Implement Runaway Momentum & Consecutive Candle Filter:
   - In `src/strat_trade/domain/strategies/support_resistance_bounce.py` and `src/strat_trade/domain/strategies/rsi_stochastic_extreme.py`:
   - Implement `check_runaway_momentum` (or private helper `_check_runaway_momentum`) that detects 3-4 consecutive M1 candles closing aggressively in the trend direction with expanding bodies (>= 50% body ratio) and minimal opposing wicks (<= 25% opposing wick ratio).
   - In `SupportResistanceBounceStrategy.evaluate_bar()`:
     - If support bounce (CALL candidate) and bearish runaway momentum is detected on preceding bars: suppress CALL entry (`action = None`, `regime = "runaway_momentum_suppressed"`).
     - If resistance rejection (PUT candidate) and bullish runaway momentum is detected on preceding bars: suppress PUT entry (`action = None`, `regime = "runaway_momentum_suppressed"`).
   - In `RsiStochasticExtremeStrategy.evaluate_bar()`:
     - If oversold exhaustion (CALL candidate) and bearish runaway momentum is detected: suppress CALL entry (`action = None`, `regime = "runaway_momentum_suppressed"`).
     - If overbought exhaustion (PUT candidate) and bullish runaway momentum is detected: suppress PUT entry (`action = None`, `regime = "runaway_momentum_suppressed"`).
2. Verify that `Support & Resistance Pin-Bar`, `RSI + Stoch Extreme Scalp`, and `EMA Ribbon Trend Pullback` have their parameters and 3-bar (180s) expiration duration correctly calibrated.
3. Write comprehensive unit tests in `tests/test_runaway_momentum_filter.py` covering:
   - Bearish waterfall candle sequence (3 and 4 consecutive large red candles) suppressing CALL signals.
   - Bullish momentum burst candle sequence (3 and 4 consecutive large green candles) suppressing PUT signals.
   - Normal rejection pin-bars with preceding quiet/ranging candles firing signals correctly without false suppression.
   - Clean edge cases (boundary wick ratios, flat bars, zero range bars).
4. Run build and test checks:
   - `.venv/bin/pytest tests/test_runaway_momentum_filter.py -v`
   - `.venv/bin/pytest` (ensure 100% pass across all tests)
   - `.venv/bin/ruff check src tests`
5. Write your complete completion report to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/worker_m1/handoff.md`.
6. Send a message to parent upon completion.
