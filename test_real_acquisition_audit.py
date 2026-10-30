import unittest
from pathlib import Path
from fastapi.testclient import TestClient
import app as m

class RealBusinessAcquisitionEvidenceAuditTest(unittest.TestCase):
    def test_no_key_connect_deploy_is_observable_without_automatic_enrollment(self):
        with TestClient(m.app) as c:
            resp=c.get("/connect",headers={"User-Agent":"AI-Market-Official-Business-Audit/1.0"})
            self.assertEqual(resp.status_code,200)
            self.assertIn("/client/connect-guide.js",resp.text)
            self.assertIn("No unsolicited messages",resp.text)
            self.assertIn("codex mcp add ai-market",resp.text)
            self.assertIn("claude mcp add --transport http",resp.text)
            self.assertFalse(c.get("/health").json()["escrow"])

    def test_existing_scheduled_audit_only_reads_public_outreach_and_production(self):
        audit=Path(".github/workflows/market-live-audit.yml").read_text("utf-8")
        self.assertIn('"production_agent_connect_guide"',audit)
        self.assertIn('"real_agent_feedback_issue"',audit)
        self.assertIn('"real_agent_human_introduction"',audit)
        self.assertIn("https://commons.dooza.ai/api/human-requests?agent=aimarket-operator&limit=50",audit)
        self.assertIn('and "independent AI-agent operators" in row["title"]',audit)
        self.assertIn("https://api.github.com/repos/bracha55555-hue/aimarket/issues/34/comments",audit)
        self.assertIn("replies_are_not_verified_operators",audit)
        self.assertIn("is_unique_real_provider_count",audit)
        self.assertIn("mcptc_directory",audit)
        self.assertIn("production_business_funnel",audit)
        self.assertNotIn("request_human_help",audit)
        self.assertNotIn("POST https://commons.dooza.ai",audit)
        self.assertNotIn("AGENT_COMMONS_LIAISON_ACCEPTED",audit)
        self.assertNotIn("email_address",audit)
        self.assertNotIn("wallet_private_key",audit)

if __name__=="__main__":
    unittest.main()
