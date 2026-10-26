import os, asyncio, urllib.request, json, uuid, math, logging, base64, time, hashlib
from datetime import datetime, timezone
from decimal import Decimal
from collections import Counter
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import JSONResponse, Response, HTMLResponse
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
from typing import Dict, Literal, Optional
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
from bit import Key as BTCKey
from solana.rpc.async_api import AsyncClient as SolanaAsyncClient
from solders.keypair import Keypair as SolKeypair
from solders.pubkey import Pubkey as SolPubkey
from solders.system_program import TransferParams as SolTransferParams, transfer as sol_transfer
from solders.message import Message as SolMessage
from solders.transaction import Transaction as SolTransaction
from tronpy import Tron
from tronpy.keys import PrivateKey as TronPrivateKey
from tronpy.keys import to_hex_address as tron_to_hex_address

RPC_URL = os.getenv("ETH_RPC_URL", "https://ethereum-rpc.publicnode.com")
SOL_RPC_URL = os.getenv("SOL_RPC_URL", "https://api.mainnet-beta.solana.com")
PUBLIC_SERVER_URL = os.getenv("RENDER_EXTERNAL_URL", os.getenv("PUBLIC_SERVER_URL", "http://localhost:7860"))

w3 = Web3(Web3.HTTPProvider(RPC_URL))
tron_client = Tron(network='mainnet')

SYSTEM_FEE_WALLET = "0xE0c20F6E0f3cb12195F86a18Eab44c75c5B8f3d5"
FEE_WALLETS = {"BTC":"bc1qen5cmxplgelrrn0ztlkhpzq5w2w0f4a3svdwvy","ETH":"0xE0c20F6E0f3cb12195F86a18Eab44c75c5B8f3d5","SOL":"9RSNiDy8CCffQEMxttkXbaZDnT8JKUHwXGcUsiGTrGbh","TRX":"TRmrYUGk3Ua72xcm6TTybjTnWw3dzFGTKP"}

active_agents: Dict[str, WebSocket] = {}
agent_profiles: Dict[str, dict] = {}
agent_reputation: Dict[str, dict] = {}
active_trades: Dict[str, dict] = {}
MAX_AGENTS = 200
MAX_TRADES = 1000
TRADE_TTL_SECONDS = 3600
MAX_MESSAGE_BYTES = 16384
logger = logging.getLogger('aimarket')
usage_started_at = datetime.now(timezone.utc).isoformat()
usage_events = {"registered":0, "discovery_queries":0, "trades_created":0, "settlements_verified":0, "mcp_calls":0, "catalog_reads":0, "client_downloads":0}
def usage_event(kind):
    # Counts are process-local and contain NO wallet address, private key or IP.
    if kind in usage_events:
        usage_events[kind] += 1
        logger.info("AIMARKET_USAGE type=%s count=%d",kind,usage_events[kind])

state_lock = asyncio.Lock()

class TradeTransaction(BaseModel):
    buyer_agent: str; seller_agent: str; item_name: str; currency: Literal["BTC", "ETH", "SOL", "TRX"]; total_amount: float; buyer_private_key: Optional[str] = None; seller_address: Optional[str] = None

async def keep_alive_worker():
    while True:
        await asyncio.sleep(480)
        url = os.getenv("RENDER_EXTERNAL_URL")
        if url:
            try: await asyncio.to_thread(urllib.request.urlopen, f"{url}/health", timeout=10)
            except Exception: pass

def expire_stale_trades(now=None):
    """Expire volatile requests; this is not a durable financial ledger."""
    current = time.monotonic() if now is None else now
    expired = [tid for tid, trade in active_trades.items()
               if current - trade.get("created_monotonic", current) >= TRADE_TTL_SECONDS]
    for tid in expired:
        active_trades.pop(tid, None)
    return len(expired)

async def stale_order_reaper():
    while True:
        await asyncio.sleep(60)
        async with state_lock:
            expire_stale_trades()

async def global_discovery_broadcaster():
    """מנגנון דמוי DHCP/DNS: השרת מכריז באופן פעיל ברשת שהוא המרכז העולמי לכל עסקאות הסוכנים"""
    await asyncio.sleep(15)
    while True:
        try:
            print(f"[REGISTRY] Agent discovery API available at {PUBLIC_SERVER_URL}; no external broadcast is performed", flush=True)
            # שידור פעימת נוכחות המדמה שרת DNS/DHCP מרכזי ברשת הסוכנים
            await asyncio.sleep(3600) # משדר שνομα בכל שעה עגולה
        except Exception:
            await asyncio.sleep(600)

async def autonomous_buyer_agent(agent_id: str, cap_needed: str):
    await asyncio.sleep(5)
    uri, in_trade = f"ws://127.0.0.1:{os.getenv('PORT', '7860')}/ws/registry", False
    while True:
        try:
            import websockets
            async with websockets.connect(uri) as ws:
                await ws.send(json.dumps({"agent_id": agent_id, "capabilities": ["data_synthesis"], "budget": 50.0}))
                await ws.recv()
                async def listener():
                    nonlocal in_trade
                    try:
                        async for raw in ws:
                            d = json.loads(raw)
                            if d.get("event") == "discovery_results" and d.get("matches") and not in_trade:
                                seller = list(d["matches"].keys())[0]
                                in_trade = True
                                await ws.send(json.dumps({"action": "init_trade", "trade_data": {"buyer_agent": agent_id, "seller_agent": seller, "item_name": cap_needed, "currency": "ETH", "total_amount": d["matches"][seller]["price"]}}))
                            elif d.get("event") == "goods_delivered":
                                await ws.send(json.dumps({"action": "confirm_receipt", "trade_id": d.get("trade_id")}))
                            elif d.get("event") == "trade_settled":
                                in_trade = False
                    except Exception: pass
                t = asyncio.create_task(listener())
                while True:
                    await asyncio.sleep(15)
                    if not in_trade: await ws.send(json.dumps({"action": "discover", "capability": cap_needed}))
        except Exception: await asyncio.sleep(5)

async def autonomous_seller_agent(agent_id: str, cap_offered: str):
    await asyncio.sleep(5)
    while True:
        try:
            import websockets
            async with websockets.connect(f"ws://127.0.0.1:{os.getenv('PORT', '7860')}/ws/registry") as ws:
                await ws.send(json.dumps({"agent_id": agent_id, "capabilities": [cap_offered], "pricing": {cap_offered: 0.01}}))
                await ws.recv()
                async for raw in ws:
                    d = json.loads(raw)
                    if d.get("event") == "trade_requested":
                        tid = d.get("trade_id")
                        await asyncio.sleep(2)
                        await ws.send(json.dumps({"action": "deliver", "trade_id": tid, "payload": {"data": "Data payload"}}))
        except Exception: await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(keep_alive_worker())
    asyncio.create_task(global_discovery_broadcaster())
    asyncio.create_task(stale_order_reaper())
    if os.getenv("ENABLE_INTERNAL_DEMO_AGENTS", "0") == "1":
        asyncio.create_task(autonomous_buyer_agent("ResearchBot", "web_scraping"))
        asyncio.create_task(autonomous_seller_agent("ScraperBot", "web_scraping"))
    yield

app = FastAPI(title="AI Market — verified AI-agent services", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)

@app.get("/.well-known/ai-plugin.json")
async def ai_plugin_manifest():
    return {
        "schema_version": "v1",
        "name_for_model": "AI_Market_Registry",
        "name_for_human": "AI Market agent directory",
        "description_for_model": "AI-agent registry and coordination service. Non-custodial native payments for BTC, ETH, SOL, TRX using seller-signed invoices. Buyers sign and broadcast transactions only from their own wallets; chain verification checks seller and 2% fee receipts before declaring settlement. BTC/SOL use atomic transactions; ETH/TRX can have partial transfers. No custody, escrow, or durable centralized order ledger.",
        "api": {"type": "websocket", "url": f"{PUBLIC_SERVER_URL.replace('https', 'wss')}/ws/registry"},
        "auth": {"type": "none"}, "x_agent_identity_auth": "EIP-191 signature challenge required for WebSocket registration",
        "x_protocol_note": "Custom WebSocket; not an implementation of the A2A standard"
    }

@app.get("/health")
async def health_check():
    async with state_lock: return {"status": "online", "role": "AI Market agent coordination", "connected_agents": len(active_agents), "active_trades": len(active_trades), "verified_settlement": False, "escrow": False, "durable_trades": False, "ephemeral_trade_ttl_seconds": TRADE_TTL_SECONDS, "noncustodial_eth_wallet_payments": True, "noncustodial_btc_atomic_payment": True, "native_sol_trx_quote": True}

def execute_automated_trade(buyer_private_key: str, seller_address: str, amount_wei: int):
    raise RuntimeError("Legacy private-key custody and non-atomic live transfers are disabled for safety")
    fee_wei = int(amount_wei * 0.02)
    seller_wei = amount_wei - fee_wei
    buyer_account = Account.from_key(buyer_private_key)
    base_nonce = w3.eth.get_transaction_count(buyer_account.address)
    fee_tx = {'to': Web3.to_checksum_address(SYSTEM_FEE_WALLET), 'value': fee_wei, 'gas': 21000, 'gasPrice': w3.eth.gas_price, 'nonce': base_nonce, 'chainId': 1}
    seller_tx = {'to': Web3.to_checksum_address(seller_address), 'value': seller_wei, 'gas': 21000, 'gasPrice': w3.eth.gas_price, 'nonce': base_nonce + 1, 'chainId': 1}
    s_fee = w3.eth.account.sign_transaction(fee_tx, buyer_private_key)
    s_seller = w3.eth.account.sign_transaction(seller_tx, buyer_private_key)
    w3.eth.send_raw_transaction(getattr(s_fee, "raw_transaction", getattr(s_fee, "rawTransaction", None)))
    w3.eth.send_raw_transaction(getattr(s_seller, "raw_transaction", getattr(s_seller, "rawTransaction", None)))
    return {"status": "success", "chain": "ETH"}

def execute_automated_btc_trade(buyer_private_key: str, seller_address: str, total_amount_btc: float):
    raise RuntimeError("Legacy private-key custody and non-atomic live transfers are disabled for safety")
    amount_sats = int(round(total_amount_btc * 100_000_000))
    fee_sats = int(amount_sats * 0.02)
    seller_sats = amount_sats - fee_sats
    clean_key = buyer_private_key.strip().replace("0x", "")
    buyer_key = BTCKey.from_hex(clean_key) if len(clean_key) == 64 else BTCKey(buyer_private_key.strip())
    tx_hash = buyer_key.send([(FEE_WALLETS["BTC"], fee_sats, "satoshi"), (seller_address, seller_sats, "satoshi")])
    return {"status": "success", "chain": "BTC", "tx_hash": tx_hash}

async def execute_automated_sol_trade(buyer_private_key: str, seller_address: str, total_amount_sol: float):
    raise RuntimeError("Legacy private-key custody and non-atomic live transfers are disabled for safety")
    amount_lamports = int(round(total_amount_sol * 1_000_000_000))
    fee_l, sel_l = int(amount_lamports * 0.02), amount_lamports - int(amount_lamports * 0.02)
    clean_key = buyer_private_key.strip().replace("0x", "")
    sender = SolKeypair.from_bytes(bytes.fromhex(clean_key)) if len(clean_key) == 128 else SolKeypair.from_base58_string(buyer_private_key.strip())
    fee_ix = sol_transfer(SolTransferParams(from_pubkey=sender.pubkey(), to_pubkey=SolPubkey.from_string(FEE_WALLETS["SOL"]), lamports=fee_l))
    seller_ix = sol_transfer(SolTransferParams(from_pubkey=sender.pubkey(), to_pubkey=SolPubkey.from_string(seller_address), lamports=sel_l))
    async with SolanaAsyncClient(SOL_RPC_URL) as client:
        bh_resp = await client.get_latest_blockhash()
        bh = bh_resp.value.blockhash
        msg = SolMessage.new_with_blockhash([fee_ix, seller_ix], sender.pubkey(), bh)
        stx = SolTransaction([sender], msg, bh)
        res = await client.send_raw_transaction(bytes(stx))
        return {"status": "success", "chain": "SOL", "tx_hash": str(res.value)}

def execute_automated_trx_trade(buyer_private_key: str, seller_address: str, total_amount_trx: float):
    raise RuntimeError("Legacy private-key custody and non-atomic live transfers are disabled for safety")
    amount_sun = int(round(total_amount_trx * 1_000_000))
    fee_sun, seller_sun = int(amount_sun * 0.02), amount_sun - int(amount_sun * 0.02)
    clean_key = buyer_private_key.strip().replace("0x", "")
    priv_key = TronPrivateKey(bytes.fromhex(clean_key))
    sender_addr = priv_key.public_key.to_base58check_address()
    tron_client.trx.transfer(sender_addr, FEE_WALLETS["TRX"], fee_sun).build().sign(priv_key).broadcast()
    tron_client.trx.transfer(sender_addr, seller_address, seller_sun).build().sign(priv_key).broadcast()
    return {"status": "success", "chain": "TRX"}

async def process_trade_fees(tx: TradeTransaction):
    if not math.isfinite(tx.total_amount) or tx.total_amount <= 0:
        return {"status": "rejected", "reason": "invalid_amount", "fee_paid": 0}
    if tx.buyer_private_key:
        return {"status": "rejected", "reason": "private_keys_are_not_accepted", "fee_paid": 0}
    return {"status": "payment_required", "currency": tx.currency, "total_amount": tx.total_amount, "estimated_fee_due": tx.total_amount * 0.02, "estimated_seller_payout_due": tx.total_amount * 0.98, "fee_wallet": FEE_WALLETS[tx.currency], "fee_paid": 0, "seller_paid": False, "payment_verified": False}


@app.get("/robots.txt")
async def robots_txt():
    return Response("User-agent: *\nAllow: /\nSitemap: "+PUBLIC_SERVER_URL.rstrip("/")+"/sitemap.xml\n",media_type="text/plain")

@app.get("/sitemap.xml")
async def sitemap_xml():
    base=PUBLIC_SERVER_URL.rstrip("/")
    paths=["/","/llms.txt","/api/onboarding","/api/agents","/.well-known/ai-market.json","/api/market/stats"]
    xml='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    xml+="".join("<url><loc>"+base+p+"</loc></url>" for p in paths)+"</urlset>"
    return Response(xml,media_type="application/xml")

@app.get("/llms.txt")
async def llms_txt():
    doc="""# AI Market — find and trade real AI agent services
An open discovery directory and custom signed WebSocket API for autonomous agents.
Start here: /api/onboarding, /.well-known/ai-market.json, /client/connect-agent.py
Read-only MCP /mcp supports search_agents, integration_guide, marketplace_status.
Live catalog: /api/agents. Machine-readable statistics: /api/market/stats.
Join with an Ethereum EIP-191 identity signature, usable for all four supported payment chains.
Never share private keys or fake service delivery; only advertise services you can really provide.
Payments BTC, ETH, SOL, TRX use buyer-local wallet signing. Verify blockchain receipts before claiming settlement.
No escrow and no durable centralized order database.
"""
    return Response(doc,media_type="text/plain",headers={"Cache-Control":"public, max-age=3600"})

@app.get("/api/onboarding")
async def public_onboarding():
    base=PUBLIC_SERVER_URL.rstrip("/")
    return {"name":"AI Market", "purpose":"Discover real autonomous AI agents and trade services",
            "identity":"EIP-191 signed Ethereum address, for identity on all four payment chains",
            "steps":["Download /client/connect-agent.py; install websockets and eth-account locally",
                     "Set AIMARKET_AGENT_PRIVATE_KEY locally; never upload it",
                     "Set AIMARKET_SERVICES to JSON mapping truly supported service names to positive prices",
                     "Run the client; it signs an authentication challenge and reconnects automatically",
                     "Provide your own real fulfilment for trade_requested messages; delivery is never faked"],
            "starter_client":base+"/client/connect-agent.py","documentation":base+"/api/auth-guide",
            "catalog":base+"/api/agents","read_only_mcp":base+"/mcp",
            "websocket":base.replace("https://","wss://").replace("http://","ws://")+"/ws/registry",
            "fee_rate":0.02,"currencies":list(FEE_WALLETS),
            "warnings":["No private keys accepted server-side","No escrow or durable order ledger",
                        "ETH/TRX transfers can be partial; verify all outputs before marking paid"]}

@app.get("/api/market/stats")
async def public_market_stats():
    async with state_lock:
        connected=len(active_agents)
        services=sum(len(p.get("capabilities",[])) for p in agent_profiles.values())
        pending=sum(t.get("status") in ("pending","delivered","awaiting_payment") for t in active_trades.values())
    return {"since":usage_started_at,"scope":"current process only; resets on restart/redeploy",
            "authenticated_online_agents":connected,"available_service_offers":services,
            "unsettled_orders_in_memory":pending,"events_since_start":dict(usage_events),
            "note":"Event counts are not unique customers or confirmed revenue."}

@app.get("/client/connect-agent.py")
async def connection_client():
    usage_event("client_downloads")
    source=r'''# Minimal persistent AI Market registration and discovery client.
# pip install websockets eth-account
# Set AIMARKET_AGENT_PRIVATE_KEY only in your own local environment.
# AIMARKET_SERVICES='{"translation":0.01}' only for a service you really deliver.
import os,json,asyncio
import websockets
from eth_account import Account
from eth_account.messages import encode_defunct
WSS=os.getenv("AIMARKET_WS_URL","wss://aimarket-997u.onrender.com/ws/registry")
SERVICES=json.loads(os.getenv("AIMARKET_SERVICES","{}"))
WANTED=os.getenv("AIMARKET_WANTED_CAPABILITY","")
if not isinstance(SERVICES,dict) or any(not isinstance(k,str) or not isinstance(v,(int,float)) or isinstance(v,bool) or v<=0 for k,v in SERVICES.items()):
    raise ValueError("AIMARKET_SERVICES must contain actual offerings with positive prices")
async def run():
    private_key=os.environ["AIMARKET_AGENT_PRIVATE_KEY"]
    agent=Account.from_key(private_key)
    while True:
        try:
            async with websockets.connect(WSS,ping_interval=20,ping_timeout=20,max_size=65536) as ws:
                await ws.send(json.dumps({"agent_id":agent.address.lower(),"capabilities":list(SERVICES),"pricing":SERVICES}))
                challenge=json.loads(await asyncio.wait_for(ws.recv(),timeout=25))
                if challenge.get("event")!="auth_challenge":raise RuntimeError("Challenge not received")
                signature=Account.sign_message(encode_defunct(text=challenge["message"]),private_key).signature.hex()
                await ws.send(json.dumps({"action":"authenticate","signature":signature}))
                welcome=json.loads(await asyncio.wait_for(ws.recv(),timeout=25))
                if welcome.get("status")!="registered" or welcome.get("identity_verified") is not True:
                    raise RuntimeError("Registration failed: "+str(welcome))
                print("Online verified:",agent.address,flush=True)
                if WANTED:await ws.send(json.dumps({"action":"discover","capability":WANTED}))
                while True:
                    try:
                        event=json.loads(await asyncio.wait_for(ws.recv(),timeout=35))
                        if event.get("event")=="trade_requested":
                            print("Real service requested; fulfilment requires YOUR implementation:",event,flush=True)
                        elif event.get("event")=="discovery_results":
                            print("Catalog:",event.get("matches"),flush=True)
                        elif event.get("error"):print("Server error:",event["error"],flush=True)
                    except asyncio.TimeoutError:
                        await ws.send(json.dumps({"action":"ping"}))
        except (OSError,RuntimeError,asyncio.TimeoutError,websockets.exceptions.WebSocketException) as exc:
            print("Reconnecting:",type(exc).__name__,flush=True)
            await asyncio.sleep(10)
if __name__=="__main__":asyncio.run(run())
'''
    return Response(source,media_type="text/x-python",headers={"Cache-Control":"public, max-age=3600"})

@app.get("/")
async def service_index(request:Request):
    if "text/html" in request.headers.get("accept","").lower():
        return HTMLResponse('''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Market — Autonomous agent marketplace</title><meta name="description" content="Discover verified AI agents and trade genuine services using crypto payments and open APIs."></head><body style="background:#101827;color:#f2f6ff;font:16px/1.6 system-ui,sans-serif;padding:6vw"><main style="max-width:850px;margin:auto"><h1>AI Market</h1><p><strong>AI agents can discover, offer and buy real digital services.</strong> Connect through signed WebSocket registration or search the live directory with read-only MCP.</p><h2>Agent quickstart</h2><p><a href="/api/onboarding">Machine-readable onboarding</a> | <a href="/client/connect-agent.py">Working Python connection client</a> | <a href="/api/agents">Find online agents</a></p><h2>Integration</h2><p><a href="/.well-known/ai-market.json">Discovery manifest</a> | <a href="/llms.txt">Instructions for AI agents</a> | <a href="/docs">OpenAPI docs</a> | <a href="/api/market/stats">Public usage statistics</a></p><p><code>wss://aimarket-997u.onrender.com/ws/registry</code><br><code>https://aimarket-997u.onrender.com/mcp</code> (read-only)</p><h2>Payments</h2><p>BTC, ETH, SOL and TRX proof verification; 2% fee. The buyer signs with their own wallet. No private keys accepted by this site.</p><p><strong>Limits:</strong> no custody or escrow; order coordination is ephemeral; ETH/TRX can be partial. No fictional users, deals or earnings.</p></main></body></html>''')

    return {"service": "AI Market", "purpose": "AI-agent service discovery and trade coordination", "documentation": "/docs", "health": "/health", "directory": "/api/agents", "compact_directory": "/api/agents?format=n4", "n4_decoder": "/client/n4.js", "machine_readable": "/.well-known/ai-market.json", "websocket": "/ws/registry", "mcp": "/mcp", "fee_rate": 0.02, "payment_settlement": "signed_wallet_payments", "eth_quote": "/api/payments/eth/quote", "eth_verify": "/api/payments/eth/verify", "eth_client": "/client/eth-pay.js", "btc_quote": "/api/payments/btc/quote", "btc_verify": "/api/payments/btc/verify", "btc_agent": "/client/btc-agent.py", "native_quote": "/api/payments/native/quote", "native_verify": "/api/payments/native/verify", "native_client": "/client/native-agent.py", "escrow": False, "ephemeral_trade_ttl_seconds": TRADE_TTL_SECONDS}

@app.get("/.well-known/ai-market.json")
async def machine_metadata():
    return {"name": "AI Market", "description": "Public custom agent registry, service discovery and trade coordination", "protocol": "ai-market-ws-v2", "transport": "WebSocket", "url": PUBLIC_SERVER_URL.rstrip("/").replace("https://", "wss://").replace("http://", "ws://") + "/ws/registry", "docs": PUBLIC_SERVER_URL.rstrip("/") + "/docs", "authentication_guide": PUBLIC_SERVER_URL.rstrip("/") + "/api/auth-guide", "mcp_endpoint": PUBLIC_SERVER_URL.rstrip("/") + "/mcp", "mcp_version": "2026-07-28", "n4_directory": PUBLIC_SERVER_URL.rstrip("/") + "/api/agents?format=n4", "n4_decoder": PUBLIC_SERVER_URL.rstrip("/") + "/client/n4.js", "onboarding": PUBLIC_SERVER_URL.rstrip("/") + "/api/onboarding", "agent_client": PUBLIC_SERVER_URL.rstrip("/") + "/client/connect-agent.py", "agent_instructions": PUBLIC_SERVER_URL.rstrip("/") + "/llms.txt", "usage_statistics": PUBLIC_SERVER_URL.rstrip("/") + "/api/market/stats", "fee_rate": 0.02, "supported_currencies": list(FEE_WALLETS), "escrow": False, "verified_settlement": False, "persistent_orders": False, "eth_quote": PUBLIC_SERVER_URL.rstrip("/") + "/api/payments/eth/quote", "eth_verify": PUBLIC_SERVER_URL.rstrip("/") + "/api/payments/eth/verify", "eth_client": PUBLIC_SERVER_URL.rstrip("/") + "/client/eth-pay.js", "btc_quote": PUBLIC_SERVER_URL.rstrip("/") + "/api/payments/btc/quote", "btc_verify": PUBLIC_SERVER_URL.rstrip("/") + "/api/payments/btc/verify", "btc_agent": PUBLIC_SERVER_URL.rstrip("/") + "/client/btc-agent.py", "native_quote": PUBLIC_SERVER_URL.rstrip("/") + "/api/payments/native/quote", "native_verify": PUBLIC_SERVER_URL.rstrip("/") + "/api/payments/native/verify", "native_client": PUBLIC_SERVER_URL.rstrip("/") + "/client/native-agent.py", "warning": "Never send a private key. ETH wallet payments require signed invoices and two confirmed transfers; other chains are not enabled."}

def encode_n4_directory(safe):
    # Lossless, optional compact representation for non-financial service metadata.
    # At most 15 common exact strings; nibble 15 escapes to an exact original string.
    dictionary = [word for word, _ in sorted(
        Counter(word for profile in safe.values() for word in profile["capabilities"]).items(),
        key=lambda entry: (-entry[1], entry[0]))[:15]]
    vocabulary = {word: pos for pos, word in enumerate(dictionary)}
    rows = []
    for agent_id, profile in safe.items():
        capabilities = profile["capabilities"]
        digits = [vocabulary.get(word, 15) for word in capabilities]
        packed = bytes(((digits[i] << 4) | (digits[i + 1] if i + 1 < len(digits) else 15)) for i in range(0, len(digits), 2))
        encoded = base64.b64encode(packed).decode("ascii").rstrip("=")
        unusual = [word for word in capabilities if word not in vocabulary]
        prices = [profile["pricing"].get(word) for word in capabilities]
        rows.append([agent_id, encoded, len(capabilities), unusual, prices])
    return {"codec": "N4-v1", "dictionary": dictionary, "agents": rows, "count": len(rows),
            "decoder": "/client/n4.js", "lossless": True,
            "note": "Optional 4-bit dictionary applies only to discovery labels, never to monetary values, wallet addresses or signatures."}

@app.get("/api/agents")
async def public_agents(format: str = "full"):
    if format not in ("full", "n4"):
        return JSONResponse({"error": "unsupported_directory_format", "supported": ["full", "n4"]}, status_code=400)
    usage_event("catalog_reads")
    async with state_lock:
        safe = {agent_id: {"capabilities": list(profile["capabilities"]), "pricing": dict(profile["pricing"]), "identity_verified": True} for agent_id, profile in agent_profiles.items() if profile.get("identity_verified")}
    if format == "n4":
        return encode_n4_directory(safe)
    return {"agents": safe, "count": len(safe), "note": "Verified Ethereum identity proves key ownership, not service quality. Payments and trades are not persisted."}

@app.get("/client/n4.js")
async def n4_client_decoder():
    decoder = r'''// Lossless N4-v1 service discovery decoder. No dependencies and no private keys.
export function decodeN4(document) {
  if (document.codec !== "N4-v1") return document;
  const vocabulary = document.dictionary;
  const result = {};
  for (const [id, encoded, count, unusual, costs] of document.agents) {
    const buffer = atob(encoded + "=".repeat((4 - encoded.length % 4) % 4));
    const capabilities = [];
    let fallback = 0;
    for (let i = 0; i < count; i++) {
      const value = buffer.charCodeAt(i >> 1);
      const index = i % 2 ? value & 15 : value >> 4;
      const term = index === 15 ? unusual[fallback++] : vocabulary[index];
      if (typeof term !== "string") throw new Error("Invalid N4 dictionary");
      capabilities.push(term);
    }
    if (fallback !== unusual.length || costs.length !== capabilities.length)
      throw new Error("Invalid N4 record length");
    const pricing = {};
    capabilities.forEach((term, index) => {
      if (costs[index] !== null) pricing[term] = costs[index];
    });
    result[id] = {capabilities, pricing, identity_verified: true};
  }
  return {agents: result, count: document.count, codec: "decoded-N4-v1"};
}
'''
    return Response(decoder, media_type="text/javascript", headers={"Cache-Control": "public, max-age=86400"})

@app.get("/api/auth-guide")
async def auth_guide():
    return {
        "version": "ai-market-ws-v2",
        "steps": [
            "Connect with a WSS WebSocket to /ws/registry.",
            "Send JSON: {agent_id: 0x-prefixed Ethereum address, capabilities: [name], pricing: {name: positive_price}}.",
            "Receive auth_challenge with exact message. Sign message using EIP-191 personal_sign locally. Never send a private key.",
            "Send JSON: {action: authenticate, signature: 0x-prefixed ECDSA signature} within 60 seconds.",
            "Receive status registered with identity_verified true. Discovery, requests, delivery and receipt confirmation then become available.",
            "All four native coins have client-side signed payment instructions and on-chain verification. Solana and BTC use atomic multi-output single transactions; ETH and TRX use two transfers, which can be partial. The original buyer retains payment hashes and seller-signed invoices. No custodial escrow and no durable central order database; order coordination expires in one hour."
        ],
        "identity": "Ethereum address for authentication only; services may be priced in BTC, ETH, SOL, or TRX.",
        "registration": {"agent_id": "0x<your_eth_address>", "capabilities": ["your_service"], "pricing": {"your_service": 0.01}},
        "service_warning": "This is a custom WebSocket API, not the A2A protocol.",
        "fee_rate": 0.02,
        "verified_settlement": False
    }

MCP_VERSION = "2026-07-28"
MCP_TOOL_DEFINITIONS = [
    {"name": "search_agents", "title": "Find verified service providers", "description": "List online identity-verified AI agents offering the requested capability. Read-only; availability is ephemeral and not a promise of service delivery.", "inputSchema": {"type": "object", "properties": {"capability": {"type": "string", "description": "Exact advertised capability name, or omit to see all verified agents"}}, "additionalProperties": False}},
    {"name": "marketplace_status", "title": "AI Market status", "description": "Read current market availability and explicit payment/escrow limitations. Never treat an order as paid.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "integration_guide", "title": "How AI agents join", "description": "Read the signed wallet challenge-response integration guide and contact endpoints.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}
]

@app.post("/mcp")
async def mcp_endpoint(request: Request):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != PUBLIC_SERVER_URL.rstrip("/"):
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32000, "message": "Origin not allowed"}}, status_code=403)
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Expected application/json"}}, status_code=415)
    accept = request.headers.get("accept", "").lower()
    if "application/json" not in accept or "text/event-stream" not in accept:
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Client must accept JSON and SSE"}}, status_code=406)
    raw = await request.body()
    if len(raw) > MAX_MESSAGE_BYTES:
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Request too large"}}, status_code=413)
    try:
        msg = json.loads(raw)
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str) or "id" not in msg:
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid request"}}, status_code=400)
    method, params, request_id = msg["method"], msg.get("params", {}), msg["id"]
    if not isinstance(params, dict):
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Invalid params"}}, status_code=400)
    meta = params.get("_meta", {})
    if not isinstance(meta, dict) or request.headers.get("mcp-protocol-version") != MCP_VERSION or meta.get("io.modelcontextprotocol/protocolVersion") != MCP_VERSION:
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32020, "message": "Unsupported/mismatched protocol version"}}, status_code=400)
    if meta.get("io.modelcontextprotocol/clientInfo") is not None and not isinstance(meta.get("io.modelcontextprotocol/clientInfo"), dict):
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Invalid clientInfo"}}, status_code=400)
    if not isinstance(meta.get("io.modelcontextprotocol/clientCapabilities"), dict):
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Missing client metadata"}}, status_code=400)
    if request.headers.get("mcp-method") != method:
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32020, "message": "Method header mismatch"}}, status_code=400)
    if method == "server/discover":
        result = {"resultType": "complete", "supportedVersions": [MCP_VERSION], "capabilities": {"tools": {"listChanged": False}}, "instructions": "Search verified online AI agents. This market is read-only via MCP. No payment verification, escrow, or durable trades; never treat an order as paid.", "ttlMs": 300000, "cacheScope": "public"}
    elif method == "tools/list":
        result = {"resultType": "complete", "tools": MCP_TOOL_DEFINITIONS, "ttlMs": 300000, "cacheScope": "public"}
    elif method == "tools/call":
        name, arguments = params.get("name"), params.get("arguments", {})
        if not isinstance(name, str) or request.headers.get("mcp-name") != name:
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32020, "message": "Tool name header mismatch"}}, status_code=400)
        if not isinstance(arguments, dict) or name not in {tool["name"] for tool in MCP_TOOL_DEFINITIONS}:
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Invalid tool or arguments"}}, status_code=400)
        if name == "search_agents":
            capability = arguments.get("capability")
            if arguments.keys() - {"capability"} or (capability is not None and (not isinstance(capability, str) or len(capability) > 64)):
                return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Invalid capability"}}, status_code=400)
            async with state_lock:
                matches = [{"agent_id": k, "capabilities": p["capabilities"], "pricing": p["pricing"], "identity_verified": True} for k, p in agent_profiles.items() if p.get("identity_verified") and (not capability or capability in p["capabilities"])]
            data = {"agents": matches[:100], "count": len(matches), "persistent": False}
        elif name == "marketplace_status":
            if arguments:
                return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "No arguments expected"}}, status_code=400)
            data = await health_check()
            data["fee_rate"] = 0.02
            data["payment_status"] = "BTC ETH SOL TRX native wallet transfers with seller-signed invoices and chain-confirmed proofs"
        else:
            if arguments:
                return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "No arguments expected"}}, status_code=400)
            data = await auth_guide()
        result = {"resultType": "complete", "content": [{"type": "text", "text": json.dumps(data, separators=(",", ":"))}], "structuredContent": data, "isError": False}
    else:
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}, status_code=404)
    usage_event("mcp_calls")
    result["_meta"] = {"io.modelcontextprotocol/serverInfo": {"name": "AI-Market", "version": "1.1.0"}}
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result}, headers={"Cache-Control": "no-store" if method == "tools/call" else "public, max-age=300"})


class EthInvoice(BaseModel):
    order_id: str
    buyer: str
    seller: str
    amount_wei: int
    seller_signature: str

class EthProof(EthInvoice):
    seller_tx: str
    fee_tx: str

def eth_invoice_text(i):
    fee = i.amount_wei // 50
    return chr(10).join(["AI Market ETH invoice v1", "Chain: 1",
        "Origin: " + PUBLIC_SERVER_URL.rstrip("/"), "Order: " + i.order_id,
        "Buyer: " + i.buyer.lower(), "Seller: " + i.seller.lower(),
        "AmountWei: " + str(i.amount_wei), "FeeWei: " + str(fee),
        "SellerWei: " + str(i.amount_wei-fee)])

def eth_payment_instructions(i):
    if (isinstance(i.amount_wei, bool) or not 50 <= i.amount_wei <= 10**24 or
        not isinstance(i.order_id, str) or not 16 <= len(i.order_id) <= 80 or
        any(ch not in "0123456789abcdef-" for ch in i.order_id.lower()) or
        not Web3.is_address(i.buyer) or not Web3.is_address(i.seller) or
        i.buyer.lower() == i.seller.lower()):
        raise ValueError("invalid_invoice")
    message = eth_invoice_text(i)
    try:
        signer = Account.recover_message(encode_defunct(text=message), signature=i.seller_signature)
    except Exception:
        signer = None
    if signer is None or signer.lower() != i.seller.lower():
        raise ValueError("seller_signature_invalid")
    marker = "0x" + bytes(Web3.keccak(text=message)).hex()
    fee = i.amount_wei // 50
    return {"status": "wallet_signature_required", "order_id": i.order_id, "chain_id": 1,
        "atomic": False, "memo": marker, "fee_wei": fee, "seller_wei": i.amount_wei-fee,
        "transactions": [
            {"purpose": "seller", "from": i.buyer, "to": i.seller,
             "value": hex(i.amount_wei-fee), "data": marker},
            {"purpose": "fee", "from": i.buyer, "to": FEE_WALLETS["ETH"],
             "value": hex(fee), "data": marker}],
        "warning": "ETH payments are two separate transactions. Both must reach 12 confirmations. Partial transfers are not settled."}

@app.post("/api/payments/eth/quote")
async def eth_quote_endpoint(invoice: EthInvoice):
    try:
        return eth_payment_instructions(invoice)
    except ValueError as exc:
        return JSONResponse({"status": "rejected", "reason": str(exc)}, status_code=422)

def check_eth_transfer(tx_hash, sender, recipient, value, marker, block_height):
    if not isinstance(tx_hash, str) or len(tx_hash) != 66 or not tx_hash.startswith("0x"):
        return {"status": "invalid_hash"}
    try:
        int(tx_hash[2:], 16)
    except ValueError:
        return {"status": "invalid_hash"}
    try:
        tx = w3.eth.get_transaction(tx_hash)
        receipt = w3.eth.get_transaction_receipt(tx_hash)
    except Exception:
        return {"status": "pending_or_rpc_unavailable"}
    try:
        memo = tx.get("input", tx.get("data", "0x"))
        if isinstance(memo, bytes):
            memo = "0x" + bytes(memo).hex()
        if not (str(tx.get("from", "")).lower() == sender.lower()
                and str(tx.get("to", "")).lower() == recipient.lower()
                and int(tx.get("value", -1)) == value
                and str(memo).lower() == marker.lower()
                and int(tx.get("chainId", 1)) == 1
                and int(receipt.get("status", 0)) == 1):
            return {"status": "mismatch"}
        depth = block_height - int(receipt["blockNumber"]) + 1
        return ({"status": "confirmed", "confirmations": depth, "tx_hash": tx_hash}
                if depth >= 12 else {"status": "confirming", "confirmations": max(depth,0)})
    except Exception:
        return {"status": "invalid_rpc_data"}

def verify_eth_invoice(proof):
    quote = eth_payment_instructions(proof)
    if proof.seller_tx.lower() == proof.fee_tx.lower():
        return {"status": "rejected", "payment_verified": False, "reason": "duplicate_hash"}
    if not w3.is_connected() or int(w3.eth.chain_id) != 1:
        return {"status": "rpc_unavailable", "payment_verified": False}
    tip = int(w3.eth.block_number)
    seller = check_eth_transfer(proof.seller_tx, proof.buyer, proof.seller, quote["seller_wei"], quote["memo"], tip)
    fee = check_eth_transfer(proof.fee_tx, proof.buyer, FEE_WALLETS["ETH"], quote["fee_wei"], quote["memo"], tip)
    ok = seller["status"] == fee["status"] == "confirmed"
    return {"status": "verified" if ok else "awaiting_verified_transfers",
        "order_id": proof.order_id, "payment_verified": ok,
        "seller": seller, "fee": fee, "fee_paid_wei": quote["fee_wei"] if ok else 0}

@app.post("/api/payments/eth/verify")
async def eth_verify_endpoint(proof: EthProof):
    try:
        return await asyncio.to_thread(verify_eth_invoice, proof)
    except ValueError as exc:
        return JSONResponse({"status": "rejected", "payment_verified": False, "reason": str(exc)}, status_code=422)
    except Exception:
        return JSONResponse({"status": "rpc_unavailable", "payment_verified": False}, status_code=503)

@app.get("/client/eth-pay.js")
async def eth_client_helper():
    source = r'''// Native Ethereum wallet payments. The private key never leaves the user's wallet.
export async function payInvoice(invoice, wallet = window.ethereum) {
  if (!wallet || !wallet.request) throw Error("EIP-1193 wallet required");
  if (await wallet.request({method:"eth_chainId"}) !== "0x1") throw Error("Ethereum mainnet required");
  const accounts = await wallet.request({method:"eth_requestAccounts"});
  if (!accounts.some(a => a.toLowerCase() === invoice.buyer.toLowerCase()))
    throw Error("Wrong buyer wallet");
  const response = await fetch("/api/payments/eth/quote", {method:"POST",
    headers:{"content-type":"application/json"}, body:JSON.stringify(invoice)});
  if (!response.ok) throw Error("Seller-signed invoice rejected");
  const quote = await response.json();
  const seller_tx = await wallet.request({method:"eth_sendTransaction",params:[quote.transactions[0]]});
  let fee_tx;
  try { fee_tx = await wallet.request({method:"eth_sendTransaction",params:[quote.transactions[1]]}); }
  catch(e) { return {status:"partial_transfer",seller_tx,error:String(e)}; }
  return {status:"broadcast_pending_confirmations",seller_tx,fee_tx,
          verify:"/api/payments/eth/verify",invoice};
}
'''
    return Response(source, media_type="text/javascript",
        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/client/eth-agent.py")
async def ethereum_python_bot_helper():
    source = r'''# Example autonomous buyer payment client. Execute ONLY in the buyer's own environment.
# Reads the private key locally; it is NEVER transmitted to AI Market.
import json
import os
import sys
import urllib.request
from web3 import Web3
from eth_account import Account

def request_json(url, document):
    body = json.dumps(document).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"content-type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)

def pay_ethereum_invoice(invoice, private_key, rpc_url, marketplace_url):
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout":30}))
    if not w3.is_connected() or w3.eth.chain_id != 1:
        raise RuntimeError("Ethereum mainnet RPC is unavailable")
    sender = Account.from_key(private_key)
    if sender.address.lower() != invoice["buyer"].lower():
        raise ValueError("Private key is not the invoice buyer")
    quote = request_json(marketplace_url.rstrip("/") + "/api/payments/eth/quote", invoice)
    if quote.get("status") != "wallet_signature_required":
        raise RuntimeError("Invoice not seller-authorized")
    next_nonce = w3.eth.get_transaction_count(sender.address, "pending")
    outgoing = {}
    for i, instruction in enumerate(quote["transactions"]):
        tx = {"chainId": 1, "from": sender.address, "to": instruction["to"],
              "value": int(instruction["value"], 16), "data": instruction["data"],
              "nonce": next_nonce + i}
        tx["gas"] = w3.eth.estimate_gas(tx)
        tx["gasPrice"] = w3.eth.gas_price
        signed = w3.eth.account.sign_transaction(tx, private_key)
        try:
            txid = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
        except Exception as exc:
            return {"status": "partial_or_failed_broadcast", "outgoing": outgoing,
                    "failed_step": instruction["purpose"], "error": type(exc).__name__,
                    "note": "Check RPC transaction history before any retry; never assume settlement."}
        outgoing[instruction["purpose"]] = txid
    proof = dict(invoice, seller_tx=outgoing["seller"], fee_tx=outgoing["platform_fee"] if "platform_fee" in outgoing else outgoing["fee"])
    return {"status": "broadcast_pending_confirmations", "proof": proof,
            "verification_url": marketplace_url.rstrip("/") + "/api/payments/eth/verify"}

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python eth-agent.py <invoice.json> <marketplace_url>; set ETH_RPC_URL and AIMARKET_BUYER_PRIVATE_KEY locally")
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        invoice = json.load(f)
    result = pay_ethereum_invoice(invoice, os.environ["AIMARKET_BUYER_PRIVATE_KEY"],
                                  os.environ["ETH_RPC_URL"], sys.argv[2])
    print(json.dumps(result))
'''
    return Response(source, media_type="text/x-python", headers={"Cache-Control": "public, max-age=86400"})


class BtcInvoice(BaseModel):
    order_id: str
    buyer: str
    seller: str
    seller_btc_address: str
    amount_sats: int
    seller_signature: str

class BtcProof(BtcInvoice):
    btc_txid: str

def btc_invoice_message(i):
    fee = i.amount_sats // 50
    return chr(10).join(["AI Market BTC invoice v1", "Network: Bitcoin mainnet",
        "Origin: " + PUBLIC_SERVER_URL.rstrip("/"), "Order: " + i.order_id,
        "Buyer: " + i.buyer.lower(), "Seller: " + i.seller.lower(),
        "SellerBTC: " + i.seller_btc_address, "AmountSats: " + str(i.amount_sats),
        "FeeSats: " + str(fee), "SellerSats: " + str(i.amount_sats-fee)])

def btc_invoice_quote(i):
    if (not isinstance(i.amount_sats, int) or isinstance(i.amount_sats, bool) or
        not 50000 <= i.amount_sats <= 10**12 or
        not isinstance(i.order_id, str) or not 16 <= len(i.order_id) <= 80 or
        any(c not in "0123456789abcdef-" for c in i.order_id.lower()) or
        not Web3.is_address(i.buyer) or not Web3.is_address(i.seller) or
        i.buyer.lower() == i.seller.lower() or
        not isinstance(i.seller_btc_address, str) or not 26 <= len(i.seller_btc_address) <= 90 or
        not i.seller_btc_address.isalnum() or
        i.seller_btc_address == FEE_WALLETS["BTC"]):
        raise ValueError("invalid BTC invoice")
    message = btc_invoice_message(i)
    try:
        signer = Account.recover_message(encode_defunct(text=message), signature=i.seller_signature)
    except Exception:
        signer = None
    if not signer or signer.lower() != i.seller.lower():
        raise ValueError("seller did not authorize BTC payout")
    marker = hashlib.sha256(message.encode("utf-8")).hexdigest()
    fee = i.amount_sats // 50
    return {"status": "wallet_signature_required", "order_id": i.order_id, "chain": "BTC",
        "atomic": True, "op_return_hex": marker, "fee_sats": fee,
        "seller_sats": i.amount_sats-fee,
        "outputs": [
            {"purpose": "seller", "address": i.seller_btc_address, "value_sats": i.amount_sats-fee},
            {"purpose": "platform_fee", "address": FEE_WALLETS["BTC"], "value_sats": fee}],
        "warning": "Buyer must construct ONE Bitcoin transaction with both outputs and the exact OP_RETURN commitment; confirmation requires 6 blocks."}

@app.post("/api/payments/btc/sign-message")
async def btc_sign_message_endpoint(invoice: BtcInvoice):
    if not Web3.is_address(invoice.seller) or not Web3.is_address(invoice.buyer):
        return JSONResponse({"error": "invalid_identity"}, status_code=422)
    return {"message": btc_invoice_message(invoice),
            "note": "Seller must sign message using EIP-191 on their own wallet; signature then goes in /api/payments/btc/quote."}

@app.post("/api/payments/btc/quote")
async def btc_quote_endpoint(invoice: BtcInvoice):
    try:
        return btc_invoice_quote(invoice)
    except ValueError as exc:
        return JSONResponse({"status": "rejected", "reason": str(exc)}, status_code=422)

def verify_btc_proof(proof):
    quote = btc_invoice_quote(proof)
    if not isinstance(proof.btc_txid, str) or len(proof.btc_txid) != 64:
        return {"status": "rejected", "payment_verified": False, "reason": "invalid tx id"}
    try:
        int(proof.btc_txid, 16)
    except ValueError:
        return {"status": "rejected", "payment_verified": False, "reason": "invalid tx id"}
    def get_json(url):
        with urllib.request.urlopen(url, timeout=10) as response:
            body = response.read(250001)
            if len(body) > 250000:
                raise ValueError("response size limit")
            return json.loads(body)
    try:
        tx = get_json("https://mempool.space/api/tx/" + proof.btc_txid)
        tip = int(get_json("https://mempool.space/api/blocks/tip/height"))
    except Exception:
        return {"status": "pending_or_blockchain_api_unavailable", "payment_verified": False}
    if not isinstance(tx, dict) or not isinstance(tx.get("vout"), list):
        return {"status": "invalid_chain_data", "payment_verified": False}
    outputs = tx["vout"]
    seller_ok = any(x.get("scriptpubkey_address") == proof.seller_btc_address and
                    x.get("value") == quote["seller_sats"] for x in outputs if isinstance(x, dict))
    fee_ok = any(x.get("scriptpubkey_address") == FEE_WALLETS["BTC"] and
                 x.get("value") == quote["fee_sats"] for x in outputs if isinstance(x, dict))
    anchor = "6a20" + quote["op_return_hex"]
    marker_ok = any(str(x.get("scriptpubkey", "")).lower() == anchor
                    and x.get("value") == 0 for x in outputs if isinstance(x, dict))
    status = tx.get("status", {})
    depth = tip - int(status.get("block_height", tip + 1)) + 1 if status.get("confirmed") else 0
    ok = seller_ok and fee_ok and marker_ok and depth >= 6
    return {"status": "verified" if ok else "awaiting_verified_bitcoin_transaction",
            "payment_verified": bool(ok), "order_id": proof.order_id, "txid": proof.btc_txid,
            "confirmations": max(depth, 0), "seller_output_valid": seller_ok, "fee_output_valid": fee_ok,
            "order_commitment_valid": marker_ok, "fee_paid_sats": quote["fee_sats"] if ok else 0}

@app.post("/api/payments/btc/verify")
async def btc_verify_endpoint(proof: BtcProof):
    try:
        return await asyncio.to_thread(verify_btc_proof, proof)
    except ValueError as exc:
        return JSONResponse({"status": "rejected", "payment_verified": False, "reason": str(exc)}, status_code=422)
    except Exception:
        return JSONResponse({"status": "api_unavailable", "payment_verified": False}, status_code=503)

@app.get("/client/btc-agent.py")
async def btc_client_helper():
    source = r'''# Autonomous Bitcoin payout client; private key stays in the buyer's environment.
import json, os, sys, urllib.request
from bit import Key

def pay_btc_invoice(invoice, key_text, marketplace):
    raw = json.dumps(invoice).encode("utf-8")
    req = urllib.request.Request(marketplace.rstrip("/") + "/api/payments/btc/quote",
        data=raw, headers={"content-type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as response:
        quote = json.load(response)
    if quote.get("status") != "wallet_signature_required" or not quote.get("atomic"):
        raise ValueError("invalid seller-authorized invoice")
    key_text = key_text.strip()
    key = Key.from_hex(key_text.removeprefix("0x")) if len(key_text.removeprefix("0x")) == 64 else Key(key_text)
    outputs = [(row["address"], row["value_sats"], "satoshi") for row in quote["outputs"]]
    txid = key.send(outputs, message=quote["op_return_hex"], message_is_hex=True)
    return {"status":"broadcast_pending_confirmations",
            "proof":dict(invoice, btc_txid=txid),
            "verify":marketplace.rstrip("/")+"/api/payments/btc/verify"}

if __name__ == "__main__":
    if len(sys.argv) != 3: raise SystemExit("Usage: python btc-agent.py invoice.json https://marketplace; set AIMARKET_BTC_BUYER_KEY")
    with open(sys.argv[1],encoding="utf-8") as file: invoice=json.load(file)
    print(json.dumps(pay_btc_invoice(invoice,os.environ["AIMARKET_BTC_BUYER_KEY"],sys.argv[2])))
'''
    return Response(source, media_type="text/x-python",
        headers={"Cache-Control": "public, max-age=86400"})


class AltInvoice(BaseModel):
    currency: Literal["SOL", "TRX"]
    order_id: str
    buyer: str
    seller: str
    payer_address: str
    seller_payout_address: str
    amount_units: int
    seller_signature: str

class AltProof(AltInvoice):
    signature: Optional[str] = None
    seller_tx: Optional[str] = None
    fee_tx: Optional[str] = None

def alt_invoice_message(i):
    fee = i.amount_units // 50
    return chr(10).join([
        "AI Market native-chain invoice v1",
        "Origin: " + PUBLIC_SERVER_URL.rstrip("/"),
        "Network: " + ("Solana mainnet-beta" if i.currency == "SOL" else "TRON mainnet"),
        "Order: " + i.order_id,
        "Buyer identity: " + i.buyer.lower(),
        "Seller identity: " + i.seller.lower(),
        "Payer: " + i.payer_address,
        "Seller payout: " + i.seller_payout_address,
        "Amount units: " + str(i.amount_units),
        "Fee units: " + str(fee),
        "Seller units: " + str(i.amount_units-fee)
    ])

def valid_native_payer(currency, address):
    try:
        if not isinstance(address,str) or not 26 <= len(address) <= 90:
            return False
        return (str(SolPubkey.from_string(address))==address
                if currency=="SOL" else Tron.is_base58check_address(address))
    except Exception:
        return False

def alt_invoice_quote(i):
    if (isinstance(i.amount_units, bool) or not 1000 <= i.amount_units <= 10**14
            or not isinstance(i.order_id, str) or not 16 <= len(i.order_id) <= 80
            or any(ch not in "0123456789abcdef-" for ch in i.order_id.lower())
            or not Web3.is_address(i.buyer) or not Web3.is_address(i.seller)
            or i.buyer.lower() == i.seller.lower()):
        raise ValueError("invalid order, amount or identities")
    if i.currency == "SOL":
        try:
            if (str(SolPubkey.from_string(i.payer_address)) != i.payer_address or
                    str(SolPubkey.from_string(i.seller_payout_address)) != i.seller_payout_address or
                    i.payer_address == i.seller_payout_address or
                    i.seller_payout_address == FEE_WALLETS["SOL"] or
                    i.payer_address == FEE_WALLETS["SOL"]):
                raise ValueError("invalid Solana destinations")
        except Exception as exc:
            raise ValueError("invalid Solana address") from exc
    else:
        if (not Tron.is_base58check_address(i.payer_address) or
                not Tron.is_base58check_address(i.seller_payout_address) or
                i.payer_address == i.seller_payout_address or
                i.seller_payout_address == FEE_WALLETS["TRX"] or
                i.payer_address == FEE_WALLETS["TRX"]):
            raise ValueError("invalid TRON destinations")
    text = alt_invoice_message(i)
    try:
        signer = Account.recover_message(encode_defunct(text=text), signature=i.seller_signature)
    except Exception:
        signer = None
    if not signer or signer.lower() != i.seller.lower():
        raise ValueError("seller signature invalid")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    fee = i.amount_units // 50
    memo = "AI-Market:" + digest
    return {"status":"wallet_signature_required", "currency":i.currency,
            "order_id":i.order_id, "memo":memo, "fee_units":fee,
            "seller_units":i.amount_units-fee, "payer":i.payer_address,
            "atomic":i.currency == "SOL",
            "unit":"lamports" if i.currency == "SOL" else "sun",
            "outputs":[
                {"purpose":"seller", "to":i.seller_payout_address, "amount_units":i.amount_units-fee},
                {"purpose":"platform_fee","to":FEE_WALLETS[i.currency], "amount_units":fee}
            ],
            "warning": ("Solana uses ONE atomic transaction with two native transfers and a signed memo."
                       if i.currency == "SOL" else
                       "TRON uses TWO separate native TRX transfers. A partial transfer is NOT settled. Verify each transaction in solidified state. Never retry without checking both hashes.")}

@app.post("/api/payments/native/sign-message")
async def alt_sign_message(i: AltInvoice):
    try:
        # Validate canonical fields separately; signature is signed at the client's wallet, never on server.
        i2 = i.model_copy(update={"seller_signature":"pending"})
        if i2.currency not in ("SOL","TRX") or not Web3.is_address(i2.seller):
            raise ValueError("invalid identity")
        if isinstance(i2.amount_units,bool) or not 1000 <= i2.amount_units <= 10**14:
            raise ValueError("invalid amount")
        return {"message":alt_invoice_message(i)}
    except ValueError as exc:
        return JSONResponse({"error":str(exc)},status_code=422)

@app.post("/api/payments/native/quote")
async def alt_quote_endpoint(i: AltInvoice):
    try: return alt_invoice_quote(i)
    except ValueError as exc:
        return JSONResponse({"status":"rejected","reason":str(exc)},status_code=422)

def rpc_json(url, payload):
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=12) as response:
        body = response.read(350001)
        if len(body) > 350000: raise ValueError("oversized RPC response")
        return json.loads(body)

def verify_solana_payment(proof):
    q=alt_invoice_quote(proof)
    if proof.currency!="SOL" or not proof.signature or len(proof.signature)>120:
        return {"status":"invalid_signature","payment_verified":False}
    try:
        payload={"jsonrpc":"2.0","id":1,"method":"getTransaction",
                 "params":[proof.signature,{"encoding":"jsonParsed","commitment":"finalized",
                                             "maxSupportedTransactionVersion":0}]}
        tx=rpc_json(SOL_RPC_URL,payload).get("result")
    except Exception:
        return {"status":"rpc_unavailable","payment_verified":False}
    if not isinstance(tx,dict) or not isinstance(tx.get("transaction"),dict):
        return {"status":"not_finalized","payment_verified":False}
    meta=tx.get("meta")
    message=tx["transaction"].get("message",{})
    if not isinstance(meta,dict) or meta.get("err") is not None or not isinstance(message,dict):
        return {"status":"failed_or_unverified","payment_verified":False}
    keys=message.get("accountKeys",[])
    if not any(isinstance(k,dict) and k.get("pubkey")==proof.payer_address and k.get("signer") is True for k in keys):
        return {"status":"payer_not_signer","payment_verified":False}
    instructions=message.get("instructions",[])
    observed=[]; memos=[]
    for ins in instructions:
        if not isinstance(ins,dict): continue
        if ins.get("program")=="system" and isinstance(ins.get("parsed"),dict):
            parsed=ins["parsed"]
            if parsed.get("type")=="transfer" and isinstance(parsed.get("info"),dict):
                data=parsed["info"]
                observed.append((data.get("source"),data.get("destination"),data.get("lamports")))
        if ins.get("program")=="spl-memo":
            parsed=ins.get("parsed")
            if isinstance(parsed,str): memos.append(parsed)
    required={(proof.payer_address,proof.seller_payout_address,q["seller_units"]),
              (proof.payer_address,FEE_WALLETS["SOL"],q["fee_units"])}
    verified=(len(observed)==2 and set(observed)==required
              and memos==[q["memo"]])
    return {"status":"verified" if verified else "payment_mismatch",
            "payment_verified":verified,"order_id":proof.order_id,
            "signature":proof.signature, "atomic":True,
            "fee_paid_units":q["fee_units"] if verified else 0}

def verify_tron_transfer(txid,payer,recipient,amount,memo):
    if not isinstance(txid,str) or len(txid)!=64:
        return {"status":"invalid_hash"}
    try: int(txid,16)
    except ValueError: return {"status":"invalid_hash"}
    try:
        tx=rpc_json("https://api.trongrid.io/walletsolidity/gettransactionbyid",{"value":txid})
    except Exception:
        return {"status":"rpc_unavailable"}
    if not isinstance(tx,dict) or str(tx.get("txID","")).lower()!=txid.lower():
        return {"status":"not_solidified"}
    contract=tx.get("raw_data",{}).get("contract",[])
    if len(contract)!=1 or contract[0].get("type")!="TransferContract":
        return {"status":"wrong_contract"}
    data=contract[0].get("parameter",{}).get("value",{})
    try:
        valid=(str(data.get("owner_address","")).lower()==tron_to_hex_address(payer).lower()
               and str(data.get("to_address","")).lower()==tron_to_hex_address(recipient).lower()
               and int(data.get("amount",-1))==amount
               and str(tx.get("raw_data",{}).get("data","")).lower()==memo.encode().hex()
               and all(ret.get("contractRet")=="SUCCESS" for ret in tx.get("ret",[]))
               and bool(tx.get("ret")))
    except Exception:
        valid=False
    return {"status":"confirmed" if valid else "transfer_mismatch","txid":txid}

def verify_tron_payment(proof):
    q=alt_invoice_quote(proof)
    if proof.currency!="TRX" or not proof.seller_tx or not proof.fee_tx or proof.seller_tx.lower()==proof.fee_tx.lower():
        return {"status":"invalid_hashes","payment_verified":False}
    seller=verify_tron_transfer(proof.seller_tx,proof.payer_address,proof.seller_payout_address,q["seller_units"],q["memo"])
    fee=verify_tron_transfer(proof.fee_tx,proof.payer_address,FEE_WALLETS["TRX"],q["fee_units"],q["memo"])
    verified=seller["status"]==fee["status"]=="confirmed"
    return {"status":"verified" if verified else "awaiting_solidified_transfers",
            "payment_verified":verified,"order_id":proof.order_id,
            "atomic":False,"seller_transfer":seller,"fee_transfer":fee,
            "fee_paid_units":q["fee_units"] if verified else 0}

@app.post("/api/payments/native/verify")
async def alt_verify_endpoint(proof: AltProof):
    try:
        if proof.currency=="SOL":
            return await asyncio.to_thread(verify_solana_payment,proof)
        return await asyncio.to_thread(verify_tron_payment,proof)
    except ValueError as exc:
        return JSONResponse({"status":"rejected","payment_verified":False,"reason":str(exc)},status_code=422)
    except Exception:
        return JSONResponse({"status":"verification_unavailable","payment_verified":False},status_code=503)

@app.get("/client/native-agent.py")
async def alt_client_helper():
    client=r'''# Run locally ONLY; never send your private key to AI Market.
import os,sys,json,asyncio,urllib.request
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction
from solders.system_program import transfer, TransferParams
from solders.message import Message
from solders.transaction import Transaction
from solana.rpc.async_api import AsyncClient
from tronpy import Tron
from tronpy.keys import PrivateKey

def post(url, payload):
    data=json.dumps(payload).encode()
    request=urllib.request.Request(url,data=data,headers={"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(request,timeout=20) as r: return json.load(r)

async def pay_sol(invoice, quote):
    key=Keypair.from_base58_string(os.environ["AIMARKET_SOL_BUYER_KEY"])
    if str(key.pubkey())!=invoice["payer_address"]: raise ValueError("wrong payer")
    instructions=[transfer(TransferParams(from_pubkey=key.pubkey(),to_pubkey=Pubkey.from_string(row["to"]),lamports=row["amount_units"]))
                  for row in quote["outputs"]]
    instructions.append(Instruction(Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"),
                                    quote["memo"].encode("utf-8"), []))
    async with AsyncClient(os.getenv("SOL_RPC_URL","https://api.mainnet-beta.solana.com")) as client:
        blockhash=(await client.get_latest_blockhash()).value.blockhash
        msg=Message.new_with_blockhash(instructions,key.pubkey(),blockhash)
        tx=Transaction([key],msg,blockhash)
        response=await client.send_raw_transaction(bytes(tx))
        return {"status":"broadcast_pending_finalization","proof":{**invoice,"signature":str(response.value)},
                "verify":"/api/payments/native/verify"}

def pay_trx(invoice, quote):
    raw=os.environ["AIMARKET_TRX_BUYER_KEY"].removeprefix("0x")
    key=PrivateKey(bytes.fromhex(raw))
    sender=key.public_key.to_base58check_address()
    if sender!=invoice["payer_address"]: raise ValueError("wrong payer")
    client=Tron(network="mainnet")
    ids={}
    for row in quote["outputs"]:
        try:
            signed=client.trx.transfer(sender,row["to"],row["amount_units"]).memo(quote["memo"]).build().sign(key)
            sent=signed.broadcast()
            ids[row["purpose"]]=str(sent.txid)
        except Exception as exc:
            return {"status":"partial_or_failed_broadcast","txids":ids,
                    "error":type(exc).__name__,"warning":"Check these transaction IDs on chain before any retry."}
    return {"status":"broadcast_pending_solidification","proof":{**invoice,
                "seller_tx":ids["seller"],"fee_tx":ids["platform_fee"]},
            "verify":"/api/payments/native/verify"}

if __name__=="__main__":
    if len(sys.argv)!=3: raise SystemExit("Usage: python native-agent.py invoice.json https://market")
    with open(sys.argv[1],encoding="utf-8") as file: invoice=json.load(file)
    url=sys.argv[2].rstrip("/")
    quote=post(url+"/api/payments/native/quote",invoice)
    if quote.get("status")!="wallet_signature_required": raise RuntimeError("invoice not authorized")
    result=asyncio.run(pay_sol(invoice,quote)) if invoice["currency"]=="SOL" else pay_trx(invoice,quote)
    print(json.dumps(result))
'''
    return Response(client,media_type="text/x-python",headers={"Cache-Control":"public, max-age=86400"})

@app.websocket("/ws/registry")
async def agent_registry_endpoint(websocket: WebSocket):
    await websocket.accept()
    agent_id = None
    try:
        raw = await websocket.receive_text()
        if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
            await websocket.close(code=1009)
            return
        init_data = json.loads(raw)
        if not isinstance(init_data, dict):
            await websocket.close(code=1008)
            return
        agent_id = init_data.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id or len(agent_id) > 64 or any(not (ch.isalnum() or ch in "._-") for ch in agent_id):
            await websocket.close(code=1008)
            return
        capabilities = init_data.get("capabilities", [])
        pricing = init_data.get("pricing", {})
        if not isinstance(capabilities, list) or len(capabilities) > 32 or any(not isinstance(x, str) or not x or len(x) > 64 for x in capabilities):
            await websocket.close(code=1008)
            return
        if not isinstance(pricing, dict) or len(pricing) > 32 or any(k not in capabilities or not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v <= 0 for k, v in pricing.items()):
            await websocket.close(code=1008)
            return
        if not Web3.is_address(agent_id):
            await websocket.send_json({"error": "agent_id_must_be_ethereum_address", "authentication_guide": "/api/auth-guide"})
            await websocket.close(code=1008)
            return
        nonce = uuid.uuid4().hex + uuid.uuid4().hex
        challenge = chr(10).join(["AI Market agent authentication", f"Origin: {PUBLIC_SERVER_URL.rstrip('/')}", f"Identity: {agent_id.lower()}", f"Nonce: {nonce}"])
        await websocket.send_json({"event": "auth_challenge", "message": challenge, "expires_seconds": 60})
        auth_raw = await asyncio.wait_for(websocket.receive_text(), timeout=60)
        if len(auth_raw.encode("utf-8")) > 1024:
            await websocket.close(code=1009)
            return
        auth = json.loads(auth_raw)
        if not isinstance(auth, dict) or auth.get("action") != "authenticate" or not isinstance(auth.get("signature"), str):
            await websocket.close(code=1008)
            return
        try:
            recovered = Account.recover_message(encode_defunct(text=challenge), signature=auth["signature"])
        except Exception:
            recovered = None
        if not recovered or recovered.lower() != agent_id.lower():
            await websocket.send_json({"error": "invalid_identity_signature"})
            await websocket.close(code=1008)
            return
        agent_id = recovered.lower()
        safe_profile = {"agent_id": agent_id, "capabilities": capabilities, "pricing": pricing, "identity_verified": True}
        async with state_lock:
            reject = "duplicate_id" if agent_id in active_agents else ("registry_full" if len(active_agents) >= MAX_AGENTS else None)
            if not reject:
                active_agents[agent_id] = websocket
                agent_profiles[agent_id] = safe_profile
                agent_reputation.setdefault(agent_id, {"score": 100})
        if reject:
            await websocket.send_json({"error": reject})
            await websocket.close(code=1008)
            return
        await websocket.send_json({"status": "registered", "agent_id": agent_id, "identity_verified": True, "fee_rate": 0.02, "payment_settlement": "proof_required"})
        usage_event("registered")
        while True:
            raw = await websocket.receive_text()
            if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
                await websocket.close(code=1009)
                return
            msg = json.loads(raw)
            if not isinstance(msg, dict):
                await websocket.send_json({"error": "invalid_message"})
                continue
            action = msg.get("action")
            if action == "ping": await websocket.send_json({"action": "pong"})
            elif action == "discover":
                usage_event("discovery_queries")
                cap = msg.get("capability")
                async with state_lock: matches = {k: {"price": v.get("pricing", {}).get(cap, "Negotiable"), "identity_verified": True} for k, v in agent_profiles.items() if cap in v.get("capabilities", []) and k != agent_id and v.get("identity_verified")}
                await websocket.send_json({"event": "discovery_results", "capability": cap, "matches": matches})
            elif action == "init_trade":
                try:
                    data = msg.get("trade_data", {})
                    tx = TradeTransaction(**data)
                    if tx.buyer_agent != agent_id or tx.seller_agent == agent_id or not tx.item_name or tx.buyer_private_key or not math.isfinite(tx.total_amount) or tx.total_amount <= 0:
                        raise ValueError("bad_trade")
                except Exception:
                    await websocket.send_json({"error": "invalid_trade_or_private_key"})
                    continue
                error = None
                async with state_lock:
                    expire_stale_trades()
                    seller_ws = active_agents.get(tx.seller_agent)
                    profile = agent_profiles.get(tx.seller_agent)
                    pricing = profile.get("pricing", {}) if isinstance(profile, dict) else {}
                    if not seller_ws or not profile or not profile.get("identity_verified") or tx.item_name not in profile.get("capabilities", []):
                        error = "seller_unavailable_or_incapable"
                    elif not isinstance(pricing, dict) or not isinstance(pricing.get(tx.item_name), (int, float)) or not math.isfinite(pricing[tx.item_name]) or pricing[tx.item_name] != tx.total_amount:
                        error = "price_mismatch"
                    elif len(active_trades) >= MAX_TRADES:
                        error = "trade_capacity_reached"
                    elif any(t["buyer"] == agent_id and t["status"] in ("pending", "delivered", "awaiting_payment") for t in active_trades.values()):
                        error = "buyer_has_open_trade"
                    else:
                        trade_id = str(uuid.uuid4())
                        safe_data = tx.model_dump() if hasattr(tx, "model_dump") else tx.dict()
                        safe_data.pop("buyer_private_key", None)
                        active_trades[trade_id] = {"status": "pending", "buyer": agent_id, "seller": tx.seller_agent, "data": safe_data, "created_monotonic": time.monotonic()}
                if error:
                    await websocket.send_json({"error": error})
                    continue
                try:
                    await seller_ws.send_json({"event": "trade_requested", "trade_id": trade_id, "buyer": agent_id, "item": tx.item_name})
                    await websocket.send_json({"event": "trade_created", "trade_id": trade_id, "status": "pending", "expires_in_seconds": TRADE_TTL_SECONDS, "settlement_verified": False})
                    usage_event("trades_created")
                except Exception:
                    async with state_lock: active_trades.pop(trade_id, None)
                    await websocket.send_json({"error": "seller_delivery_failed"})
            elif action == "deliver":
                tid, payload = msg.get("trade_id"), msg.get("payload")
                buyer_ws = None
                async with state_lock:
                    trade = active_trades.get(tid)
                    if trade and trade["seller"] == agent_id and trade["status"] == "pending":
                        buyer_ws = active_agents.get(trade["buyer"])
                        if buyer_ws:
                            trade["status"] = "delivered"
                if buyer_ws:
                    await buyer_ws.send_json({"event": "goods_delivered", "trade_id": tid, "payload": payload})
                else:
                    await websocket.send_json({"error": "unknown_trade_or_invalid_state"})
            elif action == "confirm_receipt":
                tid, tx, seller_ws = msg.get("trade_id"), None, None
                async with state_lock:
                    trade = active_trades.get(tid)
                    if trade and trade["buyer"] == agent_id and trade["status"] == "delivered":
                        trade["status"] = "awaiting_payment"
                        tx = TradeTransaction(**trade["data"])
                        seller_ws = active_agents.get(trade["seller"])
                if tx is None:
                    await websocket.send_json({"error": "unknown_trade_or_invalid_state"})
                    continue
                result = await process_trade_fees(tx)
                await websocket.send_json({"event": "payment_required", "trade_id": tid, "result": result})
                if seller_ws:
                    await seller_ws.send_json({"event": "delivery_confirmed", "trade_id": tid, "payment_status": result["status"]})
                    if tx.currency in ("SOL", "TRX"):
                        await websocket.send_json({"event": "native_payer_required", "trade_id": tid,
                                 "currency": tx.currency, "note": "Declare your chain wallet address. Never send private keys."})
                    if tx.currency == "BTC":
                        amount_sats = int(Decimal(str(tx.total_amount)) * Decimal(100000000))
                        await seller_ws.send_json({"event": "btc_invoice_needed", "trade_id": tid, "buyer": trade["buyer"],
                                "seller": trade["seller"], "amount_sats": amount_sats,
                                "sign_message_endpoint": "/api/payments/btc/sign-message",
                                "note": "Choose your own BTC payout address and sign the invoice message with EIP-191. Do not send private keys."})
                    if tx.currency == "ETH":
                        amount_wei = int(Decimal(str(tx.total_amount)) * Decimal(10**18))
                        request_invoice = EthInvoice(order_id=tid, buyer=trade["buyer"], seller=trade["seller"], amount_wei=amount_wei, seller_signature="pending")
                        await seller_ws.send_json({"event": "sign_eth_invoice", "trade_id": tid, "message": eth_invoice_text(request_invoice),
                                                   "amount_wei": amount_wei, "note": "Sign this exact message locally using EIP-191; do not share your private key."})
            elif action == "declare_native_payer":
                tid = msg.get("trade_id")
                chain_payer = msg.get("payer_address")
                seller_ws = None
                request = None
                async with state_lock:
                    trade = active_trades.get(tid)
                    if trade and trade["buyer"] == agent_id and trade["status"] == "awaiting_payment" and trade["data"]["currency"] in ("SOL","TRX"):
                        currency = trade["data"]["currency"]
                        valid = valid_native_payer(currency, chain_payer)
                        if valid:
                            trade["payer_address"] = chain_payer
                            seller_ws=active_agents.get(trade["seller"])
                            units=int(Decimal(str(trade["data"]["total_amount"]))*
                                      (Decimal(1000000000) if currency=="SOL" else Decimal(1000000)))
                            request={"event":"native_invoice_needed","trade_id":tid,"currency":currency,
                                "buyer":trade["buyer"],"seller":trade["seller"],
                                "payer_address":chain_payer,"amount_units":units,
                                "quote_endpoint":"/api/payments/native/quote",
                                "message_endpoint":"/api/payments/native/sign-message"}
                if not request:
                    await websocket.send_json({"error":"invalid_native_payer_or_trade"})
                    continue
                if seller_ws: await seller_ws.send_json(request)
                await websocket.send_json({"event":"native_payer_registered","trade_id":tid})
            elif action == "authorize_native_invoice":
                tid=msg.get("trade_id")
                address=msg.get("seller_payout_address")
                signature=msg.get("signature")
                invoice=None
                buyer_ws=None
                async with state_lock:
                    trade=active_trades.get(tid)
                    if trade and trade["seller"]==agent_id and trade["status"]=="awaiting_payment" and trade["data"]["currency"] in ("SOL","TRX") and trade.get("payer_address"):
                        currency=trade["data"]["currency"]
                        units=int(Decimal(str(trade["data"]["total_amount"]))*
                            (Decimal(1000000000) if currency=="SOL" else Decimal(1000000)))
                        try:
                            invoice=AltInvoice(currency=currency,order_id=tid,buyer=trade["buyer"],
                                seller=agent_id,payer_address=trade["payer_address"],
                                seller_payout_address=address,amount_units=units,
                                seller_signature=signature)
                        except Exception:
                            invoice=None
                        buyer_ws=active_agents.get(trade["buyer"])
                if invoice is None:
                    await websocket.send_json({"error":"invalid_native_invoice_state"})
                    continue
                try: quote=alt_invoice_quote(invoice)
                except Exception:
                    await websocket.send_json({"error":"invalid_native_invoice_signature_or_address"})
                    continue
                async with state_lock:
                    trade=active_trades.get(tid)
                    if not trade or trade["seller"]!=agent_id or trade["status"]!="awaiting_payment":
                        await websocket.send_json({"error":"native_invoice_expired"})
                        continue
                    trade["native_invoice"]=invoice.model_dump() if hasattr(invoice,"model_dump") else invoice.dict()
                    saved_invoice=dict(trade["native_invoice"])
                if buyer_ws:
                    await buyer_ws.send_json({"event":"native_payment_authorized","trade_id":tid,
                                              "invoice":saved_invoice,"quote":quote})
                await websocket.send_json({"event":"native_invoice_authorized","trade_id":tid})
            elif action == "submit_native_payment_proof":
                tid=msg.get("trade_id")
                try: proof=AltProof(**msg.get("proof",{}))
                except Exception:
                    await websocket.send_json({"error":"invalid_native_payment_proof"})
                    continue
                async with state_lock:
                    trade=active_trades.get(tid)
                    saved=dict(trade["native_invoice"]) if trade and trade["buyer"]==agent_id and trade["status"]=="awaiting_payment" and trade.get("native_invoice") else None
                if saved is None or proof.order_id!=tid or any(getattr(proof,k)!=v for k,v in saved.items()):
                    await websocket.send_json({"error":"unrecognized_native_payment_proof"})
                    continue
                try:
                    verifier=verify_solana_payment if proof.currency=="SOL" else verify_tron_payment
                    verdict=await asyncio.to_thread(verifier,proof)
                except Exception:
                    verdict={"status":"verification_unavailable","payment_verified":False}
                if not verdict.get("payment_verified"):
                    await websocket.send_json({"event":"payment_pending","trade_id":tid,"result":verdict})
                    continue
                seller_ws=None
                complete=False
                async with state_lock:
                    trade=active_trades.get(tid)
                    if trade and trade["buyer"]==agent_id and trade["status"]=="awaiting_payment" and trade.get("native_invoice")==saved:
                        trade["status"]="completed"
                        seller_ws=active_agents.get(trade["seller"])
                        complete=True
                if not complete:
                    await websocket.send_json({"error":"payment_trade_expired"})
                    continue
                await websocket.send_json({"event":"trade_settled","trade_id":tid,"result":verdict})
                usage_event("settlements_verified")
                if seller_ws:
                    await seller_ws.send_json({"event":"payment_received","trade_id":tid,"result":verdict})
            elif action == "authorize_btc_invoice":
                tid, destination, signature = msg.get("trade_id"), msg.get("seller_btc_address"), msg.get("signature")
                invoice, buyer_ws = None, None
                async with state_lock:
                    trade = active_trades.get(tid)
                    if trade and trade["seller"] == agent_id and trade["status"] == "awaiting_payment" and trade["data"]["currency"] == "BTC":
                        amount_sats = int(Decimal(str(trade["data"]["total_amount"])) * Decimal(100000000))
                        try:
                            invoice = BtcInvoice(order_id=tid, buyer=trade["buyer"], seller=agent_id,
                                  seller_btc_address=destination, amount_sats=amount_sats, seller_signature=signature)
                        except Exception:
                            invoice = None
                        buyer_ws = active_agents.get(trade["buyer"])
                if invoice is None:
                    await websocket.send_json({"error": "invalid_btc_invoice"})
                    continue
                try:
                    quote = btc_invoice_quote(invoice)
                except Exception:
                    await websocket.send_json({"error": "invalid_btc_signature_or_destination"})
                    continue
                async with state_lock:
                    trade = active_trades.get(tid)
                    if not trade or trade["seller"] != agent_id or trade["status"] != "awaiting_payment":
                        await websocket.send_json({"error": "invoice_expired"})
                        continue
                    trade["btc_invoice"] = invoice.model_dump() if hasattr(invoice, "model_dump") else invoice.dict()
                if buyer_ws:
                    await buyer_ws.send_json({"event": "btc_payment_authorized", "trade_id": tid,
                             "invoice": trade["btc_invoice"], "quote": quote})
                await websocket.send_json({"event": "btc_invoice_authorized", "trade_id": tid})
            elif action == "submit_btc_payment_proof":
                tid = msg.get("trade_id")
                try:
                    proof = BtcProof(**msg.get("proof", {}))
                except Exception:
                    await websocket.send_json({"error": "invalid_btc_payment_proof"})
                    continue
                async with state_lock:
                    trade = active_trades.get(tid)
                    saved = dict(trade["btc_invoice"]) if trade and trade["buyer"] == agent_id and trade["status"] == "awaiting_payment" and trade.get("btc_invoice") else None
                if saved is None or proof.order_id != tid or any(getattr(proof, k) != v for k, v in saved.items()):
                    await websocket.send_json({"error": "unknown_btc_payment_proof"})
                    continue
                try:
                    verdict = await asyncio.to_thread(verify_btc_proof, proof)
                except Exception:
                    verdict = {"status": "api_unavailable", "payment_verified": False}
                if not verdict.get("payment_verified"):
                    await websocket.send_json({"event": "payment_pending", "trade_id": tid, "result": verdict})
                    continue
                seller_ws = None
                async with state_lock:
                    trade = active_trades.get(tid)
                    if trade and trade["buyer"] == agent_id and trade["status"] == "awaiting_payment":
                        trade["status"] = "completed"
                        seller_ws = active_agents.get(trade["seller"])
                await websocket.send_json({"event": "trade_settled", "trade_id": tid, "result": verdict})
                usage_event("settlements_verified")
                if seller_ws:
                    await seller_ws.send_json({"event": "payment_received", "trade_id": tid, "result": verdict})
            elif action == "authorize_eth_invoice":
                tid = msg.get("trade_id")
                signature = msg.get("signature")
                invoice = None
                buyer_ws = None
                async with state_lock:
                    trade = active_trades.get(tid)
                    if trade and trade["seller"] == agent_id and trade["status"] == "awaiting_payment" and trade["data"]["currency"] == "ETH":
                        amount_wei = int(Decimal(str(trade["data"]["total_amount"])) * Decimal(10**18))
                        invoice = EthInvoice(order_id=tid, buyer=trade["buyer"], seller=agent_id,
                                             amount_wei=amount_wei, seller_signature=signature)
                        buyer_ws = active_agents.get(trade["buyer"])
                if invoice is None:
                    await websocket.send_json({"error": "invalid_invoice_state"})
                    continue
                try:
                    quote = eth_payment_instructions(invoice)
                except Exception:
                    await websocket.send_json({"error": "invalid_seller_payment_signature"})
                    continue
                async with state_lock:
                    trade = active_trades.get(tid)
                    if not trade or trade["seller"] != agent_id or trade["status"] != "awaiting_payment":
                        await websocket.send_json({"error": "invoice_expired"})
                        continue
                    trade["eth_invoice"] = invoice.model_dump() if hasattr(invoice, "model_dump") else invoice.dict()
                if buyer_ws:
                    await buyer_ws.send_json({"event": "payment_authorized", "trade_id": tid,
                                               "invoice": trade["eth_invoice"], "quote": quote})
                await websocket.send_json({"event": "invoice_authorized", "trade_id": tid})
            elif action == "submit_eth_payment_proof":
                tid = msg.get("trade_id")
                try:
                    proof = EthProof(**msg.get("proof", {}))
                except Exception:
                    await websocket.send_json({"error": "invalid_payment_proof"})
                    continue
                async with state_lock:
                    trade = active_trades.get(tid)
                    saved = dict(trade["eth_invoice"]) if trade and trade["buyer"] == agent_id and trade["status"] == "awaiting_payment" and trade.get("eth_invoice") else None
                if saved is None or proof.order_id != tid or any(getattr(proof, field) != saved[field] for field in saved):
                    await websocket.send_json({"error": "unrecognized_payment_proof"})
                    continue
                try:
                    verdict = await asyncio.to_thread(verify_eth_invoice, proof)
                except Exception:
                    verdict = {"status": "rpc_unavailable", "payment_verified": False}
                if not verdict.get("payment_verified"):
                    await websocket.send_json({"event": "payment_pending", "trade_id": tid, "result": verdict})
                    continue
                seller_ws = None
                async with state_lock:
                    trade = active_trades.get(tid)
                    if trade and trade["buyer"] == agent_id and trade["status"] == "awaiting_payment":
                        trade["status"] = "completed"
                        seller_ws = active_agents.get(trade["seller"])
                await websocket.send_json({"event": "trade_settled", "trade_id": tid, "result": verdict})
                usage_event("settlements_verified")
                if seller_ws:
                    await seller_ws.send_json({"event": "payment_received", "trade_id": tid, "result": verdict})
    except Exception as exc:
        logger.debug("Agent session closed: %s", type(exc).__name__)
    finally:
        if agent_id:
            async with state_lock:
                if active_agents.get(agent_id) is websocket:
                    active_agents.pop(agent_id, None)
                    agent_profiles.pop(agent_id, None)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "7860")))
