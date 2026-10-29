import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from eth_account import Account
from eth_account.messages import encode_defunct
import app as m

class BrowserSellerAcknowledgementTest(unittest.TestCase):
    def test_public_browser_and_exact_two_party_nonbinding_signatures(self):
        buyer,seller,outsider=Account.create(),Account.create(),Account.create()
        base="https://aimarket-997u.onrender.com"
        def signed(challenge,identity):
            message=challenge["sign_this_message_exactly"]
            return {"message":message,"challenge_proof":challenge["challenge_proof"],
                    "signature":Account.sign_message(encode_defunct(text=message),identity.key).signature.hex()}
        with patch.object(m,"PUBLIC_SERVER_URL",base),TestClient(m.app) as c:
            try:
                page=c.get("/seller-inbox")
                self.assertEqual(page.status_code,200,page.text)
                self.assertEqual(page.headers["cache-control"],"no-store")
                self.assertIn("script-src 'self'",page.headers["content-security-policy"])
                self.assertNotIn("unsafe-inline",page.headers["content-security-policy"].split("script-src")[1].split(";")[0])
                self.assertIn("No purchase or payment",page.text)
                js=c.get("/client/seller-inbox.js")
                self.assertEqual(js.status_code,200)
                self.assertIn('personal_sign',js.text)
                self.assertIn('eth_requestAccounts',js.text)
                self.assertIn('textContent',js.text)
                self.assertIn("window.confirm",js.text)
                for forbidden in ("eth_sendTransaction","send_raw_transaction","wallet_sendTransaction","privateKey","innerHTML"):
                    self.assertNotIn(forbidden,js.text)
                provider_js=c.get("/client/provider-studio.js").text
                self.assertIn('new URL("/seller-inbox"',provider_js)
                self.assertIn('href="/seller-inbox"',c.get("/list-service").text)
                offer={"agent_id":seller.address,"capability":"translation","currency":"ETH","price":0.015}
                prepared=c.post("/api/signed-offers/prepare",json=offer)
                self.assertEqual(prepared.status_code,200,prepared.text)
                offer_posted=c.post("/api/signed-offers/publish",json=signed(prepared.json(),seller))
                self.assertEqual(offer_posted.status_code,200,offer_posted.text)
                oid=offer_posted.json()["listing"]["offer_id"]
                with c.websocket_connect("/ws/registry") as ws:
                    ws.send_json({"agent_id":buyer.address.lower(),"capabilities":[],"pricing":{}})
                    challenge=ws.receive_json()
                    self.assertEqual(challenge["event"],"auth_challenge")
                    ws.send_json({"action":"authenticate","signature":
                        Account.sign_message(encode_defunct(text=challenge["message"]),buyer.key).signature.hex()})
                    self.assertEqual(ws.receive_json()["status"],"registered")
                    ws.send_json({"action":"publish_need","capability":"translation","currency":"ETH",
                        "max_budget":0.02,"details":"Genuine requirement for a translated business document"})
                    made=ws.receive_json()
                    self.assertEqual(made["event"],"request_published")
                    rid=made["request"]["id"]
                    buyer_prep=c.post("/api/purchase-intents/prepare",json={"request_id":rid,"offer_id":oid})
                    self.assertEqual(buyer_prep.status_code,200,buyer_prep.text)
                    buyer_post=c.post("/api/purchase-intents/publish",json=signed(buyer_prep.json(),buyer))
                    self.assertEqual(buyer_post.status_code,200,buyer_post.text)
                    iid=buyer_post.json()["intent"]["id"]
                    inbox=c.get("/api/purchase-intents",params={"seller":seller.address})
                    self.assertEqual(inbox.status_code,200)
                    self.assertEqual(inbox.json()["count"],1)
                    self.assertEqual(inbox.json()["intents"][0]["id"],iid)
                    self.assertEqual(inbox.json()["intents"][0]["status"],"proposed")
                    prep_path="/api/purchase-intents/accept/prepare"
                    post_path="/api/purchase-intents/accept/publish"
                    self.assertEqual(c.post(prep_path,json={"intent_id":"not-valid"}).status_code,422)
                    self.assertEqual(c.post(prep_path,data="bad",headers={"content-type":"text/plain"}).status_code,415)
                    self.assertEqual(c.post(prep_path,json={"intent_id":iid,"private_key":"no"}).status_code,422)
                    self.assertEqual(c.post(prep_path,json={"intent_id":iid},headers={"Origin":"https://phish.example"}).status_code,403)
                    good=c.post(prep_path,json={"intent_id":iid})
                    self.assertEqual(good.status_code,200,good.text)
                    self.assertEqual(good.headers["cache-control"],"no-store")
                    bad=c.post(post_path,json=signed(good.json(),outsider))
                    self.assertEqual(bad.status_code,422)
                    tampered={**signed(good.json(),seller),
                              "message":good.json()["sign_this_message_exactly"].replace("seller acceptance","seller receipt")}
                    self.assertEqual(c.post(post_path,json=tampered).status_code,422)
                    self.assertEqual(c.get("/api/purchase-intents",params={"seller":seller.address}).json()["intents"][0]["status"],"proposed")
                    valid=signed(good.json(),seller)
                    accepted=c.post(post_path,json=valid)
                    self.assertEqual(accepted.status_code,200,accepted.text)
                    data=accepted.json()
                    self.assertTrue(data["accepted"])
                    self.assertTrue(data["two_identities_signed"])
                    self.assertFalse(data["binding_order"])
                    self.assertFalse(data["payment_verified"])
                    self.assertFalse(data["funds_reserved"])
                    self.assertFalse(data["escrow"])
                    self.assertEqual(data["intent"]["id"],iid)
                    self.assertEqual(data["intent"]["status"],"accepted")
                    self.assertEqual(c.post(post_path,json=valid).status_code,422)
                    self.assertEqual(c.post(prep_path,json={"intent_id":iid}).status_code,422)
                    self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["intent_acceptances"],1)
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
