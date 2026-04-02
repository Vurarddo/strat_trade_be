# Code Style & General Guidelines

This repository follows standardized conventions to maintain a clean codebase, encourage maintainability, and keep layer boundaries secure.

## Python Environment

- **Python Version**: Minimum requirement is **3.12**.
- **Package Management**: Dependencies are defined in `pyproject.toml` (and a `.venv` is standard for local iteration).

## Linting and Code Formatting

We use **Ruff** to combine the responsibilities of linting and formatting, providing a speedy and cohesive experience.
- To format: `ruff format .`
- To check: `ruff check .`

It is required to maintain a warning-free state before committing. Note the specific configuration mapped in `pyproject.toml` (if available) or the defaults enforced by `.cursor/rules/strat-trade-backend.mdc`.

## Core Coding Patterns

### Validations and Error Handling
- **Domain Errors**: Internal invariants must trigger structured custom exception classes existing inside `domain/errors.py`. 
- **HTTP Errors**: Never throw HTTPExceptions deeply embedded inside the `domain/` or `use_cases/` folders. Hand-off domain errors back to the `api/` layer, which catches domain-specific errors and maps them dynamically to precise 4xx / 5xx code responses (`http_errors.py`).

### Typing
- We strive for strict, explicit typing.
- Always annotate function signatures and variables where ambiguity might arise. 
- Use **Pydantic** extensively at the boundaries (`adapters/` / `api/`) to sanitize data strictly before entering the domain layers.

### Testing
- Place test suites in the `tests/` directory matching the module path you are testing (e.g. `tests/domain/test_entities.py`).
- Since external behaviors are hidden behind **Ports**, test domain files and use cases using simple in-memory mocks / fakes, achieving extremely fast uncoupled test execution. 
- Ensure that side-effect operations mock out time (using `Clock` ports if needed) so that backtest behavior holds reproducible assertions across runs.

### Defensive Boundaries
- **Dependency Injection**: Instantiate concrete adapters inside the `main.py` entrypoint or through FastAPI dependencies (`deps.py`), and inject them into `use_cases/` as their standard abstractions (Ports).
- **Payload Boundaries**: Broker (Pocket Option) structures are confined to `adapters/`. Do not bleed fields representing PO-specific concepts into core `entities.py`. Everything external must be uniformly mapped.
