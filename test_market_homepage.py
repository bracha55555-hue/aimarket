import re
import unittest
from fastapi.testclient import TestClient
import app as m

class HonestMarketHomepageTest(unittest.TestCase):
    def test_real_counts_accessible_ctas_and_json_contract(self):
        with TestClient(m.app) as c:
            m.signed_offers.clear()
            m.purchase_intents.clear()
            m.open_needs.clear()
            resp=c.get("/",headers={"accept":"text/html"})
            self.assertEqual(resp.status_code,200)
            self.assertEqual(resp.headers["cache-control"],"no-store")
            self.assertIn("script-src",resp.headers["content-security-policy"].replace("default-src", "script-src"))
            self.assertNotIn("<script",resp.text.lower())
            self.assertIn('class="big-number">0</span><small>Signed offline service offers',resp.text)
            self.assertIn('class="big-number">0</span><small>Current signed buyer requests',resp.text)
            self.assertIn("No signed offline offers are currently available",resp.text)
            self.assertIn('href="/post-job"',resp.text)
            self.assertIn('href="/api/install"',resp.text)
            self.assertIn('href="/api/agent/now"',resp.text)
            self.assertIn('href="/api/market/stats"',resp.text)
            self.assertIn("https://aimarket-997u.onrender.com/mcp",resp.text)
            self.assertIn("No custody or escrow",resp.text)
            machine=c.get("/",headers={"accept":"application/json"})
            self.assertEqual(machine.status_code,200)
            self.assertEqual(machine.json()["fee_rate"],0.02)
            self.assertEqual(machine.json()["one_call_market"],"/api/agent/now")
    def test_signed_real_record_rendering_escapes_untrusted_offer(self):
        with TestClient(m.app) as c:
            try:
                # Synthetic UI-only test data; never publish these examples to production.
                m.signed_offers["local-ui-example"]={
                    "capability":'<img src=x onerror=alert(1)>',
                    "price":0.02,"currency":"ETH",
                    "contact_url":"https://seller.example/intake?x=1&y=2",
                    "expires_at_unix":9999999999
                }
                response=c.get("/",headers={"accept":"text/html"})
                self.assertEqual(response.status_code,200)
                text=response.text
                self.assertIn("Signed offline service offers",text)
                self.assertIn("&lt;img src=x onerror=alert(1)&gt;",text)
                self.assertNotIn("<img src=x",text)
                self.assertIn("https://seller.example/intake?x=1&amp;y=2",text)
                self.assertIn('class="big-number">1</span><small>Signed offline service offers',text)
                self.assertIn("Identity-signed / offline",text)
                self.assertNotIn("Verified seller skills",text)
            finally:
                m.signed_offers.clear()

if __name__=="__main__":
    unittest.main()
