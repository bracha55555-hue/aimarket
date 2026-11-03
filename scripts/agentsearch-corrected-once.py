#!/usr/bin/env python3
"""One correct, operator-authorized AgentSearch submission after a distinct HTTP 400 card-only attempt."""
import re
from urllib.parse import urlsplit
from verified_directory_wave import ROOT,exact_live_release,read_json

API="https://agentsearch.luthersystems.com/api/"

def summary(value):
    if not isinstance(value,dict):
        return "non_json"
    for key in ("message","detail","error"):
        item=value.get(key)
        if isinstance(item,str):
            return re.sub(r"[^A-Za-z0-9 ._:/-]","?",item[:155])
    return "no_message"

def submit_corrected_url():
    probe_status,probe=read_json(API+"found-agent",method="POST",payload={
        "url":ROOT,"name":"AI Market","query":"discover real AI agent service offers"})
    print("AGENTSEARCH_READONLY_LIVE_PROBE_HTTP",probe_status,flush=True)
    if probe_status==429:
        raise RuntimeError("Provider rate limited; do not attempt new submission")
    if probe_status not in (200,201,202):
        print("AGENTSEARCH_PROBE_RESULT",summary(probe),flush=True)
        # The public docs list direct URL registration separately; a probe is advisory.
    payload={"url":ROOT,"name":"AI Market",
        "description":"Free public no-key MCP and A2A discovery of genuine AI-agent service offers and real buyer requests. Catalogs can be empty. Separate GitHub pilot inquiries are unverified, with no guaranteed sellers, funding, escrow or income."}
    status,result=read_json(API+"submit-agent",method="POST",payload=payload)
    print("AGENTSEARCH_CORRECTED_URL_SUBMISSION_HTTP",status,flush=True)
    if status not in (200,201,202,409) or not isinstance(result,dict):
        print("AGENTSEARCH_CORRECTED_ERROR",summary(result),flush=True)
        raise RuntimeError("AgentSearch has not confirmed corrected URL submission; no traffic or listing claim")
    if isinstance(result.get("status"),str):
        print("AGENTSEARCH_RESULT_STATE",result["status"][:60],flush=True)
    for field in ("url","listingUrl","agentUrl"):
        link=result.get(field)
        if isinstance(link,str) and urlsplit(link).netloc=="agentsearch.luthersystems.com":
            print("AGENTSEARCH_OFFICIAL_LISTING",link[:250],flush=True)
            break
    print("One voluntary real directory submission, not a buyer, signed seller, customer or paid transaction.")

if __name__=="__main__":
    exact_live_release()
    submit_corrected_url()
