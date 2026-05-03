# Gemini sync — Strat Trade BE

## 1. Timestamp

2026-05-03T12:00:00Z

## 2. Status

| Block | Tasks | Result |
|-------|--------|--------|
| Initialization | `gemini_sync.md` template + reporting structure | Success |
| Datafeed | `tvdatafeed` (git), `TradingViewGateway`, `normalize_tradingview_ohlcv`, port `OhlcvDataFrameSource` | Success |
| BO metrics | `compute_binary_options_signal_metrics` (vectorized, domain) | Success |
| Verification | `pytest` (full suite 24 passed), ruff on new modules | Success |

## 3. Architectural Blockers

- **`CandleFeed` vs DataFrame gateway:** `ports/candles.py` still exposes async `list[Candle]` for brokers; TradingView path is intentionally **sync** `pandas.DataFrame` via `OhlcvDataFrameSource` / `TradingViewGateway` for research/backtest ingestion. Callers should convert to `Candle` or domain engines in one boundary if both stacks must meet.
- **`TvIntervalLike` typing:** when `tvdatafeed` is missing, stubs use `Any` for `Interval` in the adapter module only — install the declared dependency for real types and runtime.
- **Trading rules vs BO test frame:** internal indicator pipelines sometimes prefer `Open`/`High`/… naming; BO metrics expect lowercase `close` (configurable via `close_column`).

## 4. Questions for Quant

- **Ties (return of stake):** metrics count `ties` but EV uses `(p_win * payout) - (p_loss * 1.0)` only — should **breakeven** ties enter EV explicitly (e.g. `+ (p_tie * 0)`) or should `winrate_pct` exclude ties from the denominator?
- **Floating settlements:** equality on raw `close` vs shifted `close` defines a tie; should we use a tick/epsilon rule for real quotes?

## 5. Vectorized BO metrics — quick performance note (10,000 rows)

On a local run (warm loop, mean of 200 calls, same random 10k series as in `tests/test_binary_options_metrics.py::test_bo_metrics_vectorized_perf_10k`), **~0.08 ms per call** — dominated by pandas/numpy C implementations, not Python row loops.
