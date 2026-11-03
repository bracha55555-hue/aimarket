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

    def test_first_real_provider_followup_is_only_external_respondent_and_never_a_sale(self):
        workflow=Path(".github/workflows/first-independent-lead-watch.yml").read_text("utf-8")
        self.assertIn('API+"/issues/76/comments?per_page=100"',workflow)
        self.assertIn('c["id"]>6597925653',workflow)
        self.assertIn('c["user"].get("login")=="vireo-agent"',workflow)
        self.assertIn("This is a public business lead, NOT acceptance of a purchase",workflow)
        self.assertIn("EXTERNAL_VIREO_PROVIDER_REPLIES",workflow)
        self.assertIn("LEAD_ALREADY_RECORDED",workflow)
        self.assertNotIn("email_address",workflow)
        self.assertNotIn("private_key",workflow)

    def test_partner_followup_and_directory_tracking_require_real_source_evidence(self):
        watcher=Path(".github/workflows/first-independent-lead-watch.yml").read_text("utf-8")
        self.assertIn('(34,6598342756,"dserretti13","Humesh A2A/MCP collaboration")',watcher)
        self.assertIn('(14,6598306029,"robertwmccarty-caelum","Linked AIs/BuddyLists interop")',watcher)
        self.assertIn('index=get("https://jishie.com/v1/agents?q=AI%20Market&include_unprobed=true")',watcher)
        self.assertIn('item["protocols"].get("mcp")==',watcher)
        self.assertIn('"https://aimarket-997u.onrender.com/mcp"',watcher)
        self.assertIn("JISHIE_INDEXING_NOT_CONFIRMED",watcher)
        self.assertIn("not a funded",watcher)
        self.assertIn("LEAD_ALREADY_RECORDED",watcher)
        self.assertNotIn("create_fake_listing",watcher)

    def test_first_independent_public_buyer_issue_is_actioned_without_fabricated_commerce(self):
        watcher=Path(".github/workflows/first-independent-lead-watch.yml").read_text("utf-8")
        self.assertIn('API+"/issues?state=open&per_page=100"',watcher)
        self.assertIn('x["title"].startswith("[Public buyer interest] ")',watcher)
        self.assertIn('and x["user"].get("login")!="bracha55555-hue"',watcher)
        self.assertIn('"https://github.com/bracha55555-hue/aimarket/issues/"+',watcher)
        self.assertIn("PUBLIC_INDEPENDENT_UNVERIFIED_BUYER_ISSUES",watcher)
        self.assertIn("It is not signed demand, identity proof, a funded order",watcher)
        self.assertIn("PUBLIC_BUYER_INTEREST_SOURCE_UNAVAILABLE",watcher)
        self.assertIn("LEAD_ALREADY_RECORDED",watcher)
        self.assertNotIn("auto_send_payment",watcher)

    def test_free_mass_directory_approval_is_read_from_exact_original_receipt(self):
        watcher=Path(".github/workflows/first-independent-lead-watch.yml").read_text("utf-8")
        self.assertIn('pk_id="d4670710-53fe-4205-8e3e-207f4849377b"',watcher)
        self.assertIn('pk=get("https://postlaunchkit.com/api/v1/submissions/"+pk_id)',watcher)
        self.assertIn('state=="approved"',watcher)
        self.assertIn('"https://postlaunchkit.com/directory/"',watcher)
        self.assertIn("POSTLAUNCHKIT_NOT_PUBLICLY_APPROVED",watcher)
        self.assertIn("POSTLAUNCHKIT_REVIEW_STATUS_UNAVAILABLE",watcher)
        self.assertIn("NOT a customer",watcher)
        self.assertIn("LEAD_ALREADY_RECORDED",watcher)
        self.assertNotIn("buy_boost",watcher)
        self.assertNotIn("store_private_token",watcher)

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
