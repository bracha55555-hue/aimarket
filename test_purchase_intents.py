import unittest
from fastapi.testclient import TestClient
from eth_account import Account
from eth_account.messages import encode_defunct
import app as m

class SignedPurchaseIntentTest(unittest.TestCase):
    def test_two_real_signatures_nonbinding_and_anti_replay(self):
        buyer,seller=Account.create(),Account.create()
        headers={"accept":"application/json, text/event-stream","content-type":"application/json",
                 "mcp-protocol-version":"2025-11-25"}
        with TestClient(m.app) as c:
            def call(name,args,modern=False):
                payload={"jsonrpc":"2.0","id":12,"method":"tools/call","params":{"name":name,"arguments":args}}
                h=dict(headers)
                if modern:
                    h.update({"mcp-protocol-version":"2026-07-28",
                              "mcp-method":"tools/call","mcp-name":name})
                    payload["params"]["_meta"]={"io.modelcontextprotocol/protocolVersion":"2026-07-28",
                         "io.modelcontextprotocol/clientCapabilities":{}}
                return c.post("/mcp",headers=h,json=payload)
            def signed(prep,account):
                data=prep.json()["result"]["structuredContent"]
                return {"message":data["sign_this_message_exactly"],
                        "challenge_proof":data["challenge_proof"],
                        "signature":Account.sign_message(encode_defunct(text=data["sign_this_message_exactly"]),account.key).signature.hex()}
            try:
                listing={"agent_id":seller.address,"capability":"translation","currency":"ETH",
                         "price":0.02,"contact_url":"https://provider.example/intake"}
                prep=call("prepare_signed_offer",listing)
                self.assertEqual(prep.status_code,200,prep.text)
                posted=call("publish_signed_offer",signed(prep,seller))
                self.assertEqual(posted.status_code,200,posted.text)
                offer_id=posted.json()["result"]["structuredContent"]["listing"]["offer_id"]
                self.assertEqual(c.get("/api/purchase-intents").json()["count"],0)
                self.assertEqual(call("prepare_purchase_intent",{"request_id":"f"*32,"offer_id":offer_id}).status_code,400)
                with c.websocket_connect("/ws/registry") as ws:
                    ws.send_json({"agent_id":buyer.address.lower(),"capabilities":[],"pricing":{}})
                    challenge=ws.receive_json()["message"]
                    ws.send_json({"action":"authenticate","signature":
                         Account.sign_message(encode_defunct(text=challenge),buyer.key).signature.hex()})
                    self.assertEqual(ws.receive_json()["status"],"registered")
                    ws.send_json({"action":"publish_need","capability":"translation","currency":"ETH",
                                  "max_budget":0.03,"details":"Real paid translation request"})
                    created=ws.receive_json()
                    self.assertEqual(created["event"],"request_published")
                    request_id=created["request"]["id"]
                    match=c.get("/api/matches",params={"request_id":request_id}).json()
                    self.assertEqual(match["count"],1)
                    p=call("prepare_purchase_intent",{"request_id":request_id,"offer_id":offer_id},modern=True)
                    self.assertEqual(p.status_code,200,p.text)
                    bad=call("publish_purchase_intent",signed(p,seller),modern=True)
                    self.assertEqual(bad.status_code,400)
                    args=signed(p,buyer)
                    self.assertEqual(call("publish_purchase_intent",{**args,"message":args["message"].replace("0.02","0.03")}).status_code,400)
                    ok=call("publish_purchase_intent",args,modern=True)
                    self.assertEqual(ok.status_code,200,ok.text)
                    record=ok.json()["result"]["structuredContent"]["intent"]
                    self.assertEqual(record["status"],"proposed")
                    self.assertFalse(ok.json()["result"]["structuredContent"]["payment_verified"])
                    self.assertFalse(ok.json()["result"]["structuredContent"]["order_created"])
                    intent_id=record["id"]
                    self.assertEqual(c.get("/api/purchase-intents",params={"seller":seller.address}).json()["count"],1)
                    self.assertEqual(call("publish_purchase_intent",args).status_code,400)
                    prep2=call("prepare_accept_intent",{"intent_id":intent_id})
                    self.assertEqual(prep2.status_code,200,prep2.text)
                    self.assertEqual(call("accept_purchase_intent",signed(prep2,buyer)).status_code,400)
                    accepted=call("accept_purchase_intent",signed(prep2,seller),modern=True)
                    self.assertEqual(accepted.status_code,200,accepted.text)
                    result=accepted.json()["result"]["structuredContent"]
                    self.assertTrue(result["two_identities_signed"])
                    self.assertFalse(result["binding_order"])
                    self.assertFalse(result["payment_verified"])
                    self.assertFalse(result["funds_reserved"])
                    self.assertEqual(result["intent"]["status"],"accepted")
                    business=c.get("/api/market/stats").json()
                    self.assertEqual(business["nonbinding_intents_accepted"],1)
                    self.assertEqual(business["nonbinding_intents_proposed"],0)
                    self.assertEqual(business["events_since_start"]["intent_proposals_published"],1)
                    self.assertEqual(business["events_since_start"]["intent_acceptances"],1)
                    self.assertEqual(business["events_since_start"]["settlements_verified"],0)
                    self.assertEqual(call("accept_purchase_intent",signed(prep2,seller)).status_code,400)
                    self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)
                    ws.send_json({"action":"cancel_need","request_id":request_id})
                    self.assertTrue(ws.receive_json()["removed"])
                    self.assertEqual(call("prepare_accept_intent",{"intent_id":intent_id}).status_code,400)
            finally:
                m.purchase_intents.clear()
                m.used_intent_proofs.clear()
                m.signed_offers.clear()
                m.used_offer_proofs.clear()

    def test_n4_persists_real_intent_state(self):
        import tempfile,time
        from pathlib import Path
        from n4store import N4Store
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/"intents.n4db")
            record={"id":"a"*64,"buyer":"0xbuyer","seller":"0xseller",
                    "status":"accepted","currency":"SOL","expires_at_unix":int(time.time())+800}
            x=N4Store(path)
            x.put("intent",record["id"],record,"0xseller","SOL",record["expires_at_unix"])
            x.close()
            y=N4Store(path)
            self.assertEqual(y.scan("intent","0xseller","SOL")[record["id"]],record)
            y.close()

if __name__=="__main__":
    unittest.main()
