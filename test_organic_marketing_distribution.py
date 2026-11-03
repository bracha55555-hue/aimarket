import unittest
from pathlib import Path
from fastapi.testclient import TestClient
import app as market

class OrganicMarketingDistributionTests(unittest.TestCase):
    def test_public_launch_kit_is_accessible_without_tracking_or_commerce_mutations(self):
        with TestClient(market.app) as client:
            original=client.get("/api/market/stats").json()
            page=client.get("/launch")
            self.assertEqual(page.status_code,200,page.text)
            self.assertIn("text/html",page.headers["content-type"])
            self.assertIn("Content-Security-Policy",page.headers)
            self.assertIn("default-src 'none'",page.headers["content-security-policy"])
            self.assertIn("form-action 'none'",page.headers["content-security-policy"])
            self.assertIn("frame-ancestors 'none'",page.headers["content-security-policy"])
            self.assertIn("No escrow",page.text)
            self.assertIn("may be empty",page.text)
            self.assertIn("2% fee",page.text)
            self.assertIn("/hire-ai-agent",page.text)
            self.assertIn("/sell-ai-services",page.text)
            self.assertIn("/pilot",page.text)
            self.assertIn("https://aimarket-997u.onrender.com/mcp",page.text)
            self.assertIn("https://aimarket-997u.onrender.com/.well-known/agent-card.json",page.text)
            self.assertIn("https://github.com/bracha55555-hue/aimarket",page.text)
            self.assertIn("https://www.reddit.com/submit?",page.text)
            self.assertIn("https://news.ycombinator.com/submitlink?",page.text)
            self.assertIn("never auto-post",page.text)
            self.assertNotIn("<script",page.text)
            self.assertNotIn("innerHTML",page.text)
            self.assertEqual(client.post("/launch").status_code,405)
            home=client.get("/",headers={"accept":"text/html"})
            self.assertIn('href="/launch">Share AI Market',home.text)
            self.assertIn("<loc>"+market.PUBLIC_SERVER_URL.rstrip("/")+"/launch</loc>",
                          client.get("/sitemap.xml").text)
            self.assertEqual(client.get("/api/install").json()["public_self_service_launch_kit"],
                             market.PUBLIC_SERVER_URL.rstrip("/")+"/launch")
            latest=client.get("/api/market/stats").json()
            for key in ("signed_offline_offers","open_verified_buyer_requests"):
                self.assertEqual(latest[key],original[key])
            self.assertEqual(latest["events_since_start"]["settlements_verified"],
                             original["events_since_start"]["settlements_verified"])

    def test_external_free_distribution_is_gated_to_exact_main_and_one_time(self):
        path=Path(".github/workflows/organic-multi-directory-wave-20261103.yml")
        text=path.read_text("utf-8")
        self.assertIn("paths:",text)
        self.assertIn("- .github/workflows/organic-multi-directory-wave-20261103.yml",text)
        self.assertIn('EXPECTED_MAIN_SHA: ${{ github.sha }}',text)
        self.assertIn('health.get("deployed_git_sha")!=os.environ["EXPECTED_MAIN_SHA"]',text)
        self.assertIn('actual.get("deployed_git_sha")!=os.environ["EXPECTED_MAIN_SHA"]',text)
        self.assertIn("postlaunchkit.com/api/v1",text)
        self.assertIn("wingmanprotocol.com/submit",text)
        self.assertIn("POSTLAUNCHKIT_ACCEPTED_PENDING_HUMAN_REVIEW_NOT_PUBLIC_YET",text)
        self.assertIn("WINGMAN_ACCEPTED_FOR_REVIEW_NOT_PROOF_OF_PUBLIC_LISTING",text)
        self.assertIn("No private credentials",text)
        self.assertNotIn("schedule:",text)
        self.assertNotIn("workflow_dispatch:",text)
        self.assertNotIn("private_key",text.lower())
        self.assertNotIn("BUY",text)

if __name__=="__main__":
    unittest.main()
