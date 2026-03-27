# Strat Trade — project context

This document is the **source of truth for product intent and domain language**. Keep it updated when flows or boundaries change.

## Product summary

**Strat Trade** is a backend that integrates with the **Pocket Option** API and lets users define **indicator-based trading strategies**, **backtest** them on a chosen time range, inspect **win rate** and other metrics, then **save** and **activate** strategies. An **active** strategy runs in (near) real time, detects **signals** according to its rules, and **delivers** those signals to the user (push, websocket, or another channel — to be implemented per delivery adapter).

## Primary user journeys

1. **Compose a strategy**  
   User picks indicators (e.g. RSI, MACD), sets parameters and combination logic (e.g. “RSI oversold AND MACD cross up”). The strategy is a persisted configuration + rules, not executable broker orders unless explicitly scoped later.

2. **Backtest**  
   User selects an **instrument**, **timeframe**, and **time window** (start/end). The system loads historical candles (via Pocket Option or a normalized internal series), runs the strategy engine over that series, and returns **aggregated results** (win rate, trade count, PnL proxy if defined, drawdown, etc.).

3. **Save**  
   If the user accepts the configuration, the strategy is stored as a versioned **Strategy** (draft vs published can be a later refinement).

4. **Activate**  
   User marks a saved strategy as **active**. A **runtime** component subscribes to live/market data, evaluates the same rules on sliding windows, and emits **signals** when conditions match.

5. **Receive signals**  
   User receives notifications through the chosen channel; API must support listing recent signals and subscription status.

## Domain glossary

| Term | Meaning |
|------|--------|
| **Strategy** | Named configuration: instrument(s), timeframe, indicator set, parameters, and rule graph (how indicators combine into entries/exits). |
| **Indicator** | Pluggable computation over OHLCV (or derived) series (e.g. RSI, MACD). Each has a stable **id**, **parameter schema**, and **output schema**. |
| **Backtest run** | One execution of a strategy over a fixed historical window; produces metrics and optional per-signal log. |
| **Signal** | A time-stamped outcome of rule evaluation (e.g. “LONG”, “SHORT”, “EXIT”) with optional metadata (price, indicator snapshot). |
| **Pocket Option gateway** | Outbound adapter: auth, candles, balances, and any other supported PO operations. Domain must not depend on PO SDK types. |

## Non-goals (initial phases)

- Guaranteeing execution or profit; backtest is **simulation** unless explicitly connected to execution features later.
- UI implementation (this repo is **backend-only**).
- Storing raw third-party responses without normalization where a stable domain model is required.

## Integration assumptions (Pocket Option)

- Credentials and session identifiers live in **config/secrets**, never in code or committed files.
- All PO calls go through a **port** (`TradingGateway` / `MarketDataGateway` or split ports) implemented by **one adapter** so the broker can be swapped or mocked in tests.
- Respect **rate limits** and **timeouts**; retries only where idempotent and safe.
- **Candle history depth:** the Pocket Option adapter uses **BinaryOptionsToolsV2** (`get_candles` / `get_candles_advanced`) for native periods (1, 5, 15, 30, 60, 300 seconds). `GET /api/v1/market/candles/range` (and range-based winrate) loads `[from, to]` by **paging backward** from `to`: each call requests up to `STRAT_TRADE_MAX_CANDLES_PER_REQUEST` bars, then repeats with an end cursor before the oldest bar until `from` is covered or `STRAT_TRADE_MAX_CANDLES_RANGE_FETCH_ROUNDS` / broker history limits apply. Very long ranges may still need **persisted candles** or adapter extensions.
- **Asset catalog:** `GET /api/v1/market/assets` returns normalized rows from `PocketOptionAsync.active_assets()` (symbol, payout, `is_otc`, `is_active`, `allowed_candles`, etc.); query `active_only=true` filters to `is_active`.
- **Indicator series:** Indicator math lives in pure domain calculators (see `src/strat_trade/domain/indicators/*`). Metadata: `GET /api/v1/indicators/rsi`, `GET /api/v1/indicators/bollinger-bands`, `GET /api/v1/indicators/macd`. **Computed:** `POST /api/v1/market/indicators` — same `candles` shape as `GET /api/v1/market/candles`, plus `indicators[]` in request order; each output line is a list of `{ open_time, value }` aligned with `candles` (warmup omitted). **Gemini:** `POST /api/v1/market/indicators/gemini` — same request body; returns structured fields (`direction`, `expiration`, `win_probability`, `analysis`, `entry_time`, `close_time`, plus model echo) (requires `STRAT_TRADE_GOOGLE_GEMINI_API_KEY` or `GOOGLE_API_KEY` / `GEMINI_API_KEY`). Examples: `docs/MARKET_INDICATORS_API.md`.
- **Winrate strategy test (MVP):** The HTTP endpoint `POST /api/v1/strategy/test-winrate` and related winrate strategy evaluation are temporarily removed from the API in this iteration; strategy evaluation core is being rebuilt on top of the indicator calculators.

## Documentation map

| Document | Purpose |
|----------|--------|
| `PROJECT_CONTEXT.md` (this file) | Product and domain vocabulary |
| `ARCHITECTURE.md` | Layers, extension points, data flow |
| `CODE_STYLE.md` | Conventions and examples |
| `MARKET_INDICATORS_API.md` | `POST /api/v1/market/indicators` request/response JSON examples |

## Related Cursor rules

- `.cursor/rules/strat-trade-backend.mdc` — architecture and extensibility for this codebase  
- `.cursor/rules/strat-trade-openapi.mdc` — OpenAPI / Swagger conventions for HTTP APIs  
