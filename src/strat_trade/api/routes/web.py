from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Web UI"])

_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "web" / "templates" / "index.html"

_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="stGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#06b6d4"/>
      <stop offset="100%" stop-color="#10b981"/>
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="16" fill="#0b0f17"/>
  <rect x="1.5" y="1.5" width="61" height="61" rx="14.5" fill="none"
        stroke="url(#stGrad)" stroke-width="2.5" stroke-opacity="0.6"/>
  <!-- Trend Candles -->
  <line x1="18" y1="20" x2="18" y2="44" stroke="#06b6d4" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="14" y="26" width="8" height="12" rx="2" fill="#06b6d4"/>
  <line x1="32" y1="14" x2="32" y2="48" stroke="#10b981" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="28" y="20" width="8" height="18" rx="2" fill="#10b981"/>
  <line x1="46" y1="10" x2="46" y2="38" stroke="#38bdf8" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="42" y="14" width="8" height="14" rx="2" fill="#38bdf8"/>
  <!-- Alpha Pulse Wave -->
  <path d="M10 46 Q 24 40 32 26 T 54 12" fill="none"
        stroke="url(#stGrad)" stroke-width="3.5" stroke-linecap="round"/>
  <circle cx="54" cy="12" r="3.5" fill="#10b981"/>
</svg>"""


@router.api_route(
    "/favicon.svg",
    methods=["GET", "HEAD"],
    summary="Strat Trade SVG Favicon",
    include_in_schema=False,
)
@router.api_route(
    "/favicon.ico", methods=["GET", "HEAD"], summary="Strat Trade Favicon", include_in_schema=False
)
async def get_favicon() -> Response:
    """Returns the brand SVG favicon."""
    return Response(
        content=_FAVICON_SVG,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


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
