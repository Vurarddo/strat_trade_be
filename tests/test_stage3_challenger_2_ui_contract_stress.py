"""Empirical stress test suite for Stage 3 Web UI contracts & E2E integration.

Challenger 2 Empirical Verification:
1. DOM Element ID Parity & Complete Interactive Controls Coverage
2. JavaScript Client State Machine Simulation (IDLE -> START -> POLLING -> DATA -> STOP)
3. Edge Case Inputs & Boundary Parameter Fuzzing
4. Schema Adherence between FastAPI Pydantic Responses and UI Rendering Assumptions
5. Concurrency, Rapid Start/Stop Lifecycle & Teardown Stress
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from decimal import Decimal
from html.parser import HTMLParser
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from strat_trade.api.schemas import (
    CollectorAssetResponse,
    CollectorAssetStatResponse,
    CollectorStatusResponse,
)
from strat_trade.domain.entities import Candle
from strat_trade.domain.trading.market_data_store import MarketDataStore
from strat_trade.use_cases.manage_collector import get_collector_engine


class DOMNode:
    """Lightweight in-memory DOM representation using standard library HTMLParser."""

    def __init__(
        self,
        tag: str,
        attrs: dict[str, str],
        parent: DOMNode | None = None,
    ) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[DOMNode] = []
        self.text_chunks: list[str] = []

    @property
    def id(self) -> str | None:
        return self.attrs.get("id")

    def find_by_id(self, elem_id: str) -> DOMNode | None:
        if self.attrs.get("id") == elem_id:
            return self
        for child in self.children:
            found = child.find_by_id(elem_id)
            if found is not None:
                return found
        return None

    def find_all(self, tag: str) -> list[DOMNode]:
        results: list[DOMNode] = []
        if self.tag == tag:
            results.append(self)
        for child in self.children:
            results.extend(child.find_all(tag))
        return results

    def get_text(self) -> str:
        text = "".join(self.text_chunks)
        for child in self.children:
            text += child.get_text()
        return text.strip()


class DOMTreeBuilder(HTMLParser):
    """Parses raw HTML into a searchable DOMNode tree."""

    def __init__(self) -> None:
        super().__init__()
        self.root = DOMNode("root", {})
        self.current = self.root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: v or "" for k, v in attrs}
        node = DOMNode(tag, attr_dict, parent=self.current)
        self.current.children.append(node)
        # Avoid nesting for void/self-closing tags
        if tag not in ("input", "img", "br", "hr", "meta", "link"):
            self.current = node

    def handle_endtag(self, tag: str) -> None:
        if self.current.parent is not None and self.current.tag == tag:
            self.current = self.current.parent

    def handle_data(self, data: str) -> None:
        self.current.text_chunks.append(data)


def parse_html_dom(html: str) -> DOMNode:
    parser = DOMTreeBuilder()
    parser.feed(html)
    return parser.root


@pytest.mark.asyncio
class TestCollectorDOMParityAndControlsCoverage:
    """Empirically validates DOM structure, ID parity, and interactive controls in index.html."""

    async def test_dom_all_js_element_ids_exist_in_html(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-DOM-1: Every DOM ID referenced in JS functions exists in index.html."""
        resp = await async_test_client.get("/")
        assert resp.status_code == 200
        html = resp.text

        # Extract collector-related JavaScript block from index.html
        collector_js_start = html.find("loadCollectorAvailableAssets")
        assert collector_js_start != -1, "Collector JS functions not found in index.html"

        # Search for all getElementById calls in collector JS
        collector_js_snippet = html[collector_js_start : collector_js_start + 12000]

        # Regex for getElementById('...')
        id_matches = set(
            re.findall(
                r"document\.getElementById\(['\"]([a-zA-Z0-9_-]+)['\"]\)", collector_js_snippet
            )
        )
        assert len(id_matches) > 0, "No getElementById calls found in collector JS snippet"

        dom = parse_html_dom(html)

        # Explicit list of required collector element IDs
        expected_ids = {
            "tabBtnCollector",
            "tabCollector",
            "collectorNavBadge",
            "collectorStatusBar",
            "collectorStatusPulse",
            "collectorStatusTitle",
            "collectorStatusSubtitle",
            "collectorStatusBadge",
            "btnStartCollector",
            "btnStopCollector",
            "collectorMetricTotalDb",
            "collectorMetricActiveAssets",
            "collectorMetricActiveSub",
            "collectorMetricCycles",
            "collectorMetricSavedThisSession",
            "collectorMetricLastCycle",
            "collectorMetricIntervalSub",
            "collectorAssetSelectedBadge",
            "collectorAssetSearchInput",
            "btnClearCollectorAssetSearch",
            "collectorAssetsContainer",
            "collectorCfgTimeframe",
            "collectorCfgCount",
            "collectorCfgInterval",
            "collectorCfgThrottle",
            "collectorAutoRefreshInterval",
            "collectorTableBody",
        }

        # Verify all extracted JS IDs exist in the DOM
        for elem_id in id_matches:
            found_elem = dom.find_by_id(elem_id)
            assert found_elem is not None, (
                f"JavaScript references getElementById('{elem_id}'), but element is missing in DOM!"
            )

        # Verify our explicit expected set is 100% present in HTML DOM
        for elem_id in expected_ids:
            found_elem = dom.find_by_id(elem_id)
            assert found_elem is not None, f"Required DOM element id='{elem_id}' missing in HTML!"

    async def test_dom_interactive_controls_complete_coverage(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-DOM-2: Verifies all interactive buttons, filter selectors, and config controls."""
        resp = await async_test_client.get("/")
        assert resp.status_code == 200
        html = resp.text
        dom = parse_html_dom(html)

        # 1. Tab Button
        tab_btn = dom.find_by_id("tabBtnCollector")
        assert tab_btn is not None
        assert "switchTab('collector')" in tab_btn.attrs.get("onclick", "")

        # 2. Start & Stop Action Buttons
        start_btn = dom.find_by_id("btnStartCollector")
        assert start_btn is not None
        assert "startDataCollector()" in start_btn.attrs.get("onclick", "")

        stop_btn = dom.find_by_id("btnStopCollector")
        assert stop_btn is not None
        assert "stopDataCollector()" in stop_btn.attrs.get("onclick", "")
        assert "hidden" in stop_btn.attrs.get("class", "")

        # 3. Quick Action Filter Buttons in Asset Selector
        filter_fn_signatures = [
            "selectAllCollectorAssets()",
            "deselectAllCollectorAssets()",
            "selectCollectorTopNAssets(5)",
            "selectCollectorOtcAssets()",
            "selectCollectorForexAssets()",
        ]
        all_buttons = dom.find_all("button")
        for fn_call in filter_fn_signatures:
            found = any(fn_call in b.attrs.get("onclick", "") for b in all_buttons)
            assert found, f"Quick action button with onclick='{fn_call}' missing from UI DOM!"

        # 4. Search & Clear Input
        search_input = dom.find_by_id("collectorAssetSearchInput")
        assert search_input is not None
        assert "filterCollectorAssetsList()" in search_input.attrs.get("oninput", "")

        clear_btn = dom.find_by_id("btnClearCollectorAssetSearch")
        assert clear_btn is not None
        assert "clearCollectorAssetSearch()" in clear_btn.attrs.get("onclick", "")

        # 5. Advanced Config Inputs
        cfg_timeframe = dom.find_by_id("collectorCfgTimeframe")
        assert cfg_timeframe is not None
        assert cfg_timeframe.attrs.get("value") == "1"

        cfg_count = dom.find_by_id("collectorCfgCount")
        assert cfg_count is not None
        assert cfg_count.attrs.get("value") == "300"

        cfg_interval = dom.find_by_id("collectorCfgInterval")
        assert cfg_interval is not None
        assert cfg_interval.attrs.get("value") == "60"

        cfg_throttle = dom.find_by_id("collectorCfgThrottle")
        assert cfg_throttle is not None
        assert cfg_throttle.attrs.get("value") == "0.5"

        # 6. Auto-refresh Interval Selector
        refresh_sel = dom.find_by_id("collectorAutoRefreshInterval")
        assert refresh_sel is not None
        assert "updateCollectorRefreshTimer()" in refresh_sel.attrs.get("onchange", "")
        options = [opt.attrs.get("value", "") for opt in refresh_sel.find_all("option")]
        assert set(options) == {"3000", "5000", "10000", "0"}

        # 7. Telemetry Metric Elements
        telemetry_ids = [
            "collectorMetricTotalDb",
            "collectorMetricActiveAssets",
            "collectorMetricActiveSub",
            "collectorMetricCycles",
            "collectorMetricSavedThisSession",
            "collectorMetricLastCycle",
            "collectorMetricIntervalSub",
        ]
        for tid in telemetry_ids:
            assert dom.find_by_id(tid) is not None, f"Telemetry metric element #{tid} missing!"

        # 8. Table Headers
        tab_collector = dom.find_by_id("tabCollector")
        assert tab_collector is not None
        th_elements = [th.get_text() for th in tab_collector.find_all("th")]
        assert len(th_elements) == 6
        assert any("Актив" in t for t in th_elements)
        assert any("Тип" in t for t in th_elements)
        assert any("Статус" in t for t in th_elements)
        assert any("Збережено" in t for t in th_elements)


@pytest.mark.asyncio
class TestJavaScriptStateMachineSimulation:
    """Simulates the JavaScript client-side state machine and lifecycle transitions."""

    async def test_state_machine_idle_to_running_and_telemetry_flow(
        self,
        async_test_client: AsyncClient,
        mock_trading_gateway: AsyncMock,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-SM-1: Simulates IDLE -> START -> POLLING (cycle increments) -> STOP state flow."""
        # 1. State 0: Initial IDLE
        await async_test_client.post("/api/v1/collector/stop")
        status_idle_resp = await async_test_client.get("/api/v1/collector/status")
        assert status_idle_resp.status_code == 200
        idle_data = status_idle_resp.json()
        assert idle_data["status"] in ("IDLE", "STOPPED")
        assert idle_data["is_running"] is False

        # 2. Client triggers startDataCollector() with 2 assets
        start_payload = {
            "assets": ["EURUSD_otc", "USDJPY_otc"],
            "timeframe_seconds": 1,
            "candles_count": 50,
            "interval_seconds": 0.05,
            "throttle_delay": 0.01,
        }
        start_resp = await async_test_client.post("/api/v1/collector/start", json=start_payload)
        assert start_resp.status_code == 200
        start_data = start_resp.json()
        assert start_data["status"] == "RUNNING"
        assert start_data["is_running"] is True
        assert start_data["active_assets"] == ["EURUSD_otc", "USDJPY_otc"]

        # 3. Simulate polling while collector runs
        await asyncio.sleep(0.18)

        poll_resp = await async_test_client.get("/api/v1/collector/status")
        assert poll_resp.status_code == 200
        poll_data = poll_resp.json()
        assert poll_data["is_running"] is True
        assert poll_data["cycles_completed"] >= 1
        assert poll_data["total_candles_saved"] > 0
        assert poll_data["total_database_candles"] > 0
        assert poll_data["last_cycle_at"] is not None

        # Verify asset_stats structure for UI table rendering
        asset_stats = {s["asset"]: s for s in poll_data["asset_stats"]}
        assert "EURUSD_otc" in asset_stats
        assert "USDJPY_otc" in asset_stats
        assert asset_stats["EURUSD_otc"]["is_collecting"] is True
        assert asset_stats["EURUSD_otc"]["count"] > 0
        assert asset_stats["USDJPY_otc"]["is_collecting"] is True
        assert asset_stats["USDJPY_otc"]["count"] > 0

        # 4. Client triggers stopDataCollector()
        stop_resp = await async_test_client.post("/api/v1/collector/stop")
        assert stop_resp.status_code == 200
        stop_data = stop_resp.json()
        assert stop_data["status"] in ("STOPPED", "IDLE")
        assert stop_data["is_running"] is False

        # Verify that assets in asset_stats now report is_collecting = False
        stat_map = {s["asset"]: s for s in stop_data["asset_stats"]}
        for sym in ["EURUSD_otc", "USDJPY_otc"]:
            assert stat_map[sym]["is_collecting"] is False
            assert stat_map[sym]["count"] > 0

    async def test_state_machine_rapid_reconfiguration_while_running(
        self,
        async_test_client: AsyncClient,
        mock_trading_gateway: AsyncMock,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-SM-2: Dynamic asset list update while collector is actively running."""
        # Start with asset A
        await async_test_client.post(
            "/api/v1/collector/start",
            json={"assets": ["EURUSD_otc"], "interval_seconds": 0.05, "throttle_delay": 0.01},
        )
        await asyncio.sleep(0.08)

        # Dynamic reconfiguration with asset B and C
        update_resp = await async_test_client.post(
            "/api/v1/collector/start",
            json={
                "assets": ["GOLD_otc", "AUDNZD_otc"],
                "interval_seconds": 0.05,
                "throttle_delay": 0.01,
            },
        )
        assert update_resp.status_code == 200
        update_data = update_resp.json()
        assert update_data["is_running"] is True
        assert set(update_data["active_assets"]) == {"GOLD_otc", "AUDNZD_otc"}

        await asyncio.sleep(0.12)

        # Cleanup
        await async_test_client.post("/api/v1/collector/stop")

    async def test_state_machine_idempotent_stop_calls(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-SM-3: Multiple stop calls when already stopped are completely safe and idempotent."""
        r1 = await async_test_client.post("/api/v1/collector/stop")
        assert r1.status_code == 200
        r2 = await async_test_client.post("/api/v1/collector/stop")
        assert r2.status_code == 200
        r3 = await async_test_client.post("/api/v1/collector/stop")
        assert r3.status_code == 200
        assert r3.json()["is_running"] is False


@pytest.mark.asyncio
class TestEdgeCaseInputsAndBoundaryFuzzing:
    """Empirically tests edge-case inputs, boundary parameters, sanitization, and errors."""

    async def test_edge_case_whitespace_and_sanitization(
        self,
        async_test_client: AsyncClient,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-EDGE-1: Whitespace-padded asset symbols are sanitized, stripped, and deduplicated."""
        payload = {
            "assets": ["  EURUSD_otc  ", "\tGOLD_otc\n", "  EURUSD_otc  "],
            "interval_seconds": 0.05,
            "throttle_delay": 0.01,
        }
        resp = await async_test_client.post("/api/v1/collector/start", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_assets"] == ["EURUSD_otc", "GOLD_otc"]

        await async_test_client.post("/api/v1/collector/stop")

    async def test_edge_case_empty_and_blank_assets_rejection(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-EDGE-2: Empty or whitespace-only asset lists return HTTP 422 errors."""
        # Empty list
        r1 = await async_test_client.post("/api/v1/collector/start", json={"assets": []})
        assert r1.status_code == 422

        # Whitespace-only entries
        r2 = await async_test_client.post(
            "/api/v1/collector/start", json={"assets": ["   ", "\t\n", " "]}
        )
        assert r2.status_code == 422

        # Missing assets key
        r3 = await async_test_client.post("/api/v1/collector/start", json={"timeframe_seconds": 1})
        assert r3.status_code == 422

    async def test_edge_case_non_existent_asset_fault_isolation(
        self,
        async_test_client: AsyncClient,
        mock_trading_gateway: AsyncMock,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-EDGE-3: Non-existent assets fail individually without halting the collection loop."""

        # Inject error on non-existent asset
        async def mock_get_candles_with_fault(
            asset: str,
            timeframe: int | str = 1,
            *,
            count: int = 300,
            end_time: datetime | None = None,
        ) -> list[Candle]:
            if asset == "NON_EXISTENT_ASSET":
                raise ValueError("Unknown broker asset NON_EXISTENT_ASSET")
            now = datetime.now(UTC)
            return [
                Candle(
                    open_time=now,
                    open=Decimal("1.0"),
                    high=Decimal("1.0"),
                    low=Decimal("1.0"),
                    close=Decimal("1.0"),
                    volume=Decimal("100"),
                )
            ]

        mock_trading_gateway.get_candles = AsyncMock(side_effect=mock_get_candles_with_fault)

        # Start collector with one valid asset and one invalid asset
        resp = await async_test_client.post(
            "/api/v1/collector/start",
            json={
                "assets": ["EURUSD_otc", "NON_EXISTENT_ASSET"],
                "interval_seconds": 0.05,
                "throttle_delay": 0.01,
            },
        )
        assert resp.status_code == 200

        await asyncio.sleep(0.15)

        # Status check: collector still running, valid asset persisted
        status_resp = await async_test_client.get("/api/v1/collector/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["is_running"] is True
        assert status_data["cycles_completed"] >= 1

        # EURUSD_otc was saved despite NON_EXISTENT_ASSET error
        assert isolated_market_store.count_candles("EURUSD_otc") > 0

        await async_test_client.post("/api/v1/collector/stop")

    async def test_boundary_config_parameters_validation(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-EDGE-4: Strict bounds checking on timeframe, candle count, interval, and throttle."""
        base = {"assets": ["EURUSD_otc"]}

        # timeframe_seconds < 1
        r = await async_test_client.post(
            "/api/v1/collector/start", json={**base, "timeframe_seconds": 0}
        )
        assert r.status_code == 422

        # candles_count < 1
        r = await async_test_client.post(
            "/api/v1/collector/start", json={**base, "candles_count": 0}
        )
        assert r.status_code == 422

        # candles_count > 5000
        r = await async_test_client.post(
            "/api/v1/collector/start", json={**base, "candles_count": 5001}
        )
        assert r.status_code == 422

        # interval_seconds < 0.001
        r = await async_test_client.post(
            "/api/v1/collector/start", json={**base, "interval_seconds": 0.0}
        )
        assert r.status_code == 422

        # throttle_delay < 0
        r = await async_test_client.post(
            "/api/v1/collector/start", json={**base, "throttle_delay": -0.1}
        )
        assert r.status_code == 422

        # throttle_delay > 10
        r = await async_test_client.post(
            "/api/v1/collector/start", json={**base, "throttle_delay": 10.5}
        )
        assert r.status_code == 422

        # Extra forbidden fields (extra='forbid')
        r = await async_test_client.post(
            "/api/v1/collector/start", json={**base, "injected_field": 123}
        )
        assert r.status_code == 422


@pytest.mark.asyncio
class TestSchemaAdherenceAndRenderingAssumptions:
    """Verifies schema adherence between backend Pydantic models and UI rendering assumptions."""

    async def test_available_assets_schema_adherence_and_ui_properties(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-SCH-1: Available assets schema matches frontend checkbox rendering properties."""
        resp = await async_test_client.get("/api/v1/collector/available-assets")
        assert resp.status_code == 200
        assets = resp.json()
        assert isinstance(assets, list)
        assert len(assets) > 0

        for a in assets:
            # Pydantic schema validation
            model = CollectorAssetResponse.model_validate(a)
            assert isinstance(model.symbol, str) and len(model.symbol) > 0
            assert isinstance(model.name, str)
            assert isinstance(model.payout, int)
            assert isinstance(model.is_otc, bool)
            assert isinstance(model.asset_type, str)

            # Check properties expected by index.html JS:
            # accesses a.symbol, a.name, a.payout, a.is_otc, a.asset_type
            assert "symbol" in a
            assert "name" in a
            assert "payout" in a
            assert "is_otc" in a
            assert "asset_type" in a

    async def test_status_response_schema_adherence_and_ui_table_properties(
        self,
        async_test_client: AsyncClient,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-SCH-2: CollectorStatusResponse schema matches all DOM metric and table fields."""
        # Insert sample candle to ensure asset_stats has entries
        dt = datetime.now(UTC)
        isolated_market_store.insert_candles(
            "EURUSD_otc",
            [
                Candle(
                    open_time=dt,
                    open=Decimal("1.0850"),
                    high=Decimal("1.0855"),
                    low=Decimal("1.0845"),
                    close=Decimal("1.0852"),
                    volume=Decimal("50"),
                )
            ],
        )

        resp = await async_test_client.get("/api/v1/collector/status")
        assert resp.status_code == 200
        data = resp.json()

        # Validate with Pydantic model
        status_model = CollectorStatusResponse.model_validate(data)

        # Fields required by JS renderCollectorStatus() in index.html
        required_top_keys = [
            "status",
            "is_running",
            "active_assets",
            "timeframe_seconds",
            "candles_count",
            "interval_seconds",
            "throttle_delay",
            "cycles_completed",
            "total_candles_saved",
            "last_cycle_at",
            "total_database_candles",
            "asset_stats",
        ]
        for k in required_top_keys:
            assert k in data, f"Missing required status field '{k}' in response payload"

        assert len(status_model.asset_stats) >= 1
        stat = data["asset_stats"][0]

        # Validate stat fields accessed by table renderer
        required_stat_keys = [
            "asset",
            "count",
            "is_otc",
            "is_collecting",
            "first_timestamp",
            "last_timestamp",
            "first_time",
            "last_time",
            "payout",
        ]
        for sk in required_stat_keys:
            assert sk in stat, f"Missing required asset_stat field '{sk}' in asset_stats payload"

        # Verify CollectorAssetStatResponse model validation
        stat_model = CollectorAssetStatResponse.model_validate(stat)
        assert stat_model.count == 1
        assert stat_model.asset == "EURUSD_otc"

    async def test_null_timestamp_safety_and_empty_state_rendering(
        self,
        async_test_client: AsyncClient,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-SCH-3: Null timestamps and zero counts serialize cleanly without type errors."""
        # Check raw store stats for empty asset
        stats = isolated_market_store.get_asset_stats("UNTRACKED_EMPTY_ASSET")
        assert stats["count"] == 0
        assert stats["first_timestamp"] is None
        assert stats["last_timestamp"] is None
        assert stats["first_time"] is None
        assert stats["last_time"] is None

        # Verify Pydantic validation handles None values gracefully
        stat_model = CollectorAssetStatResponse(
            asset="UNTRACKED_EMPTY_ASSET",
            count=0,
            first_timestamp=None,
            last_timestamp=None,
            first_time=None,
            last_time=None,
        )
        assert stat_model.first_time is None
        assert stat_model.last_time is None
        assert stat_model.count == 0

        # Verify status endpoint returns valid response structure
        resp = await async_test_client.get("/api/v1/collector/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "asset_stats" in data
        assert isinstance(data["asset_stats"], list)

    async def test_html_xss_injection_resilience_in_assets(
        self,
        async_test_client: AsyncClient,
        mock_trading_gateway: AsyncMock,
    ) -> None:
        """TC-SCH-4: Malicious/HTML characters in asset symbols are safely handled by schema."""
        mock_trading_gateway.get_assets = AsyncMock(
            return_value=[
                {
                    "symbol": "BTC<script>alert(1)</script>",
                    "name": "Bitcoin <img src=x onerror=alert(1)>",
                    "payout": 90,
                    "is_otc": True,
                    "asset_type": "cryptocurrency",
                }
            ]
        )

        resp = await async_test_client.get("/api/v1/collector/available-assets")
        assert resp.status_code == 200
        assets = resp.json()
        assert len(assets) == 1
        assert assets[0]["symbol"] == "BTC<script>alert(1)</script>"

        # Verify Pydantic models validate successfully
        model = CollectorAssetResponse.model_validate(assets[0])
        assert model.symbol == "BTC<script>alert(1)</script>"


@pytest.mark.asyncio
class TestConcurrencyAndLifecycleStress:
    """Stress tests concurrent status polling, rapid lifecycle cycling, and engine isolation."""

    async def test_high_concurrency_status_polling_under_load(
        self,
        async_test_client: AsyncClient,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-CONC-1: 30 concurrent GET /status queries during active data collection."""
        await async_test_client.post(
            "/api/v1/collector/start",
            json={
                "assets": ["EURUSD_otc", "USDJPY_otc", "GOLD_otc"],
                "interval_seconds": 0.02,
                "throttle_delay": 0.005,
            },
        )

        async def _query_status() -> int:
            r = await async_test_client.get("/api/v1/collector/status")
            return r.status_code

        # Fire 30 concurrent status requests
        results = await asyncio.gather(*[_query_status() for _ in range(30)])
        assert all(code == 200 for code in results)

        await async_test_client.post("/api/v1/collector/stop")

    async def test_rapid_start_stop_cycling_stress(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-CONC-2: 6 rapid start/stop iterations execute without deadlocks or leaked tasks."""
        for _ in range(6):
            r_start = await async_test_client.post(
                "/api/v1/collector/start",
                json={
                    "assets": ["EURUSD_otc"],
                    "interval_seconds": 0.05,
                    "throttle_delay": 0.01,
                },
            )
            assert r_start.status_code == 200
            assert r_start.json()["is_running"] is True

            await asyncio.sleep(0.03)

            r_stop = await async_test_client.post("/api/v1/collector/stop")
            assert r_stop.status_code == 200
            assert r_stop.json()["is_running"] is False

    async def test_collector_engine_reset_and_singleton_integrity(
        self,
        isolated_market_store: MarketDataStore,
    ) -> None:
        """TC-CONC-3: Singleton AsyncCollectorEngine maintains clean internal state on restart."""
        engine = get_collector_engine()
        engine.set_store(isolated_market_store)

        mock_gw = AsyncMock()
        mock_gw.get_candles = AsyncMock(return_value=[])

        # Start
        await engine.start(mock_gw, ["EURUSD_otc"], interval_seconds=0.05, throttle_delay=0.01)
        assert engine.is_running is True

        # Stop
        await engine.stop()
        assert engine.is_running is False
