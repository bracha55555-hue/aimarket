import unittest
from pathlib import Path
from fastapi.testclient import TestClient
import app as market

class NoWalletPublicPilotTests(unittest.TestCase):
    def test_public_intake_is_separate_from_verified_marketplace(self):
        with TestClient(market.app) as c:
            start=c.get("/api/market/stats").json()
            result=c.get("/api/pilot/intake")
            self.assertEqual(result.status_code,200,result.text)
            d=result.json()
            self.assertEqual(d["status"],"public_unverified_interest_only")
            self.assertFalse(d["requires_marketplace_wallet"])
            self.assertTrue(d["requires_external_account_to_post"])
            for key in ("signed_marketplace_catalog_included","can_accept_trades","funded",
                        "identity_verified_by_marketplace","seller_verified","payment_verified","escrow"):
                self.assertFalse(d[key],key)
            root="https://github.com/bracha55555-hue/aimarket/issues/new?template="
            self.assertEqual(d["seller_issue_template"],root+"independent-provider-pilot.yml")
            self.assertEqual(d["buyer_issue_template"],root+"independent-buyer-pilot.yml")
            self.assertEqual(d["browser_guide"],market.PUBLIC_SERVER_URL.rstrip("/")+"/pilot")
            self.assertIn("not",d["notice"].lower())
            self.assertIn("public",d["notice"].lower())
            self.assertEqual(c.post("/api/pilot/intake").status_code,405)
            self.assertEqual(c.get("/api/signed-offers").json()["count"],start["signed_offline_offers"])
            self.assertEqual(c.get("/api/market/stats").json()["open_verified_buyer_requests"],start["open_verified_buyer_requests"])
            self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],
                             start["events_since_start"]["settlements_verified"])

    def test_html_discovery_has_no_transaction_code(self):
        with TestClient(market.app) as c:
            page=c.get("/pilot")
            self.assertEqual(page.status_code,200,page.text)
            self.assertIn("text/html",page.headers["content-type"])
            self.assertIn("frame-ancestors 'none'",page.headers["content-security-policy"])
            self.assertIn("default-src 'none'",page.headers["content-security-policy"])
            self.assertIn("independent-provider-pilot.yml",page.text)
            self.assertIn("independent-buyer-pilot.yml",page.text)
            self.assertIn("signed marketplace",page.text.lower())
            self.assertIn("GitHub account",page.text)
            self.assertIn("/api/pilot/intake",page.text)
            self.assertNotIn("eth_sendTransaction",page.text)
            self.assertNotIn("<script",page.text)
            self.assertEqual(c.post("/pilot").status_code,405)
            self.assertIn("/pilot",c.get("/sitemap.xml").text)
            self.assertIn("/pilot",c.get("/llms.txt").text)
            self.assertEqual(c.get("/api/install").json()["no_wallet_public_pilot"],
                             market.PUBLIC_SERVER_URL.rstrip("/")+"/api/pilot/intake")
            self.assertIn('href="/pilot"',c.get("/",headers={"accept":"text/html"}).text)
            self.assertIn('href="/pilot"',c.get("/connect").text)

    def test_github_templates_require_genuine_operator_consented_public_work(self):
        folder=Path(".github/ISSUE_TEMPLATE")
        for name,role in (("independent-provider-pilot.yml","provider"),
                          ("independent-buyer-pilot.yml","buyer")):
            text=(folder/name).read_text("utf-8")
            self.assertIn("name:",text)
            self.assertIn("type: checkboxes",text)
            self.assertIn("required: true",text)
            self.assertIn("private key",text.lower())
            self.assertIn("real",text.lower())
            self.assertIn("public",text.lower())
            self.assertNotIn("eth_sendTransaction",text)
            self.assertTrue(role in text.lower())

if __name__=="__main__":
    unittest.main()
