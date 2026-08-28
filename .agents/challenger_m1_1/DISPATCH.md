## 2026-08-24T13:53:13Z
<USER_REQUEST>
You are Challenger 1 for Milestone 1 of strat_trade_be.
Your working directory: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/challenger_m1_1`.
Project root: `/Users/vlados/work/projects/startup/strat_trade_be`.
Original request file: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md`.
Project file: `/Users/vlados/work/projects/startup/strat_trade_be/PROJECT.md`.
Worker handoff report: `/Users/vlados/work/projects/startup/strat_trade_be/.agents/worker_m1/handoff.md`.

You MUST read `/Users/vlados/work/projects/startup/strat_trade_be/.agents/ORIGINAL_REQUEST.md` before starting work.

Your Mission:
Empirically and adversarially stress-test `check_runaway_momentum` in `SupportResistanceBounceStrategy` and `RsiStochasticExtremeStrategy`:
1. Construct adversarial synthetic OHLCV candle streams:
   - Zero-range candles (open = high = low = close).
   - Inverted wicks, micro-wicks, equal high/low.
   - Extreme volatility price gaps and flash swings.
   - Alternating multi-bar sequences (2-bar runs vs 3-bar runs vs 4-bar runs).
   - Boundary tests for body ratio (0.49 vs 0.50 vs 0.51) and opposing wick ratio (0.24 vs 0.25 vs 0.26).
2. Verify:
   - Zero crashes, zero unhandled division-by-zero or NaN propagation.
   - Strict adherence to suppression specifications.
3. Run verification and test commands.
4. State your verdict clearly (APPROVE or REQUEST_CHANGES).
5. Write your complete adversarial report to `/Users/vlados/work/projects/startup/strat_trade_be/.agents/challenger_m1_1/handoff.md`.
6. Send a message to parent upon completion.
</USER_REQUEST>
