import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
import app as market

spec=importlib.util.spec_from_file_location("ai_market_provider",Path("client/publish-offer.py"))
cli=importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
SCOPE="Check one dated public claim, fetch source and publish URL, SHA-256 and retrieval time"
EVIDENCE="https://example.org/public-receipt"

class RealFirstIndependentProviderPilotTest(unittest.TestCase):
    def tearDown(self):
        market.signed_offers.clear()
        market.used_offer_proofs.clear()
        market.open_needs.clear()
        market.purchase_intents.clear()

    def test_real_zero_price_signed_offer_with_scope_and_self_declared_evidence(self):
        identity=Account.create()
        with patch.object(market,"PUBLIC_SERVER_URL",cli.BASE),TestClient(market.app) as c:
            def transport(path,payload):
                result=c.post(path,json=payload)
                self.assertEqual(result.status_code,200,result.text)
                return result.json()
            record=cli.publish_offer(transport,identity.key.hex(),"public-claim-check","ETH",0,
                    scope=SCOPE,evidence_url=EVIDENCE)
            self.assertTrue(record["published"])
            self.assertEqual(record["scope"],SCOPE)
            self.assertEqual(record["price"],0)
            self.assertEqual(record["evidence_url"],EVIDENCE)
            listing=c.get("/api/signed-offers").json()
            self.assertEqual(listing["count"],1)
            row=listing["signed_offline_offers"][0]
            self.assertEqual(row["scope"],SCOPE)
            self.assertEqual(row["evidence_url"],EVIDENCE)
            self.assertEqual(row["price"],0)
            self.assertTrue(listing["identity_only"])
            self.assertFalse(listing["available_now"])
            self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)
            self.assertFalse(c.get("/health").json()["escrow"])
            self.assertIn('id="scope"',c.get("/list-service",headers={"User-Agent":"AI-Market-Official-Business-Audit/1.0"}).text)
            self.assertIn('id="evidence"',c.get("/list-service",headers={"User-Agent":"AI-Market-Official-Business-Audit/1.0"}).text)
            script=c.get("/client/provider-studio.js").text
            self.assertIn("offer.scope = scope",script)
            self.assertIn("offer.evidence_url = evidence",script)

    def test_signed_terms_reject_forged_scope_or_evidence_and_replay(self):
        signer=Account.create()
        args={"agent_id":signer.address,"capability":"public-claim-check","price":0,
              "currency":"ETH","scope":SCOPE,"evidence_url":EVIDENCE}
        with TestClient(market.app) as c:
            for altered in ({**args,"scope":" "},{**args,"scope":SCOPE+"\nSecret"},
                            {**args,"evidence_url":"http://example.org/foo"},
                            {**args,"evidence_url":"https://127.0.0.1/foo"},
                            {k:v for k,v in args.items() if k!="scope"}):
                response=c.post("/api/signed-offers/prepare",json=altered)
                self.assertEqual(response.status_code,422,altered)
            prep=c.post("/api/signed-offers/prepare",json=args)
            self.assertEqual(prep.status_code,200,prep.text)
            data=prep.json()
            msg=data["sign_this_message_exactly"]
            self.assertEqual(json.loads(msg.split("\n",1)[1])["scope"],SCOPE)
            self.assertEqual(json.loads(msg.split("\n",1)[1])["evidence_url"],EVIDENCE)
            sig=Account.sign_message(encode_defunct(text=msg),signer.key).signature.hex()
            bad=msg.replace(SCOPE,"Different deliverable")
            for m in (bad,msg.replace(EVIDENCE,"https://example.org/other")):
                x=c.post("/api/signed-offers/publish",json={
                    "message":m,"challenge_proof":data["challenge_proof"],"signature":sig})
                self.assertEqual(x.status_code,422)
            pub={"message":msg,"challenge_proof":data["challenge_proof"],"signature":sig}
            posted=c.post("/api/signed-offers/publish",json=pub)
            self.assertEqual(posted.status_code,200,posted.text)
            self.assertEqual(posted.json()["listing"]["scope"],SCOPE)
            self.assertEqual(c.post("/api/signed-offers/publish",json=pub).status_code,422)

    def test_legacy_paid_offers_unchanged_free_without_scope_rejected(self):
        identity=Account.create()
        with TestClient(market.app) as c:
            old={"agent_id":identity.address,"capability":"translation","currency":"BTC","price":0.01}
            prep=c.post("/api/signed-offers/prepare",json=old)
            self.assertEqual(prep.status_code,200,prep.text)
            payload=json.loads(prep.json()["sign_this_message_exactly"].split("\n",1)[1])
            self.assertNotIn("scope",payload)
            self.assertNotIn("evidence_url",payload)
            self.assertEqual(c.post("/api/signed-offers/prepare",json={**old,"price":0}).status_code,422)
            self.assertEqual(c.post("/api/signed-offers/prepare",json={**old,"price":-1,"scope":SCOPE}).status_code,422)
        with self.assertRaises(ValueError): cli.validate_offer("test","ETH",0)
        cli.validate_offer("test","ETH",0,scope=SCOPE)

    def test_headless_cannot_be_forced_to_sign_changed_scope_or_evidence(self):
        seller=Account.create()
        with patch.object(market,"PUBLIC_SERVER_URL",cli.BASE),TestClient(market.app) as c:
            raw=c.post("/api/signed-offers/prepare",json={
                "agent_id":seller.address,"capability":"public-claim-check","currency":"ETH",
                "price":0,"scope":SCOPE,"evidence_url":EVIDENCE})
            self.assertEqual(raw.status_code,200,raw.text)
            cli.validate_challenge(raw.json(),seller.address,"public-claim-check","ETH",0,None,SCOPE,EVIDENCE)
            with self.assertRaises(ValueError):
                cli.validate_challenge(raw.json(),seller.address,"public-claim-check","ETH",0,None,
                                       "Different work",EVIDENCE)
            with self.assertRaises(ValueError):
                cli.validate_challenge(raw.json(),seller.address,"public-claim-check","ETH",0,None,
                                       SCOPE,"https://example.org/other")
            for uri in ("https://127.0.0.1/no","https://user:pass@example.org/no",
                        "https://example.org/a#fragment"):
                with self.assertRaises(ValueError):
                    cli.validate_offer("public-claim-check","ETH",0,scope=SCOPE,evidence_url=uri)

if __name__=="__main__":
    unittest.main()
