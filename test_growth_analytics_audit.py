import unittest
from fastapi.testclient import TestClient
import app as m

class AvoidSelfGeneratedGrowthMetrics(unittest.TestCase):
    def test_readonly_health_audit_does_not_pretend_to_be_buyers_or_sellers(self):
        keys=("buyer_page_requests","provider_page_requests","seller_inbox_page_requests")
        with TestClient(m.app) as c:
            def snap():
                obj=c.get("/api/market/stats").json()["business_funnel_events"]
                return {k:obj[k] for k in keys}
            initial=snap()
            for url in ("/post-job","/list-service","/seller-inbox"):
                p=c.get(url,headers={"User-Agent":"AI-Market-Official-Business-Audit/1.0"})
                self.assertEqual(p.status_code,200)
            self.assertEqual(snap(),initial)
            for url in ("/post-job","/list-service","/seller-inbox"):
                p=c.get(url,headers={"User-Agent":"Independent-Browser-Smoke-Test/1.0"})
                self.assertEqual(p.status_code,200)
            result=snap()
            for k in keys:
                self.assertEqual(result[k]-initial[k],1,k)
            self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)

if __name__=="__main__":
    unittest.main()
