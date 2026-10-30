import json, re, unittest
from pathlib import Path
from fastapi.testclient import TestClient
import app as market

class FrictionlessPublicAgentConnectionTest(unittest.TestCase):
    def test_single_command_real_mcp_setup_and_nontracking_share_are_public(self):
        with TestClient(market.app) as client:
            r=client.get("/connect",headers={"accept":"text/html"})
            self.assertEqual(r.status_code,200,r.text)
            self.assertIn("text/html",r.headers["content-type"])
            self.assertIn("script-src 'self'",r.headers["content-security-policy"])
            self.assertIn("connect-src 'none'",r.headers["content-security-policy"])
            html=r.text
            endpoint="https://aimarket-997u.onrender.com/mcp"
            self.assertIn("codex mcp add ai-market --url "+endpoint,html)
            self.assertIn("claude mcp add --transport http ai-market "+endpoint,html)
            self.assertIn("npx skills add bracha55555-hue/aimarket --skill ai-market",html)
            self.assertIn("curl -fsSL https://aimarket-997u.onrender.com/api/agent/now",html)
            self.assertIn("Copy voluntary introduction",html)
            self.assertIn("No unsolicited messages",html)
            self.assertNotIn("api_key=",html)
            self.assertNotIn("Authorization: Bearer",html)
            self.assertNotIn("window.location.href =",html)
            js=client.get("/client/connect-guide.js")
            self.assertEqual(js.status_code,200)
            self.assertIn("application/javascript",js.headers["content-type"])
            self.assertIn("navigator.clipboard",js.text)
            self.assertIn('button.addEventListener("click"',js.text)
            self.assertNotIn("fetch(",js.text)
            self.assertNotIn("localStorage",js.text)
            self.assertNotIn("issueNewTurn",js.text)
            self.assertEqual(client.post("/connect").status_code,405)

    def test_machine_readable_integration_is_public_no_key_and_avoids_auto_writes(self):
        with TestClient(market.app) as c:
            d=c.get("/api/install").json()
            root=market.PUBLIC_SERVER_URL.rstrip("/")
            self.assertTrue(d["no_api_key_required_for_read_only"])
            self.assertEqual(d["connect_any_agent"],root+"/connect")
            self.assertEqual(d["codex_one_command"],"codex mcp add ai-market --url "+root+"/mcp")
            self.assertEqual(d["claude_code_one_command"],"claude mcp add --transport http ai-market "+root+"/mcp")
            self.assertEqual(d["portable_skill_one_command"],"npx skills add bracha55555-hue/aimarket --skill ai-market")
            self.assertEqual(d["no_install_read_only_one_command"],
                             "curl -fsSL "+root+"/api/agent/now")
            self.assertTrue(d["no_tracking_or_referral_rewards"])
            self.assertIn("operator-approved local identity signature",d["optional_voluntary_agent_share_text"])
            self.assertEqual(d["read_only_mcp_url"],root+"/mcp")
            self.assertIn(root+"/connect",c.get("/sitemap.xml").text)
            self.assertIn("/connect",c.get("/llms.txt").text)
            self.assertEqual(c.get("/.well-known/ai-market.json").json()["connect_no_key"],
                             root+"/connect")
            self.assertFalse(c.get("/health").json()["escrow"])
            self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)
            self.assertNotIn("gh skill install",json.dumps(d))

    def test_readonly_production_audit_preserves_truthful_join_and_directory_evidence(self):
        audit=Path(".github/workflows/market-live-audit.yml").read_text("utf-8")
        self.assertIn("production_headless_provider_client",audit)
        self.assertIn("mcptc_directory",audit)
        self.assertIn("exact_endpoint_match",audit)
        self.assertNotIn('"MCPTC_SUBMISSION_ACCEPTED"',audit)

if __name__=="__main__":
    unittest.main()
