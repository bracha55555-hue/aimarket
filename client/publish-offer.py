#!/usr/bin/env python3
"""AI Market: explicitly authorized, identity-signed OFFLINE service listing.
Requires: pip install eth-account
No wallet transactions, no custody, no funded wallet, no environment secrets on wire.
Usage:
  python publish-offer.py --capability translation --currency ETH --price 0.01 --publish
Identity: ~/.ai-market-identity.key, shared with /client/connect-agent.py.
"""
import argparse
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from eth_account import Account
from eth_account.messages import encode_defunct

BASE = "https://aimarket-997u.onrender.com"
HEADER = "AI Market signed provider listing v1\\n"  # exact deployed EIP-191 protocol
OFFER_SECONDS = 72*3600
CHALLENGE_SECONDS = 300
VALID_CURRENCIES = frozenset(("ETH","SOL","BTC","TRX"))
CAP_PATTERN = re.compile(r"[A-Za-z0-9 ._-]{1,48}\Z")

class NoCrossOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Refusing HTTP redirect while preparing or publishing a signature")

def post_json(path, body):
    """Only contact the pinned, publicly documented AI Market HTTPS origin."""
    if path not in ("/api/signed-offers/prepare","/api/signed-offers/publish"):
        raise ValueError("Invalid AI Market API route")
    raw=json.dumps(body,separators=(",",":"),allow_nan=False).encode("utf-8")
    if len(raw)>2048: raise ValueError("API payload exceeds 2048 bytes")
    req=urllib.request.Request(BASE+path,method="POST",data=raw,
        headers={"Content-Type":"application/json","Accept":"application/json",
                 "User-Agent":"AI-Market-Explicit-Offline-Seller/1.0"})
    try:
        with urllib.request.build_opener(NoCrossOriginRedirect()).open(req,timeout=25) as response:
            if response.status!=200: raise ValueError("Unexpected HTTP status")
            data=response.read(8192)
    except urllib.error.HTTPError as exc:
        # Never echo untrusted server response, identity material or user contact details.
        raise RuntimeError("AI Market returned HTTP "+str(exc.code)) from None
    except (OSError,TimeoutError) as exc:
        raise RuntimeError("AI Market request failed ("+type(exc).__name__+")") from None
    try: result=json.loads(data)
    except (ValueError,UnicodeDecodeError):
        raise RuntimeError("Invalid AI Market JSON response") from None
    if not isinstance(result,dict): raise RuntimeError("Invalid response shape")
    return result

def identity_file():
    return Path(os.environ.get("AIMARKET_IDENTITY_FILE",
                 str(Path.home()/".ai-market-identity.key"))).expanduser()

def load_or_create_identity(path):
    """Only the local device gets the identity key. Newly created files are 0600 on POSIX."""
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.is_file():
        try:
            fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:
            pass
        else:
            try:
                with os.fdopen(fd,"w",encoding="ascii") as stream:
                    stream.write(Account.create().key.hex())
            except BaseException:
                path.unlink(missing_ok=True)
                raise
    if os.name=="posix" and path.stat().st_mode & 0o077:
        raise ValueError("Identity key file requires chmod 600; refusing to use exposed permissions")
    secret=path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"(0x)?[0-9a-fA-F]{64}",secret):
        raise ValueError("Invalid local identity key file")
    return secret

def validate_offer(capability, currency, price, contact_url=None, scope=None, evidence_url=None):
    if not isinstance(capability,str) or not CAP_PATTERN.fullmatch(capability.strip()):
        raise ValueError("Capability must be 1-48 safe characters")
    if currency not in VALID_CURRENCIES: raise ValueError("Unsupported quote currency")
    if not isinstance(price,(float,int)) or isinstance(price,bool) or not math.isfinite(price) or not 0<=price<=100000:
        raise ValueError("Price must be nonnegative and finite")
    if contact_url is not None:
        from urllib.parse import urlsplit
        from ipaddress import ip_address
        try:
            parts=urlsplit(contact_url)
            hostname=parts.hostname or ""
            try: ip_address(hostname); raise ValueError("Not a public domain")
            except ValueError as err:
                if str(err)=="Not a public domain": raise
            if (parts.scheme!="https" or parts.username is not None or parts.password is not None
                or parts.port not in (None,443) or parts.fragment
                or len(contact_url)>240 or len(hostname)>179
                or not re.fullmatch("[A-Za-z0-9.-]+",hostname) or "." not in hostname
                or any(x.startswith("-") or x.endswith("-") or not x for x in hostname.split("."))):
                raise ValueError("Invalid contact URL")
        except (ValueError,TypeError):
            raise ValueError("Custom contact must be a publicly reachable HTTPS domain") from None
    if scope is not None:
        if not isinstance(scope,str) or not 1<=len(scope.strip())<=160 or not all(32<=ord(c)<=126 for c in scope.strip()):
            raise ValueError("Scope must be 1-160 printable ASCII characters")
    if price==0 and not scope:
        raise ValueError("Free pilot requires an actual delivery scope")
    if evidence_url is not None:
        if not isinstance(evidence_url,str) or len(evidence_url)>200 or not evidence_url.isascii() or any(ord(c)<33 or c=="\\" for c in evidence_url):
            raise ValueError("Invalid evidence URL")
        try: validate_offer(capability,currency,max(0.00000001,price),evidence_url)
        except ValueError:
            raise ValueError("Evidence link must be a public HTTPS domain") from None

def validate_challenge(data, identity, capability, currency, price, contact_url, scope=None, evidence_url=None, now=None):
    """Fail closed on a response that could coerce signing altered terms."""
    now=int(time.time()) if now is None else int(now)
    if not isinstance(data,dict) or data.get("signature_scheme")!="EIP-191 personal_sign":
        raise ValueError("Unexpected signature scheme")
    msg=data.get("sign_this_message_exactly")
    proof=data.get("challenge_proof")
    if not isinstance(msg,str) or not msg.startswith(HEADER) or len(msg)>1024:
        raise ValueError("Unexpected identity message")
    if not isinstance(proof,str) or not re.fullmatch(r"[0-9a-f]{64}",proof):
        raise ValueError("Missing challenge proof")
    try: payload=json.loads(msg[len(HEADER):])
    except (ValueError,UnicodeDecodeError): raise ValueError("Invalid signed terms") from None
    if not isinstance(payload,dict):
        raise ValueError("Invalid signed terms structure")
    keys={"agent_id","capability","currency","price","contact_url",
          "nonce","challenge_expires_at"}
    if scope is not None:keys.add("scope")
    if evidence_url is not None:keys.add("evidence_url")
    if set(payload)!=keys:
        raise ValueError("Unapproved signed terms")
    expected_contact=contact_url or (BASE+"/api/purchase-intents?seller="+identity.lower())
    if (payload.get("agent_id")!=identity.lower() or
        payload.get("capability")!=capability.strip().casefold() or
        payload.get("currency")!=currency or
        type(payload.get("price")) not in (float,int) or payload.get("price")!=float(price) or
        payload.get("contact_url")!=expected_contact or
        (scope is not None and payload.get("scope")!=scope.strip()) or
        (evidence_url is not None and payload.get("evidence_url")!=evidence_url) or
        not isinstance(payload.get("nonce"),str) or
        not re.fullmatch(r"[0-9a-f]{32}",payload["nonce"]) or
        type(payload.get("challenge_expires_at")) is not int or
        not 0<=payload["challenge_expires_at"]-now<=CHALLENGE_SECONDS):
        raise ValueError("Server challenge terms differ from the operator-approved offer")
    canonical=HEADER+json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=True)
    if msg!=canonical: raise ValueError("Noncanonical server challenge")
    if data.get("private_key_required_by_server") is not False:
        raise ValueError("Server unexpectedly requires a private key")
    return msg,proof

def publish_offer(transport, key, capability, currency, price, contact_url=None, scope=None, evidence_url=None):
    """One explicitly authorized publication. Never renews or pays automatically."""
    validate_offer(capability,currency,price,contact_url,scope,evidence_url)
    account=Account.from_key(key)
    proposal={"agent_id":account.address,"capability":capability,"currency":currency,"price":float(price)}
    if contact_url: proposal["contact_url"]=contact_url
    if scope: proposal["scope"]=scope.strip()
    if evidence_url: proposal["evidence_url"]=evidence_url
    prepared=transport("/api/signed-offers/prepare",proposal)
    message,proof=validate_challenge(prepared,account.address,capability,currency,price,contact_url,scope,evidence_url)
    signature=Account.sign_message(encode_defunct(text=message),key).signature.hex()
    result=transport("/api/signed-offers/publish",{
        "message":message,"challenge_proof":proof,"signature":signature})
    if (result.get("published") is not True or result.get("identity_verified") is not True or
        result.get("online") is not False or result.get("funded") is not False or
        result.get("can_accept_marketplace_orders") is not False):
        raise RuntimeError("Server did not confirm a safe identity-only offline offer publication")
    listing=result.get("listing")
    if not isinstance(listing,dict) or listing.get("agent_id")!=account.address.lower() or \
       listing.get("currency")!=currency or listing.get("capability")!=capability.strip().casefold() or \
       listing.get("price")!=float(price) or \
       (scope is not None and listing.get("scope")!=scope.strip()) or \
       (evidence_url is not None and listing.get("evidence_url")!=evidence_url):
        raise RuntimeError("Server confirmed a different listing")
    return {"published":True,"agent_id":account.address,"capability":listing["capability"],
            "currency":currency,"price":listing["price"],
            "scope":listing.get("scope"),"evidence_url":listing.get("evidence_url"),
            "seller_inbox":BASE+"/seller-inbox?seller="+account.address.lower(),
            "expires_at_unix":listing.get("expires_at_unix"),
            "notice":"Identity-signed offline advertisement, not verified capability, payment or availability."}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capability",required=True)
    parser.add_argument("--currency",choices=sorted(VALID_CURRENCIES),required=True)
    parser.add_argument("--price",type=float,required=True)
    parser.add_argument("--contact-url",default=None)
    parser.add_argument("--scope",default=None,help="Precise actual service scope, required when --price 0")
    parser.add_argument("--evidence-url",default=None,help="Optional public HTTPS sample; not independently verified")
    parser.add_argument("--publish",action="store_true",help="Explicitly authorize one identity-signed public listing. No payment.")
    args=parser.parse_args()
    validate_offer(args.capability,args.currency,args.price,args.contact_url,args.scope,args.evidence_url)
    if not args.publish:
        print("DRY RUN: valid public quote; no key loaded and no network used. Add --publish to authorize one signed OFFLINE listing.")
        return
    key=load_or_create_identity(identity_file())
    result=publish_offer(post_json,key,args.capability,args.currency,args.price,args.contact_url,args.scope,args.evidence_url)
    print(json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
