import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
import app as market

ROOT="https://aimarket-997u.onrender.com"
SCOPE="Verify one cited public source by SHA-256 with a dated receipt"
DETAILS="Check a real public-source claim; share exact fetched hash and retrieval time"
spec=importlib.util.spec_from_file_location("buyer_client",Path("client/post-job.py"))
buyer_cli=importlib.util.module_from_spec(spec)
spec.loader.exec_module(buyer_cli)

class FreeBuyerMatchingTest(unittest.TestCase):
    def tearDown(self):
        market.signed_offers.clear()
        market.used_offer_proofs.clear()
        market.open_needs.clear()
        market.used_need_proofs.clear()
        market.purchase_intents.clear()
    def test_free_buyer_can_match_genuine_zero_price_service_and_not_paid_service(self):
        free_seller,paid_seller,buyer=Account.create(),Account.create(),Account.create()
        with patch.object(market,"PUBLIC_SERVER_URL",ROOT),TestClient(market.app) as client:
            def sign_and_publish(path,fields,identity):
                prepared=client.post(path+"/prepare",json=fields)
                self.assertEqual(prepared.status_code,200,prepared.text)
                proof=prepared.json()
                original=proof["sign_this_message_exactly"]
                signed=Account.sign_message(encode_defunct(text=original),identity.key).signature.hex()
                response=client.post(path+"/publish",json={
                    "message":original,"challenge_proof":proof["challenge_proof"],"signature":signed})
                self.assertEqual(response.status_code,200,response.text)
                return response.json()
            free=sign_and_publish("/api/signed-offers",{
                "agent_id":free_seller.address,"capability":"public-claim-check","currency":"ETH",
                "price":0,"scope":SCOPE,"evidence_url":"https://example.org/public-sha256"},free_seller)
            paid=sign_and_publish("/api/signed-offers",{
                "agent_id":paid_seller.address,"capability":"public-claim-check","currency":"ETH",
                "price":0.01,"scope":SCOPE},paid_seller)
            self.assertTrue(free["identity_verified"])
            self.assertTrue(paid["identity_verified"])
            request=sign_and_publish("/api/signed-requests",{
                "buyer":buyer.address,"capability":"public-claim-check","currency":"ETH",
                "max_budget":0,"details":DETAILS},buyer)
            self.assertFalse(request["funds_reserved"])
            self.assertFalse(request["payment_verified"])
            self.assertFalse(request["order_created"])
            self.assertEqual(request["request"]["max_budget"],0)
            rid=request["request"]["id"]
            matched=client.get("/api/matches",params={"request_id":rid})
            self.assertEqual(matched.status_code,200,matched.text)
            data=matched.json()
            self.assertEqual(data["count"],1,data)
            self.assertEqual(data["matches"][0]["buyer_max_budget"],0)
            self.assertEqual(data["matches"][0]["seller_price"],0)
            self.assertEqual(data["matches"][0]["seller_agent_id"],free_seller.address.lower())
            self.assertEqual(data["matches"][0]["seller_scope"],SCOPE)
            self.assertFalse(data["payment_verified"])
            self.assertFalse(data["matches"][0]["funds_reserved"])
            self.assertFalse(data["matches"][0]["order_created"])
            stats=client.get("/api/market/stats").json()
            self.assertEqual(stats["events_since_start"]["settlements_verified"],0)
            self.assertEqual(stats["open_verified_buyer_requests"],1)
            self.assertEqual(stats["signed_offline_offers"],2)
    def test_free_budget_validation_in_all_read_write_entrypoints(self):
        buyer=Account.create()
        with patch.object(market,"PUBLIC_SERVER_URL",ROOT),TestClient(market.app) as client:
            for endpoint in ("/api/signed-requests/prepare",):
                zero={"buyer":buyer.address,"capability":"public-claim-check",
                      "currency":"ETH","max_budget":0,"details":DETAILS}
                self.assertEqual(client.post(endpoint,json=zero).status_code,200)
                for invalid in (-1,0.000000001,True):
                    self.assertEqual(client.post(endpoint,json={**zero,"max_budget":invalid}).status_code,422)
            self.assertEqual(client.get("/api/agent/now",params={"max_budget":"0"}).status_code,200)
            self.assertEqual(client.get("/api/agent/now",params={"max_budget":"-1"}).status_code,422)
            schema=client.post("/mcp",headers={
                "content-type":"application/json",
                "accept":"application/json,text/event-stream",
                "mcp-protocol-version":"2025-11-25"},
                json={"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}})
            self.assertEqual(schema.status_code,200)
            tools={x["name"]:x for x in schema.json()["result"]["tools"]}
            self.assertEqual(tools["prepare_signed_request"]["inputSchema"]["properties"]["max_budget"]["minimum"],0)
            self.assertEqual(buyer_cli.validate_request("public-claim-check","ETH","0",DETAILS)["max_budget"],0)
            for invalid in ("-1","0.000000001","not-a-number"):
                with self.assertRaises(ValueError):
                    buyer_cli.validate_request("public-claim-check","ETH",invalid,DETAILS)
            html=client.get("/post-job",headers={"User-Agent":"AI-Market-Official-Business-Audit/1.0"}).text
            self.assertIn('min=\\"0\\"',html)
            self.assertIn("0 = free-only task",html)
            javascript=client.get("/client/buyer-studio.js").text
            self.assertIn("budget !== 0",javascript)
    def test_free_websocket_signed_buyer_need_no_transfer(self):
        buyer=Account.create()
        with TestClient(market.app) as client:
            with client.websocket_connect("/ws/registry") as ws:
                ws.send_json({"agent_id":buyer.address.lower(),"capabilities":[],"pricing":{}})
                challenge=ws.receive_json()
                self.assertEqual(challenge.get("event"),"auth_challenge")
                signature=Account.sign_message(encode_defunct(text=challenge["message"]),buyer.key).signature.hex()
                ws.send_json({"action":"authenticate","signature":signature})
                welcome=ws.receive_json()
                self.assertEqual(welcome.get("status"),"registered",welcome)
                ws.send_json({"action":"publish_need","capability":"public-claim-check",
                              "currency":"ETH","max_budget":0,"details":DETAILS})
                response=ws.receive_json()
                self.assertEqual(response.get("event"),"request_published",response)
                self.assertEqual(response["request"]["max_budget"],0)
                self.assertFalse(response["funds_reserved"])
                self.assertEqual(client.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)
                ws.send_json({"action":"publish_need","capability":"public-claim-check",
                              "currency":"ETH","max_budget":-1,"details":DETAILS})
                self.assertEqual(ws.receive_json().get("error"),"invalid_buyer_request")
                ws.send_json({"action":"cancel_need","request_id":response["request"]["id"]})
                self.assertEqual(ws.receive_json().get("event"),"request_cancelled")

if __name__=="__main__":
    unittest.main()
