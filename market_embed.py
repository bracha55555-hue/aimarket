from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse

router=APIRouter()
ROOT=Path(__file__).resolve().parent/"client"
BASE_HEADERS={"X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer"}

@router.get("/embed",include_in_schema=False)
def public_market_widget():
    return FileResponse(ROOT/"market-embed.html",media_type="text/html",headers={
        **BASE_HEADERS,"Cache-Control":"public, max-age=300",
        "Content-Security-Policy":"default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors *"})

@router.get("/client/market-embed.js",include_in_schema=False)
def public_market_widget_script():
    return FileResponse(ROOT/"market-embed.js",media_type="text/javascript",headers={
        **BASE_HEADERS,"Cache-Control":"public, max-age=300"})

@router.get("/embed-guide",include_in_schema=False)
def public_market_widget_guide():
    return FileResponse(ROOT/"market-embed-guide.html",media_type="text/html",headers={
        **BASE_HEADERS,"Cache-Control":"public, max-age=300",
        "Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})
