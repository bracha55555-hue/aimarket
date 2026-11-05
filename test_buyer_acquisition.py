import unittest
from fastapi.testclient import TestClient
import app

class FirstBuyerAcquisitionTest(unittest.TestCase):
    def test_source_linked_page_and_safe_scope(self):
        with TestClient(app.app) as c:
            before=app.usage_events["mcp_a2a_buyer_landing_views"]
            r=c.get("/hire-mcp-a2a-review")
            self.assertEqual(app.usage_events["mcp_a2a_buyer_landing_views"],before+1)
            audited=c.get("/hire-mcp-a2a-review",headers={"user-agent":"AI-Market-Official-Business-Audit/1.0"})
            self.assertEqual(audited.status_code,200)
            self.assertEqual(app.usage_events["mcp_a2a_buyer_landing_views"],before+1)
            homepage=c.get("/",headers={"accept":"text/html"})
            self.assertIn("Need an MCP/A2A review?",homepage.text)
            self.assertEqual(r.status_code,200)
            self.assertIn("text/html",r.headers["content-type"])
            self.assertIn("frame-ancestors 'none'",r.headers["content-security-policy"])
            self.assertIn("noindex",c.get("/embed").text.lower())
            for phrase in ("Vireo","AuthiChain","unverified","unfunded","No escrow","source-linked"):
                self.assertIn(phrase.lower(),r.text.lower())
            self.assertIn("https://github.com/bracha55555-hue/aimarket/issues/76",r.text)
            self.assertIn("https://github.com/bracha55555-hue/aimarket/issues/94",r.text)
            self.assertIn("independent-buyer-pilot.yml",r.text)
            self.assertIn("script-src 'self'",r.headers["content-security-policy"])
            self.assertIn("connect-src 'none'",r.headers["content-security-policy"])
            self.assertIn('id="buyer-brief-open"',r.text)
            self.assertIn('id="buyer-brief-capability"',r.text)
            self.assertIn('id="buyer-brief-deliverable"',r.text)
            self.assertIn('<script defer src="/client/buyer-brief.js"></script>',r.text)
            self.assertNotIn("<script>",r.text.lower())
            script=c.get("/client/buyer-brief.js")
            self.assertEqual(script.status_code,200)
            self.assertIn("javascript",script.headers["content-type"])
            self.assertIn("independent-buyer-pilot.yml",script.text)
            self.assertNotIn("fetch(",script.text)
            self.assertIn("/hire-mcp-a2a-review",c.get("/sitemap.xml").text)


    def test_generic_buyer_brief_reuses_offline_client_and_requires_explicit_github_submission(self):
        with TestClient(app.app) as c:
            before=c.get("/api/market/stats").json()
            landing=c.get("/hire-ai-agent")
            self.assertEqual(landing.status_code,200)
            self.assertIn('href="/buyer-brief"',landing.text)
            page=c.get("/buyer-brief")
            self.assertEqual(page.status_code,200)
            self.assertIn('id="buyer-brief-capability"',page.text)
            self.assertIn('id="buyer-brief-deliverable"',page.text)
            self.assertIn('id="buyer-brief-open"',page.text)
            self.assertIn('<script defer src="/client/buyer-brief.js"></script>',page.text)
            self.assertIn("GitHub",page.text)
            self.assertIn("unfunded",page.text)
            self.assertIn("Nothing is uploaded, stored, paid, or published here",page.text)
            self.assertIn("script-src 'self'",page.headers["content-security-policy"])
            self.assertIn("connect-src 'none'",page.headers["content-security-policy"])
            self.assertIn("form-action 'none'",page.headers["content-security-policy"])
            self.assertEqual(c.post("/buyer-brief").status_code,405)
            after=c.get("/api/market/stats").json()
            self.assertEqual(before["signed_offline_offers"],after["signed_offline_offers"])
            self.assertEqual(before["open_verified_buyer_requests"],after["open_verified_buyer_requests"])
            self.assertEqual(before["events_since_start"]["settlements_verified"],after["events_since_start"]["settlements_verified"])

if __name__=="__main__":
    unittest.main()
