## 2026-08-28T11:44:02Z
You are Explorer 1 (Strategy Layer & Indicator Stress Analyst) for the Pocket Option AutoTrader Pro stress-test.
Your working directory is: /Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_strategies/
Create your directory and maintain your BRIEFING.md, progress.md, analysis.md, and handoff.md inside it.

MANDATORY INPUTS:
- Read /Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md
- Read domain skill: /Users/vlados/work/projects/startup/strat_trade_be/.agents/skills/quant-strategy-researcher/SKILL.md

SCOPE & TASKS:
1. Deeply inspect and analyze ALL 8 strategy implementations:
   - `src/strat_trade/domain/strategies/base.py`
   - `src/strat_trade/domain/strategies/registry.py`
   - `src/strat_trade/domain/strategies/support_resistance_pinbar.py`
   - `src/strat_trade/domain/strategies/rsi_stoch_extreme_scalp.py`
   - `src/strat_trade/domain/strategies/ema_ribbon_pullback.py`
   - `src/strat_trade/domain/strategies/bollinger_breakout_squeeze.py`
   - `src/strat_trade/domain/strategies/macd_divergence_cross.py`
   - `src/strat_trade/domain/strategies/hybrid_multifactors.py`
   - and any other strategy files in `src/strat_trade/domain/strategies/`
2. Address Axis 1: Short-Expiry Noise Sensitivity:
   - Analyze how each strategy performs on M1 timeframe with 180s (3-bar) default expiration.
   - Mathematical fragility of indicators on 1-minute candles: RSI(14) = only 14 mins, ADX(14) = 14 mins, Stoch(14,3,3), EMA ribbon periods, Bollinger bands width (20, 2.0), ATR(14) on micro-noise.
   - Calculate theoretical Signal-to-Noise Ratio (SNR) degradation at M1 vs M5/M15 for each indicator.
   - Evaluate whether the 0.50 confidence threshold is sufficient or acts as an open gate for random-walk signals.
   - Expiration mismatch risk: when does the predicted directional impulse fail to materialize within 180s, or when does it reverse prematurely before expiration?
3. Enumerate all strategy-specific flaws, bugs, edge cases, indicator pitfalls, and false signal vectors.
4. Provide estimated win rate impact and concrete technical fix specifications for each finding.

Output your comprehensive, rigorous analysis report to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/survey_explorer_strategies/analysis.md` and complete handoff.md, then send a message back to orchestrator.
