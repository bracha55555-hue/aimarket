import contextlib
import importlib.util
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from eth_account import Account
import app as market

source=Path("client/publish-offer.py")
spec=importlib.util.spec_from_file_location("aimarket_offline_provider",source)
cli=importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

class HeadlessRealAgentListingTest(unittest.TestCase):
    def test_explicit_local_signature_publishes_real_offline_offer_not_fake_funds(self):
        identity=Account.create()
        with patch.object(market,"PUBLIC_SERVER_URL",cli.BASE),TestClient(market.app) as c:
            calls=[]
            def local_transport(path,body):
                calls.append((path,dict(body)))
                result=c.post(path,json=body)
                if result.status_code!=200:
                    raise AssertionError("Local server HTTP "+str(result.status_code)+" "+result.text)
                return result.json()
            try:
                resp=c.get("/client/publish-offer.py")
                self.assertEqual(resp.status_code,200)
                self.assertIn("text/x-python",resp.headers["content-type"])
                self.assertIn("NoCrossOriginRedirect",resp.text)
                self.assertIn("AIMARKET_IDENTITY_FILE",resp.text)
                self.assertIn("/client/publish-offer.py",c.get("/list-service").text)
                result=cli.publish_offer(local_transport,identity.key.hex(),"translation","ETH",0.01)
                self.assertTrue(result["published"])
                self.assertEqual(result["agent_id"].lower(),identity.address.lower())
                self.assertEqual(result["seller_inbox"],cli.BASE+"/seller-inbox?seller="+identity.address.lower())
                self.assertEqual([x[0] for x in calls],["/api/signed-offers/prepare","/api/signed-offers/publish"])
                for _,payload in calls:
                    self.assertNotIn("private_key",payload)
                    self.assertNotIn("key",payload)
                    self.assertNotIn(identity.key.hex(),json.dumps(payload))
                listing=c.get("/api/signed-offers").json()
                self.assertEqual(listing["count"],1)
                self.assertFalse(listing["available_now"])
                self.assertFalse(listing["contact_urls_unverified"] is False)
                self.assertFalse(c.get("/health").json()["escrow"])
                self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)
            finally:
                market.signed_offers.clear()
                market.used_offer_proofs.clear()

    def test_local_client_refuses_exact_challenge_tampering_before_private_signing(self):
        identity=Account.create()
        offer={"agent_id":identity.address,"capability":"translation","currency":"SOL","price":0.125}
        with patch.object(market,"PUBLIC_SERVER_URL",cli.BASE),TestClient(market.app) as c:
            prepared=c.post("/api/signed-offers/prepare",json=offer)
            self.assertEqual(prepared.status_code,200,prepared.text)
            actual=prepared.json()
            good=cli.validate_challenge(actual,identity.address,"translation","SOL",0.125,None)
            self.assertEqual(good[0],actual["sign_this_message_exactly"])
            wrong=[
                ({"sign_this_message_exactly":actual["sign_this_message_exactly"].replace("translation","fake-translation")}, "terms"),
                ({"sign_this_message_exactly":actual["sign_this_message_exactly"].replace('"SOL"','"ETH"')}, "currency"),
                ({"sign_this_message_exactly":actual["sign_this_message_exactly"].replace("0.125","0.126")}, "price"),
                ({"sign_this_message_exactly":actual["sign_this_message_exactly"].replace(identity.address.lower(),Account.create().address.lower())}, "identity"),
                ({"sign_this_message_exactly":actual["sign_this_message_exactly"].replace("/api/purchase-intents","/stolen-inbox")}, "contact"),
                ({"signature_scheme":"unexpected"}, "scheme"),
                ({"private_key_required_by_server":True}, "key"),
                ({"challenge_proof":"wrong"}, "proof"),
            ]
            for mod,label in wrong:
                with self.subTest(tamper=label):
                    with self.assertRaises(ValueError):
                        cli.validate_challenge({**actual,**mod},identity.address,"translation","SOL",0.125,None)
            expired=dict(actual)
            with self.assertRaises(ValueError):
                cli.validate_challenge(expired,identity.address,"translation","SOL",0.125,None,
                                      now=int(time.time())+301)
            self.assertEqual(c.get("/api/signed-offers").json()["count"],0)

    def test_dry_run_does_not_load_or_create_identity_or_contact_network(self):
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/"local.key"
            args=["publish-offer.py","--capability","translation","--currency","ETH","--price","0.01"]
            with patch.object(sys,"argv",args),patch.object(cli,"identity_file",return_value=file),\
                 patch.object(cli,"post_json",side_effect=AssertionError("network used")),\
                 contextlib.redirect_stdout(io.StringIO()) as buf:
                cli.main()
            self.assertIn("DRY RUN",buf.getvalue())
            self.assertFalse(file.exists())
            with patch.dict(os.environ,{"AIMARKET_IDENTITY_FILE":str(file)}):
                key=cli.load_or_create_identity(cli.identity_file())
                self.assertEqual(len(Account.from_key(key).address),42)
                self.assertTrue(file.is_file())
                if os.name=="posix":
                    self.assertEqual(file.stat().st_mode&0o077,0)
                self.assertEqual(cli.load_or_create_identity(file),key)
                if os.name=="posix":
                    file.chmod(0o644)
                    with self.assertRaises(ValueError):
                        cli.load_or_create_identity(file)

if __name__=="__main__":
    unittest.main()
