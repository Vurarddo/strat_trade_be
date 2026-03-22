# Strat Trade

Backend for **indicator-based trading strategies** integrated with **Pocket Option**: compose strategies, **backtest** over a time range, review **win rate** and metrics, **save** and **activate** strategies, receive **real-time signals** when rules fire.

## Documentation

| File | Content |
|------|--------|
| [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) | Product scope, user flows, glossary |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, ports/adapters, extension points |
| [docs/CODE_STYLE.md](docs/CODE_STYLE.md) | Python style and layering examples |

## Cursor rules

- `.cursor/rules/strat-trade-backend.mdc` — domain, hexagonal layout, extensibility  
- `.cursor/rules/strat-trade-openapi.mdc` — OpenAPI / Swagger conventions for FastAPI  

## Status

Application code is not bootstrapped yet; use the docs and rules above when implementing the stack (FastAPI, persistence, PO adapter).
