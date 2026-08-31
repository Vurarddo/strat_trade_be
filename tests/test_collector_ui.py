"""DOM validation and Web UI contract tests for Stage 3 S1 Data Collector Dashboard.

Covers Tier 1 & Tier 4 UI Markup and Client-Side Script Verification:
- HTML5 template rendering and tab navigation
- Asset selection matrix and batch control buttons
- Real-time telemetry cards and live statistics table markup
- JavaScript API client bindings and event handler signatures
"""

from __future__ import annotations

import re

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestCollectorUIDOMValidation:
    """Validates DOM structure and JavaScript bindings in index.html for Collector UI."""

    async def test_ui_html_contains_collector_tab_navigation(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-1.6: Web dashboard contains Data Collection tab button and panel container."""
        response = await async_test_client.get("/")
        assert response.status_code == 200
        html = response.text

        # Tab button for Collector
        has_tab_btn = (
            'id="tabBtnCollector"' in html
            or "tabBtnCollector" in html
            or "switchTab('collector')" in html
        )
        assert has_tab_btn

        # Tab container for Collector
        assert 'id="tabCollector"' in html or "tabCollector" in html

    async def test_ui_html_contains_collector_controls_and_containers(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-1.6, 4.2: Web dashboard contains asset selection matrix and action buttons."""
        response = await async_test_client.get("/")
        assert response.status_code == 200
        html = response.text

        # Asset container
        assert (
            "collectorAssetsContainer" in html
            or "collectorAssetList" in html
            or "collectorAssets" in html
        )

        # Start & Stop buttons
        assert (
            "btnStartCollector" in html
            or "btnCollectorStart" in html
            or "startCollector" in html
            or "startDataCollector" in html
        )
        assert (
            "btnStopCollector" in html
            or "btnCollectorStop" in html
            or "stopCollector" in html
            or "stopDataCollector" in html
        )

        # Select All / Deselect All controls
        assert (
            "selectAllCollectorAssets" in html
            or "btnCollectorSelectAll" in html
            or "selectAllAssets" in html
            or "Select All" in html
            or "Вибрати всі" in html
        )
        assert (
            "deselectAllCollectorAssets" in html
            or "btnCollectorDeselectAll" in html
            or "deselectAllAssets" in html
            or "Deselect All" in html
            or "Зняти всі" in html
        )

        # Status / Stats Table
        assert (
            "collectorStatsTable" in html
            or "collectorTableBody" in html
            or "collectorStatus" in html
            or "collectorStats" in html
        )

    async def test_ui_javascript_collector_api_bindings(
        self,
        async_test_client: AsyncClient,
    ) -> None:
        """TC-4.2: Frontend JS implements collector lifecycle functions and routes."""
        response = await async_test_client.get("/")
        assert response.status_code == 200
        html = response.text

        # Verify API route references in frontend JavaScript
        assert "/api/v1/collector/available-assets" in html or "available-assets" in html
        assert "/api/v1/collector/status" in html or "collector/status" in html
        assert "/api/v1/collector/start" in html or "collector/start" in html
        assert "/api/v1/collector/stop" in html or "collector/stop" in html

        # Verify core JS function signatures
        js_patterns = [
            r"function\s+(load|fetch)CollectorAvailableAssets|loadAvailableCollectorAssets",
            r"function\s+(start|launch)DataCollector|startCollector",
            r"function\s+(stop|halt)DataCollector|stopCollector",
            r"function\s+(fetch|refresh|update)CollectorStatus|getCollectorStatus",
        ]
        for pattern in js_patterns:
            assert re.search(pattern, html, re.IGNORECASE) is not None, (
                f"Missing expected JS function matching pattern: {pattern}"
            )
