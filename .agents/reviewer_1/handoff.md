# Reviewer 1 Handoff Report — Stage 2: S1 Market Data Collector & MarketDataStore

**Verdict**: **APPROVE**

---

## 1. Observation

### 1.1 Reviewed Work Products
- `src/strat_trade/domain/trading/market_data_store.py`:
  - Implements `MarketDataStore` encapsulating SQLite storage at `data/market_data.db` (or custom path).
  - Uses SQLite WAL mode (`PRAGMA journal_mode=WAL;`, `PRAGMA synchronous=NORMAL;`, `PRAGMA busy_timeout=5000;`).
  - Creates table `candles_s1` with schema: `asset TEXT`, `timestamp REAL`, `open REAL`, `high REAL`, `low REAL`, `close REAL`, `volume REAL DEFAULT 0.0`, with compound unique constraint `UNIQUE(asset, timestamp)` and index `idx_candles_s1_asset_timestamp`.
  - Provides robust timestamp parsing (`_extract_ts`) handling naive/aware `datetime`, millisecond/second epoch `int`/`float`, and ISO string timestamps.
  - Implements batch upsert `insert_candles()` using `INSERT OR IGNORE` with insertion count calculation via `conn.total_changes`.
  - Implements retrieval methods `get_candles()` (returning domain `Candle` entities with `Decimal` precision and UTC timezone) and `get_candles_df()` (returning pandas `DataFrame` with UTC datetime index/column ready for `BinaryBacktestEngine`).
  - Implements metadata and inspection methods: `get_stored_assets()`, `get_asset_stats()`, `count_candles()`, `get_total_candle_count()`, `get_latest_timestamp()`, `clear_candles()`.
- `scripts/collect_s1_data.py`:
  - Standalone executable script (`#!/usr/bin/env python3`) for periodic 1-second candle ingestion.
  - Resolves SSID via a 7-tier priority cascade: CLI `--ssid` $\to$ CLI `--ssid-file` $\to$ `Settings()` $\to$ `STRAT_TRADE_POCKET_OPTION_SSID` / `POCKET_OPTION_SSID` $\to$ `STRAT_TRADE_POCKET_OPTION_SSID_FILE` / `POCKET_OPTION_SSID_FILE` $\to$ `.ssid` file $\to$ `"demo"`.
  - Instantiates `PocketOptionTradingGateway` and `MarketDataStore`.
  - Implements `run_collector_loop()` and `collect_cycle()` with per-asset fault isolation catching `(BrokerUnavailableError, TimeoutError)`, `InvalidMarketParametersError`, `(ConnectionError, OSError)`, and generic `Exception` without terminating the loop.
  - Supports comprehensive CLI arguments: `--assets`, `--timeframe`, `--count`, `--interval`, `--db-path`, `--ssid`, `--ssid-file`, `--demo`, `--live`, `--once`, `--max-cycles`, `--throttle-delay`, `--log-level`.
  - Handles `SIGINT` / `SIGTERM` / `asyncio.CancelledError` gracefully, ensuring `gateway.aclose()` is awaited.
- `tests/test_market_data_store.py`: 11 unit tests covering schema, WAL mode, deduplication, timestamp formats, DataFrame generation, metadata queries, and malformed inputs.
- `tests/test_collect_s1_data.py`: 14 unit tests covering SSID resolution hierarchy, cycle execution, exception resilience, loop control, CLI parsing, and graceful termination.
- `tests/test_s1_data_collection_integration.py`: 2 end-to-end integration tests validating multi-cycle overlapping ingestion deduplication and downstream time-based backtest execution with `BinaryBacktestEngine`.

### 1.2 Verification Commands & Output
1. **Stage 2 Test Suite**:
   ```bash
   .venv/bin/pytest tests/test_market_data_store.py tests/test_collect_s1_data.py tests/test_s1_data_collection_integration.py -v
   # Result: 27 passed in 0.63s
   ```
2. **Full Project Regression Test Suite**:
   ```bash
   .venv/bin/pytest -v
   # Result: 1209 passed in 59.70s
   ```
3. **Linter**:
   ```bash
   .venv/bin/ruff check src tests scripts
   # Result: All checks passed! (0 errors)
   ```
4. **Static Type Checker**:
   ```bash
   .venv/bin/mypy src/strat_trade/domain/trading/market_data_store.py scripts/collect_s1_data.py
   # Result: Success: no issues found in 2 source files
   ```
5. **Standalone Script CLI Verification**:
   ```bash
   .venv/bin/python scripts/collect_s1_data.py --help
   # Result: Exited 0, displayed complete argument documentation.
   
   .venv/bin/python scripts/collect_s1_data.py --once --db-path /tmp/test_eval_market.db --assets EURUSD_otc --log-level DEBUG
   # Result: Exited 0, demonstrated graceful broker timeout handling, logged cleanly, and shut down gateway connection properly.
   ```

---

## 2. Logic Chain

1. **Adversarial & Integrity Evaluation**:
   - Checked for hardcoded test outputs or dummy facades: None found.
   - Database operations use parameterized queries (`?`), preventing SQL injection and handling SQLite locking properly.
   - Deduplication is verified: In an overlapping polling cycle (e.g. 300 candles fetched every 60 seconds with 240 seconds overlap), `INSERT OR IGNORE` on `UNIQUE(asset, timestamp)` cleanly ignores duplicate entries without throwing errors or expanding disk footprint unnecessarily.
2. **Domain Architecture Conformance**:
   - `MarketDataStore` correctly resides under `src/strat_trade/domain/trading/` and interacts with domain `Candle` entities with strict `Decimal` pricing and UTC timezones.
   - `get_candles_df()` outputs standard pandas DataFrame format compatible with `BinaryBacktestEngine` and indicators (`timestamp`, `open`, `high`, `low`, `close`, `volume`).
3. **Robustness & Operational Resilience**:
   - Network dropouts, broker resets, or temporary HTTP/WebSocket timeouts in `scripts/collect_s1_data.py` are caught at the individual asset level within `collect_cycle()`, allowing the collector to continue servicing remaining assets and retrying on subsequent cycles.
   - Graceful shutdown handles `SIGINT` (Ctrl+C) and `SIGTERM` via `asyncio.Event`, interrupting long sleep intervals immediately without dangling threads or unclosed WebSocket connections.

---

## 3. Caveats

- **SQLite WAL Files**: SQLite generates `-wal` and `-shm` auxiliary files alongside `data/market_data.db` while transactions are active. Any file backup or archiving tooling should include all matching `.db*` files.
- **Broker Rate Limits**: Default throttle delay between individual asset requests is set to 0.5s with a 60s cycle interval. When expanding to a large asset pool ($\ge 20$ assets), throttle delay and cycle intervals should be configured accordingly to avoid broker websocket rate throttling.

---

## 4. Conclusion

The Stage 2 implementation fully satisfies all requirements specified in `ORIGINAL_REQUEST.md` (§ Follow-up — 2026-08-31T15:45:40Z):
- `MarketDataStore` is fully implemented, performant, and concurrency-safe with SQLite WAL mode.
- `scripts/collect_s1_data.py` is a robust, standalone async collector with full CLI configuration, error recovery, and clean shutdown handling.
- Comprehensive test coverage (27 unit/integration tests) and 100% full project regression pass (1,209 tests).

**Final Verdict**: **APPROVE**

---

## 5. Verification Method

To independently verify this review:

```bash
# 1. Run Stage 2 test suite
.venv/bin/pytest tests/test_market_data_store.py tests/test_collect_s1_data.py tests/test_s1_data_collection_integration.py -v

# 2. Run full regression suite
.venv/bin/pytest -v

# 3. Run linting
.venv/bin/ruff check src tests scripts

# 4. Run mypy typing check
.venv/bin/mypy src/strat_trade/domain/trading/market_data_store.py scripts/collect_s1_data.py

# 5. Test CLI help
.venv/bin/python scripts/collect_s1_data.py --help
```
