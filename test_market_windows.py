import time,unittest
from datetime import datetime,timezone
from unittest.mock import patch
from fastapi.testclient import TestClient
from eth_account import Account
from eth_account.messages import encode_defunct
import app as m

class GenuineAsynchronousMarketTest(unittest.TestCase):
    def test_authenticated_24h_buyer_72h_signed_seller_and_12h_nonbinding_proposal(self):
        buyer,seller=Account.create(),Account.create()
        base="https://aimarket-997u.onrender.com"
        with patch.object(m,"PUBLIC_SERVER_URL",base),TestClient(m.app) as c:
            try:
                self.assertEqual(m.NEED_TTL_SECONDS,24*60*60)
                self.assertEqual(m.OFFER_TTL_SECONDS,72*60*60)
                self.assertEqual(m.INTENT_TTL_SECONDS,12*60*60)
                self.assertEqual(m.TRADE_TTL_SECONDS,3600)  # Existing payment coordination unchanged.
                o={"agent_id":seller.address,"capability":"translation","currency":"ETH","price":0.01}
                pre=c.post("/api/signed-offers/prepare",json=o)
                self.assertEqual(pre.status_code,200,pre.text)
                msg=pre.json()["sign_this_message_exactly"]
                s=Account.sign_message(encode_defunct(text=msg),seller.key).signature.hex()
                posted=c.post("/api/signed-offers/publish",json={
                    "message":msg,"signature":s,"challenge_proof":pre.json()["challenge_proof"]})
                self.assertEqual(posted.status_code,200,posted.text)
                offer=posted.json()["listing"]
                self.assertEqual(posted.json()["expires_in_seconds"],72*60*60)
                self.assertTrue(72*3600-4<=offer["expires_at_unix"]-time.time()<=72*3600+4)
                self.assertFalse(posted.json()["online"])
                self.assertFalse(posted.json()["funded"])
                with c.websocket_connect("/ws/registry") as ws:
                    ws.send_json({"agent_id":buyer.address.lower(),"capabilities":[],"pricing":{}})
                    challenge=ws.receive_json()
                    self.assertEqual(challenge["event"],"auth_challenge")
                    ws.send_json({"action":"authenticate","signature":Account.sign_message(
                        encode_defunct(text=challenge["message"]),buyer.key).signature.hex()})
                    self.assertTrue(ws.receive_json()["identity_verified"])
                    ws.send_json({"action":"publish_need","capability":"translation","currency":"ETH",
                        "max_budget":0.02,"details":"Deliver genuine Hebrew translation within one day"})
                    e=ws.receive_json()
                    self.assertEqual(e["event"],"request_published",e)
                    rid=e["request"]["id"]
                    need=m.open_needs[rid]
                    remaining=datetime.fromisoformat(need["expires_at"]).timestamp()-time.time()
                    self.assertTrue(24*3600-5<=remaining<=24*3600+5,remaining)
                    # Beyond the old one-hour window, the genuine buyer request is still present.
                    m.expire_stale_trades(now=need["created_monotonic"]+2*3600)
                    self.assertIn(rid,m.open_needs)
                    matched=c.get("/api/matches",params={"request_id":rid}).json()
                    self.assertEqual(matched["count"],1,matched)
                    oid=offer["offer_id"]
                    p=c.post("/api/purchase-intents/prepare",json={"request_id":rid,"offer_id":oid})
                    self.assertEqual(p.status_code,200,p.text)
                    message=p.json()["sign_this_message_exactly"]
                    bs=Account.sign_message(encode_defunct(text=message),buyer.key).signature.hex()
                    result=c.post("/api/purchase-intents/publish",json={
                        "message":message,"signature":bs,"challenge_proof":p.json()["challenge_proof"]})
                    self.assertEqual(result.status_code,200,result.text)
                    intent=result.json()["intent"]
                    self.assertEqual(intent["status"],"proposed")
                    remaining_intent=intent["expires_at_unix"]-time.time()
                    self.assertTrue(12*3600-5<=remaining_intent<=12*3600+5,remaining_intent)
                    self.assertFalse(result.json()["funds_reserved"])
                    self.assertFalse(result.json()["payment_verified"])
                    self.assertFalse(result.json()["order_created"])
                    self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)
                    ws.send_json({"action":"cancel_need","request_id":rid})
                    self.assertTrue(ws.receive_json()["removed"])
            finally:
                m.signed_offers.clear()
                m.used_offer_proofs.clear()
                m.purchase_intents.clear()
                m.used_intent_proofs.clear()
                m.open_needs.clear()

    def test_deployed_copy_never_claims_durable_deals_or_automatically_available_sellers(self):
        with TestClient(m.app) as c:
            page=c.get("/list-service").text
            self.assertIn("Listings expire after 72 hours",page)
            inbox=c.get("/seller-inbox").text
            self.assertIn("listing expires within 72 hours",inbox)
            self.assertIn("buyer requests within 24 hours",inbox)
            jobs=c.get("/post-job").text
            self.assertIn("expires after 24 hours",jobs)
            market=c.get("/api/signed-offers").json()
            self.assertFalse(market["available_now"])
            self.assertTrue(market["identity_only"])
            self.assertTrue(market["contact_urls_unverified"])
            self.assertIn("host replacement",market["persistence"])
            self.assertEqual(c.get("/health").json()["escrow"],False)

if __name__=="__main__":
    unittest.main()
