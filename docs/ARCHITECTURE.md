# Strat Trade — architecture

## Goals

- **Hexagonal (ports & adapters)** so domain and use cases stay free of FastAPI, Pocket Option SDK, and database details.
- **Easy extension**: new indicators, new strategy rule types, and new outbound channels without rewriting the core engine.
- **Testability**: backtest and signal logic unit-tested with in-memory candle series; adapters integration-tested or contract-tested.

## Suggested package layout (Python)

```text
src/strat_trade/
  domain/           # Entities, value objects, domain errors (no I/O)
  use_cases/        # Application services; orchestrate ports
  ports/            # Protocols / ABCs: gateways, repositories, clocks
  adapters/
    http/           # FastAPI routes, deps, OpenAPI-only DTOs mapping
    pocket_option/  # PO client implementation of ports
    persistence/    # SQLAlchemy / repositories
    realtime/       # Websockets, SSE, or message fan-out
```

Routes stay **thin**: validate input → call use case → map result to response. **No** indicator math or PO JSON parsing in route handlers.

## Core flows

### Backtest

1. HTTP layer receives `strategy_id` or inline strategy definition + `from` / `to` / timeframe.
2. Use case loads strategy (if persisted) and resolves **indicator pipeline** from a **registry**.
3. **Market data port** fetches candles for the window (PO adapter or fake in tests).
4. **Strategy engine** walks the series (or chunked stream), updates indicator state, evaluates rules, records hypothetical trades/signals.
5. Use case returns **BacktestResult** (metrics + optional detail).

### Live signals

1. **Scheduler or streaming consumer** ticks on new candles or poll interval.
2. For each **active** strategy, engine evaluates the latest window.
3. On match, persist **Signal** (optional) and publish via **NotificationPort** / websocket adapter.

## Extension points

### 1. Indicators

- Define a small interface, e.g. `IndicatorSpec` (id, params) + `IndicatorCalculator` protocol: `(series_window) -> IndicatorValues`.
- Register calculators in a **registry** keyed by indicator id (string or enum).
- Adding RSI v2 = new class + registration; no changes to the engine’s core loop beyond generic “run registered indicator”.

### 2. Strategy rules

- Represent rules as **data** (AST or JSON-serializable graph) interpreted by a **RuleEvaluator**, not as arbitrary Python lambdas from the API (security and reproducibility).
- New rule types = new evaluator node + schema validation; keep evaluator table-driven where possible.

### 3. Pocket Option and other brokers

- New broker = new adapter package implementing the same **ports**. Domain types use **normalized** candles and account views.

### 4. API surface

- Version prefix `/api/v1/`. Breaking changes → v2 or additive fields with defaults.

## Persistence (evolution)

- **Strategy** and **BacktestRun** are natural aggregates for storage.
- **Signal** rows or event log for audit and “recent signals” API.
- Migrations via Alembic when SQLAlchemy is introduced.

## Observability

- Structured logging with `strategy_id`, `backtest_id`, `correlation_id` on requests.
- Metrics: backtest duration, PO call latency/error rate, signals emitted per minute.

## Security

- Authenticate API users (mechanism TBD: JWT, API keys).
- Never log secrets or full PO payloads containing credentials.
- Validate and bound all time ranges and candle limits to prevent abuse.
