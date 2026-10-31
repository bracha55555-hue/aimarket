import json
import time
import unittest
from unittest.mock import patch
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
import app as m

class SignedMCPBuyerTest(unittest.TestCase):
    def setUp(self):
        self.buyer=Account.create()
        self.seller=Account.create()
        self.terms={"buyer":self.buyer.address,"capability":"translation","currency":"ETH",
                    "max_budget":0.02,"details":"Translate a genuine client document, preserving formatting"}
        self.patch=patch.object(m,"PUBLIC_SERVER_URL","https://aimarket-997u.onrender.com")
        self.patch.start()
        self.client=TestClient(m.app)
        self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.patch.stop()
        m.open_needs.clear()
        m.used_need_proofs.clear()

    def prepare(self,terms=None):
        r=self.client.post("/api/signed-requests/prepare",json=terms or self.terms)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def publish(self,prepared,identity=None):
        message=prepared["sign_this_message_exactly"]
        key=(identity or self.buyer).key
        return self.client.post("/api/signed-requests/publish",json={
            "message":message,"challenge_proof":prepared["challenge_proof"],
            "signature":Account.sign_message(encode_defunct(text=message),key).signature.hex()})

    def test_real_signed_need_is_public_and_replay_fails(self):
        p=self.prepare()
        self.assertEqual(p["signature_scheme"],"EIP-191 personal_sign")
        self.assertFalse(p["private_key_required_by_server"])
        self.assertEqual(m.open_needs,{})
        r=self.publish(p)
        self.assertEqual(r.status_code,200,r.text)
        j=r.json()
        self.assertTrue(j["published"])
        self.assertTrue(j["new"])
        self.assertTrue(j["identity_verified"])
        self.assertFalse(j["funds_reserved"])
        self.assertFalse(j["payment_verified"])
        self.assertFalse(j["order_created"])
        self.assertFalse(j["escrow"])
        self.assertEqual(j["expires_in_seconds"],86400)
        self.assertEqual(j["request"]["buyer"],self.buyer.address.lower())
        self.assertEqual(j["request"]["max_budget"],0.02)
        self.assertEqual(self.client.get("/api/requests").json()["count"],1)
        self.assertEqual(self.client.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)
        self.assertEqual(self.publish(p).status_code,422)
        p2=self.prepare()
        j2=self.publish(p2).json()
        self.assertTrue(j2["published"])
        self.assertFalse(j2["new"])
        self.assertEqual(self.client.get("/api/requests").json()["count"],1)

    def test_wrong_signer_mutation_budget_and_expiration_fail(self):
        p=self.prepare()
        self.assertEqual(self.publish(p,self.seller).status_code,422)
        for newmessage in (p["sign_this_message_exactly"].replace('"ETH"','"SOL"'),
                           p["sign_this_message_exactly"].replace('0.02','0.03'),
                           p["sign_this_message_exactly"].replace(m.PUBLIC_SERVER_URL,'https://evil.invalid')):
            response=self.client.post("/api/signed-requests/publish",json={
                "message":newmessage,"challenge_proof":p["challenge_proof"],
                "signature":Account.sign_message(encode_defunct(text=newmessage),self.buyer.key).signature.hex()})
            self.assertEqual(response.status_code,422)
        with patch.object(m.time,"time",return_value=time.time()+301):
            self.assertEqual(self.publish(p).status_code,422)
        self.assertEqual(self.client.get("/api/requests").json()["count"],0)
        for mutation in ({"max_budget":0},{"max_budget":True},{"max_budget":float("nan")},
                         {"currency":"USD"},{"details":""},{"capability":"<script>"}):
            payload={**self.terms,**mutation}
            # Test JSON parsing with finite, well-defined payloads separately.
            if mutation.get("max_budget")!=mutation.get("max_budget"): continue
            self.assertEqual(self.client.post("/api/signed-requests/prepare",json=payload).status_code,422)
        self.assertEqual(self.client.post("/api/signed-requests/prepare",
            json={**self.terms,"private_key":"NEVER"}).status_code,422)

    def test_buyer_capacity_and_original_wire_compatibility(self):
        for index in range(3):
            params={**self.terms,"details":"Translate actual client document "+str(index)}
            self.assertEqual(self.publish(self.prepare(params)).status_code,200)
        self.assertEqual(self.client.get("/api/requests").json()["count"],3)
        newer={**self.terms,"details":"Fourth real request should be rejected"}
        self.assertEqual(self.publish(self.prepare(newer)).status_code,422)
        self.assertEqual(self.client.get("/api/requests").json()["count"],3)
        headers={"content-type":"application/json","accept":"application/json,text/event-stream","mcp-protocol-version":"2025-11-25"}
        old=self.client.post("/mcp",headers=headers,json={
            "jsonrpc":"2.0","id":1,"method":"tools/list","params":{}})
        self.assertEqual(old.status_code,200,old.text)
        self.assertIn("prepare_signed_request",{x["name"] for x in old.json()["result"]["tools"]})
        request=self.client.post("/mcp",headers=headers,json={
            "jsonrpc":"2.0","id":2,"method":"tools/call",
            "params":{"name":"prepare_signed_request","arguments":self.terms}})
        self.assertEqual(request.status_code,200,request.text)
        self.assertIn("sign_this_message_exactly",request.json()["result"]["structuredContent"])
        modern_headers={**headers,"mcp-protocol-version":"2026-07-28","mcp-method":"tools/list"}
        modern=self.client.post("/mcp",headers=modern_headers,json={
            "jsonrpc":"2.0","id":3,"method":"tools/list",
            "params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
                                "io.modelcontextprotocol/clientCapabilities":{}}}})
        self.assertEqual(modern.status_code,200,modern.text)
        self.assertEqual({x["name"] for x in modern.json()["result"]["tools"]},
                         {x["name"] for x in old.json()["result"]["tools"]})

if __name__=="__main__":
    unittest.main()
