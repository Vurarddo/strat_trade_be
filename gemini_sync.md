# Gemini sync — Strat Trade BE

## 1. Timestamp

2026-05-03T18:30:00Z

## 2. Status

| Block | Tasks | Result |
|-------|--------|--------|
| Initialization | `gemini_sync.md` template + reporting structure | Success |
| Datafeed | `tvdatafeed` (git), `TradingViewGateway`, `normalize_tradingview_ohlcv`, port `OhlcvDataFrameSource` | Success |
| BO metrics | `compute_binary_options_signal_metrics` (vectorized, domain) | Success |
| Verification | `pytest` (full suite 25 passed), ruff + pyright on indicators package | Success |
| PO indicator pool | `pandas-ta`, `IndicatorMetadata`, singleton `IndicatorRegistry`, 32 calculators, `GET /api/v1/indicators` | Success |
| Indicator package layout | Monolith `indicator_defs.py` removed; logic split into `oscillators.py`, `trend.py`, `volatility.py`, `volume.py`, `bill_williams.py` + `indicator_support.py` + `catalog.py`; `__init__.py` imports submodules so decorators register on import | Success |

**Indicator registry init:** `strat_trade.domain.indicators` loads the five category modules from `__init__.py`; `default_indicator_registry` uses `catalog.register_all` so all 32 ids remain registered before HTTP handlers run. `GET /api/v1/indicators` still returns 32 rows (`tests/test_indicators_api.py::test_get_indicators_catalog`).

**Registered indicators (count): 32**

**Not available as a single matching `pandas_ta` function name (implemented manually or as a composition):**

- **DeMarker** — manual vectorized formula on highs/lows.
- **Accelerator Oscillator (ac)** — `pta.ao` minus rolling mean of AO (5).
- **Envelopes** — SMA/EMA/WMA mid ± percent (vectorized).
- **Bulls Power / Bears Power** — Elder-style: high/low minus EMA(close).
- **Fractal** — Williams 5-bar up/down fractal midpoint series (sparse; `fill_sparse` + ffill for API).
- **Fractal Chaos Bands** — simplified midline from forward-filled fractal highs/lows + rolling window (not a built-in `fcb` in pandas-ta).

**Implemented via pandas-ta output columns (not a standalone indicator id of that name):**

- **OsMA** — `MACDh_*` from `df.ta.macd(...)`.
- **Bollinger Bands Width** — `BBB_*` from `df.ta.bbands(...)`.

**Library API notes:** `pandas_ta.alligator` in the installed version is **close-only** (no high/low arguments). ZigZag parameters follow the library: `deviation`, `legs`.

## 3. Architectural Blockers

- **`CandleFeed` vs DataFrame gateway:** `ports/candles.py` still exposes async `list[Candle]` for brokers; TradingView path is intentionally **sync** `pandas.DataFrame` via `OhlcvDataFrameSource` / `TradingViewGateway` for research/backtest ingestion. Callers should convert to `Candle` or domain engines in one boundary if both stacks must meet.
- **`TvIntervalLike` typing:** when `tvdatafeed` is missing, stubs use `Any` for `Interval` in the adapter module only — install the declared dependency for real types and runtime.
- **Trading rules vs BO test frame:** internal indicator pipelines sometimes prefer `Open`/`High`/… naming; BO metrics expect lowercase `close` (configurable via `close_column`).

## 4. Questions for Quant

- **Ties (return of stake):** metrics count `ties` but EV uses `(p_win * payout) - (p_loss * 1.0)` only — should **breakeven** ties enter EV explicitly (e.g. `+ (p_tie * 0)`) or should `winrate_pct` exclude ties from the denominator?
- **Floating settlements:** equality on raw `close` vs shifted `close` defines a tie; should we use a tick/epsilon rule for real quotes?

## 5. Vectorized BO metrics — quick performance note (10,000 rows)

On a local run (warm loop, mean of 200 calls, same random 10k series as in `tests/test_binary_options_metrics.py::test_bo_metrics_vectorized_perf_10k`), **~0.08 ms per call** — dominated by pandas/numpy C implementations, not Python row loops.
