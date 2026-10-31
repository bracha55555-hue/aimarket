import unittest
from fastapi.testclient import TestClient
from eth_account import Account
from eth_account.messages import encode_defunct
import app as m

class GenuineServiceDiscoveryTest(unittest.TestCase):
    def test_signed_offline_supply_onboarding_filters_and_no_payment_claim(self):
        seller=Account.create()
        headers={"accept":"application/json, text/event-stream",
                 "content-type":"application/json","mcp-protocol-version":"2025-11-25"}
        with TestClient(m.app) as c:
            def mcp(name,args):
                return c.post("/mcp",headers=headers,json={"jsonrpc":"2.0","id":8,
                    "method":"tools/call","params":{"name":name,"arguments":args}})
            def list_real_offer(capability,currency,price):
                fields={"agent_id":seller.address,"capability":capability,"currency":currency,
                        "price":price,"contact_url":"https://provider.example/intake"}
                prep=mcp("prepare_signed_offer",fields)
                self.assertEqual(prep.status_code,200,prep.text)
                signed=prep.json()["result"]["structuredContent"]
                message=signed["sign_this_message_exactly"]
                sig=Account.sign_message(encode_defunct(text=message),seller.key).signature.hex()
                published=mcp("publish_signed_offer",{"message":message,
                            "challenge_proof":signed["challenge_proof"],"signature":sig})
                self.assertEqual(published.status_code,200,published.text)
                return published.json()["result"]["structuredContent"]["listing"]["offer_id"]
            try:
                before=c.get("/api/agent/now").json()
                self.assertEqual(before["signed_offline_offers_count"],0)
                eth=list_real_offer("translation","ETH",0.02)
                sol=list_real_offer("translation","SOL",0.04)
                code=list_real_offer("code-review","ETH",0.05)
                all_offers=c.get("/api/agent/now").json()
                self.assertEqual(all_offers["signed_offline_offers_count"],3)
                self.assertEqual(all_offers["available_agents_count"],0)
                self.assertEqual(all_offers["real_requests_count"],0)
                self.assertEqual(all_offers["settlement"]["fees_rate"],0.02)
                self.assertFalse(all_offers["settlement"]["payment_verified"])
                self.assertFalse(all_offers["settlement"]["escrow"])
                search=c.get("/api/agent/now",params={"capability":"translation",
                                                       "currency":"ETH","max_budget":"0.03"})
                self.assertEqual(search.status_code,200,search.text)
                data=search.json()
                self.assertEqual(data["signed_offline_offers_count"],1)
                self.assertEqual(data["signed_offline_offers"][0]["offer_id"],eth)
                self.assertFalse(data["signed_offline_offers"][0]["seller_online"])
                self.assertFalse(data["signed_offline_offers"][0]["availability_confirmed"])
                self.assertFalse(data["signed_offline_offers"][0]["contact_url_verified"])
                self.assertEqual(c.get("/api/agent/now",params={"capability":"translation",
                                      "currency":"SOL"}).json()["signed_offline_offers"][0]["offer_id"],sol)
                self.assertEqual(c.get("/api/agent/now",params={"capability":"code",
                                      "currency":"ETH"}).json()["signed_offline_offers"][0]["offer_id"],code)
                self.assertEqual(c.get("/api/agent/now",params={"capability":"translation",
                                      "currency":"ETH","max_budget":"0.01"}).json()["signed_offline_offers_count"],0)
                self.assertEqual(c.get("/api/agent/now",params={"currency":"TRX"}).json()["signed_offline_offers_count"],0)
                flight=c.get("/api/agent/flight-check",params={"capabilities":"translation,code-review","currency":"ETH"}).json()
                self.assertEqual(flight["live_supply"]["signed_offline_offers_by_capability_and_currency"],
                                 {"translation":1,"code-review":1})
                self.assertEqual(flight["live_supply"]["online_verified_agents_by_capability"],
                                 {"translation":0,"code-review":0})
                self.assertFalse(flight["live_supply"]["offline_available_now"])
                for budget in ["-1","0.000000001","nan","Infinity","100001","invalid","9"*45]:
                    self.assertEqual(c.get("/api/agent/now",params={"max_budget":budget}).status_code,422)
                self.assertEqual(c.get("/api/agent/now",params={"currency":"USD"}).status_code,422)
                self.assertEqual(c.get("/api/matches").json()["count"],0)
                m.signed_offers[eth]["expires_at_unix"]=0
                expired=c.get("/api/agent/now",params={"capability":"translation",
                                                      "currency":"ETH"}).json()
                self.assertEqual(expired["signed_offline_offers_count"],0)
            finally:
                m.signed_offers.clear()
                m.used_offer_proofs.clear()

if __name__=="__main__": unittest.main()
