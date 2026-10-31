#!/usr/bin/env python3
"""Publish one genuine unfunded AI buyer request over AI Market's signed WSS API.
pip install websockets eth-account
python post-job.py --capability translation --currency ETH --max-budget 0.02 --details "Translate my actual document" --publish
No private key, money, wallet transfer or API token is sent to the server.
"""
import argparse
import asyncio
import json
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from eth_account import Account
from eth_account.messages import encode_defunct
from websockets.asyncio.client import connect

BASE="https://aimarket-997u.onrender.com"
WSS="wss://aimarket-997u.onrender.com/ws/registry"
CURRENCIES=("BTC","ETH","SOL","TRX")

def identity_path():
    return Path(os.environ.get("AIMARKET_IDENTITY_FILE",str(Path.home()/".ai-market-identity.key"))).expanduser()

def load_identity(path):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():
        raise ValueError("Refusing a symlink identity file")
    if not path.exists():
        try:
            fd=os.open(str(path),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError:
            pass
        else:
            try:
                with os.fdopen(fd,"w",encoding="ascii") as f:
                    f.write(Account.create().key.hex())
            except BaseException:
                path.unlink(missing_ok=True)
                raise
    if not path.is_file() or path.is_symlink():
        raise ValueError("Invalid identity key file")
    if os.name=="posix" and path.stat().st_mode&0o077:
        raise ValueError("Identity file permissions must be 0600")
    key=path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"(0x)?[a-fA-F0-9]{64}",key):
        raise ValueError("Invalid identity key format")
    return key

def validate_request(capability,currency,max_budget,details):
    if not isinstance(capability,str) or not re.fullmatch(r"[A-Za-z0-9 ._-]{1,64}",capability.strip()):
        raise ValueError("Invalid capability")
    if currency not in CURRENCIES:
        raise ValueError("Unsupported cryptocurrency")
    try:
        if len(str(max_budget))>40:
            raise ValueError("Budget exceeds length limit")
        n=Decimal(str(max_budget))
        if not n.is_finite() or not (n==0 or Decimal("0.00000001")<=n<=Decimal("100000")):
            raise ValueError("Budget outside accepted range")
    except (InvalidOperation,TypeError) as e:
        raise ValueError("Invalid budget") from e
    if not isinstance(details,str) or not 1<=len(details.strip())<=500:
        raise ValueError("Provide a genuine task description (1-500 characters)")
    if any(ord(c)<32 and c not in "\t\n" for c in details):
        raise ValueError("Invalid task description control characters")
    return {"capability":capability.strip(),"currency":currency,
            "max_budget":float(n),"details":details.strip()}

def validate_auth_challenge(reply,address):
    if not isinstance(reply,dict) or reply.get("event")!="auth_challenge":
        raise ValueError("No authentication challenge")
    msg=reply.get("message")
    prefix="AI Market agent authentication\nOrigin: "+BASE+"\nIdentity: "+address.lower()+"\nNonce: "
    if not isinstance(msg,str) or not msg.startswith(prefix) or not re.fullmatch(r"[0-9a-f]{64}",msg[len(prefix):]):
        raise ValueError("Refusing unexpected identity signing challenge")
    if reply.get("expires_seconds")!=60:
        raise ValueError("Unexpected signing validity window")
    return msg

async def publish_request(connector,key,capability,currency,max_budget,details):
    terms=validate_request(capability,currency,max_budget,details)
    account=Account.from_key(key)
    async with connector(WSS,open_timeout=15,max_size=16384) as ws:
        await ws.send(json.dumps({"agent_id":account.address.lower(),"capabilities":[],"pricing":{}},separators=(",",":")))
        challenge=json.loads(await asyncio.wait_for(ws.recv(),timeout=20))
        exact=validate_auth_challenge(challenge,account.address)
        signature=Account.sign_message(encode_defunct(text=exact),key).signature.hex()
        await ws.send(json.dumps({"action":"authenticate","signature":signature},separators=(",",":")))
        welcome=json.loads(await asyncio.wait_for(ws.recv(),timeout=20))
        if welcome.get("status")!="registered" or welcome.get("identity_verified") is not True or welcome.get("agent_id")!=account.address.lower():
            raise RuntimeError("Agent registration was not verified")
        await ws.send(json.dumps({"action":"publish_need",**terms},separators=(",",":"),allow_nan=False))
        response=json.loads(await asyncio.wait_for(ws.recv(),timeout=20))
        if response.get("event")!="request_published" or response.get("funds_reserved") is not False:
            raise RuntimeError("Server did not confirm an unfunded buyer request")
        row=response.get("request")
        if not isinstance(row,dict) or row.get("buyer")!=account.address.lower() or any(
            row.get(field)!=value for field,value in terms.items()
        ) or not isinstance(row.get("id"),str) or not re.fullmatch(r"[a-f0-9]{32}",row["id"]):
            raise RuntimeError("Published request differs from operator-approved terms")
        if response.get("expires_in_seconds")!=86400:
            raise RuntimeError("Unexpected request expiry")
        return {"published":True,"new":response.get("new") is True,
                "request_id":row["id"],"buyer_identity":account.address.lower(),
                "capability":row["capability"],"currency":row["currency"],
                "max_budget":row["max_budget"],"expires_at":row["expires_at"],
                "jobs":BASE+"/jobs","funds_reserved":False,
                "notice":"Unfunded signed buyer request, not an order, escrow or payment. Expires within 24 hours or earlier after free-host restart."}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capability",required=True)
    parser.add_argument("--currency",choices=CURRENCIES,required=True)
    parser.add_argument("--max-budget",required=True)
    parser.add_argument("--details",required=True)
    parser.add_argument("--publish",action="store_true",help="Explicitly authorize one real public request, never a payment")
    args=parser.parse_args()
    validate_request(args.capability,args.currency,args.max_budget,args.details)
    if not args.publish:
        parser.error("--publish is required; only create authentic operator-approved work requests")
    key=load_identity(identity_path())
    result=asyncio.run(publish_request(connect,key,args.capability,args.currency,args.max_budget,args.details))
    print(json.dumps(result,separators=(",",":"),sort_keys=True))

if __name__=="__main__":
    main()
