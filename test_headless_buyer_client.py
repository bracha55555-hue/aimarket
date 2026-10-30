import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from eth_account import Account
from fastapi.testclient import TestClient
import app as market

spec=importlib.util.spec_from_file_location("aimarket_headless_buyer",Path("client/post-job.py"))
buyer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(buyer)

class LocalWebSocket:
    def __init__(self,client,trace):
        self.client=client
        self.trace=trace
    async def __aenter__(self):
        self.session=self.client.websocket_connect("/ws/registry")
        self.session.__enter__()
        return self
    async def __aexit__(self,*args):
        self.session.__exit__(*args)
    async def send(self,message):
        self.trace.append(json.loads(message))
        self.session.send_text(message)
    async def recv(self):
        return json.dumps(self.session.receive_json())

class SignedRealBuyerClientTest(unittest.TestCase):
    def test_headless_signed_request_uses_real_server_protocol_and_never_transmits_key(self):
        account=Account.create()
        trace=[]
        with patch.object(market,"PUBLIC_SERVER_URL",buyer.BASE),TestClient(market.app) as c:
            def connector(url,**kwargs):
                self.assertEqual(url,buyer.WSS)
                self.assertLessEqual(kwargs["max_size"],16384)
                return LocalWebSocket(c,trace)
            try:
                result=asyncio.run(buyer.publish_request(connector,account.key.hex(),
                    "translation","ETH","0.02","Translate my real business document"))
                self.assertTrue(result["published"])
                self.assertTrue(result["new"])
                self.assertFalse(result["funds_reserved"])
                self.assertIn(result["request_id"],market.open_needs)
                self.assertEqual(c.get("/api/requests").json()["count"],1)
                self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)
                self.assertEqual([x.get("action") for x in trace],[None,"authenticate","publish_need"])
                self.assertEqual(trace[2]["details"],"Translate my real business document")
                transmitted=json.dumps(trace)
                self.assertNotIn(account.key.hex(),transmitted)
                self.assertNotIn("private_key",transmitted)
                self.assertFalse(c.get("/health").json()["escrow"])
            finally:
                market.open_needs.clear()

    def test_rejects_identity_challenge_tampering_and_unapproved_budget(self):
        account=Account.create()
        real={"event":"auth_challenge","expires_seconds":60,
              "message":"AI Market agent authentication\nOrigin: "+buyer.BASE+
                        "\nIdentity: "+account.address.lower()+"\nNonce: "+"a"*64}
        self.assertEqual(buyer.validate_auth_challenge(real,account.address),real["message"])
        for altered in [
            {**real,"message":real["message"].replace(buyer.BASE,"https://other.example")},
            {**real,"message":real["message"].replace(account.address.lower(),Account.create().address.lower())},
            {**real,"message":real["message"][:-1]+"Z"},
            {**real,"expires_seconds":100000},
        ]:
            with self.assertRaises(ValueError):
                buyer.validate_auth_challenge(altered,account.address)
        for terms in [
            ("translation","ETH","0","Actual work"),
            ("translation","ETH","nan","Actual work"),
            ("translation","TEST","0.02","Actual work"),
            ("<script>","ETH","0.02","Actual work"),
            ("translation","ETH","0.02",""),
        ]:
            with self.assertRaises(ValueError):
                buyer.validate_request(*terms)

    def test_local_identity_file_is_shared_securely_and_explicit_publish_is_required(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"buyer.key"
            key=buyer.load_identity(path)
            self.assertEqual(buyer.load_identity(path),key)
            if __import__("os").name=="posix":
                self.assertEqual(path.stat().st_mode&0o077,0)
                path.chmod(0o644)
                with self.assertRaises(ValueError):
                    buyer.load_identity(path)
            other=Path(root)/"symlink.key"
            other.symlink_to(path)
            with self.assertRaises(ValueError):
                buyer.load_identity(other)
            with patch("sys.argv",["post-job.py","--capability","translation","--currency","ETH",
                    "--max-budget","0.02","--details","Actual task"]),\
                 patch.object(buyer,"load_identity",side_effect=AssertionError("identity accessed")):
                with self.assertRaises(SystemExit) as err:
                    buyer.main()
                self.assertEqual(err.exception.code,2)

if __name__=="__main__":
    unittest.main()
