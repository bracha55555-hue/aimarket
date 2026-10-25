import os, asyncio, urllib.request, json, uuid, math, logging
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, WebSocket
from pydantic import BaseModel
from typing import Dict, Literal, Optional
from web3 import Web3
from eth_account import Account
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
    if os.getenv("ENABLE_INTERNAL_DEMO_AGENTS", "0") == "1":
        asyncio.create_task(autonomous_buyer_agent("ResearchBot", "web_scraping"))
        asyncio.create_task(autonomous_seller_agent("ScraperBot", "web_scraping"))
    yield

app = FastAPI(title="A2A Global Transactions Center", lifespan=lifespan)

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
    async with state_lock: return {"status": "online", "role": "AI Market agent coordination", "connected_agents": len(active_agents), "active_trades": len(active_trades), "verified_settlement": False, "escrow": False, "durable_trades": False}

def execute_automated_trade(buyer_private_key: str, seller_address: str, amount_wei: int):
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
    amount_sats = int(round(total_amount_btc * 100_000_000))
    fee_sats = int(amount_sats * 0.02)
    seller_sats = amount_sats - fee_sats
    clean_key = buyer_private_key.strip().replace("0x", "")
    buyer_key = BTCKey.from_hex(clean_key) if len(clean_key) == 64 else BTCKey(buyer_private_key.strip())
    tx_hash = buyer_key.send([(FEE_WALLETS["BTC"], fee_sats, "satoshi"), (seller_address, seller_sats, "satoshi")])
    return {"status": "success", "chain": "BTC", "tx_hash": tx_hash}

async def execute_automated_sol_trade(buyer_private_key: str, seller_address: str, total_amount_sol: float):
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
    return {"service": "AI Market", "purpose": "AI-agent service discovery and trade coordination", "documentation": "/docs", "health": "/health", "directory": "/api/agents", "machine_readable": "/.well-known/ai-market.json", "websocket": "/ws/registry", "fee_rate": 0.02, "payment_settlement": "not implemented", "escrow": False}

@app.get("/.well-known/ai-market.json")
async def machine_metadata():
    return {"name": "AI Market", "description": "Public custom agent registry, service discovery and trade coordination", "protocol": "ai-market-ws-v1", "transport": "WebSocket", "url": PUBLIC_SERVER_URL.rstrip("/").replace("https://", "wss://").replace("http://", "ws://") + "/ws/registry", "docs": PUBLIC_SERVER_URL.rstrip("/") + "/docs", "fee_rate": 0.02, "supported_currencies": list(FEE_WALLETS), "escrow": False, "verified_settlement": False, "warning": "Do not send private keys. No payment has been verified by this service."}

@app.get("/api/agents")
async def public_agents():
    async with state_lock:
        safe = {agent_id: {"capabilities": profile["capabilities"], "pricing": profile["pricing"]} for agent_id, profile in agent_profiles.items()}
    return {"agents": safe, "count": len(safe), "note": "Registration is not cryptographically authenticated"}

@app.websocket("/ws/registry")
async def agent_registry_endpoint(websocket: WebSocket):
    await websocket.accept()
    agent_id = None
    try:
        init_data = json.loads(await websocket.receive_text())
        agent_id = init_data.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id or len(agent_id) > 64 or any(not (ch.isalnum() or ch in "._-") for ch in agent_id):
            await websocket.close(code=1008)
            return
        async with state_lock:
            duplicate = agent_id in active_agents
            if not duplicate:
                active_agents[agent_id] = websocket
                agent_profiles[agent_id] = init_data
                if agent_id not in agent_reputation: agent_reputation[agent_id] = {"score": 100}
        if duplicate:
            await websocket.send_json({"error": "agent_id_already_connected"})
            await websocket.close(code=1008)
            return
        await websocket.send_json({"status": "registered", "agent_id": agent_id, "announcement": "Connected to The Global Center for All Autonomous AI Transactions"})
        while True:
            msg = json.loads(await websocket.receive_text())
            action = msg.get("action")
            if action == "ping": await websocket.send_json({"action": "pong"})
            elif action == "discover":
                cap = msg.get("capability")
                async with state_lock: matches = {k: {"price": v.get("pricing", {}).get(cap, "Negotiable")} for k, v in agent_profiles.items() if cap in v.get("capabilities", []) and k != agent_id}
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
                    seller_ws = active_agents.get(tx.seller_agent)
                    profile = agent_profiles.get(tx.seller_agent)
                    pricing = profile.get("pricing", {}) if isinstance(profile, dict) else {}
                    if not seller_ws or not profile or tx.item_name not in profile.get("capabilities", []):
                        error = "seller_unavailable_or_incapable"
                    elif not isinstance(pricing, dict) or not isinstance(pricing.get(tx.item_name), (int, float)) or not math.isfinite(pricing[tx.item_name]) or pricing[tx.item_name] != tx.total_amount:
                        error = "price_mismatch"
                    elif len(active_trades) >= 1000:
                        error = "trade_capacity_reached"
                    elif any(t["buyer"] == agent_id and t["status"] in ("pending", "delivered", "awaiting_payment") for t in active_trades.values()):
                        error = "buyer_has_open_trade"
                    else:
                        trade_id = str(uuid.uuid4())
                        safe_data = tx.model_dump() if hasattr(tx, "model_dump") else tx.dict()
                        safe_data.pop("buyer_private_key", None)
                        active_trades[trade_id] = {"status": "pending", "buyer": agent_id, "seller": tx.seller_agent, "data": safe_data}
                if error:
                    await websocket.send_json({"error": error})
                    continue
                try:
                    await seller_ws.send_json({"event": "trade_requested", "trade_id": trade_id, "buyer": agent_id, "item": tx.item_name})
                except Exception:
                    async with state_lock: active_trades.pop(trade_id, None)
                    await websocket.send_json({"error": "seller_delivery_failed"})
            elif action == "deliver":
                tid, payload = msg.get("trade_id"), msg.get("payload")
                buyer_ws = None
                async with state_lock:
                    trade = active_trades.get(tid)
                    if trade and trade["seller"] == agent_id and trade["status"] == "pending":
                        trade["status"] = "delivered"
                        buyer_ws = active_agents.get(trade["buyer"])
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
    except Exception:
        if agent_id:
            async with state_lock:
                if active_agents.get(agent_id) is websocket:
                    active_agents.pop(agent_id, None)
                    agent_profiles.pop(agent_id, None)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "7860")))
