"""Read-only downloadable Dify/OpenAPI integration; no extra public tools or writes."""
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse

router=APIRouter()
OPENAPI_FILE=Path(__file__).resolve().parent/"integrations"/"ai-market-readonly-openapi.json"

@router.get("/integrations/ai-market-readonly-openapi.json",include_in_schema=False)
def read_only_custom_agent_tool_spec():
    return FileResponse(OPENAPI_FILE,media_type="application/json",headers={
        "Cache-Control":"public, max-age=3600",
        "X-Content-Type-Options":"nosniff",
        "Access-Control-Allow-Origin":"*"})
