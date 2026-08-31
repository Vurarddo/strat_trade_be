# Stage 2 Implementation & Verification Handoff Report: S1 Market Data Collector & MarketDataStore

## 1. Observation

### 1.1 Requirements Addressed (§ Follow-up — 2026-08-31T15:45:40Z in `ORIGINAL_REQUEST.md`)
- **R1. Database Schema for Market Data**:
  - Implemented `src/strat_trade/domain/trading/market_data_store.py` connecting to SQLite database at `data/market_data.db` (or custom path).
  - Automatically creates parent directories if they do not exist.
  - Sets PRAGMAs: `PRAGMA journal_mode=WAL;`, `PRAGMA synchronous=NORMAL;`, `PRAGMA busy_timeout=5000;`.
  - Creates table `candles_s1` with columns: `asset` (TEXT), `timestamp` (REAL), `open` (REAL), `high` (REAL), `low` (REAL), `close` (REAL), `volume` (REAL).
  - Enforces compound unique constraint `UNIQUE(asset, timestamp)` and creates index `idx_candles_s1_asset_timestamp`.
  - Implemented methods:
    - `insert_candles(asset: str, candles: Sequence[Candle | dict[str, Any]]) -> int` with `INSERT OR IGNORE` and precise insertion count tracking.
    - `save_candles(asset: str, candles: Sequence[Candle]) -> int` (convenience alias).
    - `insert_candle(asset: str, candle: Candle | dict[str, Any]) -> bool` (single-candle insert helper).
    - `get_candles(asset: str, start_time: datetime | float | int | None = None, end_time: datetime | float | int | None = None, limit: int | None = None) -> list[Candle]` returning domain `Candle` entities with UTC timezone and `Decimal` pricing.
    - `get_candles_df(asset: str, start_time: datetime | float | int | None = None, end_time: datetime | float | int | None = None, limit: int | None = None) -> pd.DataFrame` returning canonical DataFrames with `['timestamp', 'open', 'high', 'low', 'close', 'volume']` ready for `BinaryBacktestEngine`.
    - Metadata and inspection methods: `get_stored_assets() -> list[str]`, `get_asset_stats(asset: str) -> dict[str, Any]`, `count_candles(asset: str | None = None) -> int`, `get_total_candle_count() -> int`, `get_latest_timestamp(asset: str) -> float | None`, `clear_candles(asset: str | None = None) -> int`.
- **R2. Data Collection Script**:
  - Implemented standalone executable script `scripts/collect_s1_data.py` (`#!/usr/bin/env python3`).
  - Resolves SSID via robust hierarchy: CLI `--ssid` $\to$ CLI `--ssid-file` $\to$ `Settings()` $\to$ `STRAT_TRADE_POCKET_OPTION_SSID` / `POCKET_OPTION_SSID` $\to$ `STRAT_TRADE_POCKET_OPTION_SSID_FILE` / `POCKET_OPTION_SSID_FILE` $\to$ root `.ssid` file $\to$ fallback `"demo"`.
  - Instantiates `PocketOptionTradingGateway` and `MarketDataStore`.
  - Async collection loop querying `gateway.get_candles(asset, timeframe=1, count=300)` for target assets (default: `["EURUSD_otc", "GOLD_otc", "AUDNZD_otc"]`).
  - Catches `(BrokerUnavailableError, TimeoutError)`, `InvalidMarketParametersError`, `(ConnectionError, OSError)`, and generic `Exception` per asset without crashing the loop.
  - Supports CLI flags: `--assets`, `--timeframe`, `--count`, `--interval`, `--db-path`, `--ssid`, `--ssid-file`, `--demo`, `--live`, `--once`, `--max-cycles`, `--throttle-delay`, `--log-level`.
  - Graceful shutdown handling `SIGINT`, `SIGTERM`, and `asyncio.CancelledError`, awaiting `gateway.aclose()`.
- **R3. Safe Upsert Logic**:
  - Deduplication via `UNIQUE(asset, timestamp)` and `INSERT OR IGNORE` safely handles overlapping historical candle batches (e.g. 240 seconds overlap per 60s cycle).

### 1.2 Test Suite Implementation
- Created `tests/test_market_data_store.py` (11 unit tests covering schema, WAL, deduplication, timestamp normalization, DataFrame generation, metadata inspection, and malformed inputs).
- Created `tests/test_collect_s1_data.py` (14 unit tests covering SSID resolution, fault resilience, loop control, CLI parsing, and graceful shutdown).
- Created `tests/test_s1_data_collection_integration.py` (2 end-to-end integration tests covering multi-cycle overlapping polling deduplication and time-based backtest execution with `BinaryBacktestEngine`).

---

## 2. Logic Chain

1. **Schema & Concurrency Design**:
   - `MarketDataStore` sets WAL mode and synchronous=NORMAL to allow concurrent background ingestion from the collector script while backtesting or UI queries read from the same database file without database lock contention.
   - `PRAGMA busy_timeout=5000` guarantees graceful waiting under concurrent transactions.
2. **Idempotency on Overlapping Polls**:
   - Because `collect_s1_data.py` polls every 60s and fetches 300 1-second candles, 240 candles per cycle overlap with previous cycles.
   - Using `INSERT OR IGNORE` on `UNIQUE(asset, timestamp)` guarantees that re-queried candles are discarded with zero disk duplication and zero SQLite integrity errors.
   - `store.insert_candles()` calculates newly inserted rows via SQLite connection changes delta (`conn.total_changes - initial_changes`).
3. **Time-Based Backtest Compatibility**:
   - `store.get_candles_df()` converts SQLite float epoch timestamps to UTC `pd.Timestamp` series sorted ascending.
   - Verified that `BinaryBacktestEngine` accepts this DataFrame and correctly executes time-based exit matching on high-frequency S1 data.
4. **Resilience in Collector Daemon**:
   - Individual asset fetch failures (network drops, broker timeouts, unlisted asset pairs) are caught per asset.
   - The loop continues with remaining assets and retries next cycle, preserving daemon uptime.
   - Between cycles, `asyncio.wait_for(shutdown_event.wait(), timeout=interval)` allows instant termination on Ctrl+C / SIGINT without waiting for the sleep timer to expire.

---

## 3. Caveats

- **Live vs Demo Gateway**: In live production environments with real funds, a valid browser session SSID must be supplied via `--ssid`, `--ssid-file`, or environment variables. In test/demo mode, the script defaults to demo mode with safe fallbacks.
- **SQLite WAL Files**: SQLite generates `-wal` and `-shm` temporary index files in the target database directory during active writes. When backing up or moving `data/market_data.db`, all three files must be considered or checkpointed.

---

## 4. Conclusion

All requirements for Stage 2 are fully implemented, verified, and passing:
1. `src/strat_trade/domain/trading/market_data_store.py` provides high-performance SQLite persistence with WAL mode, deduplication, and direct DataFrame/domain Candle conversion.
2. `scripts/collect_s1_data.py` provides a standalone, resilient, CLI-driven async collector for 1-second candles.
3. 27 new tests across 3 test suites validate 100% of the Stage 2 requirements.
4. Project regression suite passed at 1,209 / 1,209 tests (100%).
5. Code style and typing verified: 0 ruff errors, 0 mypy errors on new files.

---

## 5. Verification Method

To independently verify the implementation:

```bash
# 1. Run Stage 2 unit and integration test suite (27 tests)
.venv/bin/pytest tests/test_market_data_store.py tests/test_collect_s1_data.py tests/test_s1_data_collection_integration.py -v

# 2. Run the full project regression test suite (1209 tests)
.venv/bin/pytest -v

# 3. Verify code style and linting
.venv/bin/ruff check src tests scripts

# 4. Verify static typing with mypy
.venv/bin/mypy src/strat_trade/domain/trading/market_data_store.py scripts/collect_s1_data.py tests/test_market_data_store.py tests/test_collect_s1_data.py tests/test_s1_data_collection_integration.py

# 5. Verify standalone script CLI execution
.venv/bin/python scripts/collect_s1_data.py --help
```
