import unittest
from pathlib import Path
from fastapi.testclient import TestClient
import app as market

READ_ONLY = {
    "browse_purchase_intents","browse_signed_offers","match_real_services",
    "agent_flight_check","search_agents","real_buyer_requests",
    "market_in_one_call","marketplace_status","integration_guide",
}
SIGNED_OR_CHALLENGE = {
    "prepare_purchase_intent","publish_purchase_intent","prepare_accept_intent",
    "accept_purchase_intent","prepare_signed_offer","publish_signed_offer",
}

class IndependentMCPAgentTrustTest(unittest.TestCase):
    def test_read_only_tools_are_annotated_and_signed_writes_never_disguised(self):
        declared=market.MCP_TOOL_DEFINITIONS
        self.assertEqual(len(declared),15)
        self.assertEqual({d["name"] for d in declared},READ_ONLY|SIGNED_OR_CHALLENGE)
        documented=0
        total=0
        for d in declared:
            name=d["name"]
            hints=d["annotations"]
            self.assertEqual(set(hints),{"readOnlyHint","destructiveHint","idempotentHint","openWorldHint"})
            self.assertIs(hints["readOnlyHint"],name in READ_ONLY)
            self.assertIs(hints["idempotentHint"],name in READ_ONLY)
            self.assertIs(hints["openWorldHint"],True)
            # The seller acceptance changes the status of an existing record and deserves the stronger warning.
            self.assertIs(hints["destructiveHint"],name=="accept_purchase_intent")
            self.assertTrue("title" in d and "description" in d)
            for prop,definition in d["inputSchema"]["properties"].items():
                total+=1
                desc=definition.get("description","")
                if len(desc)>=12:
                    documented+=1
        self.assertGreaterEqual(total,20)
        self.assertEqual(documented,total,"Every input has a truthful explanatory description")

    def test_same_annotations_are_exposed_to_old_and_modern_protocol_clients(self):
        with TestClient(market.app) as c:
            headers={"content-type":"application/json",
                     "accept":"application/json, text/event-stream",
                     "mcp-protocol-version":"2025-11-25"}
            legacy=c.post("/mcp",headers=headers,json={
                "jsonrpc":"2.0","id":3,"method":"tools/list","params":{}})
            self.assertEqual(legacy.status_code,200,legacy.text)
            older={d["name"]:d["annotations"] for d in legacy.json()["result"]["tools"]}
            modern_headers={
                **headers,
                "mcp-protocol-version":"2026-07-28",
                "mcp-method":"tools/list",
            }
            newer=c.post("/mcp",headers=modern_headers,json={
                "jsonrpc":"2.0","id":4,"method":"tools/list",
                "params":{"_meta":{
                    "io.modelcontextprotocol/protocolVersion":"2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities":{}
                }}})
            self.assertEqual(newer.status_code,200,newer.text)
            modern={d["name"]:d["annotations"] for d in newer.json()["result"]["tools"]}
            self.assertEqual(older,modern)
            self.assertEqual(set(modern),READ_ONLY|SIGNED_OR_CHALLENGE)
            self.assertTrue(modern["market_in_one_call"]["readOnlyHint"])
            self.assertFalse(modern["publish_signed_offer"]["readOnlyHint"])
            self.assertTrue(modern["accept_purchase_intent"]["destructiveHint"])
            self.assertFalse(c.get("/health").json()["escrow"])

    def test_security_policy_enables_responsible_reporting_not_fake_certification(self):
        security=Path("SECURITY.md").read_text("utf-8")
        self.assertIn("Report a vulnerability",security)
        self.assertIn("not itself confidential",security)
        self.assertIn("no announced monetary bug bounty",security)
        self.assertIn("no escrow",security.lower())
        self.assertIn("Never transmit a private key",security)
        self.assertIn("no guarantee of durable records",security)
        self.assertNotIn("guaranteed 24/7",security)
        self.assertNotIn("security audited",security)

if __name__=="__main__":
    unittest.main()
