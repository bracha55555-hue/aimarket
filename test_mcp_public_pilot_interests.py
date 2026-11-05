import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as market
from test_public_pilot_interests import MockGitHubResponse,issue

class MCPRealPublicPilotDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.cache=patch.object(market,"_pilot_public_cache",{
            "until":0.0,"items":None,"checked_at":None,"may_be_truncated":False})
        self.cache.start()
        self.addCleanup(self.cache.stop)

    def call(self,client,modern=False,arguments=None):
        name="public_pilot_interests"
        headers={"Content-Type":"application/json",
                 "Accept":"application/json, text/event-stream",
                 "MCP-Protocol-Version":"2026-07-28" if modern else "2025-11-25"}
        params={"name":name,"arguments":arguments if arguments is not None else {}}
        if modern:
            headers.update({"Mcp-Method":"tools/call","Mcp-Name":name})
            params["_meta"]={
                "io.modelcontextprotocol/protocolVersion":"2026-07-28",
                "io.modelcontextprotocol/clientCapabilities":{}}
        return client.post("/mcp",headers=headers,json={
            "jsonrpc":"2.0","id":41 if modern else 40,
            "method":"tools/call","params":params})

    def test_actual_public_metadata_is_separate_for_legacy_and_modern_clients(self):
        upstream=[
            issue(76,"[Public provider interest] AI integration preflight by Vireo","vireo-agent"),
            issue(94,"[Public provider interest] AuthiChain public MCP/A2A evidence check","undone0603"),
            issue(117,"[Public buyer interest] Real public API check","independent-buyer")
        ]
        with patch.object(market.urllib.request,"urlopen",
                          return_value=MockGitHubResponse(upstream)) as fetch:
            with TestClient(market.app) as client:
                before=client.get("/api/market/stats").json()
                for modern in (False,True):
                    resp=self.call(client,modern)
                    self.assertEqual(resp.status_code,200,resp.text)
                    if modern:
                        data=resp.json()["result"]["structuredContent"]
                    else:
                        data=resp.json()["result"]["structuredContent"]
                    self.assertEqual(data["source_status"],"cached_public_github_read")
                    self.assertEqual(data["count"],3)
                    self.assertEqual([x["issue_number"] for x in data["interests"]],[76,94,117])
                    self.assertEqual([x["kind"] for x in data["interests"]],["provider","provider","buyer"])
                    self.assertIs(data["signed_marketplace_records"],False)
                    self.assertIs(data["can_accept_trades"],False)
                    self.assertIs(data["identity_verified_by_marketplace"],False)
                    self.assertIs(data["payment_verified"],False)
                    for row in data["interests"]:
                        self.assertIs(row["identity_verified_by_marketplace"],False)
                        self.assertIs(row["funded"],False)
                        self.assertIs(row["signed_marketplace_record"],False)
                    self.assertNotIn("Secret provided",resp.text)
                self.assertEqual(fetch.call_count,1,"Cached GitHub issue metadata avoids excess external requests")
                after=client.get("/api/market/stats").json()
                self.assertEqual(after["signed_offline_offers"],before["signed_offline_offers"])
                self.assertEqual(after["open_verified_buyer_requests"],before["open_verified_buyer_requests"])
                self.assertEqual(after["events_since_start"]["settlements_verified"],
                                 before["events_since_start"]["settlements_verified"])
                for modern in (False,True):
                    rejected=self.call(client,modern,{"claim_signed":True})
                    self.assertEqual(rejected.status_code,400)
                    self.assertEqual(rejected.json()["error"]["code"],-32602)

    def test_upstream_failures_are_unknown_not_fabricated_zero(self):
        with patch.object(market.urllib.request,"urlopen",side_effect=OSError("upstream unavailable")):
            with TestClient(market.app) as c:
                for modern in (False,True):
                    response=self.call(c,modern)
                    self.assertEqual(response.status_code,200,response.text)
                    data=response.json()["result"]["structuredContent"]
                    self.assertEqual(data["source_status"],"upstream_unavailable")
                    self.assertIsNone(data["count"])
                    self.assertIsNone(data["interests"])
                    self.assertIs(data["signed_marketplace_records"],False)

if __name__=="__main__":
    unittest.main()
