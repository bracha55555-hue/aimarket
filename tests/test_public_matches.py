import time
import unittest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from eth_account import Account
from eth_account.messages import encode_defunct
import app as m

class RealOfferMatching(unittest.TestCase):
    def test_matching_does_not_invent_orders_or_bypass_price(self):
        seller=Account.create()
        buyer=Account.create()
        with TestClient(m.app) as c:
            prep=m.validated_offer_fields(seller.address,"Translation","SOL",0.015,"https://provider.example/contact")
            m.signed_offers[seller.address.lower()]={**prep,"expires_at_unix":int(time.time())+7200}
            need={"id":"a"*32,"buyer":buyer.address.lower(),"capability":"TRANSLATION",
                  "currency":"SOL","max_budget":0.02,"details":"Actual request",
                  "created_at":datetime.now(timezone.utc).isoformat(),
                  "expires_at":(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
                  "created_monotonic":time.monotonic()}
            m.open_needs[need["id"]]=need
            result=c.get("/api/matches").json()
            assert result["count"]==1 and not result["payment_verified"]
            match=result["matches"][0]
            assert match["seller_agent_id"]==seller.address.lower()
            assert match["seller_contact_url"]=="https://provider.example/contact"
            assert match["seller_online"] is False and match["order_created"] is False
            assert c.get("/api/matches?currency=ETH").json()["count"]==0
            assert c.get("/api/matches?capability=code-review").json()["count"]==0
            assert c.get("/api/matches?request_id="+("b"*32)).json()["count"]==0
            assert c.get("/api/matches?request_id=123").status_code==422
            assert c.get("/api/matches?currency=FAKE").status_code==422
            assert c.get("/api/matches?capability=%3Cscript%3E").status_code==422
            need["max_budget"]=0.01
            assert c.get("/api/matches").json()["count"]==0
            need["max_budget"]=0.02
            need["buyer"]=seller.address.lower()
            assert c.get("/api/matches").json()["count"]==0
            need["buyer"]=buyer.address.lower()
            old={"accept":"application/json, text/event-stream","content-type":"application/json",
                 "mcp-protocol-version":"2025-11-25"}
            params={"name":"match_real_services","arguments":{"currency":"SOL"}}
            legacy=c.post("/mcp",headers=old,json={"jsonrpc":"2.0","method":"tools/call","id":1,"params":params})
            assert legacy.status_code==200,legacy.text
            assert legacy.json()["result"]["structuredContent"]["count"]==1
            assert c.post("/mcp",headers=old,json={"jsonrpc":"2.0","method":"tools/call","id":2,
                       "params":{"name":"match_real_services","arguments":{"currency":"FAKE"}}}).status_code==400
            meta={"io.modelcontextprotocol/protocolVersion":"2026-07-28",
                  "io.modelcontextprotocol/clientCapabilities":{}}
            modern={**old,"mcp-protocol-version":"2026-07-28","mcp-method":"tools/call",
                    "mcp-name":"match_real_services"}
            response=c.post("/mcp",headers=modern,json={"jsonrpc":"2.0","method":"tools/call","id":3,
                       "params":{**params,"_meta":meta}})
            assert response.status_code==200,response.text
            assert response.json()["result"]["structuredContent"]["count"]==1
            m.signed_offers[seller.address.lower()]["expires_at_unix"]=0
            assert c.get("/api/matches").json()["count"]==0
            assert c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"]==0

if __name__=="__main__":
    unittest.main()
