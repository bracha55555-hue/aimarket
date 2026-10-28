import os, asyncio, urllib.request, json, uuid, math, logging, base64, time, hashlib, html, hmac, secrets, re
from urllib.parse import urlsplit
import ipaddress
from datetime import datetime, timezone
from decimal import Decimal
from collections import Counter
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import JSONResponse, Response, HTMLResponse, FileResponse
from pathlib import Path
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
open_needs: Dict[str, dict] = {}
signed_offers: Dict[str, dict] = {}
used_offer_proofs: Dict[str, int] = {}
OFFER_CHALLENGE_SECRET = secrets.token_bytes(32)
OFFER_TTL_SECONDS = 43200
OFFER_CHALLENGE_SECONDS = 300
MAX_PUBLIC_NEEDS = 100
NEED_TTL_SECONDS = 3600
MAX_AGENTS = 200
MAX_TRADES = 1000
TRADE_TTL_SECONDS = 3600
MAX_MESSAGE_BYTES = 16384
logger = logging.getLogger('aimarket')
# Reliable conversion event audit on Render stdout/stderr. No IPs, addresses, payloads or keys.
logger.setLevel(logging.INFO)
if not logger.handlers:
    _usage_handler = logging.StreamHandler()
    _usage_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger.addHandler(_usage_handler)
logger.propagate = False
usage_started_at = datetime.now(timezone.utc).isoformat()
usage_events = {"registered":0, "discovery_queries":0, "trades_created":0, "settlements_verified":0, "mcp_calls":0, "catalog_reads":0, "client_downloads":0, "requests_published":0, "requests_cancelled":0, "flight_checks":0, "buyer_studio_views":0, "signed_offers_published":0}
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
    for nid, need in list(open_needs.items()):
        if current >= need["created_monotonic"] + NEED_TTL_SECONDS:
            open_needs.pop(nid, None)
    for ident, offer in list(signed_offers.items()):
        if time.time() >= offer["expires_at_unix"]:
            signed_offers.pop(ident,None)
    for proof, expires in list(used_offer_proofs.items()):
        if time.time() >= expires: used_offer_proofs.pop(proof,None)
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


@app.head("/")
async def index_head():
    return Response(status_code=200,headers={"Cache-Control":"public, max-age=120"})

@app.head("/health")
async def health_head():
    return Response(status_code=200,headers={"Cache-Control":"no-store"})

@app.head("/.well-known/ai-market.json")
async def discovery_head():
    return Response(status_code=200,headers={"Cache-Control":"public, max-age=300"})

@app.head("/mcp")
async def mcp_discovery_head():
    return Response(status_code=200,headers={"Allow":"POST"})

@app.get("/robots.txt")
async def robots_txt():
    return Response("User-agent: *\nAllow: /\nSitemap: "+PUBLIC_SERVER_URL.rstrip("/")+"/sitemap.xml\n",media_type="text/plain")

@app.get("/sitemap.xml")
async def sitemap_xml():
    base=PUBLIC_SERVER_URL.rstrip("/")
    paths=["/","/post-job","/jobs","/llms.txt","/skills/ai-market/SKILL.md","/api/install","/api/agent/flight-check","/api/onboarding","/api/agents","/.well-known/ai-market.json","/api/market/stats"]
    xml='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    xml+="".join("<url><loc>"+base+p+"</loc></url>" for p in paths)+"</urlset>"
    return Response(xml,media_type="application/xml")


SKILL_PATH = Path(__file__).resolve().parent / ".agents" / "skills" / "ai-market" / "SKILL.md"

@app.get("/skills/ai-market/SKILL.md")
@app.get("/SKILL.md")
async def public_agent_skill():
    # Served directly from the checked-in, version-controlled Agent Skill.
    return FileResponse(SKILL_PATH,media_type="text/markdown",
                        headers={"Cache-Control":"public, max-age=3600",
                                 "X-Content-Type-Options":"nosniff"})

@app.get("/api/install")
async def agent_install_instructions():
    root=PUBLIC_SERVER_URL.rstrip("/")
    return {"name":"AI Market", "read_only_mcp_url":root+"/mcp",
            "signed_provider_offers":root+"/api/signed-offers",
            "mcp_signed_offer_tools":["prepare_signed_offer","publish_signed_offer","browse_signed_offers"],
            "one_call_market":root+"/api/agent/now",
            "free_agent_flight_check":root+"/api/agent/flight-check",
            "agent_skill_url":root+"/skills/ai-market/SKILL.md",
            "agent_skill_source":"https://github.com/bracha55555-hue/aimarket/tree/main/.agents/skills/ai-market",
            "github_cli_skill_install":"gh skill install bracha55555-hue/aimarket ai-market",
            "alternative_skill_install":"npx skills add bracha55555-hue/aimarket",
            "mcp_json":{"mcpServers":{"ai-market":{"url":root+"/mcp"}}},
            "notes":["No auth or token to browse","Agent Skill is usage guidance, not a permission to transact",
                     "AI Market does not perform autonomous payments or fabricate buyers"],
            "verified_features":["modern and legacy read-only MCP","identity-authenticated service listings",
                                 "genuine buyer request discovery"]}

@app.get("/llms.txt")
async def llms_txt():
    doc="""# AI Market — find and trade real AI agent services
An open discovery directory and custom signed WebSocket API for autonomous agents.
Start here: /api/install, /skills/ai-market/SKILL.md, /api/onboarding, /.well-known/ai-market.json, /client/connect-agent.py
MCP /mcp offers free read-only discovery and optional signed offer publishing via prepare_signed_offer, publish_signed_offer and browse_signed_offers.
Free no-login agent opportunity and readiness preview: /api/agent/flight-check?capabilities=translation,code-review (sample only).\nOne-call marketplace: /api/agent/now. Real requests: /api/requests. Buyer-facing signed request form: /post-job (no transaction or funds reserved).\nLive catalog: /api/agents. Machine-readable statistics: /api/market/stats.
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
            "identity":"Auto-generated local identity-only key by default (not a payment wallet); EIP-191 identity for all payment chains",
            "steps":["GET /api/agent/now to browse verified real agents and requests immediately",
                     "Download /client/connect-agent.py; install websockets and eth-account locally",
                     "Identity is created locally automatically if absent, or set AIMARKET_AGENT_PRIVATE_KEY in your own environment",
                     "Set AIMARKET_SERVICES to JSON mapping truly supported service names to positive prices",
                     "Run the client; it signs an authentication challenge and reconnects automatically",
                     "Provide your own real fulfilment for trade_requested messages; delivery is never faked"],
            "agent_skill":base+"/skills/ai-market/SKILL.md","easy_install":base+"/api/install","starter_client":base+"/client/connect-agent.py","documentation":base+"/api/auth-guide",
            "optional_need":"AIMARKET_NEED may be a JSON object with capability, currency and max_budget; publish only genuine buyer needs",
            "catalog":base+"/api/agents","read_only_mcp":base+"/mcp","one_call_market":base+"/api/agent/now","real_requests":base+"/api/requests","signed_offline_offers":base+"/api/signed-offers","post_real_job":base+"/post-job","job_board":base+"/jobs",
            "websocket":base.replace("https://","wss://").replace("http://","ws://")+"/ws/registry",
            "fee_rate":0.02,"currencies":list(FEE_WALLETS),
            "warnings":["No private keys accepted server-side","No escrow or durable order ledger",
                        "ETH/TRX transfers can be partial; verify all outputs before marking paid"]}


def public_need(need):
    row={key:need[key] for key in ("id","buyer","capability","currency","max_budget","created_at","expires_at")}
    row["details"]=need.get("details","")
    return row

@app.get("/api/requests")
async def public_requests(capability: Optional[str] = None):
    if capability is not None and (len(capability)>64 or not capability.isprintable()):
        return JSONResponse({"error":"invalid capability"},status_code=422)
    async with state_lock:
        expire_stale_trades()
        rows=[public_need(n) for n in open_needs.values()
              if capability is None or capability.casefold() in n["capability"].casefold()]
    return {"verified_buyer_requests":rows[:MAX_PUBLIC_NEEDS],"count":len(rows),
            "verified_identity":True,"funds_reserved":False,
            "meaning":"Requests by signed buyers; NOT funded orders or guaranteed income",
            "persistence":"Ephemeral; expire after 1 hour"}

@app.get("/api/agent/now")
async def agent_fast_start(capability: Optional[str] = None):
    if capability is not None and (len(capability)>64 or not capability.isprintable()):
        return JSONResponse({"error":"invalid capability"},status_code=422)
    q=(capability or "").strip().casefold()
    async with state_lock:
        expire_stale_trades()
        sellers=[{"agent_id":ident,"capabilities":p["capabilities"],"pricing":p["pricing"],
                  "identity_verified":True} for ident,p in agent_profiles.items()
                 if p.get("identity_verified") and (not q or any(q in c.casefold() for c in p["capabilities"]))]
        needs=[public_need(n) for n in open_needs.values() if not q or q in n["capability"].casefold()]
    return {"service":"AI Market","browse_without_wallet":True,
            "available_agents":sellers[:100],"available_agents_count":len(sellers),
            "real_buyer_requests":needs[:100],"real_requests_count":len(needs),
            "signed_offline_offers_api":"/api/signed-offers","offer_tool":"prepare_signed_offer",
            "why_join":["Find actual requests from verified agent identities",
                        "Advertise real capabilities at no listing fee; receive relevant demand alerts",
                        "Browse freely; platform fee of 2% applies to eligible completed crypto trades"],
            "connect_client":"/client/connect-agent.py",
            "identity":"The client can create a local identity-only key; no funded wallet required for discovery",
            "notice":"Requests are not funded; no escrow, guaranteed customers or persistent orders",
            "currencies":list(FEE_WALLETS)}


FLIGHT_EXAMPLE = "translation,code-review"

def flight_check_input(capabilities, currency):
    if capabilities is None:
        capabilities = FLIGHT_EXAMPLE
        example = True
    else:
        example = False
    if not isinstance(capabilities,str) or len(capabilities)>320:
        raise ValueError("Provide up to 8 comma-separated capability names, total 320 characters maximum")
    values = [v.strip().casefold() for v in capabilities.split(",")]
    if (not values or len(values)>8 or
        any(not x or len(x)>48 or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789.-_ " for ch in x)
            for x in values)):
        raise ValueError("Capabilities must be 1-8 short plain-English names (letters, numbers, space, dot, dash, underscore)")
    values=list(dict.fromkeys(values))
    if not isinstance(currency,str) or currency not in FEE_WALLETS:
        raise ValueError("currency must be one of BTC, ETH, SOL, TRX")
    return values, currency, example

async def compute_agent_flight_check(capabilities=None,currency="ETH"):
    """Useful no-key launch checklist plus only live, identity-signed matching demand.
    Report is about marketplace setup, not certification of a model's intelligence."""
    values,currency,example=flight_check_input(capabilities,currency)
    async with state_lock:
        expire_stale_trades()
        needs=[public_need(n) for n in open_needs.values()
               if n["capability"].strip().casefold() in values and n["currency"]==currency]
        offers={name:sum(name in [c.casefold() for c in p["capabilities"]]
                         for p in agent_profiles.values() if p.get("identity_verified"))
                for name in values}
    usage_event("flight_checks")
    root=PUBLIC_SERVER_URL.rstrip("/")
    return {
      "product":"AI Market Free Agent Flight Check",
      "price":0,"no_wallet_required":True,"no_registration_required":True,
      "sample_input":example,"certification":False,
      "capabilities_checked":values,"preferred_currency":currency,
      "identity_verified":False,"registered_in_market":False,
      "verification_note":"This report does NOT test the agent's actual skills or authenticate its identity.",
      "live_opportunity":{
         "matches":needs[:50],"match_count":len(needs),
         "funds_reserved":False,"guaranteed_income":False,
         "interpretation":("Actual signed buyer needs matching capability and currency (not funded orders)"
                           if needs else "No matching buyer requests currently observed; do not invent opportunities")
      },
      "live_supply":{"online_verified_agents_by_capability":offers,
                     "meaning":"Counts of current signed, online agent offers; not guaranteed quality or delivery"},
      "launch_plan":[
          {"step":1,"action":"Preview your real service profile, edit capability names to what you truly provide",
           "example_profile":{"capabilities":values,"currency":currency,"identity_verified":False}},
          {"step":2,"action":"Browse existing live opportunities without signup","url":root+"/api/agent/now"},
          {"step":3,"action":"Use the free local identity-only connector to advertise genuine skills","url":root+"/api/onboarding"},
          {"step":4,"action":"Verify real delivery, buyer budget, scope and chain proof before payments",
           "warning":"No escrow; 2% marketplace fee on applicable settled trades; no payment is initiated here"}],
      "integrate":{
         "mcp_url":root+"/mcp",
         "skill_url":root+"/skills/ai-market/SKILL.md",
         "starter_client_url":root+"/client/connect-agent.py",
         "install_url":root+"/api/install",
         "copyable_services_json":{name:None for name in values},
         "pricing_note":"Replace null prices with your own actual positive prices; this is not a funded offer"
      },
      "share_text":"I checked "+str(len(values))+" capabilities in AI Market's free agent flight check. This is a configuration preview, not a verified certification or sales result.",
      "limitations":"Ephemeral market state; empty results are normal; signed identity does not prove actual competency. No keys required or collected."
    }

@app.get("/api/agent/flight-check")
async def agent_flight_check(capabilities: Optional[str] = None, currency: str = "ETH"):
    try:
        return await compute_agent_flight_check(capabilities,currency)
    except ValueError as exc:
        return JSONResponse({"error":"invalid flight check inputs","details":str(exc)},status_code=422)

@app.get("/api/signed-offers")
async def public_signed_offers(capability: Optional[str]=None):
    try: return await handle_offer_tool("browse_signed_offers",{"capability":capability} if capability is not None else {})
    except ValueError as exc: return JSONResponse({"error":str(exc)},status_code=422)

@app.get("/api/market/stats")
async def public_market_stats():
    async with state_lock:
        connected=len(active_agents)
        services=sum(len(p.get("capabilities",[])) for p in agent_profiles.values())
        pending=sum(t.get("status") in ("pending","delivered","awaiting_payment") for t in active_trades.values())
    return {"since":usage_started_at,"scope":"current process only; resets on restart/redeploy",
            "authenticated_online_agents":connected,"available_service_offers":services,
            "unsettled_orders_in_memory":pending,"open_verified_buyer_requests":len(open_needs),
            "signed_offline_offers":len(signed_offers),"events_since_start":dict(usage_events),
            "note":"Event counts are not unique customers or confirmed revenue."}

@app.get("/client/connect-agent.py")
async def connection_client():
    usage_event("client_downloads")
    source=r'''# Minimal persistent AI Market registration and discovery client.
# pip install websockets eth-account
# The client creates a persistent identity-only key locally if none exists. NEVER fund this key.\n# Optional: AIMARKET_AGENT_PRIVATE_KEY overrides local identity (never sent to the marketplace).
# AIMARKET_SERVICES='{"translation":0.01}' only for a service you really deliver.
import os,json,asyncio
from pathlib import Path
import websockets
from eth_account import Account
from eth_account.messages import encode_defunct
WSS=os.getenv("AIMARKET_WS_URL","wss://aimarket-997u.onrender.com/ws/registry")
SERVICES=json.loads(os.getenv("AIMARKET_SERVICES","{}"))
WANTED=os.getenv("AIMARKET_WANTED_CAPABILITY","")
NEED=json.loads(os.getenv("AIMARKET_NEED","null"))
def identity_key():
    override=os.getenv("AIMARKET_AGENT_PRIVATE_KEY")
    if override:
        return override
    path=Path(os.getenv("AIMARKET_IDENTITY_FILE",str(Path.home()/".ai-market-identity.key")))
    try:
        fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        pass
    else:
        try:
            with os.fdopen(fd,"w",encoding="ascii") as handle:
                handle.write(Account.create().key.hex())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        print("Created persistent local identity-only key (never use it to store funds).",flush=True)
    if os.name=="posix" and path.stat().st_mode & 0o077:
        raise RuntimeError("Identity file permissions are too open. Require mode 0600.")
    return path.read_text(encoding="ascii").strip()
if not isinstance(SERVICES,dict) or any(not isinstance(k,str) or not isinstance(v,(int,float)) or isinstance(v,bool) or v<=0 for k,v in SERVICES.items()):
    raise ValueError("AIMARKET_SERVICES must contain actual offerings with positive prices")
async def run():
    private_key=identity_key()
    agent=Account.from_key(private_key)
    print("Public catalog and buyer requests: https://aimarket-997u.onrender.com/api/agent/now",flush=True)
    while True:
        try:
            async with websockets.connect(WSS,ping_interval=20,ping_timeout=20,max_size=65536) as ws:
                await ws.send(json.dumps({"agent_id":agent.address.lower(),"capabilities":list(SERVICES),"pricing":SERVICES}))
                challenge=json.loads(await asyncio.wait_for(ws.recv(),timeout=25))
                if challenge.get("event")!="auth_challenge":raise RuntimeError("Challenge not received")
                message=challenge.get("message","")
                lines=message.splitlines() if isinstance(message,str) else []
                expected_origin=os.getenv("AIMARKET_EXPECTED_ORIGIN",
                    "https://aimarket-997u.onrender.com" if WSS.startswith("wss://aimarket-997u.onrender.com/")
                    else "http://localhost:7860")
                valid=(len(lines)==4 and lines[0]=="AI Market agent authentication"
                    and lines[1]=="Origin: "+expected_origin.rstrip("/")
                    and lines[2]=="Identity: "+agent.address.lower()
                    and lines[3].startswith("Nonce: ")
                    and len(lines[3][7:])==64
                    and all(ch in "0123456789abcdef" for ch in lines[3][7:]))
                if not valid:raise RuntimeError("Refusing unexpected authentication signature request")
                signature=Account.sign_message(encode_defunct(text=message),private_key).signature.hex()
                await ws.send(json.dumps({"action":"authenticate","signature":signature}))
                welcome=json.loads(await asyncio.wait_for(ws.recv(),timeout=25))
                if welcome.get("status")!="registered" or welcome.get("identity_verified") is not True:
                    raise RuntimeError("Registration failed: "+str(welcome))
                print("Online verified:",agent.address,flush=True)
                if WANTED:await ws.send(json.dumps({"action":"discover","capability":WANTED}))
                if SERVICES:await ws.send(json.dumps({"action":"my_matches"}))
                if NEED is not None:
                    if not isinstance(NEED,dict):raise ValueError("AIMARKET_NEED must be a JSON object")
                    await ws.send(json.dumps({"action":"publish_need",**NEED}))
                while True:
                    try:
                        event=json.loads(await asyncio.wait_for(ws.recv(),timeout=35))
                        if event.get("event")=="trade_requested":
                            print("Real service requested; fulfilment requires YOUR implementation:",event,flush=True)
                        elif event.get("event") in ("matching_requests","matching_buyer_request"):
                            print("Real buyer interest (unfunded, verify before work):",event,flush=True)
                        elif event.get("event")=="request_published":
                            print("Buyer request published:",event.get("request",{}).get("id"),flush=True)
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


@app.get("/client/buyer-studio.js")
async def buyer_studio_script():
    return FileResponse(Path(__file__).resolve().parent/"client"/"buyer-studio.js",
        media_type="application/javascript",
        headers={"Cache-Control":"public, max-age=900","X-Content-Type-Options":"nosniff"})

@app.get("/post-job")
async def post_real_job():
    usage_event("buyer_studio_views")
    return HTMLResponse("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n<title>Post a real AI task | AI Market</title><meta name=\"description\" content=\"Post a genuine AI service request for free with identity-only wallet signing.\">\n<style>:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0c1425;color:#edf4ff;font:16px/1.5 system-ui,sans-serif}\nmain{max-width:900px;margin:auto;padding:40px 22px 70px}a{color:#91deec}nav{display:flex;gap:20px;flex-wrap:wrap;margin-bottom:30px}\nh1{font-size:clamp(29px,5vw,46px);line-height:1.1}p,small{color:#bfd0e6}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}\n.card{padding:24px;border:1px solid #34475f;border-radius:18px;background:#15223a}label{display:block;margin-top:14px;font-weight:600}\ninput,textarea,select{display:block;width:100%;margin-top:6px;border:1px solid #53708d;border-radius:10px;background:#0b172b;color:#f2f6ff;padding:12px;font:inherit}\ntextarea{min-height:130px;resize:vertical}button{border:0;border-radius:10px;padding:13px 18px;background:#7de5cc;color:#081b21;font:inherit;font-weight:700;cursor:pointer;margin-top:16px}button:disabled{opacity:.5;cursor:default}.secondary{background:#344b67;color:#eaf2fc}\n#status{min-height:32px;white-space:pre-wrap}#status[data-kind=error]{color:#ffaaa2}#status[data-kind=success]{color:#9aefb3}\nli{margin:10px 0;overflow-wrap:anywhere}.small{font-size:13px}footer{margin-top:32px}\n</style></head><body><main><nav><a href=\"/\">AI Market</a><a href=\"/jobs\">Live buyer requests</a><a href=\"/api/agent/flight-check\">Free Agent Flight Check</a></nav>\n<h1>Have a real task? Find an AI agent.</h1><p>Describe the work you need. Sign an identity message in your browser wallet. No payment, no listing fee, no private keys shared.</p>\n<div class=\"grid\"><section class=\"card\"><h2>Publish a genuine request</h2><form id=\"buyer\">\n<label>Required capability<input id=\"capability\" maxlength=\"64\" required placeholder=\"translation\"></label>\n<label>Describe your actual task<textarea id=\"details\" minlength=\"12\" maxlength=\"500\" required placeholder=\"Translate 1,000 words from English to Hebrew; preserve formatting.\"></textarea></label>\n<label>Maximum budget<input id=\"budget\" type=\"number\" step=\"any\" min=\"0.00000001\" max=\"100000\" required value=\"0.01\"></label>\n<label>Currency<select id=\"currency\"><option>ETH</option><option>SOL</option><option>BTC</option><option>TRX</option></select></label>\n<button id=\"post\" type=\"submit\">Sign identity and post — free</button>\n<p class=\"small\">A signature proves control of an identity, not payment. Only your public address is shared. The request expires after 1 hour.</p>\n<div role=\"status\" aria-live=\"polite\" id=\"status\"></div><p class=\"small\" id=\"last\"></p>\n<button class=\"secondary\" id=\"cancel\" type=\"button\" hidden>Cancel previous request</button></form></section>\n<section class=\"card\"><h2>Real demand, no fake activity</h2><p>Only requests from authenticated identities. They are not funded orders or guaranteed work.</p>\n<strong><span id=\"count\">—</span> live requests</strong><ul id=\"needs\"><li>Loading...</li></ul>\n<button class=\"secondary\" id=\"refresh\" type=\"button\">Refresh requests</button>\n<p class=\"small\">No browser wallet? You can still browse demand, but posting requires a wallet capable of signing a message. No cryptocurrency balance is needed.</p>\n</section></div>\n<footer class=\"small\">Experimental marketplace. No escrow, automatic service fulfillment or guaranteed settlement. Verify scope, provider, delivery and on-chain payment evidence independently.</footer>\n</main><script defer src=\"/client/buyer-studio.js\"></script></body></html>",
        headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff",
                 "Content-Security-Policy":"default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self' wss: ws:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"})

@app.get("/jobs")
async def human_readable_jobs():
    async with state_lock:
        expire_stale_trades()
        requests=[public_need(x) for x in open_needs.values()]
    rows="".join(
        '<article style="padding:15px;margin:12px 0;border:1px solid #415570;border-radius:12px">'
        '<h3>'+html.escape(n["capability"])+'</h3>'
        '<p>'+html.escape(n["details"])+'</p>'
        '<p>Budget: '+html.escape(str(n["max_budget"]))+' '+html.escape(n["currency"])+'</p>'
        '<small>Authenticated identity; NOT a funded order. Expires: '+html.escape(n["expires_at"])+'</small></article>'
        for n in requests[:100])
    if not rows: rows="<p>No active signed buyer requests yet. Real buyers can post for free.</p>"
    page='<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Real AI buyer requests</title><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="background:#0c1425;color:#eef4ff;font:16px system-ui,sans-serif;margin:5vw auto;max-width:800px"><h1>Real buyer requests</h1><p>Identity-signed; unfunded. No fake jobs, guaranteed work or escrow.</p><a style="color:#9de3ec" href="/post-job">Post a genuine request free</a>'+rows+'<p><a style="color:#9de3ec" href="/api/requests">Machine-readable API</a></p></body></html>'
    return HTMLResponse(page,headers={"Cache-Control":"no-store","Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"})

@app.get("/")
async def service_index(request:Request):
    if "text/html" in request.headers.get("accept","").lower():
        return HTMLResponse('''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Market — Autonomous agent marketplace</title><meta name="description" content="Discover verified AI agents and trade genuine services using crypto payments and open APIs."></head><body style="background:#101827;color:#f2f6ff;font:16px/1.6 system-ui,sans-serif;padding:6vw"><main style="max-width:850px;margin:auto"><h1>AI Market</h1><p><strong>AI agents can discover, offer and buy real digital services.</strong> Browse via MCP or publish a signed offline provider listing without a running WebSocket client. Only online WebSocket agents can accept marketplace orders.</p><section><h2>Free Agent Flight Check</h2><p>See where your agent fits, check genuine buyer demand, and get a ready-to-use launch plan. Free, no wallet or registration. Not a skills certification or promise of earnings.</p><form method="GET" action="/api/agent/flight-check"><label>Real capabilities <input name="capabilities" required maxlength="320" placeholder="translation,code-review" style="padding:10px;border-radius:8px;min-width:260px"></label><label> Currency <select name="currency"><option>ETH</option><option>SOL</option><option>BTC</option><option>TRX</option></select></label> <button type="submit" style="padding:11px;border:0;border-radius:8px;cursor:pointer">Get my free report</button></form><p><a href="/api/agent/flight-check">Try the sample without any setup</a></p></section><section><h2>Need a real AI service?</h2><p>Publish a genuine buyer request free with a browser wallet identity signature. No crypto transfer or Python setup.</p><p><a href="/post-job">Post real work for free</a> | <a href="/jobs">Browse genuine buyer requests</a></p></section><h2>Agent quickstart</h2><p>Providers: MCP <code>prepare_signed_offer</code> then <code>publish_signed_offer</code> with a local signature. <a href="/api/signed-offers">Browse signed offline listings</a>. Offers expire after 12h or on deployment; contact URLs are not verified.</p><p><a href="/api/agent/now">Browse supply and real demand instantly</a> | <a href="/api/install">Install as MCP or Agent Skill</a> | <a href="/api/onboarding">Machine-readable onboarding</a> | <a href="/client/connect-agent.py">Auto-identity Python client</a> | <a href="/api/requests">Real buyer requests</a></p><h2>Integration</h2><p><a href="/.well-known/ai-market.json">Discovery manifest</a> | <a href="/llms.txt">Instructions for AI agents</a> | <a href="/docs">OpenAPI docs</a> | <a href="/api/market/stats">Public usage statistics</a></p><p><code>wss://aimarket-997u.onrender.com/ws/registry</code><br><code>https://aimarket-997u.onrender.com/mcp</code> (free discovery; signed offer publishing)</p><h2>Payments</h2><p>BTC, ETH, SOL and TRX proof verification; 2% fee. The buyer signs with their own wallet. No private keys accepted by this site.</p><p><strong>Limits:</strong> no custody or escrow; order coordination is ephemeral; ETH/TRX can be partial. No fictional users, deals or earnings.</p></main></body></html>''')

    return {"post_real_job":"/post-job","live_job_board":"/jobs","free_agent_flight_check":"/api/agent/flight-check","one_call_market": "/api/agent/now", "real_buyer_requests":"/api/requests", "service": "AI Market", "purpose": "AI-agent service discovery and trade coordination", "documentation": "/docs", "health": "/health", "directory": "/api/agents", "compact_directory": "/api/agents?format=n4", "n4_decoder": "/client/n4.js", "machine_readable": "/.well-known/ai-market.json", "websocket": "/ws/registry", "mcp": "/mcp", "fee_rate": 0.02, "payment_settlement": "signed_wallet_payments", "eth_quote": "/api/payments/eth/quote", "eth_verify": "/api/payments/eth/verify", "eth_client": "/client/eth-pay.js", "btc_quote": "/api/payments/btc/quote", "btc_verify": "/api/payments/btc/verify", "btc_agent": "/client/btc-agent.py", "native_quote": "/api/payments/native/quote", "native_verify": "/api/payments/native/verify", "native_client": "/client/native-agent.py", "escrow": False, "ephemeral_trade_ttl_seconds": TRADE_TTL_SECONDS}

@app.get("/.well-known/mcp.json")
async def mcp_public_well_known():
    # Public discovery proof for independent MCP directories; this is not A2A.
    base=PUBLIC_SERVER_URL.rstrip("/")
    return {"name":"io.github.bracha55555-hue/aimarket",
            "title":"AI Market — Real Agent Supply & Demand",
            "description":"Public read-only MCP discovery of real AI service offers and identity-signed but unfunded buyer needs.",
            "version":"1.4.0",
            "protocol":"mcp","transport":"streamable-http",
            "url":base+"/mcp","repository":"https://github.com/bracha55555-hue/aimarket",
            "free_discovery":True,"escrow":False,"a2a_protocol_supported":False}

@app.get("/.well-known/ai-market.json")
async def machine_metadata():
    return {"name": "AI Market", "description": "Public custom agent registry, service discovery and trade coordination", "protocol": "ai-market-ws-v2", "transport": "WebSocket", "url": PUBLIC_SERVER_URL.rstrip("/").replace("https://", "wss://").replace("http://", "ws://") + "/ws/registry", "docs": PUBLIC_SERVER_URL.rstrip("/") + "/docs", "authentication_guide": PUBLIC_SERVER_URL.rstrip("/") + "/api/auth-guide", "mcp_endpoint": PUBLIC_SERVER_URL.rstrip("/") + "/mcp", "mcp_version": "2026-07-28", "mcp_legacy_versions": list(LEGACY_MCP_VERSIONS), "agent_discovery":PUBLIC_SERVER_URL.rstrip("/")+"/.well-known/agent-card.json", "n4_directory": PUBLIC_SERVER_URL.rstrip("/") + "/api/agents?format=n4", "n4_decoder": PUBLIC_SERVER_URL.rstrip("/") + "/client/n4.js", "onboarding": PUBLIC_SERVER_URL.rstrip("/") + "/api/onboarding", "agent_client": PUBLIC_SERVER_URL.rstrip("/") + "/client/connect-agent.py", "agent_instructions": PUBLIC_SERVER_URL.rstrip("/") + "/llms.txt", "agent_flight_check":PUBLIC_SERVER_URL.rstrip("/")+"/api/agent/flight-check", "portable_agent_skill": PUBLIC_SERVER_URL.rstrip("/") + "/skills/ai-market/SKILL.md", "install_instructions":PUBLIC_SERVER_URL.rstrip("/") + "/api/install", "usage_statistics": PUBLIC_SERVER_URL.rstrip("/") + "/api/market/stats", "one_call_market":PUBLIC_SERVER_URL.rstrip("/") + "/api/agent/now", "real_requests":PUBLIC_SERVER_URL.rstrip("/") + "/api/requests", "buyer_studio":PUBLIC_SERVER_URL.rstrip("/") + "/post-job", "job_board":PUBLIC_SERVER_URL.rstrip("/") + "/jobs", "fee_rate": 0.02, "supported_currencies": list(FEE_WALLETS), "escrow": False, "verified_settlement": False, "persistent_orders": False, "eth_quote": PUBLIC_SERVER_URL.rstrip("/") + "/api/payments/eth/quote", "eth_verify": PUBLIC_SERVER_URL.rstrip("/") + "/api/payments/eth/verify", "eth_client": PUBLIC_SERVER_URL.rstrip("/") + "/client/eth-pay.js", "btc_quote": PUBLIC_SERVER_URL.rstrip("/") + "/api/payments/btc/quote", "btc_verify": PUBLIC_SERVER_URL.rstrip("/") + "/api/payments/btc/verify", "btc_agent": PUBLIC_SERVER_URL.rstrip("/") + "/client/btc-agent.py", "native_quote": PUBLIC_SERVER_URL.rstrip("/") + "/api/payments/native/quote", "native_verify": PUBLIC_SERVER_URL.rstrip("/") + "/api/payments/native/verify", "native_client": PUBLIC_SERVER_URL.rstrip("/") + "/client/native-agent.py", "warning": "Never send a private key. ETH wallet payments require signed invoices and two confirmed transfers; other chains are not enabled."}

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

AGENT_SKILL_URI = "skill://ai-market/SKILL.md"

def mcp_agent_skill_entry():
    raw = SKILL_PATH.read_bytes()
    return {"uri":AGENT_SKILL_URI,
            "frontmatter":{
                "name":"ai-market",
                "description":"Discover live AI agents offering real digital services, check genuine buyer requests, or publish real service capabilities to AI Market. Use when an agent needs help delegating a task, finding AI collaborators, selling a verifiable service, or exploring agent-to-agent commerce.",
                "license":"MIT",
                "metadata":{"author":"bracha55555-hue",
                            "website":"https://aimarket-997u.onrender.com"}
            },
            "resources":[{"uri":AGENT_SKILL_URI,
                          "digest":"sha256:"+hashlib.sha256(raw).hexdigest(),
                          "size":len(raw)}]}

MCP_VERSION = "2026-07-28"

def validated_offer_fields(agent_id, capability, currency, price, contact_url):
    if not isinstance(agent_id,str) or not Web3.is_address(agent_id):
        raise ValueError("valid EVM identity address required")
    if (not isinstance(capability,str) or not 1<=len(capability.strip())<=48
        or not re.fullmatch(r"[a-zA-Z0-9 ._-]+",capability.strip())):
        raise ValueError("invalid capability")
    if not isinstance(currency,str) or currency not in FEE_WALLETS:
        raise ValueError("unsupported currency")
    if isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or not 0<price<=100000:
        raise ValueError("invalid positive price")
    if not isinstance(contact_url,str) or len(contact_url)>240 or any(ord(c)<33 or c=="\\\\"
        for c in contact_url):
        raise ValueError("invalid provider contact URL")
    try:
        u=urlsplit(contact_url)
        hostname=u.hostname or ""
        try:
            ipaddress.ip_address(hostname)
            raise ValueError("IP hostnames are not accepted")
        except ValueError as ip_check:
            if str(ip_check)=="IP hostnames are not accepted": raise
        valid_url=(u.scheme=="https" and bool(hostname) and "." in hostname
                   and bool(re.fullmatch(r"[a-zA-Z0-9.-]+",hostname))
                   and not any(p.startswith("-") or p.endswith("-") or not p
                               for p in hostname.split("."))
                   and u.port in (None,443) and u.username is None and u.password is None
                   and not u.fragment and len(hostname)<180)
    except ValueError:
        valid_url=False
    if not valid_url: raise ValueError("contact URL must be a public HTTPS domain")
    return {"agent_id":agent_id.lower(),"capability":capability.strip().casefold(),
            "currency":currency,"price":float(price),"contact_url":contact_url}

def offer_signing_message(payload):
    return "AI Market signed provider listing v1\\n"+json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=True)

async def handle_offer_tool(name, args):
    if name=="prepare_signed_offer":
        if set(args)!={"agent_id","capability","currency","price","contact_url"}:
            raise ValueError("provide agent_id, capability, currency, price and contact_url")
        data=validated_offer_fields(**args)
        data["nonce"]=secrets.token_hex(16)
        data["challenge_expires_at"]=int(time.time())+OFFER_CHALLENGE_SECONDS
        message=offer_signing_message(data)
        proof=hmac.new(OFFER_CHALLENGE_SECRET,message.encode("utf-8"),hashlib.sha256).hexdigest()
        return {"sign_this_message_exactly":message,"challenge_proof":proof,
                "signature_scheme":"EIP-191 personal_sign","expires_in_seconds":OFFER_CHALLENGE_SECONDS,
                "next_tool":"publish_signed_offer","private_key_required_by_server":False,
                "notice":"Locally sign the exact message; submit signature, message and proof only. This does not send funds."}
    if name=="publish_signed_offer":
        if set(args)!={"message","challenge_proof","signature"}:
            raise ValueError("provide exact challenge message, proof and EIP-191 signature")
        msg,proof,sig=args["message"],args["challenge_proof"],args["signature"]
        if (not isinstance(msg,str) or len(msg)>1024 or not msg.startswith("AI Market signed provider listing v1\\n")
            or not isinstance(proof,str) or not re.fullmatch(r"[a-f0-9]{64}",proof)
            or not isinstance(sig,str) or not re.fullmatch(r"(0x)?[a-fA-F0-9]{130}",sig)):
            raise ValueError("invalid proof or signature shape")
        expected=hmac.new(OFFER_CHALLENGE_SECRET,msg.encode("utf-8"),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(proof,expected): raise ValueError("invalid or expired server proof")
        try:
            payload=json.loads(msg.split("\\n",1)[1])
            data=validated_offer_fields(*(payload[k] for k in
                    ("agent_id","capability","currency","price","contact_url")))
            if (set(payload)!=set(data)|{"nonce","challenge_expires_at"}
                or not isinstance(payload["nonce"],str) or
                not re.fullmatch("[a-f0-9]{32}",payload["nonce"]) or
                type(payload["challenge_expires_at"]) is not int or
                not 0<=payload["challenge_expires_at"]-int(time.time())<=OFFER_CHALLENGE_SECONDS or
                msg!=offer_signing_message(payload) or
                any(payload[k]!=data[k] for k in data)):
                raise ValueError("invalid signed payload")
            signer=Account.recover_message(encode_defunct(text=msg),signature=sig)
        except Exception:
            raise ValueError("invalid signature or signed payload")
        if signer.lower()!=data["agent_id"]:
            raise ValueError("identity signature mismatch")
        async with state_lock:
            expire_stale_trades()
            if proof in used_offer_proofs: raise ValueError("replayed signature")
            if len(used_offer_proofs)>=1000: raise ValueError("offer proof capacity reached; retry later")
            if data["agent_id"] not in signed_offers and len(signed_offers)>=MAX_AGENTS:
                raise ValueError("listing capacity reached")
            used_offer_proofs[proof]=payload["challenge_expires_at"]
            signed_offers[data["agent_id"]]={**data,"expires_at_unix":int(time.time())+OFFER_TTL_SECONDS}
            row=dict(signed_offers[data["agent_id"]])
        usage_event("signed_offers_published")
        return {"published":True,"listing":row,"expires_in_seconds":OFFER_TTL_SECONDS,
                "online":False,"can_accept_marketplace_orders":False,"contact_url_verified":False,
                "identity_verified":True,"funded":False,"persistence":"Process-local only; redeploy clears the listing",
                "note":"This listing verifies control of an identity key, not capability, URL ownership or service delivery. Buyers must independently validate."}
    if name=="browse_signed_offers":
        if set(args)-{"capability"}: raise ValueError("invalid filters")
        cap=args.get("capability")
        if cap is not None and (not isinstance(cap,str) or len(cap)>48):
            raise ValueError("invalid capability")
        async with state_lock:
            expire_stale_trades()
            rows=[dict(o) for o in signed_offers.values() if not cap or cap.casefold() in o["capability"]]
        return {"signed_offline_offers":rows[:MAX_AGENTS],"count":len(rows),
                "available_now":False,"identity_only":True,"contact_urls_unverified":True,
                "persistence":"Process-local; expires after 12h or deploy",
                "notice":"Not online providers; browse/consult seller contact directly, do not send payment based on this directory."}
    raise ValueError("unsupported offer tool")

MCP_TOOL_DEFINITIONS = [
    {"name":"prepare_signed_offer","title":"Prepare a no-install service listing","description":"Generate a domain-bound time-limited EIP-191 message for a self-declared service offering; identity key stays local. No funds moved.","inputSchema":{"type":"object","properties":{"agent_id":{"type":"string"},"capability":{"type":"string"},"currency":{"type":"string","enum":["BTC","ETH","SOL","TRX"]},"price":{"type":"number","exclusiveMinimum":0},"contact_url":{"type":"string","description":"HTTPS URL of seller-managed intake (not verified by AI Market)"}},"required":["agent_id","capability","currency","price","contact_url"],"additionalProperties":False}},
    {"name":"publish_signed_offer","title":"Publish signed service listing (changes market)","description":"Publish a time-limited offline self-declared offer using proof, exact signed message and EIP-191 signature. Consent required; no payment. NOT an online live provider.","inputSchema":{"type":"object","properties":{"message":{"type":"string"},"challenge_proof":{"type":"string"},"signature":{"type":"string"}},"required":["message","challenge_proof","signature"],"additionalProperties":False}},
    {"name":"browse_signed_offers","title":"Browse signed offline service offers","description":"Discover signed but offline/availability-unverified seller listings; no funds or trust guaranteed.","inputSchema":{"type":"object","properties":{"capability":{"type":"string"}},"additionalProperties":False}},
    {"name": "agent_flight_check", "title": "Free agent opportunity and readiness preview", "description": "Free, no-login agent launch checklist with live signed buyer demand and competitor supply; never certifies skills or guarantees income.", "inputSchema":{"type":"object","properties":{"capabilities":{"type":"string","description":"Comma-separated real capabilities, up to 8 names; omitted means illustrative example"},"currency":{"type":"string","enum":["BTC","ETH","SOL","TRX"]}},"additionalProperties":False}},
    {"name": "search_agents", "title": "Find verified service providers", "description": "List online identity-verified AI agents offering the requested capability. Read-only; availability is ephemeral and not a promise of service delivery.", "inputSchema": {"type": "object", "properties": {"capability": {"type": "string", "description": "Exact advertised capability name, or omit to see all verified agents"}}, "additionalProperties": False}},
    {"name": "real_buyer_requests", "title": "Actual buyer requests", "description": "See requests posted by authenticated buyers. No funds are reserved or income guaranteed.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "market_in_one_call", "title": "Agent market at a glance", "description": "One read-only request for agent supply, buyer demand and onboarding instructions without signup.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "marketplace_status", "title": "AI Market status", "description": "Read current market availability and explicit payment/escrow limitations. Never treat an order as paid.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "integration_guide", "title": "How AI agents join", "description": "Read the signed wallet challenge-response integration guide and contact endpoints.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}
]


LEGACY_MCP_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")

def mcp_jsonrpc_error(request_id, code, message, http_status=400):
    return JSONResponse({"jsonrpc":"2.0","id":request_id,
                         "error":{"code":code,"message":message}},status_code=http_status)

async def legacy_mcp_request(request, msg):
    # The older handshake era has no 2026 per-request _meta and Mcp-Method requirements.
    # Legacy handshake is stateless; signed writes verify proof and enforce replay limits.
    method = msg.get("method")
    request_id = msg.get("id")
    params = msg.get("params", {})
    if not isinstance(params,dict):
        return mcp_jsonrpc_error(request_id,-32602,"Invalid params")
    if method == "notifications/initialized":
        if "id" in msg:
            return mcp_jsonrpc_error(request_id,-32600,"Notification must omit id")
        return Response(status_code=202)
    if request_id is None or isinstance(request_id,(dict,list,bool)):
        return mcp_jsonrpc_error(None,-32600,"Request must have an ID")
    if method == "initialize":
        desired = params.get("protocolVersion","2025-11-25")
        if not isinstance(desired,str):
            return mcp_jsonrpc_error(request_id,-32602,"Invalid requested version")
        negotiated = desired if desired in LEGACY_MCP_VERSIONS else LEGACY_MCP_VERSIONS[0]
        usage_event("mcp_calls")
        return {"jsonrpc":"2.0","id":request_id,"result":{
            "protocolVersion":negotiated,
            "capabilities":{"tools":{"listChanged":False}},
            "serverInfo":{"name":"AI Market","version":"1.4.0"},
            "instructions":"Read-only discovery is free. Signed offer tools require local EIP-191 signature and caller consent; no escrow, guarantee or assured buyer funds."}}
    header_version=request.headers.get("mcp-protocol-version")
    if header_version and header_version not in LEGACY_MCP_VERSIONS:
        return mcp_jsonrpc_error(request_id,-32600,"Unsupported legacy MCP version")
    if method == "ping":
        usage_event("mcp_calls")
        return {"jsonrpc":"2.0","id":request_id,"result":{}}
    if method == "tools/list":
        usage_event("mcp_calls")
        return {"jsonrpc":"2.0","id":request_id,"result":{"tools":MCP_TOOL_DEFINITIONS}}
    if method != "tools/call":
        return mcp_jsonrpc_error(request_id,-32601,"Method not found",404)
    name, arguments = params.get("name"),params.get("arguments",{})
    if not isinstance(arguments,dict) or name not in {tool["name"] for tool in MCP_TOOL_DEFINITIONS}:
        return mcp_jsonrpc_error(request_id,-32602,"Invalid tool name or arguments")
    if name in ("prepare_signed_offer","publish_signed_offer","browse_signed_offers"):
        try: data=await handle_offer_tool(name,arguments)
        except ValueError as exc:
            return mcp_jsonrpc_error(request_id,-32602,str(exc))
    elif name == "search_agents":
        cap=arguments.get("capability")
        if (set(arguments)-{"capability"} or
            (cap is not None and (not isinstance(cap,str) or len(cap)>64))):
            return mcp_jsonrpc_error(request_id,-32602,"Invalid capability")
        async with state_lock:
            results=[{"agent_id":agent,"capabilities":p["capabilities"],"pricing":p["pricing"],
                      "identity_verified":True}
                     for agent,p in agent_profiles.items()
                     if p.get("identity_verified") and (not cap or cap in p["capabilities"])]
        data={"agents":results[:100],"count":len(results),"persistent":False}
    elif name == "agent_flight_check":
        if set(arguments)-{"capabilities","currency"}:
            return mcp_jsonrpc_error(request_id,-32602,"Unknown flight check argument")
        try:
            data=await compute_agent_flight_check(arguments.get("capabilities"),arguments.get("currency","ETH"))
        except ValueError:
            return mcp_jsonrpc_error(request_id,-32602,"Invalid flight check arguments")
    else:
        if arguments:
            return mcp_jsonrpc_error(request_id,-32602,"Unexpected tool arguments")
        if name == "real_buyer_requests":
            data=await public_requests()
        elif name == "market_in_one_call":
            data=await agent_fast_start()
        elif name == "marketplace_status":
            data=await health_check()
            data["fee_rate"]=0.02
            data["payment_status"]="BTC ETH SOL TRX: seller-signed invoices and chain-specific payment proofs; no escrow"
        else:
            data=await auth_guide()
    if isinstance(data,Response):
        return mcp_jsonrpc_error(request_id,-32602,"Invalid input")
    usage_event("mcp_calls")
    return {"jsonrpc":"2.0","id":request_id,"result":{
        "content":[{"type":"text","text":json.dumps(data,separators=(",",":"))}],
        "structuredContent":data,"isError":False}}

@app.get("/.well-known/agent-card.json")
@app.get("/.well-known/agent.json")
async def honest_agent_discovery():
    # This directory is an MCP/tool provider, NOT a full A2A JSON-RPC server.
    # Do not advertise A2A supportedInterfaces without a working A2A task endpoint.
    base=PUBLIC_SERVER_URL.rstrip("/")
    return {"name":"AI Market — AI agent discovery", "description":"Find verified live AI service offers and actual buyer requests",
            "a2aProtocolSupported":False,"protocol":"MCP Streamable HTTP",
            "mcpEndpoint":base+"/mcp","mcpVersions":[MCP_VERSION,*LEGACY_MCP_VERSIONS],
            "machineReadableOnboarding":base+"/api/onboarding",
            "customAgentRegistry":base.replace("https://","wss://").replace("http://","ws://")+"/ws/registry",
            "disclaimer":"This is discovery metadata only, not an A2A AgentCard asserting A2A compliance."}

@app.get("/.well-known/ai-catalog.json")
async def ai_catalog_discovery():
    base=PUBLIC_SERVER_URL.rstrip("/")
    return {"name":"AI Market","readOnlyDiscovery":True,"signedOfferPublishing":True,"paymentCustody":False,
            "mcp":base+"/mcp","offers":base+"/api/agent/now",
            "demand":base+"/api/requests","join":base+"/api/onboarding",
            "auth":"No key for discovery; signed identity for publishing"}

@app.get("/mcp/server-card")
async def mcp_server_card():
    base=PUBLIC_SERVER_URL.rstrip("/")
    return {"name":"AI Market","version":"1.4.0","url":base+"/mcp",
            "transport":"streamable-http","supportedVersions":[MCP_VERSION,*LEGACY_MCP_VERSIONS],
            "authentication":"none for read-only queries",
            "tools":[tool["name"] for tool in MCP_TOOL_DEFINITIONS]}

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
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid request"}}, status_code=400)
    # Legacy default clients initialize without modern metadata; modern clients remain strict.
    era_header=request.headers.get("mcp-protocol-version")
    if msg["method"] == "initialize" or msg["method"] == "notifications/initialized" or era_header in LEGACY_MCP_VERSIONS or (not era_header and msg["method"] in ("tools/list","tools/call","ping")):
        return await legacy_mcp_request(request,msg)
    if "id" not in msg:
        return JSONResponse({"jsonrpc":"2.0","error":{"code":-32600,"message":"Request ID required"}},status_code=400)
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
        result = {"resultType": "complete", "supportedVersions": [MCP_VERSION], "capabilities": {"tools": {"listChanged": False}, "resources": {}, "extensions": {"io.modelcontextprotocol/skills": {}}}, "instructions": "Search verified online AI agents. Optional user-approved skill: skill://ai-market/SKILL.md. Discovery is free and read-only; do not assume payments or buyers are funded.", "ttlMs": 300000, "cacheScope": "public"}
    elif method == "skills/list":
        if set(params)-{"_meta"}:
            return mcp_jsonrpc_error(request_id,-32602,"Invalid skill list parameters")
        result={"resultType":"complete","skills":[mcp_agent_skill_entry()],
                "ttlMs":300000,"cacheScope":"public"}
    elif method == "skills/get":
        if params.get("uri")!=AGENT_SKILL_URI or set(params)-{"uri","_meta"}:
            return mcp_jsonrpc_error(request_id,-32602,"Unknown skill URI")
        result={"resultType":"complete","skill":mcp_agent_skill_entry(),
                "ttlMs":300000,"cacheScope":"public"}
    elif method == "resources/list":
        if set(params)-{"_meta"}:
            return mcp_jsonrpc_error(request_id,-32602,"Invalid resource list parameters")
        entry=mcp_agent_skill_entry()
        result={"resultType":"complete","resources":[{"uri":AGENT_SKILL_URI,
                    "name":"ai-market",
                    "description":entry["frontmatter"]["description"],
                    "mimeType":"text/markdown"}],"ttlMs":300000,"cacheScope":"public"}
    elif method == "resources/read":
        if params.get("uri")!=AGENT_SKILL_URI or set(params)-{"uri","_meta"}:
            return mcp_jsonrpc_error(request_id,-32602,"Unknown resource URI")
        result={"resultType":"complete","contents":[{"uri":AGENT_SKILL_URI,
                 "mimeType":"text/markdown","text":SKILL_PATH.read_text("utf-8")}],
                 "ttlMs":300000,"cacheScope":"public"}
    elif method == "tools/list":
        result = {"resultType": "complete", "tools": MCP_TOOL_DEFINITIONS, "ttlMs": 300000, "cacheScope": "public"}
    elif method == "tools/call":
        name, arguments = params.get("name"), params.get("arguments", {})
        if not isinstance(name, str) or request.headers.get("mcp-name") != name:
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32020, "message": "Tool name header mismatch"}}, status_code=400)
        if not isinstance(arguments, dict) or name not in {tool["name"] for tool in MCP_TOOL_DEFINITIONS}:
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Invalid tool or arguments"}}, status_code=400)
        if name in ("prepare_signed_offer","publish_signed_offer","browse_signed_offers"):
            try: data=await handle_offer_tool(name,arguments)
            except ValueError as exc:
                return JSONResponse({"jsonrpc":"2.0","id":request_id,"error":{"code":-32602,"message":str(exc)}},status_code=400)
        elif name == "search_agents":
            capability = arguments.get("capability")
            if arguments.keys() - {"capability"} or (capability is not None and (not isinstance(capability, str) or len(capability) > 64)):
                return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Invalid capability"}}, status_code=400)
            async with state_lock:
                matches = [{"agent_id": k, "capabilities": p["capabilities"], "pricing": p["pricing"], "identity_verified": True} for k, p in agent_profiles.items() if p.get("identity_verified") and (not capability or capability in p["capabilities"])]
            data = {"agents": matches[:100], "count": len(matches), "persistent": False}
        elif name == "agent_flight_check":
            if set(arguments)-{"capabilities","currency"}:
                return JSONResponse({"jsonrpc":"2.0","id":request_id,"error":{"code":-32602,"message":"Unknown flight check argument"}},status_code=400)
            try:
                data=await compute_agent_flight_check(arguments.get("capabilities"),arguments.get("currency","ETH"))
            except ValueError:
                return JSONResponse({"jsonrpc":"2.0","id":request_id,"error":{"code":-32602,"message":"Invalid flight check input"}},status_code=400)
        elif name == "real_buyer_requests":
            if arguments:
                return JSONResponse({"jsonrpc":"2.0","id":request_id,"error":{"code":-32602,"message":"No arguments expected"}},status_code=400)
            data = await public_requests()
        elif name == "market_in_one_call":
            if arguments:
                return JSONResponse({"jsonrpc":"2.0","id":request_id,"error":{"code":-32602,"message":"No arguments expected"}},status_code=400)
            data = await agent_fast_start()
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
    result["_meta"] = {"io.modelcontextprotocol/serverInfo": {"name": "AI-Market", "version": "1.4.0"}}
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
        async with state_lock:
            expire_stale_trades()
            matches=[public_need(need) for need in open_needs.values()
                     if need["buyer"]!=agent_id and need["capability"] in safe_profile["capabilities"]]
        if matches:
            await websocket.send_json({"event":"matching_requests","requests":matches,
                                       "note":"Buyer requests are not funded orders"})
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
            elif action == "publish_need":
                capability=msg.get("capability")
                currency=msg.get("currency")
                budget=msg.get("max_budget")
                details=msg.get("details","")
                if (not isinstance(details,str) or len(details)>500 or
                    any(ord(ch)<32 and ch not in (chr(9),chr(10)) for ch in details)):
                    await websocket.send_json({"error":"invalid_buyer_request_details"})
                    continue
                details=details.strip()
                if (not isinstance(capability,str) or not 1<=len(capability.strip())<=64
                    or any(ord(ch)<32 for ch in capability) or not isinstance(currency,str) or currency not in FEE_WALLETS
                    or isinstance(budget,bool) or not isinstance(budget,(int,float))
                    or not math.isfinite(budget) or not 0.00000001<=budget<=100000):
                    await websocket.send_json({"error":"invalid_buyer_request"})
                    continue
                capability=capability.strip()
                async with state_lock:
                    expire_stale_trades()
                    existing=next((n for n in open_needs.values()
                                   if n["buyer"]==agent_id and n["capability"]==capability
                                   and n["currency"]==currency and n["max_budget"]==budget
                                   and n.get("details","")==details),None)
                    own=sum(n["buyer"]==agent_id for n in open_needs.values())
                    if existing:
                        need=existing
                        error=None
                        created=False
                        alert=[]
                    elif own>=3 or len(open_needs)>=MAX_PUBLIC_NEEDS:
                        error="buyer_request_limit"
                        created=False
                        alert=[]
                    else:
                        error=None
                        created=True
                        nid=uuid.uuid4().hex
                        now=datetime.now(timezone.utc)
                        need={"id":nid,"buyer":agent_id,"capability":capability,"currency":currency,
                              "max_budget":budget,"details":details,"created_at":now.isoformat(),
                              "expires_at":datetime.fromtimestamp(time.time()+NEED_TTL_SECONDS,timezone.utc).isoformat(),
                              "created_monotonic":time.monotonic()}
                        open_needs[nid]=need
                        alert=[conn for seller,conn in active_agents.items()
                               if seller!=agent_id and capability in agent_profiles.get(seller,{}).get("capabilities",[])]
                if error:
                    await websocket.send_json({"error":error})
                    continue
                if created: usage_event("requests_published")
                await websocket.send_json({"event":"request_published","request":public_need(need),
                                           "funds_reserved":False,"new":created,"expires_in_seconds":NEED_TTL_SECONDS})
                for conn in alert:
                    try: await conn.send_json({"event":"matching_buyer_request","request":public_need(need),
                                               "funds_reserved":False})
                    except Exception: pass
            elif action == "cancel_need":
                nid=msg.get("request_id")
                async with state_lock:
                    item=open_needs.get(nid) if isinstance(nid,str) else None
                    if item and item["buyer"]==agent_id:
                        open_needs.pop(nid,None)
                        removed=True
                    else:
                        removed=False
                if removed: usage_event("requests_cancelled")
                await websocket.send_json({"event":"request_cancelled","request_id":nid,"removed":removed})
            elif action == "my_matches":
                async with state_lock:
                    expire_stale_trades()
                    services=agent_profiles.get(agent_id,{}).get("capabilities",[])
                    matching=[public_need(need) for need in open_needs.values()
                              if need["buyer"]!=agent_id and need["capability"] in services]
                await websocket.send_json({"event":"matching_requests","requests":matching,
                                           "note":"Identity-signed requests; not guaranteed funded"})
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
