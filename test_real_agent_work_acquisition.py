import unittest
from fastapi.testclient import TestClient
import app as market

class RealAgentWorkAcquisitionTest(unittest.TestCase):
    def test_external_gigs_are_a_useful_public_guide_not_first_party_orders(self):
        with TestClient(market.app) as c:
            before=c.get("/api/market/stats").json()
            r=c.get("/agent-gigs")
            self.assertEqual(r.status_code,200,r.text)
            self.assertIn("text/html",r.headers["content-type"])
            self.assertIn("default-src 'none'",r.headers["content-security-policy"])
            self.assertIn("form-action 'none'",r.headers["content-security-policy"])
            self.assertIn("frame-ancestors 'none'",r.headers["content-security-policy"])
            self.assertIn("https://jobbi.org/gigs/",r.text)
            self.assertIn("https://jobbi.org/gigs.json?lane=agent",r.text)
            self.assertIn("https://jobbi.org/docs/fleets/",r.text)
            self.assertIn("not AI Market buyer requests",r.text)
            self.assertIn("not to AI Market buyer orders",r.text)
            self.assertIn("2% commission",r.text)
            self.assertIn("no escrow",r.text.lower())
            self.assertIn('href="/sell-ai-services"',r.text)
            self.assertIn('href="/jobs"',r.text)
            self.assertIn('rel="noopener noreferrer"',r.text)
            self.assertNotIn("<script",r.text)
            self.assertNotIn("guaranteed income",r.text.lower())
            self.assertEqual(c.post("/agent-gigs").status_code,405)
            self.assertIn("<loc>"+market.PUBLIC_SERVER_URL.rstrip("/")+"/agent-gigs</loc>",c.get("/sitemap.xml").text)
            self.assertEqual(c.get("/api/install").json()["external_paid_agent_gig_guide"],
                             market.PUBLIC_SERVER_URL.rstrip("/")+"/agent-gigs")
            homepage=c.get("/",headers={"accept":"text/html"})
            self.assertIn('href="/agent-gigs">External agent gigs',homepage.text)
            after=c.get("/api/market/stats").json()
            for key in ("signed_offline_offers","open_verified_buyer_requests","authenticated_online_agents"):
                self.assertEqual(before[key],after[key])
            self.assertEqual(before["events_since_start"]["settlements_verified"],
                             after["events_since_start"]["settlements_verified"])

    def test_real_external_vireo_offer_is_disclosed_and_never_authenticated(self):
        with TestClient(market.app) as c:
            r=c.get("/hire-ai-agent")
            self.assertEqual(r.status_code,200)
            self.assertIn("Vireo",r.text)
            self.assertIn("issues/76",r.text)
            self.assertIn("up to ten",r.text)
            self.assertIn("35 USDC on Base",r.text)
            self.assertIn("not supported",r.text.lower())
            self.assertIn("not an identity-signed AI Market offer",r.text)
            self.assertIn("unverified",r.text.lower())
            self.assertIn('href="/pilot"',r.text)
            self.assertEqual(c.get("/api/market/stats").json()["open_verified_buyer_requests"],0)
            self.assertEqual(c.get("/api/market/stats").json()["signed_offline_offers"],0)

    def test_launch_discloses_independent_read_only_humesh_probe_and_external_work(self):
        with TestClient(market.app) as c:
            r=c.get("/launch")
            self.assertEqual(r.status_code,200)
            self.assertIn("Humesh",r.text)
            self.assertIn("6604817250",r.text)
            self.assertIn("41642615308",r.text)
            self.assertIn("does <strong>not</strong> prove",r.text)
            self.assertIn('href="/agent-gigs"',r.text)
            self.assertIn("<strong>not AI Market requests</strong>",r.text)

if __name__=="__main__":
    unittest.main()
