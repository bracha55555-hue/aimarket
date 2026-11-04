import unittest
from fastapi.testclient import TestClient
import app

class FirstBuyerAcquisitionTest(unittest.TestCase):
    def test_source_linked_page_and_safe_scope(self):
        with TestClient(app.app) as c:
            r=c.get("/hire-mcp-a2a-review")
            self.assertEqual(r.status_code,200)
            self.assertIn("text/html",r.headers["content-type"])
            self.assertIn("frame-ancestors 'none'",r.headers["content-security-policy"])
            self.assertIn("noindex",c.get("/embed").text.lower())
            for phrase in ("Vireo","AuthiChain","unverified","unfunded","No escrow","source-linked"):
                self.assertIn(phrase.lower(),r.text.lower())
            self.assertIn("https://github.com/bracha55555-hue/aimarket/issues/76",r.text)
            self.assertIn("https://github.com/bracha55555-hue/aimarket/issues/94",r.text)
            self.assertIn("independent-buyer-pilot.yml",r.text)
            self.assertNotIn("<script",r.text.lower())
            self.assertIn("/hire-mcp-a2a-review",c.get("/sitemap.xml").text)

if __name__=="__main__":
    unittest.main()
