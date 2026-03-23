# Strat Trade — code style and examples

Stack target: **Python 3.12+**, **FastAPI**, **Pydantic v2**, **Ruff** (lint + format). Adjust versions in `pyproject.toml` when the project is bootstrapped.

## General principles

- **SOLID / DRY / KISS**: one reason to change per module; reuse ports; avoid speculative abstractions.
- **Types on boundaries**: public functions and port methods are typed; prefer `Protocol` for ports.
- **I/O at edges**: no `httpx` or SQLAlchemy in `domain/` or pure engine code.

## Naming

| Area | Convention |
|------|------------|
| Modules | `snake_case` |
| Classes | `PascalCase` |
| Functions / methods | `snake_case` |
| Constants | `UPPER_SNAKE` |
| Ports | Noun + role: `CandleFeed`, `StrategyRepository` |
| Adapters | Implementation name: `PocketOptionCandleFeed` |

## Layering example (good)

**Port** (`ports/candles.py`):

```python
from typing import Protocol
from datetime import datetime
from strat_trade.domain.entities import Candle

class CandleFeed(Protocol):
    async def get_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        ...
```

**Use case** (`use_cases/run_backtest.py`):

```python
from strat_trade.ports.candles import CandleFeed
from strat_trade.domain.backtest import BacktestEngine

async def run_backtest(
    feed: CandleFeed,
    engine: BacktestEngine,
    *,
    symbol: str,
    timeframe: str,
) -> BacktestSummary:
    candles = await feed.get_candles(...)
    return engine.run(candles)
```

**Adapter** (`adapters/pocket_option/candles.py`): implements `CandleFeed`, maps PO JSON → `Candle`.

**Route** (`adapters/http/routes/backtests.py`): parses body → calls `run_backtest` → returns DTO.

## Anti-patterns (avoid)

```python
# BAD: domain importing FastAPI or requests
from fastapi import Depends
import httpx

def compute_rsi(candles: list) -> list[float]:
    r = httpx.get("https://api.broker/...")  # never here
    ...
```

```python
# BAD: god use case doing HTTP + SQL + math in one function
async def backtest(...):
    rows = await db.execute(...)
    po = httpx.get(...)
    rsi = manual_rsi(po.json())
    await db.insert(...)
```

Prefer three units: **repository**, **feed adapter**, **engine**.

## Pydantic

- **Settings**: `pydantic-settings`, env prefixes, no secrets in defaults.
- **API models**: separate from domain entities when shapes differ; map explicitly.

```python
from pydantic import BaseModel, Field

class BacktestRequest(BaseModel):
    strategy_id: str = Field(examples=["strat_01"])
    range_start: datetime
    range_end: datetime
```

## Errors

- Raise **domain exceptions** in core; map to HTTP in a single exception handler or per-router dependency.
- Use stable **error codes** in JSON for clients, e.g. `{ "code": "INVALID_RANGE", "message": "..." }`.

## Tests

- **Unit**: engine + indicators with synthetic candles.
- **API**: `TestClient` with overridden dependencies (fake `CandleFeed`).
- File names: `test_<module>.py`; test functions `test_<behavior>_<expected>()`.

## Imports

- Stdlib → third party → local (`isort` / Ruff isort rules).
- No wildcard imports.

## Formatting

- Line length **100** or **88** — pick one in Ruff and stay consistent.
- Trailing commas in multi-line collections.
