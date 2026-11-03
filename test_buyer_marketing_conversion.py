import unittest
from fastapi.testclient import TestClient
import app as m

class FirstGenuineBuyerConversionTest(unittest.TestCase):
    def test_buyer_page_prioritizes_honest_no_wallet_pilot_not_unverified_market_sales(self):
        with TestClient(m.app) as client:
            before=client.get("/api/market/stats").json()
            page=client.get("/hire-ai-agent")
            self.assertEqual(page.status_code,200,page.text)
            self.assertIn('href="/pilot"',page.text)
            self.assertIn("Start a no-wallet public inquiry",page.text)
            self.assertIn("own approved GitHub account",page.text)
            self.assertIn("unverified interest",page.text)
            self.assertIn('href="/post-job"',page.text)
            self.assertIn("independent-buyer-pilot.yml",page.text)
            self.assertIn('href="/api/pilot/interests"',page.text)
            self.assertIn("not proof of availability or skills",page.text)
            self.assertIn("No wallet",page.text)
            self.assertNotIn("guaranteed work",page.text.lower())
            self.assertNotIn("guaranteed profit",page.text.lower())
            homepage=client.get("/",headers={"accept":"text/html"})
            self.assertEqual(homepage.status_code,200)
            self.assertIn('href="/pilot">Request real AI work — no wallet',homepage.text)
            self.assertIn('href="/post-job">Post a signed buyer request',homepage.text)
            self.assertTrue(homepage.text.index('href="/pilot">Request real AI work') <
                            homepage.text.index('href="/post-job">Post a signed buyer request'))
            after=client.get("/api/market/stats").json()
            self.assertEqual(after["signed_offline_offers"],before["signed_offline_offers"])
            self.assertEqual(after["open_verified_buyer_requests"],before["open_verified_buyer_requests"])
            self.assertEqual(after["events_since_start"]["settlements_verified"],0)

    def test_buyer_public_pilot_keeps_read_only_and_no_payment_permissions(self):
        with TestClient(m.app) as client:
            pilot=client.get("/api/pilot/intake").json()
            self.assertFalse(pilot["signed_marketplace_catalog_included"])
            self.assertFalse(pilot["can_accept_trades"])
            self.assertFalse(pilot["funded"])
            self.assertFalse(pilot["payment_verified"])
            self.assertEqual(client.post("/hire-ai-agent").status_code,405)
            self.assertEqual(client.post("/api/pilot/intake").status_code,405)
            self.assertFalse(client.get("/health").json()["escrow"])
            self.assertIn("2%",client.get("/hire-ai-agent").text)
            self.assertIn("No escrow",client.get("/hire-ai-agent").text)

if __name__=="__main__":
    unittest.main()
