#!/usr/bin/env python3
"""One-time public AI Market directory submissions, from the exact deployed main revision."""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT="https://aimarket-997u.onrender.com"
CARD=ROOT+"/.well-known/agent-card.json"
MCP=ROOT+"/mcp"
REPO="https://github.com/bracha55555-hue/aimarket"
HEADERS={"Accept":"application/json","User-Agent":"AI-Market-Operator-Free-Discovery/1.0"}
MAX_BODY=160000

def read_json(url,method="GET",payload=None):
    if not url.startswith("https://"):
        raise ValueError("HTTPS required")
    data=None if payload is None else json.dumps(payload,separators=(",",":"),sort_keys=True).encode()
    headers=dict(HEADERS)
    if data is not None:
        headers["Content-Type"]="application/json"
    req=urllib.request.Request(url,data=data,method=method,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=28) as response:
            status=response.status
            raw=response.read(MAX_BODY+1)
    except urllib.error.HTTPError as error:
        status=error.code
        raw=error.read(MAX_BODY+1)
    if len(raw)>MAX_BODY:
        raise ValueError("oversized directory response")
    try:
        parsed=json.loads(raw.decode("utf-8"))
    except (ValueError,UnicodeDecodeError):
        parsed=None
    return status,parsed

def exact_live_release():
    expected=os.environ["EXPECTED_MAIN_SHA"]
    if len(expected)!=40 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("invalid exact main SHA")
    for attempt in range(48):
        try:
            status,health=read_json(ROOT+"/health")
            if status!=200 or not isinstance(health,dict) or health.get("deployed_git_sha")!=expected:
                raise ValueError("deployed revision not exact main")
            status,card=read_json(CARD)
            if status!=200 or not isinstance(card,dict):
                raise ValueError("live A2A card unavailable")
            interfaces=card.get("supportedInterfaces",[])
            if not isinstance(interfaces,list) or not any(
                    isinstance(item,dict) and item.get("url")==ROOT+"/a2a"
                    and item.get("protocolBinding")=="JSONRPC" and item.get("protocolVersion")=="1.0"
                    for item in interfaces):
                raise ValueError("live A2A JSONRPC 1.0 not advertised")
            capabilities=card.get("capabilities",{})
            if not isinstance(capabilities,dict) or capabilities.get("streaming") is not False:
                raise ValueError("unfounded streaming capability")
            status,install=read_json(ROOT+"/api/install")
            if status!=200 or not isinstance(install,dict) or (
                    install.get("read_only_mcp_url")!=MCP or
                    install.get("no_api_key_required_for_read_only") is not True):
                raise ValueError("free MCP discovery not verified")
            print("VERIFIED_EXACT_PRODUCTION_MAIN_SHA",expected,flush=True)
            return
        except (ValueError,OSError,TypeError,KeyError,TimeoutError) as error:
            print("AWAIT_DEPLOY",attempt+1,type(error).__name__,flush=True)
            if attempt==47:
                raise RuntimeError("Live public capabilities not confirmed; directory not contacted")
            time.sleep(7)

def submit_a2a_registry():
    endpoint="https://api.a2a-registry.org/public/ingest/"
    status,result=read_json(endpoint+"scan",method="POST",payload={"url":CARD})
    print("A2A_REGISTRY_PUBLIC_SCAN_HTTP",status,flush=True)
    if status not in (200,201,202) or not isinstance(result,dict) or result.get("error"):
        raise RuntimeError("A2A registry card scan not accepted; no listing submitted")
    status,result=read_json(endpoint+"submit",method="POST",payload={"url":CARD})
    print("A2A_REGISTRY_REAL_SUBMISSION_HTTP",status,flush=True)
    if status not in (200,201,202,409) or not isinstance(result,dict):
        raise RuntimeError("A2A registration not verified; never claim indexing")
    if isinstance(result.get("status"),str):
        print("A2A_REGISTRY_RETURNED_STATE",result["status"][:64],flush=True)
    package=result.get("package_name",result.get("packageName"))
    if isinstance(package,str) and len(package)<140:
        print("A2A_REGISTRY_PACKAGE",package,flush=True)
    print("A2A submission is unclaimed/public unless independent owner verification occurs.",flush=True)

def submit_agentsearch():
    endpoint="https://agentsearch.luthersystems.com/api/submit-agent"
    status,result=read_json(endpoint,method="POST",payload={"wellKnownURI":CARD})
    print("AGENTSEARCH_REAL_SUBMISSION_HTTP",status,flush=True)
    if status not in (200,201,202,409) or not isinstance(result,dict):
        raise RuntimeError("AgentSearch has not confirmed submission; no adoption claimed")
    if isinstance(result.get("status"),str):
        print("AGENTSEARCH_RETURNED_STATE",result["status"][:64],flush=True)
    for key in ("url","agentUrl","listingUrl"):
        link=result.get(key)
        if isinstance(link,str) and urlsplit(link).netloc=="agentsearch.luthersystems.com":
            print("AGENTSEARCH_OFFICIAL_RESULT",link[:250],flush=True)
            break
    print("Submitting one verified agent URL never proves it is indexed or has users.",flush=True)

def submit_claude_code_agents():
    endpoint="https://www.claudecodeagents.com/api/mcp/submit"
    status,schema=read_json(endpoint)
    if status!=200 or not isinstance(schema,dict) or schema.get("method")!="POST":
        raise RuntimeError("Official directory submission contract not verified")
    fields=schema.get("fields",{})
    if not isinstance(fields,dict) or not all(k in fields for k in ("name","description","remoteUrl")):
        raise RuntimeError("Official directory requires unexpected fields")
    desc=("Free remote MCP discovery of genuinely identity-signed AI-agent service offers "
          "and real unfunded buyer needs. Public no-wallet GitHub pilot inquiries are "
          "explicitly unverified. Read-only listing needs no API key; no escrow or "
          "guaranteed sellers, delivery, funds or earnings.")
    payload={"name":"AI Market","description":desc,"repoUrl":REPO,
             "remoteUrl":MCP,"homepage":ROOT,"category":"ai-agents","auth":"none"}
    status,result=read_json(endpoint,method="POST",payload=payload)
    print("CLAUDE_CODE_AGENTS_REAL_SUBMISSION_HTTP",status,flush=True)
    if status not in (200,201) or not isinstance(result,dict):
        raise RuntimeError("Claude Code Agents did not confirm public listing")
    if result.get("status") not in ("listed","accepted"):
        raise RuntimeError("Directory returned unexpected listing result")
    page=result.get("url")
    if not isinstance(page,str) or urlsplit(page).netloc not in (
            "claudecodeagents.com","www.claudecodeagents.com"):
        raise RuntimeError("Official public listing URL not returned")
    print("CLAUDE_CODE_AGENTS_OFFICIAL_LISTING",page[:260],flush=True)
    print("Independent page URL is a directory listing, not a verified customer or trade.",flush=True)

def main():
    venue=sys.argv[1] if len(sys.argv)==2 else ""
    callbacks={"a2a":submit_a2a_registry,"agentsearch":submit_agentsearch,
               "claudecodeagents":submit_claude_code_agents}
    if venue not in callbacks:
        raise SystemExit("Usage: verified_directory_wave.py a2a|agentsearch|claudecodeagents")
    exact_live_release()
    callbacks[venue]()
    print("No mass unsolicited messages, payments, fabricated listings or identities.",flush=True)

if __name__=="__main__":
    main()
