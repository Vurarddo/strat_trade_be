## 2026-08-24T13:42:10Z
Survey and investigate the strategy engine and strategy portfolio in the codebase:
1. Examine `src/` to find where strategies are defined, registered, auto-matched (`StrategyAutoMatcher`), and executed in `LiveDemoBotEngine` / `bot_engine`.
2. Inspect the implementation of:
   - `MACD Divergence & Cross` and `hybrid_multifactors` (how they are currently registered and how to deactivate them from default live bot assignments)
   - `Support & Resistance Pin-Bar` (`SupportResistanceBounceStrategy`), `RsiStochasticExtremeStrategy`, `EMARibbonTrendPullbackStrategy` (or their actual class/module names)
   - Parameters, default expiration bars, timeframe alignment, multi-factor confluence.
3. Investigate the runaway momentum and consecutive candle filter requirement:
   - Where entry guards are evaluated in `SupportResistanceBounceStrategy` and `RsiStochasticExtremeStrategy`.
   - How candle sequences (3-4 consecutive M1 candles with expanding bodies, minimal wicks) can be detected and filtered.
4. Report on existing code structure, exact file paths, line numbers, classes, methods, and interface contracts.
5. Write your complete analysis to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/explorer_survey_1/handoff.md`.
6. Send a message back to parent upon completion.
