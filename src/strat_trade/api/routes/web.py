from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Web UI"])

_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "web" / "templates" / "index.html"


@router.get("/", response_class=HTMLResponse, summary="Web Dashboard UI")
@router.get("/dashboard", response_class=HTMLResponse, summary="Web Dashboard UI")
async def get_dashboard() -> HTMLResponse:
    """Serve the single-page application dashboard for backtesting, charts, and API testing."""
    if _TEMPLATE_PATH.is_file():
        content = _TEMPLATE_PATH.read_text(encoding="utf-8")
        return HTMLResponse(content=content)
    return HTMLResponse(
        content="<h1>Template not found</h1><p>Expected at: " + str(_TEMPLATE_PATH) + "</p>",
        status_code=404,
    )
