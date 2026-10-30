import unittest
from pathlib import Path
from fastapi.testclient import TestClient
import app as m

class IndependentDirectoryAndHeadlessClientAuditTest(unittest.TestCase):
    def test_official_auditor_can_verify_headless_client_without_inventing_adoption(self):
        with TestClient(m.app) as c:
            before=c.get("/api/market/stats").json()["events_since_start"]["client_downloads"]
            response=c.get("/client/publish-offer.py",headers={
                "User-Agent":"AI-Market-Official-Business-Audit/1.0"})
            self.assertEqual(response.status_code,200,response.text)
            self.assertIn("text/x-python",response.headers["content-type"])
            self.assertIn("--publish",response.text)
            self.assertIn("NoCrossOriginRedirect",response.text)
            self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["client_downloads"],before)
            ordinary=c.get("/client/publish-offer.py",headers={
                "User-Agent":"Independent-Agent-Developer/1.0"})
            self.assertEqual(ordinary.status_code,200)
            self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["client_downloads"],before+1)
            self.assertFalse(c.get("/health").json()["escrow"])

    def test_readonly_audit_never_claims_mcp_directory_listing_from_queue_receipt(self):
        audit=Path(".github/workflows/market-live-audit.yml").read_text(encoding="utf-8")
        self.assertIn('https://mcp.tc/v0.1/servers?search=AI%20Market&limit=100',audit)
        self.assertIn('remote.get("url")==base+"/mcp"',audit)
        self.assertIn('"status":"not_yet_visible"',audit)
        self.assertIn('"public_listing_verified"',audit)
        self.assertIn('"mcptc_directory"',audit)
        self.assertIn('"production_headless_provider_client"',audit)
        self.assertIn("never count queue acceptance as a listing",audit)
        self.assertNotIn('https://mcp.tc/submit',audit)
        self.assertNotIn('"MCPTC_SUBMISSION_ACCEPTED"',audit)
        self.assertNotIn("private_key_required_by_server",audit)
if __name__=="__main__":
    unittest.main()
