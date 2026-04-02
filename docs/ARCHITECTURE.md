# Architecture

Strat Trade Backend is built using **Hexagonal Architecture** (also known as Ports and Adapters). This promotes a clear separation of concerns, ensures business logic is entirely decoupled from external dependencies (e.g., FastAPI, Pocket Option SDK), and optimizes testability.

## Layers

1. **`domain/`** 
   - Contains the core business logic: entities, value objects, domain exceptions, pure mathematics for strategy evaluation, and the backtest engine core.
   - **Rule**: Absolutely no imports from FastAPI, database dependencies, or external HTTP libraries.
2. **`use_cases/`** 
   - Contains the orchestration layer. Use cases load necessary configuration, call the requisite feeders (`CandleFeed`), pipe data to the domain engine, and act on the results (e.g., saving to the DB or publishing a live signal).
   - **Rule**: Depends strictly on internal domain features and **ports** (Abstract Base Classes / Protocols).
3. **`ports/`** 
   - Define the narrow interfaces for interacting outside the core. Examples: `CandleFeed`, `TradingGateway`, `SignalPublisher`, `StrategyRepository`.
4. **`adapters/`** 
   - Implement the actual details for the defined `ports/`. Examples include Pocket Option API adapters, WebSocket streams, SQLAlchemy persistence structures, and FastAPI routes (mapping HTTP requests to `use_cases`). FastAPI routes reside in `api/` which functionally serves as a primary driving adapter.

## Primary Flows

- **FastAPI / HTTP Flow**: 
  HTTP Request -> FastAPI Route validation (`api/`) -> Invocation of a specific Use Case (`use_cases/`) -> Use Case calls Domain Rules / Ports -> Returns payload back through FastAPI.
- **Real-Time Evaluation Loop**:
  Continuous polling or streaming through an infrastructure adapter pushes data into the same engine primitives used in backtests, applying a "rolling window" for indicator calculations.

## Extension Points

### 1. Indicators
Indicators are designed to be easily pluggable:
- **Identifier**: Each indicator requires a stable, unique string ID.
- **Schema**: It requires a Pydantic (or similar) parameter schema for validation.
- **Calculator**: A calculator class implementing the shared indicator protocol.
- **Registry**: The indicator must be mapped in the central registry so that adding a new indicator implies no side effects on disjoint modules.

### 2. Strategy Rules
To maintain security and stability, strategy rules are strictly **data-driven**:
- Instead of using raw Python strings (which are risky via `eval`), rules are structured as an AST (Abstract Syntax Tree) or directed graph.
- These nodes are interpreted by a central `RuleEvaluator`.
- **To add new rules/conditions**: Introduce new node objects, a validation rule, and a branch in the evaluator.

### 3. Broker Integrations
If integrating an alternative broker / data provider:
- Implement a new **adapter** corresponding precisely to the existing **ports** (e.g., `TradingGateway`, `CandleFeed`).
- Ensure output types map directly back to pure domain structures like `Candle` or `Balance` rather than introducing platform-specific entities into the domain.
