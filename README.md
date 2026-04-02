# Strat Trade

Backend for **indicator-based trading strategies** integrated with **Pocket Option**: compose strategies, **backtest** over a time range, review **win rate** and metrics, **save** and **activate** strategies, receive **real-time signals** when rules fire.

## Running the project

**Requirements:** Python **3.12+**.

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

**Configuration:** copy [`.env.example`](.env.example) to `.env` and set Pocket Option credentials (SSID in the environment or via `POCKET_OPTION_SSID_FILE`, e.g. a one-line `.ssid` file — see comments in `.env.example`). The app loads `.env` from the **current working directory**, so start the server from the repo root unless you export variables another way.

**API server:**

```bash
uvicorn strat_trade.main:app --reload --host 127.0.0.1 --port 8000
```

- [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) — Swagger UI (OpenAPI)  
- [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) — liveness  

**Tests and lint (optional):**

```bash
pytest
ruff check .
ruff format --check .
```

## Documentation

| File | Content |
|------|--------|
| [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) | Product scope, user flows, glossary |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, ports/adapters, extension points |
| [docs/CODE_STYLE.md](docs/CODE_STYLE.md) | Python style and layering examples |
| [docs/API_REFERENCE.md](docs/API_REFERENCE.md) | Endpoints, request schemas, and responses |

## Cursor rules

- `.cursor/rules/strat-trade-backend.mdc` — domain, hexagonal layout, extensibility  
- `.cursor/rules/strat-trade-openapi.mdc` — OpenAPI / Swagger conventions for FastAPI  

## Status

Core API routes (health, balance, candles, indicators) and Pocket Option adapter are implemented; strategy/backtest persistence and signal streaming are still to be expanded — see [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md).
