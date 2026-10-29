import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from eth_account import Account
from eth_account.messages import encode_defunct
import app as m

class BrowserBuyerProposalTest(unittest.TestCase):
    def test_genuine_buyer_matches_genuine_seller_with_only_identity_signatures(self):
        buyer,seller,wrong=Account.create(),Account.create(),Account.create()
        base="https://aimarket-997u.onrender.com"
        with patch.object(m,"PUBLIC_SERVER_URL",base),TestClient(m.app) as c:
            def sign(challenge,identity):
                msg=challenge["sign_this_message_exactly"]
                return {"message":msg,"challenge_proof":challenge["challenge_proof"],
                        "signature":Account.sign_message(encode_defunct(text=msg),identity.key).signature.hex()}
            try:
                seller_info={"agent_id":seller.address,"capability":"translation","currency":"ETH","price":0.012}
                offerprep=c.post("/api/signed-offers/prepare",json=seller_info)
                self.assertEqual(offerprep.status_code,200,offerprep.text)
                offerposted=c.post("/api/signed-offers/publish",json=sign(offerprep.json(),seller))
                self.assertEqual(offerposted.status_code,200,offerposted.text)
                offer_id=offerposted.json()["listing"]["offer_id"]
                self.assertEqual(c.get("/api/matches").json()["count"],0)
                invalid=c.post("/api/purchase-intents/prepare",json={"request_id":"a"*32,"offer_id":offer_id})
                self.assertEqual(invalid.status_code,422)
                page=c.get("/post-job")
                self.assertEqual(page.status_code,200)
                self.assertIn('id="matching-offers"',page.text)
                self.assertIn('id="refresh-matches"',page.text)
                js=c.get("/client/buyer-studio.js")
                self.assertEqual(js.status_code,200)
                self.assertIn("/api/purchase-intents/prepare",js.text)
                self.assertIn("/api/purchase-intents/publish",js.text)
                for forbidden in ("eth_sendTransaction","wallet_sendTransaction","privateKey","send_raw_transaction"):
                    self.assertNotIn(forbidden,js.text)
                with c.websocket_connect("/ws/registry") as ws:
                    ws.send_json({"agent_id":buyer.address.lower(),"capabilities":[],"pricing":{}})
                    challenge=ws.receive_json()
                    self.assertEqual(challenge["event"],"auth_challenge")
                    ws.send_json({"action":"authenticate","signature":
                        Account.sign_message(encode_defunct(text=challenge["message"]),buyer.key).signature.hex()})
                    self.assertEqual(ws.receive_json()["status"],"registered")
                    ws.send_json({"action":"publish_need","capability":"translation","currency":"ETH",
                                  "max_budget":0.02,"details":"Genuine translation request with documented deliverable"})
                    made=ws.receive_json()
                    self.assertEqual(made["event"],"request_published")
                    rid=made["request"]["id"]
                    matched=c.get("/api/matches",params={"request_id":rid})
                    self.assertEqual(matched.status_code,200)
                    rows=matched.json()
                    self.assertEqual(rows["count"],1)
                    self.assertFalse(rows["payment_verified"])
                    self.assertEqual(rows["matches"][0]["offer_id"],offer_id)
                    prepare=c.post("/api/purchase-intents/prepare",json={"request_id":rid,"offer_id":offer_id})
                    self.assertEqual(prepare.status_code,200,prepare.text)
                    self.assertEqual(prepare.headers["cache-control"],"no-store")
                    args=sign(prepare.json(),buyer)
                    bad=c.post("/api/purchase-intents/publish",json=sign(prepare.json(),wrong))
                    self.assertEqual(bad.status_code,422)
                    self.assertEqual(c.post("/api/purchase-intents/publish",
                                     json={**args,"message":args["message"].replace("0.012","0.013")}).status_code,422)
                    self.assertEqual(c.post("/api/purchase-intents/publish",json=args,
                                     headers={"Origin":"https://malicious.example"}).status_code,403)
                    self.assertEqual(c.get("/api/purchase-intents").json()["count"],0)
                    published=c.post("/api/purchase-intents/publish",json=args)
                    self.assertEqual(published.status_code,200,published.text)
                    outcome=published.json()
                    self.assertTrue(outcome["published"])
                    self.assertFalse(outcome["seller_accepted"])
                    self.assertFalse(outcome["payment_verified"])
                    self.assertFalse(outcome["funds_reserved"])
                    self.assertFalse(outcome["order_created"])
                    self.assertEqual(c.post("/api/purchase-intents/publish",json=args).status_code,422)
                    inbox=c.get("/api/purchase-intents",params={"seller":seller.address})
                    self.assertEqual(inbox.status_code,200)
                    self.assertEqual(inbox.json()["count"],1)
                    self.assertEqual(inbox.json()["intents"][0]["status"],"proposed")
                    self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)
                    ws.send_json({"action":"cancel_need","request_id":rid})
                    self.assertTrue(ws.receive_json()["removed"])
            finally:
                m.signed_offers.clear()
                m.used_offer_proofs.clear()
                m.purchase_intents.clear()
                m.used_intent_proofs.clear()
                m.open_needs.clear()

if __name__=="__main__":
    unittest.main()
