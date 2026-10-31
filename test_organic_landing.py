import unittest
from fastapi.testclient import TestClient
import app as market

class OrganicBuyerSellerLandingTest(unittest.TestCase):
    def test_public_indexable_acquisition_pages_are_honest_and_separate(self):
        with TestClient(market.app) as c:
            before=c.get("/api/market/stats").json()["events_since_start"]
            for path in ("/hire-ai-agent","/sell-ai-services"):
                self.assertEqual(c.get(path,headers={"User-Agent":"AI-Market-Official-Business-Audit/1.0"}).status_code,200)
            after=c.get("/api/market/stats").json()["events_since_start"]
            self.assertEqual(after["buyer_landing_views"],before["buyer_landing_views"])
            self.assertEqual(after["provider_landing_views"],before["provider_landing_views"])
            home=c.get("/",headers={"accept":"text/html"})
            self.assertEqual(home.status_code,200)
            self.assertIn('href="/hire-ai-agent"',home.text)
            self.assertIn('href="/sell-ai-services"',home.text)
            paths=(("/hire-ai-agent","Find an AI Agent for a Real Task"),
                   ("/sell-ai-services","Offer Your AI Agent"))
            for path,title in paths:
                with self.subTest(path=path):
                    r=c.get(path)
                    self.assertEqual(r.status_code,200,r.text)
                    self.assertIn("text/html",r.headers["content-type"])
                    self.assertIn(title,r.text)
                    self.assertIn("index,follow",r.text)
                    self.assertIn('rel="canonical"',r.text)
                    self.assertIn("https://aimarket-997u.onrender.com"+path,r.text)
                    self.assertIn("default-src 'none'",r.headers["content-security-policy"])
                    self.assertIn("frame-ancestors 'none'",r.headers["content-security-policy"])
                    self.assertIn("No escrow" if path=="/hire-ai-agent" else "does not hold escrow",r.text)
                    self.assertNotIn("guaranteed income",r.text.lower())
                    self.assertNotIn("5-star",r.text.lower())
                    self.assertEqual(c.post(path).status_code,405)
                    self.assertEqual(c.get("/sitemap.xml").text.count("<loc>"+market.PUBLIC_SERVER_URL.rstrip("/")+path+"</loc>"),1)
            visits=c.get("/api/market/stats").json()["events_since_start"]
            self.assertEqual(visits["buyer_landing_views"]-before["buyer_landing_views"],1)
            self.assertEqual(visits["provider_landing_views"]-before["provider_landing_views"],1)
            self.assertIn("/sell-ai-services",c.get("/sitemap.xml").text)
            self.assertIn("/hire-ai-agent",c.get("/sitemap.xml").text)
            self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)
            self.assertFalse(c.get("/health").json()["escrow"])

if __name__=="__main__":
    unittest.main()
