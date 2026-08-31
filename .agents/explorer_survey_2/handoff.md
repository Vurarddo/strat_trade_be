# Stage 3 Exploration & Design Report: Web API & UI Dashboard Specialist (Survey 2)

## Executive Summary

This report establishes the complete architecture and implementation blueprint for **Stage 3 of Pocket Option AutoTrader Pro** (Requirements R1, R2, and R3). It covers the FastAPI backend endpoints, the shared asynchronous collector execution engine, the Jinja2 SPA template markup, Tailwind CSS / Lucide UI components, and the reactive JavaScript client-side polling and state management for the **S1 Data Collection Panel**.

---

## 1. Observation

### 1.1 FastAPI App Structure & Route Registrations
- **Main Entrypoint (`src/strat_trade/main.py`)**:
  - Application factory / instance: `app = FastAPI(title="Strat Trade API", version="0.1.0", lifespan=lifespan)`.
  - Lifespan context manager initializes `Settings()` and `PocketOptionTradingGateway(...)`, attaching them to `app.state.settings` and `app.state.trading_gateway` (lines 24–40). On application shutdown, `await gateway.aclose()` is executed.
  - Exception handling: `register_domain_exception_handlers(app)` in `src/strat_trade/api/http_errors.py` automatically maps domain exceptions (`BrokerUnavailableError` -> 502, `InvalidMarketParametersError` -> 400, `DomainError` -> 400) to standard `ErrorEnvelope(error=ErrorBody(code=..., message=...))` JSON responses.
  - Existing router inclusions (lines 68–76):
    - `web_router` (mounted at `/`, serves `/`, `/dashboard`, `/favicon.svg`, `/favicon.ico`)
    - `bot_router` (prefix `/api/v1`, tags `["Live Demo Bot"]`)
    - `audit_router` (prefix `/api/v1`, tags `["Trade Audit & XLS Merger"]`)
    - `backtest_router` (prefix `/api/v1`, tags `["Backtest"]`)
    - `balance_router` (prefix `/api/v1`, tags `["Account"]`)
    - `candles_router` (prefix `/api/v1`, tags `["Market data"]`)
    - `indicators_router` (prefix `/api/v1`, tags `["Market data"]`)
    - `indicator_catalog_router` (prefix `/api/v1`, tags `["Market data"]`)
    - `tradingview_router` (prefix `/api/v1`, tags `["TradingView"]`)
- **Dependency Injection (`src/strat_trade/api/deps.py`)**:
  - `get_trading_gateway(request: Request) -> TradingGateway` returns `request.app.state.trading_gateway`.
  - `get_candle_feed(request: Request) -> CandleFeed` returns `request.app.state.trading_gateway`.
  - `get_settings(request: Request) -> Settings` returns `request.app.state.settings`.
  - Type annotations: `TradingGatewayDep = Annotated[TradingGateway, Depends(get_trading_gateway)]`, `CandleFeedDep = Annotated[CandleFeed, Depends(get_candle_feed)]`.

### 1.2 Web UI & Template Architecture (`src/strat_trade/web/templates/index.html`)
- **Single-Page Application (SPA)**: 3,396 lines, self-contained HTML/CSS/JS file loaded by `HTMLResponse` from `src/strat_trade/api/routes/web.py`.
- **Styling & Assets**:
  - Tailwind CSS CDN (`https://cdn.tailwindcss.com`) with custom dark mode config: `surface-900` (`#0b0f17`), `surface-800` (`#111827`), `surface-700` (`#1f2937`), `brand-500` (`#06b6d4`), `call` (`#10b981`), `put` (`#ef4444`).
  - Custom CSS classes: `.glass-card` (backdrop blur, subtle border, shadow), `.glass-input` (semi-transparent inputs with cyan focus ring), custom webkit scrollbar.
  - Lucide Icons CDN (`https://unpkg.com/lucide@latest`), rendered dynamically with `lucide.createIcons()`.
  - TradingView Lightweight Charts v4.2.1 for candle & equity visualization.
- **Tab Navigation System**:
  - Managed by `switchTab(tabId)` (lines 1652–1700). Toggles `.hidden` on corresponding `<div id="tab<Name>">` containers and updates active/inactive Tailwind classes on `<button id="tabBtn<Name>">`.
  - Existing tabs: `liveBot`, `audit`, `portfolio`, `single`, `optimizer`, `apiTester`.
- **Asset Selection & Filtering Components**:
  - `loadAssetsList()` (lines 1730–1834) fetches from `GET /api/v1/market/assets` and populates `<select>` and checkbox containers (`botAssetsContainer`, `portfolioAssetsContainer`).
  - Filter buttons (`selectBotTopNAssets`, `selectBotOtcAssets`, `selectBotOtcForexAssets`, `selectBotForexAssets`, `clearBotSelectedAssets`) and real-time text filter (`filterBotAssetsList()`).
- **Real-Time Polling & Status Pattern**:
  - Bot execution uses `setInterval(fetchLiveBotStatus, 3000)` with `clearInterval` on stop/halt (lines 2099–2102, 2164–2166).
  - Status ribbons dynamically update text, pulsing indicator colors (`bg-emerald-400 animate-pulse` vs `bg-gray-500` vs `bg-rose-500`), and button visibility (`btnStart`, `btnStop`, `btnResume`).

### 1.3 Underlying Data Storage & Gateway Capabilities
- **`MarketDataStore` (`src/strat_trade/domain/trading/market_data_store.py`)**:
  - SQLite backend (`data/market_data.db`) with WAL mode (`PRAGMA journal_mode=WAL`) and `busy_timeout=5000`.
  - Methods:
    - `insert_candles(asset: str, candles: Sequence[Candle | dict]) -> int`: Batch insertion with duplicate suppression via `INSERT OR IGNORE INTO candles_s1 ...`.
    - `get_asset_stats(asset: str) -> dict[str, Any]`: Returns `count`, `first_timestamp`, `last_timestamp`, `first_time`, `last_time`.
    - `get_stored_assets() -> list[str]`: List of distinct asset symbols with recorded data.
    - `get_total_candle_count() -> int` / `count_candles(asset=...) -> int`.
- **`PocketOptionTradingGateway` (`src/strat_trade/adapters/pocket_option_gateway.py`)**:
  - `async def get_assets() -> list[dict[str, Any]]`: Returns list of dictionaries with keys `symbol`, `name`, `payout`, `is_otc`, `asset_type`.
  - `async def get_candles(asset: str, timeframe: int | str, *, count: int, end_time: datetime | None = None) -> list[Candle]`: Retrieves live S1/M1 candles from Pocket Option WebSocket client.
  - `_client_connected()` reuses single active WebSocket session across the process.
- **Stage 2 Standalone Collector (`scripts/collect_s1_data.py`)**:
  - Implements `collect_cycle(gateway, store, assets, timeframe, count, throttle_delay, shutdown_event)` and `run_collector_loop(...)` with comprehensive exception catching (`BrokerUnavailableError`, `TimeoutError`, `InvalidMarketParametersError`, `ConnectionError`, `OSError`).

---

## 2. Logic Chain & Technical Architecture

```
+-----------------------------------------------------------------------------------+
|                            FastAPI Lifespan (main.py)                             |
|  - app.state.trading_gateway: PocketOptionTradingGateway (Single WebSocket conn)  |
|  - app.state.settings: Settings                                                   |
+-----------------------------------------+-----------------------------------------+
                                          |
        +---------------------------------+---------------------------------+
        |                                                                   |
        v                                                                   v
+-------------------------------+                         +-----------------------------------+
| Collector API Route           |                         | Collector Engine                  |
| (api/routes/collector.py)     |                         | (use_cases/manage_collector.py)   |
| - GET  /available-assets      | <--- Dependency Injected -- AsyncCollectorEngine (Singleton)|
| - GET  /status                |      TradingGatewayDep  | - _task: asyncio.Task             |
| - POST /start                 |                         | - _lock: asyncio.Lock             |
| - POST /stop                  |                         | - MarketDataStore (market_data.db)|
+---------------+---------------+                         +-----------------+-----------------+
                |                                                           |
                | JSON Responses (Pydantic Models)                          | Async Loop
                v                                                           v
+-------------------------------------------------------------+   +---------------------------+
| Web SPA Dashboard (templates/index.html)                    |   | Pocket Option Broker WS   |
| - Tab: "Збір S1 Даних" (tabCollector)                       |   | (Single Shared Gateway)   |
| - Dynamic Checkbox Matrix + "Select All" / "Deselect All"   |   +-------------+-------------+
| - Real-time Search & Category Quick Filters                 |                 |
| - Start / Stop Buttons with Loading State                   |                 v
| - Auto-refreshing Status Table (3s / 5s Polling)            |   +---------------------------+
| - Telemetry Ribbon (DB Count, Cycle Count, Uptime)          |   | SQLite (candles_s1 WAL)   |
+-------------------------------------------------------------+   +---------------------------+
```

### 2.1 Backend Route Design (`src/strat_trade/api/routes/collector.py`)
To align with the project's existing architecture (`src/strat_trade/api/routes/*`):
- Place the core router in `src/strat_trade/api/routes/collector.py`.
- Also provide a clean proxy / re-export in `src/strat_trade/web/routes/collector.py` so that imports from either namespace resolve correctly.
- Register `collector_router` in `src/strat_trade/main.py`:
  ```python
  from strat_trade.api.routes.collector import router as collector_router
  app.include_router(collector_router, prefix="/api/v1")
  ```

#### Pydantic Schemas (`src/strat_trade/api/schemas.py` or `src/strat_trade/api/routes/collector.py`)
```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class CollectorAssetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(description="Broker asset identifier (e.g. EURUSD_otc).")
    name: str = Field(description="Human-readable asset name (e.g. EUR/USD OTC).")
    payout: int = Field(default=80, description="Current payout percentage.")
    is_otc: bool = Field(default=True, description="True for OTC assets.")
    asset_type: str = Field(default="currency", description="Asset category.")

class CollectorAssetStatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset: str
    name: str | None = None
    count: int = Field(description="Total candles saved for this asset.")
    first_timestamp: float | None = None
    last_timestamp: float | None = None
    first_time: datetime | None = None
    last_time: datetime | None = None
    payout: int = 80
    is_otc: bool = True
    is_collecting: bool = False

class CollectorStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["IDLE", "RUNNING", "STOPPED"] = Field(description="Collector operational status.")
    is_running: bool
    started_at: datetime | None = None
    active_assets: list[str] = Field(default_factory=list)
    timeframe_seconds: int = 1
    candles_count: int = 300
    interval_seconds: float = 60.0
    throttle_delay: float = 0.5
    cycles_completed: int = 0
    total_candles_saved: int = 0
    last_cycle_at: datetime | None = None
    asset_stats: list[CollectorAssetStatResponse] = Field(default_factory=list)
    total_database_candles: int = 0

class StartCollectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assets: list[str] = Field(min_length=1, description="List of asset symbols to collect.")
    timeframe_seconds: int = Field(default=1, ge=1, description="Candle timeframe in seconds (default 1 for S1).")
    candles_count: int = Field(default=300, ge=1, le=5000, description="Number of candles per query batch.")
    interval_seconds: float = Field(default=60.0, ge=1.0, description="Sleep interval between cycles.")
    throttle_delay: float = Field(default=0.5, ge=0.0, le=10.0, description="Sleep delay between individual asset queries.")
```

#### Route Handlers Specification
```python
router = APIRouter(prefix="/collector", tags=["Market Data Collector"])

@router.get("/available-assets", response_model=list[CollectorAssetResponse], summary="List available broker assets")
async def get_available_assets(gateway: TradingGatewayDep) -> list[CollectorAssetResponse]:
    """Fetches live active assets from Pocket Option via shared gateway."""

@router.get("/status", response_model=CollectorStatusResponse, summary="Get data collector status")
def get_collector_status() -> CollectorStatusResponse:
    """Returns runtime state, cycle stats, and per-asset database row counts."""

@router.post("/start", response_model=CollectorStatusResponse, summary="Start background S1 collection loop")
async def start_collector(req: StartCollectorRequest, gateway: TradingGatewayDep) -> CollectorStatusResponse:
    """Launches the S1 collector loop as an asyncio background task inside FastAPI."""

@router.post("/stop", response_model=CollectorStatusResponse, summary="Stop background S1 collection loop")
async def stop_collector() -> CollectorStatusResponse:
    """Gracefully cancels the background collector task."""
```

### 2.2 Thread-Safe Background Execution Engine (`src/strat_trade/use_cases/manage_collector.py`)
```python
class AsyncCollectorEngine:
    """Singleton service managing the lifecycle of the FastAPI background collector task."""
    def __init__(self, store: MarketDataStore | None = None) -> None:
        self.store = store or MarketDataStore()
        self.status: Literal["IDLE", "RUNNING", "STOPPED"] = "IDLE"
        self.started_at: datetime | None = None
        self.active_assets: list[str] = []
        self.timeframe_seconds: int = 1
        self.candles_count: int = 300
        self.interval_seconds: float = 60.0
        self.throttle_delay: float = 0.5
        self.cycles_completed: int = 0
        self.total_candles_saved: int = 0
        self.last_cycle_at: datetime | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._gateway: Any = None

    async def start(self, gateway: Any, assets: list[str], timeframe: int = 1, count: int = 300, interval: float = 60.0, throttle: float = 0.5) -> CollectorStatusResponse:
        async with self._lock:
            if self.status == "RUNNING":
                return self.get_status()
            self._gateway = gateway
            self.active_assets = list(dict.fromkeys(assets))
            self.timeframe_seconds = timeframe
            self.candles_count = count
            self.interval_seconds = interval
            self.throttle_delay = throttle
            self.started_at = datetime.now(UTC)
            self.status = "RUNNING"
            self._task = asyncio.create_task(self._run_loop())
            return self.get_status()

    async def stop(self) -> CollectorStatusResponse:
        async with self._lock:
            if self.status != "RUNNING":
                return self.get_status()
            self.status = "STOPPED"
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None
            return self.get_status()
```
**Safety & Concurrency Guarantees**:
1. **Single WebSocket Session**: Reuses `gateway = request.app.state.trading_gateway` without instantiating extra `PocketOptionTradingGateway` objects, preventing socket churn and broker connection limits.
2. **Graceful Cancellation**: Uses `try ... await asyncio.sleep(...) except asyncio.CancelledError:` so the task exits immediately on `/stop` without leaving orphan coroutines or throwing unhandled exceptions to the event loop.
3. **Transient Fault Tolerance**: Individual asset fetch errors (`BrokerUnavailableError`, `TimeoutError`, `InvalidMarketParametersError`, `ConnectionError`, `OSError`) are caught and logged per asset; remaining assets and subsequent cycles continue unimpeded.

---

## 3. Frontend UI Design & Markup Blueprint (`src/strat_trade/web/templates/index.html`)

### 3.1 Navigation Header Integration
Add the new tab button into the existing tab list:
```html
<button onclick="switchTab('collector')" id="tabBtnCollector" class="tab-btn px-4 py-2.5 border-b-2 border-transparent text-gray-400 hover:text-gray-200 font-semibold text-sm flex items-center gap-2 whitespace-nowrap">
  <i data-lucide="database" class="w-4 h-4 text-brand-400"></i> Збір S1 Даних
  <span id="collectorNavBadge" class="px-1.5 py-0.2 rounded bg-gray-800 text-gray-400 text-[10px] font-bold">IDLE</span>
</button>
```

### 3.2 Main Content Markup (`#tabCollector`)
```html
<!-- ========================================================================= -->
<!-- TAB: S1 MARKET DATA COLLECTOR                                             -->
<!-- ========================================================================= -->
<div id="tabCollector" class="hidden space-y-6">

  <!-- Live Status & Action Header Ribbon -->
  <div id="collectorStatusBar" class="glass-card rounded-2xl p-4 border border-gray-800 bg-surface-900/60 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
    <div class="flex items-center space-x-3">
      <div id="collectorStatusPulse" class="w-3.5 h-3.5 rounded-full bg-gray-500"></div>
      <div>
        <div class="flex items-center gap-2">
          <h2 id="collectorStatusTitle" class="text-sm font-bold text-gray-200">Збір S1 даних готовий до запуску</h2>
          <span id="collectorStatusBadge" class="text-[10px] font-bold px-2 py-0.5 rounded bg-gray-800 text-gray-400 border border-gray-700">IDLE</span>
        </div>
        <p id="collectorStatusSubtitle" class="text-xs text-gray-400">Оберіть активи та запустіть фоновий збір 1-секундних свічок у локальну SQLite базу</p>
      </div>
    </div>

    <div class="flex items-center gap-2 self-end sm:self-auto">
      <button type="button" onclick="fetchCollectorStatus()" class="px-3 py-1.5 rounded-xl bg-surface-800 hover:bg-surface-700 text-gray-300 font-semibold text-xs border border-gray-700 transition flex items-center gap-1.5">
        <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i> Оновити
      </button>
      <button type="button" id="btnStartCollector" onclick="startDataCollector()" class="px-4 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-lg shadow-emerald-600/30 transition flex items-center gap-1.5">
        <i data-lucide="play" class="w-3.5 h-3.5"></i> Запустити збір
      </button>
      <button type="button" id="btnStopCollector" onclick="stopDataCollector()" class="hidden px-4 py-1.5 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs shadow-lg shadow-rose-600/30 transition flex items-center gap-1.5">
        <i data-lucide="square" class="w-3.5 h-3.5"></i> Зупинити збір
      </button>
    </div>
  </div>

  <!-- Telemetry Ribbon -->
  <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
    <div class="glass-card rounded-xl p-3.5 border-l-4 border-cyan-500">
      <div class="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Всього свічок у базі</div>
      <div id="collectorMetricTotalDb" class="text-lg font-bold text-cyan-400 tabular-nums">0</div>
      <div class="text-[11px] text-gray-400">Таблиця candles_s1 (SQLite)</div>
    </div>

    <div class="glass-card rounded-xl p-3.5 border-l-4 border-emerald-500">
      <div class="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Активних активів у зборі</div>
      <div id="collectorMetricActiveAssets" class="text-lg font-bold text-emerald-400 tabular-nums">0</div>
      <div id="collectorMetricActiveSub" class="text-[11px] text-gray-400">0 обрано для моніторингу</div>
    </div>

    <div class="glass-card rounded-xl p-3.5 border-l-4 border-purple-500">
      <div class="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Пройдено циклів збору</div>
      <div id="collectorMetricCycles" class="text-lg font-bold text-purple-400 tabular-nums">0</div>
      <div id="collectorMetricSavedThisSession" class="text-[11px] text-gray-400">+0 свічок за поточну сесію</div>
    </div>

    <div class="glass-card rounded-xl p-3.5 border-l-4 border-amber-500">
      <div class="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Останній цикл / Uptime</div>
      <div id="collectorMetricLastCycle" class="text-sm font-bold text-gray-200 tabular-nums">Очікування...</div>
      <div id="collectorMetricIntervalSub" class="text-[11px] text-gray-400">Інтервал: 60с (пауза 0.5с)</div>
    </div>
  </div>

  <!-- Main 2-Column Grid -->
  <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">

    <!-- Left Column: Asset Selector & Configuration Dock (5 cols) -->
    <div class="lg:col-span-5 glass-card rounded-2xl p-5 space-y-4">
      <div class="flex items-center justify-between border-b border-gray-800 pb-3">
        <div>
          <h2 class="text-sm font-bold text-gray-200 uppercase tracking-wider flex items-center gap-2">
            <i data-lucide="check-square" class="w-4 h-4 text-brand-400"></i> Вибір активів для збору
          </h2>
          <p class="text-[11px] text-gray-400">Виберіть активи або скористайтесь швидкими фільтрами</p>
        </div>
        <span id="collectorAssetSelectedBadge" class="text-xs text-brand-400 font-semibold px-2 py-0.5 rounded bg-brand-500/10 border border-brand-500/20">
          0 обрано
        </span>
      </div>

      <!-- Quick Action Filter Buttons -->
      <div class="flex flex-wrap gap-1.5">
        <button type="button" onclick="selectAllCollectorAssets()" class="text-[10px] px-2 py-1 rounded bg-brand-500/20 hover:bg-brand-500/30 text-brand-300 border border-brand-500/30 transition">
          ✓ Обрати всі
        </button>
        <button type="button" onclick="deselectAllCollectorAssets()" class="text-[10px] px-2 py-1 rounded bg-surface-800 hover:bg-surface-700 text-gray-400 border border-gray-700 transition">
          ✕ Зняти всі
        </button>
        <button type="button" onclick="selectCollectorTopNAssets(5)" class="text-[10px] px-2 py-1 rounded bg-surface-800 hover:bg-surface-700 text-cyan-400 border border-cyan-500/30 transition">
          ⚡ Топ-5 Payout
        </button>
        <button type="button" onclick="selectCollectorOtcAssets()" class="text-[10px] px-2 py-1 rounded bg-surface-800 hover:bg-surface-700 text-emerald-400 border border-emerald-500/30 transition">
          🟢 Усі OTC
        </button>
        <button type="button" onclick="selectCollectorForexAssets()" class="text-[10px] px-2 py-1 rounded bg-surface-800 hover:bg-surface-700 text-purple-400 border border-purple-500/30 transition">
          💱 Валюти
        </button>
      </div>

      <!-- Search Input -->
      <div class="relative">
        <div class="absolute inset-y-0 left-0 pl-2.5 flex items-center pointer-events-none text-gray-400">
          <i data-lucide="search" class="w-3.5 h-3.5"></i>
        </div>
        <input type="text" id="collectorAssetSearchInput" oninput="filterCollectorAssetsList()" placeholder="🔍 Пошук активу (EUR, OTC, Crypto, Gold)..." class="w-full pl-8 pr-7 py-1.5 glass-input text-xs rounded-lg border-gray-700 bg-surface-900/90 text-gray-200 placeholder-gray-500 focus:border-brand-500 transition" />
        <button type="button" onclick="clearCollectorAssetSearch()" id="btnClearCollectorAssetSearch" class="hidden absolute inset-y-0 right-0 pr-2.5 flex items-center text-gray-500 hover:text-gray-300 transition">
          <i data-lucide="x" class="w-3.5 h-3.5"></i>
        </button>
      </div>

      <!-- Checkbox Assets List Container -->
      <div id="collectorAssetsContainer" class="max-h-64 overflow-y-auto p-2 rounded-xl bg-surface-900/90 border border-gray-800 space-y-1">
        <div class="text-center py-6 text-xs text-gray-500">Завантаження доступних активів брокера...</div>
      </div>

      <!-- Advanced Collector Settings (Collapsible) -->
      <details class="group rounded-xl border border-gray-800 bg-surface-900/40 p-3">
        <summary class="flex items-center justify-between text-xs font-semibold text-gray-300 cursor-pointer select-none">
          <span class="flex items-center gap-1.5"><i data-lucide="sliders" class="w-3.5 h-3.5 text-gray-400"></i> Параметри збору (Таймфрейм, Інтервал, Троттлінг)</span>
          <i data-lucide="chevron-down" class="w-3.5 h-3.5 text-gray-400 group-open:rotate-180 transition-transform"></i>
        </summary>
        <div class="grid grid-cols-2 gap-3 mt-3 pt-2 border-t border-gray-800/60">
          <div>
            <label class="text-[11px] text-gray-400 block mb-1">Таймфрейм (секунди)</label>
            <input type="number" id="collectorCfgTimeframe" value="1" min="1" step="1" class="w-full glass-input text-xs rounded-lg px-2.5 py-1.5" />
          </div>
          <div>
            <label class="text-[11px] text-gray-400 block mb-1">Свічок за запит (count)</label>
            <input type="number" id="collectorCfgCount" value="300" min="50" max="1000" step="50" class="w-full glass-input text-xs rounded-lg px-2.5 py-1.5" />
          </div>
          <div>
            <label class="text-[11px] text-gray-400 block mb-1">Інтервал циклу (сек)</label>
            <input type="number" id="collectorCfgInterval" value="60" min="5" step="5" class="w-full glass-input text-xs rounded-lg px-2.5 py-1.5" />
          </div>
          <div>
            <label class="text-[11px] text-gray-400 block mb-1">Затримка між активами (сек)</label>
            <input type="number" id="collectorCfgThrottle" value="0.5" min="0.1" max="5.0" step="0.1" class="w-full glass-input text-xs rounded-lg px-2.5 py-1.5" />
          </div>
        </div>
      </details>
    </div>

    <!-- Right Column: Status Table & Database Records (7 cols) -->
    <div class="lg:col-span-7 glass-card rounded-2xl p-5 space-y-4">
      <div class="flex items-center justify-between border-b border-gray-800 pb-3">
        <div>
          <h3 class="text-xs font-bold text-gray-200 uppercase tracking-wider flex items-center gap-1.5">
            <i data-lucide="table" class="w-4 h-4 text-cyan-400"></i> Статус збору за активами & Збережені дані
          </h3>
          <p class="text-[11px] text-gray-400">Реальний стан записів у базі SQLite (автооновлення кожні 3с)</p>
        </div>
        <div class="flex items-center gap-2">
          <select id="collectorAutoRefreshInterval" onchange="updateCollectorRefreshTimer()" class="glass-input text-[11px] rounded-lg px-2 py-1 border-gray-700 bg-surface-900 text-gray-300">
            <option value="3000" selected>Автооновлення: 3с</option>
            <option value="5000">Автооновлення: 5с</option>
            <option value="10000">Автооновлення: 10с</option>
            <option value="0">Вимкнено</option>
          </select>
        </div>
      </div>

      <div class="overflow-x-auto max-h-[420px]">
        <table class="w-full text-left text-xs text-gray-300">
          <thead class="bg-surface-800/80 text-[10px] uppercase tracking-wider text-gray-400 sticky top-0">
            <tr>
              <th class="px-3 py-2">Актив</th>
              <th class="px-3 py-2">Тип</th>
              <th class="px-3 py-2">Статус</th>
              <th class="px-3 py-2 text-right">Збережено свічок</th>
              <th class="px-3 py-2">Перша свічка (UTC)</th>
              <th class="px-3 py-2">Остання свічка (UTC)</th>
            </tr>
          </thead>
          <tbody id="collectorTableBody" class="divide-y divide-gray-800/60 font-mono">
            <tr>
              <td colspan="6" class="text-center py-8 text-gray-500">Завантаження статусу бази даних...</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

  </div>

</div>
```

---

## 4. Client-Side JavaScript Logic (`index.html`)

### 4.1 Global Variables & State
```javascript
let collectorPollingInterval = null;
let globalCollectorAssetsList = [];
let currentCollectorStatus = null;
```

### 4.2 Tab Switching & Initialization Hooks
Update `switchTab(tabId)` in `index.html`:
```javascript
function switchTab(tabId) {
  document.getElementById('tabLiveBot').classList.toggle('hidden', tabId !== 'liveBot');
  document.getElementById('tabAudit').classList.toggle('hidden', tabId !== 'audit');
  document.getElementById('tabCollector').classList.toggle('hidden', tabId !== 'collector');
  document.getElementById('tabPortfolio').classList.toggle('hidden', tabId !== 'portfolio');
  document.getElementById('tabSingle').classList.toggle('hidden', tabId !== 'single');
  document.getElementById('tabOptimizer').classList.toggle('hidden', tabId !== 'optimizer');
  document.getElementById('tabApiTester').classList.toggle('hidden', tabId !== 'apiTester');

  const btnL = document.getElementById('tabBtnLiveBot');
  const btnAud = document.getElementById('tabBtnAudit');
  const btnCol = document.getElementById('tabBtnCollector');
  const btnP = document.getElementById('tabBtnPortfolio');
  const btnS = document.getElementById('tabBtnSingle');
  const btnO = document.getElementById('tabBtnOptimizer');
  const btnA = document.getElementById('tabBtnApi');

  const activeClass = 'tab-btn px-4 py-2.5 border-b-2 border-brand-500 text-brand-400 font-bold text-sm flex items-center gap-2 whitespace-nowrap';
  const inactiveClass = 'tab-btn px-4 py-2.5 border-b-2 border-transparent text-gray-400 hover:text-gray-200 font-semibold text-sm flex items-center gap-2 whitespace-nowrap';

  btnL.className = tabId === 'liveBot' ? activeClass.replace('border-brand-500 text-brand-400', 'border-emerald-500 text-emerald-400') : inactiveClass;
  btnAud.className = tabId === 'audit' ? activeClass.replace('border-brand-500 text-brand-400', 'border-cyan-500 text-cyan-400') : inactiveClass;
  btnCol.className = tabId === 'collector' ? activeClass : inactiveClass;
  btnP.className = tabId === 'portfolio' ? activeClass : inactiveClass;
  btnS.className = tabId === 'single' ? activeClass : inactiveClass;
  btnO.className = tabId === 'optimizer' ? activeClass : inactiveClass;
  btnA.className = tabId === 'apiTester' ? activeClass : inactiveClass;

  setTimeout(() => {
    if (tabId === 'collector') {
      loadCollectorAvailableAssets();
      fetchCollectorStatus();
      startCollectorPolling();
    } else if (tabId === 'liveBot') {
      fetchLiveBotStatus();
    } else if (tabId === 'audit') {
      loadInternalTradesAudit();
    }
  }, 60);
}
```

### 4.3 Asset Checkbox Population & Quick Filtering Functions
```javascript
async function loadCollectorAvailableAssets() {
  const container = document.getElementById('collectorAssetsContainer');
  if (globalCollectorAssetsList.length > 0) return; // Cached

  try {
    const res = await fetch('/api/v1/collector/available-assets');
    if (!res.ok) throw new Error('Failed to load available assets');
    let assets = await res.json();
    if (!assets || assets.length === 0) {
      container.innerHTML = '<div class="text-center py-4 text-xs text-gray-500">Немає доступних активів</div>';
      return;
    }

    assets.sort((a, b) => b.payout - a.payout || a.name.localeCompare(b.name));
    globalCollectorAssetsList = assets;
    renderCollectorAssetCheckboxes(assets);
  } catch (err) {
    console.warn('Error loading collector assets:', err);
    container.innerHTML = '<div class="text-center py-4 text-xs text-rose-400">Помилка завантаження активів</div>';
  }
}

function renderCollectorAssetCheckboxes(assets) {
  const container = document.getElementById('collectorAssetsContainer');
  container.innerHTML = '';

  assets.forEach((a, idx) => {
    const isSelected = idx < 5; // Default select top 5
    const row = document.createElement('label');
    row.className = 'collector-asset-item flex items-center justify-between p-1.5 rounded-lg hover:bg-surface-800/80 cursor-pointer text-xs transition';
    row.dataset.symbol = a.symbol.toLowerCase();
    row.dataset.name = a.name.toLowerCase();
    row.dataset.type = (a.asset_type || 'currency').toLowerCase();
    row.dataset.isOtc = a.is_otc ? 'true' : 'false';

    row.innerHTML = `
      <div class="flex items-center gap-2">
        <input type="checkbox" name="collectorAsset" value="${a.symbol}" data-payout="${a.payout}" data-asset-type="${a.asset_type || 'currency'}" data-is-otc="${a.is_otc ? 'true' : 'false'}" class="collector-checkbox w-3.5 h-3.5 text-brand-500 rounded bg-gray-900 border-gray-700 focus:ring-brand-500" ${isSelected ? 'checked' : ''} onchange="updateCollectorSelectedCount()" />
        <span class="font-medium text-gray-200">${a.name}</span>
      </div>
      <div class="flex items-center gap-1.5">
        <span class="px-1.5 py-0.5 rounded text-[9px] font-bold ${a.is_otc ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30' : 'bg-gray-800 text-gray-400'}">
          ${a.is_otc ? 'OTC' : 'Spot'}
        </span>
        <span class="px-1.5 py-0.5 rounded text-[10px] font-bold ${a.payout >= 90 ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-cyan-500/20 text-cyan-400'}">
          ${a.payout}%
        </span>
      </div>
    `;
    container.appendChild(row);
  });

  updateCollectorSelectedCount();
  lucide.createIcons();
}

function updateCollectorSelectedCount() {
  const checked = document.querySelectorAll('.collector-checkbox:checked');
  const badge = document.getElementById('collectorAssetSelectedBadge');
  if (badge) badge.textContent = `${checked.length} обрано`;
}

function selectAllCollectorAssets() {
  document.querySelectorAll('.collector-checkbox').forEach(cb => cb.checked = true);
  updateCollectorSelectedCount();
}

function deselectAllCollectorAssets() {
  document.querySelectorAll('.collector-checkbox').forEach(cb => cb.checked = false);
  updateCollectorSelectedCount();
}

function selectCollectorTopNAssets(n) {
  document.querySelectorAll('.collector-checkbox').forEach((cb, idx) => {
    cb.checked = idx < n;
  });
  updateCollectorSelectedCount();
}

function selectCollectorOtcAssets() {
  document.querySelectorAll('.collector-checkbox').forEach(cb => {
    cb.checked = cb.dataset.isOtc === 'true' || cb.value.toLowerCase().includes('otc');
  });
  updateCollectorSelectedCount();
}

function selectCollectorForexAssets() {
  document.querySelectorAll('.collector-checkbox').forEach(cb => {
    cb.checked = cb.dataset.assetType === 'currency';
  });
  updateCollectorSelectedCount();
}

function filterCollectorAssetsList() {
  const query = document.getElementById('collectorAssetSearchInput').value.trim().toLowerCase();
  const clearBtn = document.getElementById('btnClearCollectorAssetSearch');
  clearBtn.classList.toggle('hidden', !query);

  document.querySelectorAll('.collector-asset-item').forEach(item => {
    const sym = item.dataset.symbol || '';
    const name = item.dataset.name || '';
    const type = item.dataset.type || '';
    const match = !query || sym.includes(query) || name.includes(query) || type.includes(query);
    item.style.display = match ? 'flex' : 'none';
  });
}

function clearCollectorAssetSearch() {
  document.getElementById('collectorAssetSearchInput').value = '';
  filterCollectorAssetsList();
}
```

### 4.4 Start, Stop & Status Polling Handlers
```javascript
async function startDataCollector() {
  const checked = Array.from(document.querySelectorAll('.collector-checkbox:checked')).map(cb => cb.value);
  if (checked.length === 0) {
    alert('Будь ласка, оберіть хоча б один актив для збору.');
    return;
  }

  const timeframe = parseInt(document.getElementById('collectorCfgTimeframe').value) || 1;
  const count = parseInt(document.getElementById('collectorCfgCount').value) || 300;
  const interval = parseFloat(document.getElementById('collectorCfgInterval').value) || 60.0;
  const throttle = parseFloat(document.getElementById('collectorCfgThrottle').value) || 0.5;

  const btn = document.getElementById('btnStartCollector');
  btn.disabled = true;
  btn.innerHTML = `<span class="animate-spin mr-2">&#9696;</span> Запуск...`;

  try {
    const res = await fetch('/api/v1/collector/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        assets: checked,
        timeframe_seconds: timeframe,
        candles_count: count,
        interval_seconds: interval,
        throttle_delay: throttle
      })
    });
    const data = await res.json();
    if (!res.ok) {
      const msg = data.error ? data.error.message : (data.detail || 'Помилка старту збору');
      throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
    renderCollectorStatus(data);
    startCollectorPolling();
  } catch (err) {
    alert(`Помилка старту: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="play" class="w-3.5 h-3.5"></i> Запустити збір`;
    lucide.createIcons();
  }
}

async function stopDataCollector() {
  const btn = document.getElementById('btnStopCollector');
  btn.disabled = true;
  btn.innerHTML = `<span class="animate-spin mr-2">&#9696;</span> Зупинка...`;

  try {
    const res = await fetch('/api/v1/collector/stop', { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      renderCollectorStatus(data);
    }
  } catch (err) {
    console.warn('Error stopping collector:', err);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="square" class="w-3.5 h-3.5"></i> Зупинити збір`;
    lucide.createIcons();
  }
}

async function fetchCollectorStatus() {
  try {
    const res = await fetch('/api/v1/collector/status');
    if (!res.ok) return;
    const data = await res.json();
    renderCollectorStatus(data);
  } catch (err) {
    console.warn('Error fetching collector status:', err);
  }
}

function startCollectorPolling() {
  if (collectorPollingInterval) clearInterval(collectorPollingInterval);
  const sel = document.getElementById('collectorAutoRefreshInterval');
  const ms = sel ? parseInt(sel.value) : 3000;
  if (ms > 0) {
    collectorPollingInterval = setInterval(fetchCollectorStatus, ms);
  }
}

function updateCollectorRefreshTimer() {
  startCollectorPolling();
}

function renderCollectorStatus(data) {
  currentCollectorStatus = data;
  const isRunning = data.status === 'RUNNING' || data.is_running;

  // 1. Status ribbon & Header elements
  const pulse = document.getElementById('collectorStatusPulse');
  const badge = document.getElementById('collectorStatusBadge');
  const navBadge = document.getElementById('collectorNavBadge');
  const title = document.getElementById('collectorStatusTitle');
  const sub = document.getElementById('collectorStatusSubtitle');
  const btnStart = document.getElementById('btnStartCollector');
  const btnStop = document.getElementById('btnStopCollector');

  if (isRunning) {
    pulse.className = 'w-3.5 h-3.5 rounded-full bg-emerald-400 animate-pulse';
    badge.textContent = 'RUNNING';
    badge.className = 'text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30';
    if (navBadge) {
      navBadge.textContent = 'LIVE';
      navBadge.className = 'px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-400 text-[10px] font-bold animate-pulse';
    }
    title.textContent = `Збір даних активний (${data.active_assets.length} активів)`;
    sub.textContent = `Фоновий процес збирає S${data.timeframe_seconds} свічки кожні ${data.interval_seconds}с.`;
    btnStart.classList.add('hidden');
    btnStop.classList.remove('hidden');
  } else {
    pulse.className = 'w-3.5 h-3.5 rounded-full bg-gray-500';
    badge.textContent = data.status || 'IDLE';
    badge.className = 'text-[10px] font-bold px-2 py-0.5 rounded bg-gray-800 text-gray-400 border border-gray-700';
    if (navBadge) {
      navBadge.textContent = data.status || 'IDLE';
      navBadge.className = 'px-1.5 py-0.2 rounded bg-gray-800 text-gray-400 text-[10px] font-bold';
    }
    title.textContent = 'Збір S1 даних готовий до запуску';
    sub.textContent = 'Оберіть активи та натисніть "Запустити збір" для початку збереження в базу.';
    btnStart.classList.remove('hidden');
    btnStop.classList.add('hidden');
  }

  // 2. Telemetry Ribbon metrics
  document.getElementById('collectorMetricTotalDb').textContent = Number(data.total_database_candles || 0).toLocaleString();
  document.getElementById('collectorMetricActiveAssets').textContent = data.active_assets.length;
  document.getElementById('collectorMetricActiveSub').textContent = `${data.active_assets.length} у списку збору`;
  document.getElementById('collectorMetricCycles').textContent = data.cycles_completed || 0;
  document.getElementById('collectorMetricSavedThisSession').textContent = `+${Number(data.total_candles_saved || 0).toLocaleString()} свічок за сесію`;

  if (data.last_cycle_at) {
    const d = new Date(data.last_cycle_at);
    document.getElementById('collectorMetricLastCycle').textContent = d.toLocaleTimeString();
  } else if (isRunning) {
    document.getElementById('collectorMetricLastCycle').textContent = 'Виконується...';
  } else {
    document.getElementById('collectorMetricLastCycle').textContent = 'Очікування...';
  }
  document.getElementById('collectorMetricIntervalSub').textContent = `Інтервал: ${data.interval_seconds}с (пауза ${data.throttle_delay}с)`;

  // 3. Render Status Table
  const tbody = document.getElementById('collectorTableBody');
  if (!data.asset_stats || data.asset_stats.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-gray-500">Немає збережених даних. Запустіть збір для початку збереження.</td></tr>`;
    return;
  }

  tbody.innerHTML = '';
  data.asset_stats.forEach(stat => {
    const isAct = stat.is_collecting || (data.active_assets && data.active_assets.includes(stat.asset));
    const firstStr = stat.first_time ? new Date(stat.first_time).toISOString().replace('T', ' ').slice(0, 19) : '—';
    const lastStr = stat.last_time ? new Date(stat.last_time).toISOString().replace('T', ' ').slice(0, 19) : '—';

    const tr = document.createElement('tr');
    tr.className = 'hover:bg-surface-800/50 transition';
    tr.innerHTML = `
      <td class="px-3 py-2 font-semibold text-gray-200">
        ${stat.name || stat.asset}
        <span class="text-[10px] text-gray-500 block font-normal">${stat.asset}</span>
      </td>
      <td class="px-3 py-2">
        <span class="px-1.5 py-0.5 rounded text-[9px] font-bold ${stat.is_otc ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30' : 'bg-gray-800 text-gray-400'}">
          ${stat.is_otc ? 'OTC' : 'Spot'}
        </span>
      </td>
      <td class="px-3 py-2">
        ${isAct && isRunning ?
          '<span class="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-400"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping"></span> Збір</span>' :
          '<span class="text-[10px] text-gray-500">Очікування</span>'}
      </td>
      <td class="px-3 py-2 text-right font-bold text-cyan-400 tabular-nums">
        ${Number(stat.count || 0).toLocaleString()}
      </td>
      <td class="px-3 py-2 text-[11px] text-gray-400 tabular-nums">${firstStr}</td>
      <td class="px-3 py-2 text-[11px] text-gray-300 tabular-nums">${lastStr}</td>
    `;
    tbody.appendChild(tr);
  });
}
```

---

## 5. Caveats

1. **Broker Connection Resilience**: When Pocket Option is offline or the demo session token requires refresh, `gateway.get_assets()` falls back to the curated fallback assets list (`_CURATED_ASSETS`). The collector background loop gracefully handles broker disconnects without interrupting server uptime.
2. **SQLite Database Lock Concurrency**: SQLite with WAL mode (`PRAGMA journal_mode=WAL`) allows concurrent reader connections (e.g. backtesting engine queries) while the collector process executes write transactions. The collector utilizes batch inserts with `INSERT OR IGNORE` to prevent table fragmentation and redundant row storage.
3. **No Code Written to Source Files (Read-Only Mode)**: In compliance with the explorer role constraints, all code snippets, schemas, and template markup are presented in this report for implementation by the builder/implementer agents.

---

## 6. Conclusion & Recommendations for Implementation

### Summary of Implementation Actions
1. **Pydantic Schemas**: Add `CollectorAssetResponse`, `CollectorAssetStatResponse`, `CollectorStatusResponse`, and `StartCollectorRequest` to `src/strat_trade/api/schemas.py`.
2. **Service Layer**: Implement `AsyncCollectorEngine` singleton in `src/strat_trade/use_cases/manage_collector.py`.
3. **API Routes**: Create `src/strat_trade/api/routes/collector.py` (and re-export in `src/strat_trade/web/routes/collector.py`) and include it in `src/strat_trade/main.py`.
4. **UI Template**: Inject the Data Collection tab button and markup into `src/strat_trade/web/templates/index.html` along with the JavaScript functions.
5. **Testing**: Add API integration test suite `tests/test_collector_api.py` validating `/available-assets`, `/status`, `/start`, and `/stop`.

---

## 7. Verification Method

To verify the completed implementation independently:

1. **FastAPI Route Unit & Integration Tests**:
   ```bash
   .venv/bin/pytest tests/test_collector_api.py -v
   ```
2. **Full Regression Suite**:
   ```bash
   .venv/bin/pytest tests/test_collect_s1_data.py tests/test_market_data_store.py tests/test_bot_and_audit_api.py -v
   ```
3. **Web Dashboard Health Check & UI Smoke Test**:
   ```bash
   curl -s http://127.0.0.1:8000/api/v1/collector/status | jq .
   curl -s http://127.0.0.1:8000/api/v1/collector/available-assets | jq '.[0:3]'
   ```
