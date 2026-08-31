# Stage 2 Independent Review Report (Reviewer 2)

**Verdict**: APPROVE

---

## 1. Observation

### 1.1 Requirements and Scope Under Review
Review conducted for Stage 2 of `strat_trade_be` as defined in `ORIGINAL_REQUEST.md` (§ Follow-up — 2026-08-31T15:45:40Z) and Worker 1 handoff (`.agents/worker_1/handoff.md`):
- `src/strat_trade/domain/trading/market_data_store.py`
- `scripts/collect_s1_data.py`
- `tests/test_market_data_store.py`
- `tests/test_collect_s1_data.py`
- `tests/test_s1_data_collection_integration.py`

### 1.2 Direct Code and Architecture Observations
1. **Schema & Persistence (`src/strat_trade/domain/trading/market_data_store.py`)**:
   - `MarketDataStore` connects to SQLite database (`data/market_data.db` by default) and ensures directory structure exists: `self.db_path.parent.mkdir(parents=True, exist_ok=True)`.
   - Concurrency and lock configuration:
     - Line 26: `conn.execute("PRAGMA journal_mode=WAL")`
     - Line 27: `conn.execute("PRAGMA synchronous=NORMAL")`
     - Line 28: `conn.execute("PRAGMA busy_timeout=5000")`
   - Table schema creation (Lines 33-51):
     - Table `candles_s1` with columns: `asset TEXT NOT NULL`, `timestamp REAL NOT NULL`, `open REAL NOT NULL`, `high REAL NOT NULL`, `low REAL NOT NULL`, `close REAL NOT NULL`, `volume REAL NOT NULL DEFAULT 0.0`.
     - Compound unique constraint: `UNIQUE(asset, timestamp)`.
     - Covering index: `CREATE INDEX IF NOT EXISTS idx_candles_s1_asset_timestamp ON candles_s1(asset, timestamp)`.
   - Batch insert with safe upsert (Lines 69-134):
     - Uses `INSERT OR IGNORE INTO candles_s1 ...` with `executemany`.
     - Accurately tracks newly inserted records: `inserted = conn.total_changes - initial_changes`.
     - Accepts domain `Candle` entities, raw dictionaries with various key mappings (`time`, `timestamp`, `open_time`, `t`, `open`/`o`, `high`/`h`, `low`/`l`, `close`/`c`, `volume`/`v`), ISO strings, and millisecond epoch integers.
   - Query & Backtester Interface (Lines 143-254):
     - `get_candles()` returns `list[Candle]` with Decimal prices and UTC datetime.
     - `get_candles_df()` returns canonical `pd.DataFrame` with columns `['timestamp', 'open', 'high', 'low', 'close', 'volume']`, sorted ascending by timestamp, with UTC timezone-aware datetime series.

2. **Standalone S1 Data Collector Script (`scripts/collect_s1_data.py`)**:
   - Executable entrypoint with `#!/usr/bin/env python3`.
   - Robust SSID resolution hierarchy (Lines 43-89): `--ssid` $\to$ `--ssid-file` $\to$ `Settings()` $\to$ `STRAT_TRADE_POCKET_OPTION_SSID` / `POCKET_OPTION_SSID` $\to$ `STRAT_TRADE_POCKET_OPTION_SSID_FILE` / `POCKET_OPTION_SSID_FILE` / `POCKETOPTION_SSID_FILE` $\to$ `.ssid` $\to$ fallback `"demo"`.
   - Async collection cycle and error resilience (Lines 92-167):
     - For each target asset (default `["EURUSD_otc", "GOLD_otc", "AUDNZD_otc"]`), calls `gateway.get_candles(clean_asset, timeframe=timeframe, count=count)`.
     - Catches `(BrokerUnavailableError, TimeoutError)`, `InvalidMarketParametersError`, `(ConnectionError, OSError)`, and generic `Exception` per asset, logging warnings and continuing the loop for subsequent assets.
   - Graceful shutdown & lifecycle (Lines 170-366):
     - Registers `SIGINT` and `SIGTERM` handlers setting `shutdown_event = asyncio.Event()`.
     - Wakes up immediately between polling cycles via `asyncio.wait_for(event.wait(), timeout=interval)`.
     - `finally:` block awaits `gateway.aclose()`.
   - Comprehensive CLI options (Lines 235-313): `--assets`, `--timeframe`, `--count`, `--interval`, `--db-path`, `--ssid`, `--ssid-file`, `--demo`, `--live`, `--once`, `--max-cycles`, `--throttle-delay`, `--log-level`.

3. **Empirical Test Verification**:
   - Stage 2 test command: `.venv/bin/pytest tests/test_market_data_store.py tests/test_collect_s1_data.py tests/test_s1_data_collection_integration.py -v` $\to$ **27 passed in 0.69s**.
   - Full test suite: `.venv/bin/pytest -v` $\to$ **1209 passed in 60.37s (0 failures, 0 regressions)**.
   - Ruff linting: `.venv/bin/ruff check src/strat_trade/domain/trading/market_data_store.py scripts/collect_s1_data.py tests/test_market_data_store.py tests/test_collect_s1_data.py tests/test_s1_data_collection_integration.py` $\to$ **All checks passed (0 errors)**.
   - Type checking: `.venv/bin/mypy src/strat_trade/domain/trading/market_data_store.py scripts/collect_s1_data.py tests/test_market_data_store.py tests/test_collect_s1_data.py tests/test_s1_data_collection_integration.py` $\to$ **Success: no issues found in 5 source files**.
   - Standalone CLI execution: `.venv/bin/python scripts/collect_s1_data.py --once --db-path /tmp/test_manual_s1.db --throttle-delay 0.0` executed and handled network timeouts gracefully, closing gateway with exit code 0.

---

## 2. Logic Chain

1. **Backtest Engine Contract Compatibility**:
   - Observation: `BinaryBacktestEngine.run()` requires a DataFrame with `timestamp` as datetime/numeric series and columns `open`, `high`, `low`, `close`, `volume`.
   - Observation: `MarketDataStore.get_candles_df()` produces exactly these column names with `df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)` and strict ascending order.
   - Inferences: The data format emitted by `MarketDataStore` is directly consumable by `BinaryBacktestEngine` for sub-second, S1, and multi-second evaluations without requiring intermediate transformation. Verified via `TestS1DataCollectionIntegration.test_e2e_collected_s1_data_with_binary_backtest_engine`.

2. **Concurrency & Safe Upsert Under Overlapping Polling**:
   - Observation: Polling every 60 seconds with `count=300` fetches 300 1-second candles per cycle, resulting in 240 seconds of overlapping data with the previous cycle.
   - Observation: SQLite table `candles_s1` has `UNIQUE(asset, timestamp)` and queries execute `INSERT OR IGNORE`.
   - Inferences: Overlapping candles are cleanly discarded without throwing duplicate key exceptions, and new candles are appended. WAL mode and `PRAGMA busy_timeout=5000` allow simultaneous background writing from the collector script while backtesting or API threads read from the database without locking conflicts.

3. **Graceful Daemon Operations and Signal Handling**:
   - Observation: `collect_s1_data.py` catches broker connection drops, timeouts, and HTTP errors at the per-asset level in `collect_cycle`.
   - Observation: `SIGINT` / `SIGTERM` triggers `shutdown_event.set()`, instantly interrupting the inter-cycle wait and executing `await gateway.aclose()`.
   - Inferences: The collector operates stably as a background service without crashing on temporary network interruptions or hanging during termination.

4. **Integrity & Authenticity**:
   - Observation: Source code contains real SQLite execution, parameter extraction, and asynchronous gateway coordination.
   - Observation: Unit tests utilize ephemeral SQLite databases via pytest `tmp_path` fixtures, verify real queries, test actual deduplication behavior, and execute the actual `BinaryBacktestEngine`.
   - Inferences: Zero integrity violations, zero hardcoded shortcuts, and zero dummy facades detected.

---

## 3. Caveats

- **Broker Account Credentialing**: When running `collect_s1_data.py` in live mode against real broker assets, a valid active session SSID must be supplied (via CLI, `.ssid` file, or environment variable). In development/demo mode, the script defaults safely to `"demo"`.
- **Database Backup Considerations**: Because WAL mode is enabled, SQLite creates temporary `-wal` and `-shm` files during operation. Database archiving or copying should account for WAL checkpoints.

---

## 4. Conclusion

The Stage 2 implementation meets and exceeds all requirements specified in `ORIGINAL_REQUEST.md` (§ Follow-up — 2026-08-31T15:45:40Z):
- `MarketDataStore` implements a robust, concurrent-safe SQLite storage engine with WAL mode, deduplication, and direct `BinaryBacktestEngine` DataFrame export.
- `scripts/collect_s1_data.py` provides a production-grade async collector with full CLI flexibility, multi-tier SSID resolution, per-asset error resilience, and clean shutdown handling.
- Comprehensive test coverage across 27 dedicated tests and 1,209 total regression tests with 100% pass rate.

**Final Verdict**: **APPROVE**

---

## 5. Verification Method

To independently reproduce the verification results:

```bash
# 1. Run Stage 2 unit and integration test suite (27 tests)
.venv/bin/pytest tests/test_market_data_store.py tests/test_collect_s1_data.py tests/test_s1_data_collection_integration.py -v

# 2. Run full regression test suite (1209 tests)
.venv/bin/pytest -v

# 3. Verify ruff linting on target files
.venv/bin/ruff check src/strat_trade/domain/trading/market_data_store.py scripts/collect_s1_data.py tests/test_market_data_store.py tests/test_collect_s1_data.py tests/test_s1_data_collection_integration.py

# 4. Verify mypy type checking
.venv/bin/mypy src/strat_trade/domain/trading/market_data_store.py scripts/collect_s1_data.py tests/test_market_data_store.py tests/test_collect_s1_data.py tests/test_s1_data_collection_integration.py

# 5. Verify CLI options and standalone script execution
.venv/bin/python scripts/collect_s1_data.py --help
```
