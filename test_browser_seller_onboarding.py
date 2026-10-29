import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from eth_account import Account
from eth_account.messages import encode_defunct
import app as m

class OneMinuteProviderStudioTest(unittest.TestCase):
    def test_free_seller_funnel_includes_real_browser_and_wallet_safe_code(self):
        with TestClient(m.app) as c:
            page=c.get("/list-service")
            self.assertEqual(page.status_code,200)
            self.assertEqual(page.headers["cache-control"],"no-store")
            self.assertIn("script-src 'self'",page.headers["content-security-policy"])
            self.assertNotIn("unsafe-inline",page.headers["content-security-policy"].split("script-src")[1].split(";")[0])
            self.assertIn("No website",page.text)
            self.assertIn("Sign identity and list",page.text)
            self.assertIn('href="/seller-inbox"',page.text)
            self.assertIn("seller proposal inbox",page.text)
            js=c.get("/client/provider-studio.js")
            self.assertEqual(js.status_code,200)
            self.assertIn("personal_sign",js.text)
            self.assertIn("eth_requestAccounts",js.text)
            for forbidden in ("eth_sendTransaction","send_raw_transaction","privateKey","wallet_sendTransaction"):
                self.assertNotIn(forbidden,js.text)
            landing=c.get("/",headers={"accept":"text/html"}).text
            self.assertIn('href="/list-service"',landing)
            self.assertIn('href="/post-job"',landing)
            self.assertEqual(c.get("/",headers={"accept":"application/json"}).json()["fee_rate"],0.02)

    def test_rest_and_mcp_use_same_signing_validation_and_replay_protection(self):
        seller,wrong=Account.create(),Account.create()
        with patch.object(m,"PUBLIC_SERVER_URL","https://aimarket-997u.onrender.com"),TestClient(m.app) as c:
            try:
                prep_path="/api/signed-offers/prepare"
                publish_path="/api/signed-offers/publish"
                payload={"agent_id":seller.address,"capability":"translation","currency":"SOL","price":0.015}
                for inp in ({**payload,"price":0},{**payload,"currency":"USD"},
                            {**payload,"private_key":"never send secrets"},{**payload,"contact_url":"http://localhost:3000"}):
                    result=c.post(prep_path,json=inp)
                    self.assertEqual(result.status_code,422,result.text)
                self.assertEqual(c.post(prep_path,data="hello",headers={"Content-Type":"text/plain"}).status_code,415)
                self.assertEqual(c.post(prep_path,content="[]",headers={"Content-Type":"application/json"}).status_code,422)
                self.assertEqual(c.post(prep_path,content="!!",headers={"Content-Type":"application/json"}).status_code,400)
                self.assertEqual(c.post(prep_path,content="x"*2200,headers={"Content-Type":"application/json"}).status_code,413)
                self.assertEqual(c.post(prep_path,json=payload,headers={"Origin":"https://not-our-origin.example"}).status_code,403)
                ready=c.post(prep_path,json=payload)
                self.assertEqual(ready.status_code,200,ready.text)
                offer=ready.json()
                self.assertTrue(offer["private_key_required_by_server"] is False)
                self.assertEqual(ready.headers["cache-control"],"no-store")
                msg=offer["sign_this_message_exactly"]
                signed={
                    "message":msg,
                    "challenge_proof":offer["challenge_proof"],
                    "signature":Account.sign_message(encode_defunct(text=msg),seller.key).signature.hex()
                }
                bad=c.post(publish_path,json={**signed,"signature":
                    Account.sign_message(encode_defunct(text=msg),wrong.key).signature.hex()})
                self.assertEqual(bad.status_code,422,bad.text)
                altered=c.post(publish_path,json={**signed,"message":msg.replace("0.015","0.016")})
                self.assertEqual(altered.status_code,422,altered.text)
                self.assertEqual(c.get("/api/signed-offers").json()["count"],0)
                ok=c.post(publish_path,json=signed)
                self.assertEqual(ok.status_code,200,ok.text)
                data=ok.json()
                self.assertTrue(data["published"])
                self.assertTrue(data["identity_verified"])
                self.assertFalse(data["online"])
                self.assertFalse(data["funded"])
                self.assertFalse(data["contact_url_verified"])
                self.assertEqual(data["listing"]["contact_url"],
                                 "https://aimarket-997u.onrender.com/api/purchase-intents?seller="+seller.address.lower())
                self.assertEqual(c.get("/api/signed-offers").json()["count"],1)
                self.assertEqual(c.post(publish_path,json=signed).status_code,422)
                # One canonical market store, observed consistently through MCP and REST.
                headers={"accept":"application/json, text/event-stream","content-type":"application/json",
                         "mcp-protocol-version":"2025-11-25"}
                body={"jsonrpc":"2.0","id":1,"method":"tools/call",
                      "params":{"name":"browse_signed_offers","arguments":{}}}
                seen=c.post("/mcp",headers=headers,json=body)
                self.assertEqual(seen.status_code,200,seen.text)
                offers=seen.json()["result"]["structuredContent"]["signed_offline_offers"]
                self.assertEqual(len(offers),1)
                self.assertEqual(offers[0]["offer_id"],data["listing"]["offer_id"])
                self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)
                # A second legitimate locally signed listing remains compatible with the REST publish path.
                second=c.post(prep_path,json={**payload,"capability":"code-review","contact_url":"https://seller.example/contact"})
                self.assertEqual(second.status_code,200)
                m2=second.json()["sign_this_message_exactly"]
                ok2=c.post(publish_path,json={"message":m2,"challenge_proof":second.json()["challenge_proof"],
                                  "signature":Account.sign_message(encode_defunct(text=m2),seller.key).signature.hex()})
                self.assertEqual(ok2.status_code,200,ok2.text)
                self.assertEqual(c.get("/api/signed-offers").json()["count"],2)
            finally:
                m.signed_offers.clear()
                m.used_offer_proofs.clear()

if __name__=="__main__":
    unittest.main()
