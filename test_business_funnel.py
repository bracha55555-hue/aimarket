import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from eth_account import Account
from eth_account.messages import encode_defunct
import app as m

class AnonymousBusinessFunnelTest(unittest.TestCase):
    def test_real_signatures_count_stages_without_customer_identity_or_payment(self):
        seller,buyer=Account.create(),Account.create()
        base="https://aimarket-997u.onrender.com"
        def signed(challenge,identity):
            msg=challenge["sign_this_message_exactly"]
            return {"message":msg,"challenge_proof":challenge["challenge_proof"],
                    "signature":Account.sign_message(encode_defunct(text=msg),identity.key).signature.hex()}
        with patch.object(m,"PUBLIC_SERVER_URL",base),TestClient(m.app) as c:
            before=c.get("/api/market/stats").json()["business_funnel_events"]
            try:
                self.assertEqual(c.get("/list-service").status_code,200)
                self.assertEqual(c.get("/post-job").status_code,200)
                self.assertEqual(c.get("/seller-inbox").status_code,200)
                bad=c.post("/api/signed-offers/prepare",json={"agent_id":seller.address,
                    "capability":"translation","currency":"ETH","price":0})
                self.assertEqual(bad.status_code,422)
                self.assertEqual(c.get("/api/market/stats").json()["business_funnel_events"]["valid_provider_signing_challenges"],
                                 before["valid_provider_signing_challenges"])
                data={"agent_id":seller.address,"capability":"translation","currency":"ETH","price":0.01}
                prepared=c.post("/api/signed-offers/prepare",json=data)
                self.assertEqual(prepared.status_code,200,prepared.text)
                offerposted=c.post("/api/signed-offers/publish",json=signed(prepared.json(),seller))
                self.assertEqual(offerposted.status_code,200,offerposted.text)
                oid=offerposted.json()["listing"]["offer_id"]
                with c.websocket_connect("/ws/registry") as ws:
                    ws.send_json({"agent_id":buyer.address.lower(),"capabilities":[],"pricing":{}})
                    welcome=ws.receive_json()
                    self.assertEqual(welcome["event"],"auth_challenge")
                    ws.send_json({"action":"authenticate","signature":
                        Account.sign_message(encode_defunct(text=welcome["message"]),buyer.key).signature.hex()})
                    self.assertTrue(ws.receive_json()["identity_verified"])
                    ws.send_json({"action":"publish_need","capability":"translation","currency":"ETH",
                        "max_budget":0.02,"details":"Translate a genuine public business document into Hebrew"})
                    event=ws.receive_json()
                    self.assertEqual(event["event"],"request_published")
                    rid=event["request"]["id"]
                    p=c.post("/api/purchase-intents/prepare",json={"request_id":rid,"offer_id":oid})
                    self.assertEqual(p.status_code,200,p.text)
                    proposal=c.post("/api/purchase-intents/publish",json=signed(p.json(),buyer))
                    self.assertEqual(proposal.status_code,200,proposal.text)
                    self.assertFalse(proposal.json()["payment_verified"])
                    iid=proposal.json()["intent"]["id"]
                    pa=c.post("/api/purchase-intents/accept/prepare",json={"intent_id":iid})
                    self.assertEqual(pa.status_code,200,pa.text)
                    approved=c.post("/api/purchase-intents/accept/publish",json=signed(pa.json(),seller))
                    self.assertEqual(approved.status_code,200,approved.text)
                    self.assertFalse(approved.json()["payment_verified"])
                    record=c.get("/api/market/stats").json()
                    actual=record["business_funnel_events"]
                    expected={"buyer_page_requests":1,"buyer_requests_signed":1,
                        "provider_page_requests":1,"valid_provider_signing_challenges":1,
                        "provider_offers_signed":1,"valid_buyer_proposal_challenges":1,
                        "buyer_proposals_signed":1,"seller_inbox_page_requests":1,
                        "valid_seller_ack_challenges":1,"seller_acknowledgements_signed":1}
                    for name,delta in expected.items():
                        self.assertEqual(actual[name]-before[name],delta,name)
                    self.assertEqual(set(actual),set(expected))
                    self.assertTrue(all(type(value) is int for value in actual.values()))
                    self.assertNotIn(seller.address,repr(actual))
                    self.assertNotIn(buyer.address,repr(actual))
                    self.assertIn("tests",record["business_funnel_scope"].lower())
                    self.assertIn("not necessarily the same customers",record["business_funnel_scope"])
                    self.assertEqual(record["events_since_start"]["settlements_verified"],0)
                    self.assertEqual(record["nonbinding_intents_accepted"],1)
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
