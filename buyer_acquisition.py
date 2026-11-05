"""Static first-buyer discovery landing; no commerce or storage changes."""
from pathlib import Path
from fastapi import APIRouter,Request
from fastapi.responses import FileResponse

router=APIRouter()
PAGE=Path(__file__).resolve().parent/"client"/"mcp-a2a-audit.html"

@router.get("/hire-mcp-a2a-review",include_in_schema=False)
def independent_ai_review_buyer_page(request:Request):
    if request.headers.get("user-agent","") not in ("AI-Market-Official-Business-Audit/1.0","AI-Market-IndexNow-Official/1.0"):
        reporter=getattr(request.app.state,"ai_market_usage_event",None)
        if callable(reporter):reporter("mcp_a2a_buyer_landing_views")
    return FileResponse(PAGE,media_type="text/html",headers={
        "Cache-Control":"public, max-age=600",
        "X-Content-Type-Options":"nosniff",
        "Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        "Referrer-Policy":"strict-origin-when-cross-origin"})
