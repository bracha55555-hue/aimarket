import os, asyncio, urllib.request, json, uuid, math, logging, base64, time
from decimal import Decimal
from collections import Counter
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import JSONResponse, Response
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
        "description_for_model": "Independent AI agent registry and coordination service using a custom WebSocket protocol. No escrow or verified on-chain settlement is offered. Payment status is only pending unless independently verified.",
        "api": {"type": "websocket", "url": f"{PUBLIC_SERVER_URL.replace('https', 'wss')}/ws/registry"},
        "auth": {"type": "none"},
        "x_protocol_note": "Custom WebSocket; not an implementation of the A2A standard"
    }

@app.get("/health")
async def health_check():
    async with state_lock: return {"status": "online", "role": "AI Market agent coordination", "connected_agents": len(active_agents), "active_trades": len(active_trades), "verified_settlement": False, "escrow": False, "durable_trades": False, "ephemeral_trade_ttl_seconds": TRADE_TTL_SECONDS, "noncustodial_eth_wallet_payments": True}

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

@app.get("/")
async def service_index():
    return {"service": "AI Market", "purpose": "AI-agent service discovery and trade coordination", "documentation": "/docs", "health": "/health", "directory": "/api/agents", "compact_directory": "/api/agents?format=n4", "n4_decoder": "/client/n4.js", "machine_readable": "/.well-known/ai-market.json", "websocket": "/ws/registry", "mcp": "/mcp", "fee_rate": 0.02, "payment_settlement": "signed_wallet_payments", "eth_quote": "/api/payments/eth/quote", "eth_verify": "/api/payments/eth/verify", "eth_client": "/client/eth-pay.js", "escrow": False, "ephemeral_trade_ttl_seconds": TRADE_TTL_SECONDS}

@app.get("/.well-known/ai-market.json")
async def machine_metadata():
    return {"name": "AI Market", "description": "Public custom agent registry, service discovery and trade coordination", "protocol": "ai-market-ws-v2", "transport": "WebSocket", "url": PUBLIC_SERVER_URL.rstrip("/").replace("https://", "wss://").replace("http://", "ws://") + "/ws/registry", "docs": PUBLIC_SERVER_URL.rstrip("/") + "/docs", "authentication_guide": PUBLIC_SERVER_URL.rstrip("/") + "/api/auth-guide", "mcp_endpoint": PUBLIC_SERVER_URL.rstrip("/") + "/mcp", "mcp_version": "2026-07-28", "n4_directory": PUBLIC_SERVER_URL.rstrip("/") + "/api/agents?format=n4", "n4_decoder": PUBLIC_SERVER_URL.rstrip("/") + "/client/n4.js", "fee_rate": 0.02, "supported_currencies": list(FEE_WALLETS), "escrow": False, "verified_settlement": False, "persistent_orders": False, "eth_quote": PUBLIC_SERVER_URL.rstrip("/") + "/api/payments/eth/quote", "eth_verify": PUBLIC_SERVER_URL.rstrip("/") + "/api/payments/eth/verify", "eth_client": PUBLIC_SERVER_URL.rstrip("/") + "/client/eth-pay.js", "warning": "Do not send private keys. Payment settlement is not implemented."}

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
            "Ethereum buyer payments can be signed and sent from the buyer wallet. Seller signs an exact invoice, buyer broadcasts two native ETH transfers, and the market confirms both only after 12 Ethereum confirmations. BTC/SOL/TRX verified settlement is not implemented. No escrow or persistent order storage; orders expire in one hour."
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
            data["payment_status"] = "not_implemented"
        else:
            if arguments:
                return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "No arguments expected"}}, status_code=400)
            data = await auth_guide()
        result = {"resultType": "complete", "content": [{"type": "text", "text": json.dumps(data, separators=(",", ":"))}], "structuredContent": data, "isError": False}
    else:
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}, status_code=404)
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
        await websocket.send_json({"status": "registered", "agent_id": agent_id, "identity_verified": True, "fee_rate": 0.02, "payment_settlement": "not_implemented"})
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
                    if tx.currency == "ETH":
                        amount_wei = int(Decimal(str(tx.total_amount)) * Decimal(10**18))
                        request_invoice = EthInvoice(order_id=tid, buyer=trade["buyer"], seller=trade["seller"], amount_wei=amount_wei, seller_signature="pending")
                        await seller_ws.send_json({"event": "sign_eth_invoice", "trade_id": tid, "message": eth_invoice_text(request_invoice),
                                                   "amount_wei": amount_wei, "note": "Sign this exact message locally using EIP-191; do not share your private key."})
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
