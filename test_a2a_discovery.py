import time
import unittest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
import app as m

class ActualA2ADiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(m.app)
        self.client.__enter__()
        m.open_needs.clear()
        m.signed_offers.clear()
    def tearDown(self):
        m.open_needs.clear()
        m.signed_offers.clear()
        self.client.__exit__(None,None,None)

    def rpc(self,cmd,version="1.0",extra=None,request_id=5):
        body={"jsonrpc":"2.0","id":request_id,"method":"SendMessage",
              "params":{"message":{"messageId":"external-msg-123","role":"ROLE_USER",
                                   "parts":[{"text":cmd}]}}}
        if extra: body.update(extra)
        return self.client.post("/a2a",json=body,
            headers={"A2A-Version":version,"User-Agent":"Independent-A2A-Client/1.0"})

    def test_agentcard_has_real_v1_jsonrpc_binding_only(self):
        response=self.client.get("/.well-known/agent-card.json")
        self.assertEqual(response.status_code,200,response.text)
        card=response.json()
        self.assertEqual(card["supportedInterfaces"],[
            {"url":m.PUBLIC_SERVER_URL.rstrip("/")+"/a2a","protocolBinding":"JSONRPC","protocolVersion":"1.0"},
            {"url":m.PUBLIC_SERVER_URL.rstrip("/")+"/a2a","protocolBinding":"JSONRPC","protocolVersion":"0.3.0"}])
        self.assertFalse(card["capabilities"]["streaming"])
        self.assertFalse(card["capabilities"]["pushNotifications"])
        self.assertEqual(card["defaultInputModes"],["text/plain"])
        self.assertTrue(card["skills"])
        self.assertIn("unfunded",card["description"])
        self.assertEqual(self.client.get("/.well-known/agent.json").json(),card)
        self.assertTrue(self.client.get("/.well-known/mcp.json").json()["a2a_protocol_supported"])
        self.assertTrue(self.client.get("/.well-known/ai-market.json").json()["a2a_protocol_supported"])
        self.assertIn(m.PUBLIC_SERVER_URL.rstrip("/")+"/.well-known/agent-card.json",self.client.get("/sitemap.xml").text)

    def test_empty_genuine_market_no_spending_no_key_and_no_fake_buyer(self):
        first=self.rpc("market")
        self.assertEqual(first.status_code,200,first.text)
        data=first.json()
        self.assertEqual(data["id"],5)
        self.assertEqual(data["result"]["message"]["role"],"ROLE_AGENT")
        self.assertEqual(data["result"]["message"]["parts"][1]["data"]["buyer_request_count"],0)
        self.assertEqual(data["result"]["message"]["parts"][1]["data"]["signed_offline_offer_count"],0)
        self.assertFalse(data["result"]["message"]["parts"][1]["data"]["escrow"])
        self.assertEqual(len(m.open_needs),0)
        self.assertEqual(len(m.signed_offers),0)
        for word in ("offers","requests","offers:translation"):
            response=self.rpc(word)
            self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)

    def test_real_current_data_from_same_internal_catalog(self):
        now=datetime.now(timezone.utc)
        m.open_needs["need1"]={"id":"need1","buyer":"0x0000000000000000000000000000000000000001",
            "capability":"translation","currency":"ETH","max_budget":0.1,
            "created_at":now.isoformat(),"expires_at":(now+timedelta(hours=1)).isoformat(),
            "created_monotonic":time.monotonic(),"details":"Genuine sample only inside test process"}
        m.signed_offers["offer1"]={"offer_id":"offer1",
            "agent_id":"0x0000000000000000000000000000000000000002",
            "capability":"translation","currency":"ETH","price":0.05,
            "contact_url":"https://example.org/inbox","expires_at_unix":int(time.time())+2000}
        needs=self.rpc("requests").json()["result"]["message"]["parts"][1]["data"]
        self.assertEqual(needs["request_count"],1)
        self.assertEqual(needs["unfunded_requests"][0]["id"],"need1")
        offers=self.rpc("offers:translation").json()["result"]["message"]["parts"][1]["data"]
        self.assertEqual(offers["offer_count"],1)
        self.assertEqual(offers["identity_signed_offline_offers"][0]["offer_id"],"offer1")
        other=self.rpc("offers:code-review").json()["result"]["message"]["parts"][1]["data"]
        self.assertEqual(other["offer_count"],0)
        self.assertEqual(len(m.purchase_intents),0)
        self.assertEqual(len(m.active_trades),0)

    def test_independent_legacy_03_agent_compatibility_without_write_access(self):
        body={"jsonrpc":"2.0","id":"probe-1","method":"message/send",
              "params":{"message":{"messageId":"skitter-style-01","role":"user",
                                   "parts":[{"kind":"text","text":"offers"}]}}}
        response=self.client.post("/a2a",json=body,
            headers={"User-Agent":"Independent-A2A-Client/0.3"})
        self.assertEqual(response.status_code,200,response.text)
        msg=response.json()["result"]
        self.assertEqual(msg["kind"],"message")
        self.assertEqual(msg["role"],"agent")
        self.assertEqual(msg["parts"][0]["kind"],"text")
        self.assertEqual(msg["parts"][1]["kind"],"data")
        self.assertEqual(msg["parts"][1]["data"]["offer_count"],0)
        self.assertFalse(msg["parts"][1]["data"]["escrow"])
        for cmd in ("market","requests","offers:translation"):
            body["params"]["message"]["parts"][0]["text"]=cmd
            self.assertEqual(self.client.post("/a2a",json=body,
                headers={"A2A-Version":"0.3.0"}).status_code,200)
        body["params"]["message"]["parts"][0]["text"]="buy now"
        self.assertEqual(self.client.post("/a2a",json=body).status_code,400)
        body["params"]["message"]["parts"][0]["text"]="offers"
        self.assertEqual(self.client.post("/a2a",json=body,
            headers={"A2A-Version":"1.0"}).status_code,400)
        body["method"]="SendMessage"
        self.assertEqual(self.client.post("/a2a",json=body).status_code,400)
        self.assertEqual(len(m.open_needs),0)
        self.assertEqual(len(m.signed_offers),0)

    def test_fail_closed_on_payment_commands_and_unsupported_methods(self):
        for cmd in ("buy now","pay 0.5 ETH","publish job","send private key","offers:<script>"):
            self.assertEqual(self.rpc(cmd).status_code,400,cmd)
        self.assertEqual(self.rpc("offers",version="0.3").status_code,400)
        self.assertEqual(self.rpc("offers",extra={"method":"GetTask"}).json()["error"]["code"],-32601)
        self.assertEqual(self.rpc("offers",extra={"params":{"message":{"messageId":"abc",
            "role":"ROLE_USER","taskId":"existing","parts":[{"text":"offers"}]}}}).status_code,400)
        self.assertEqual(self.rpc("offers",request_id=True).status_code,400)
        huge=self.client.post("/a2a",content=b"X"*5000,
                              headers={"Content-Type":"application/json"})
        self.assertEqual(huge.status_code,413)
        self.assertEqual(len(m.open_needs),0)
        self.assertEqual(len(m.signed_offers),0)

    def test_official_read_only_audits_not_counted_as_independent_adoption(self):
        if True:
            before=self.client.get("/api/market/stats").json()["events_since_start"]["a2a_discovery_calls"]
            body={"jsonrpc":"2.0","id":3,"method":"SendMessage",
                "params":{"message":{"messageId":"m-1","role":"ROLE_USER","parts":[{"text":"status"}]}}}
            for ua in ("AI-Market-Official-Business-Audit/1.0","AI-Market-IndexNow-Official/1.0"):
                self.assertEqual(self.client.post("/a2a",json=body,headers={"User-Agent":ua}).status_code,200)
            after=self.client.get("/api/market/stats").json()["events_since_start"]["a2a_discovery_calls"]
            self.assertEqual(after,before)
            self.assertEqual(self.client.post("/a2a",json=body,headers={"User-Agent":"OtherAgent/1.0"}).status_code,200)
            self.assertEqual(self.client.get("/api/market/stats").json()["events_since_start"]["a2a_discovery_calls"],before+1)

if __name__=="__main__": unittest.main()
