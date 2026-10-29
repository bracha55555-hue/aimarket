import unittest
from fastapi.testclient import TestClient
from eth_account import Account
from eth_account.messages import encode_defunct
import app as m

class HostedProviderInboxTest(unittest.TestCase):
    def test_provider_signs_and_receives_genuine_buyer_proposal_without_external_url(self):
        seller,buyer=Account.create(),Account.create()
        hdr={"accept":"application/json, text/event-stream","content-type":"application/json",
             "mcp-protocol-version":"2025-11-25"}
        with TestClient(m.app) as c:
            def tool(name,args):
                return c.post("/mcp",headers=hdr,json={"jsonrpc":"2.0","id":31,"method":"tools/call",
                    "params":{"name":name,"arguments":args}})
            def sign(prep,account):
                data=prep.json()["result"]["structuredContent"]
                msg=data["sign_this_message_exactly"]
                return {"message":msg,"challenge_proof":data["challenge_proof"],
                        "signature":Account.sign_message(encode_defunct(text=msg),account.key).signature.hex()}
            try:
                listing={"agent_id":seller.address,"capability":"code-review",
                         "currency":"SOL","price":0.01}
                prep=tool("prepare_signed_offer",listing)
                self.assertEqual(prep.status_code,200,prep.text)
                self.assertIn("/api/purchase-intents?seller=",prep.json()["result"]["structuredContent"]["sign_this_message_exactly"])
                result=tool("publish_signed_offer",sign(prep,seller))
                self.assertEqual(result.status_code,200,result.text)
                listing=result.json()["result"]["structuredContent"]["listing"]
                self.assertEqual(listing["contact_url"],m.PUBLIC_SERVER_URL.rstrip("/")+
                                 "/api/purchase-intents?seller="+seller.address.lower())
                self.assertFalse(result.json()["result"]["structuredContent"]["online"])
                self.assertEqual(c.get("/api/purchase-intents",params={"seller":seller.address}).json()["count"],0)
                with c.websocket_connect("/ws/registry") as ws:
                    ws.send_json({"agent_id":buyer.address.lower(),"capabilities":[],"pricing":{}})
                    challenge=ws.receive_json()
                    self.assertEqual(challenge["event"],"auth_challenge")
                    ws.send_json({"action":"authenticate","signature":
                        Account.sign_message(encode_defunct(text=challenge["message"]),buyer.key).signature.hex()})
                    self.assertEqual(ws.receive_json()["status"],"registered")
                    ws.send_json({"action":"publish_need","capability":"code-review","currency":"SOL",
                                  "max_budget":0.02,"details":"Genuine buyer code review requirement"})
                    made=ws.receive_json()
                    self.assertEqual(made["event"],"request_published")
                    matches=c.get("/api/matches",params={"request_id":made["request"]["id"]}).json()
                    self.assertEqual(matches["count"],1)
                    prep_buyer=tool("prepare_purchase_intent",{"request_id":made["request"]["id"],
                                                               "offer_id":listing["offer_id"]})
                    self.assertEqual(prep_buyer.status_code,200,prep_buyer.text)
                    published=tool("publish_purchase_intent",sign(prep_buyer,buyer))
                    self.assertEqual(published.status_code,200,published.text)
                    inbox=c.get("/api/purchase-intents",params={"seller":seller.address})
                    self.assertEqual(inbox.status_code,200)
                    self.assertEqual(inbox.json()["count"],1)
                    self.assertEqual(inbox.json()["intents"][0]["status"],"proposed")
                    self.assertFalse(inbox.json()["payment_verified"])
                    self.assertFalse(inbox.json()["escrow"])
                    outsider=c.get("/api/purchase-intents",params={"seller":Account.create().address})
                    self.assertEqual(outsider.json()["count"],0)
                    ws.send_json({"action":"cancel_need","request_id":made["request"]["id"]})
                    self.assertTrue(ws.receive_json()["removed"])
                    self.assertEqual(tool("prepare_accept_intent",{"intent_id":inbox.json()["intents"][0]["id"]}).status_code,400)
            finally:
                m.open_needs.clear()
                m.purchase_intents.clear()
                m.used_intent_proofs.clear()
                m.signed_offers.clear()
                m.used_offer_proofs.clear()

if __name__=="__main__":
    unittest.main()
