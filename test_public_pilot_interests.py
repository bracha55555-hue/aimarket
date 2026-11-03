import json
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as m

class MockGitHubResponse:
    status=200
    def __init__(self,items):
        self.payload=json.dumps(items).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False
    def read(self,n):
        return self.payload[:n]

def issue(number,title,author="independent-agent",**overrides):
    row={"number":number,"title":title,"state":"open",
         "html_url":"https://github.com/bracha55555-hue/aimarket/issues/"+str(number),
         "created_at":"2026-11-02T21:13:19Z","user":{"login":author},
         "body":"Secret provided by a public issue author must never be copied into public interest API."}
    row.update(overrides)
    return row

class PublicUnverifiedPilotInterestDiscovery(unittest.TestCase):
    def test_live_external_issue_metadata_remains_unverified_and_excludes_bodies(self):
        upstream=[issue(76,"[Public provider interest] AI integration preflight by Vireo","vireo-agent"),
                  issue(77,"[Public buyer interest] One genuinely needed public-source citation"),
                  issue(78,"[Public provider interest] unrelated pull request",pull_request={"url":"x"}),
                  issue(79,"[Public provider interest] forged destination",
                        html_url="https://attack.example/issue/79"),
                  issue(80,"Unrelated public GitHub issue")]
        with patch.object(m,"_pilot_public_cache",{"until":0.0,"items":None,"checked_at":None,
                                                  "may_be_truncated":False}),patch.object(
                m.urllib.request,"urlopen",return_value=MockGitHubResponse(upstream)) as fetch:
            with TestClient(m.app) as c:
                pre=c.get("/api/market/stats").json()
                response=c.get("/api/pilot/interests")
                self.assertEqual(response.status_code,200,response.text)
                self.assertIn("max-age=90",response.headers["cache-control"])
                self.assertEqual(response.headers["x-content-type-options"],"nosniff")
                data=response.json()
                self.assertEqual(data["source_status"],"cached_public_github_read")
                self.assertEqual(data["count"],2)
                self.assertEqual([x["issue_number"] for x in data["interests"]],[76,77])
                self.assertEqual([x["kind"] for x in data["interests"]],["provider","buyer"])
                self.assertEqual(data["interests"][0]["github_author"],"vireo-agent")
                self.assertFalse(data["signed_marketplace_records"])
                self.assertFalse(data["can_accept_trades"])
                self.assertFalse(data["identity_verified_by_marketplace"])
                self.assertFalse(data["payment_verified"])
                for row in data["interests"]:
                    for key in ("signed_marketplace_record","identity_verified_by_marketplace","funded"):
                        self.assertFalse(row[key],key)
                self.assertNotIn("Secret provided",response.text)
                self.assertNotIn("35 USDC",response.text)
                self.assertNotIn("attack.example",response.text)
                second=c.get("/api/pilot/interests")
                self.assertEqual(second.status_code,200)
                self.assertEqual(fetch.call_count,1)
                self.assertEqual(c.get("/api/market/stats").json()["signed_offline_offers"],pre["signed_offline_offers"])
                self.assertEqual(c.get("/api/market/stats").json()["open_verified_buyer_requests"],pre["open_verified_buyer_requests"])
                self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],
                                 pre["events_since_start"]["settlements_verified"])

    def test_upstream_unavailable_returns_explicit_503_not_a_false_empty_market(self):
        with patch.object(m,"_pilot_public_cache",{"until":0.0,"items":None,"checked_at":None,
                                                  "may_be_truncated":False}),patch.object(
                m.urllib.request,"urlopen",side_effect=OSError("rate limited or unavailable")):
            with TestClient(m.app) as c:
                result=c.get("/api/pilot/interests")
                self.assertEqual(result.status_code,503,result.text)
                self.assertEqual(result.json()["source_status"],"upstream_unavailable")
                self.assertIsNone(result.json()["count"])
                self.assertIsNone(result.json()["interests"])
                self.assertFalse(result.json()["signed_marketplace_records"])
                self.assertEqual(result.headers["cache-control"],"no-store")

    def test_static_page_and_agent_discovery_link_to_public_only_metadata(self):
        with TestClient(m.app) as c:
            page=c.get("/pilot")
            self.assertEqual(page.status_code,200)
            self.assertIn('id="pilot-items"',page.text)
            self.assertIn('src="/client/public-pilot-feed.js"',page.text)
            self.assertIn("script-src 'self'",page.headers["content-security-policy"])
            self.assertIn("connect-src 'self'",page.headers["content-security-policy"])
            self.assertNotIn("unsafe-inline",page.headers["content-security-policy"].split("script-src ")[1].split(";")[0])
            js=c.get("/client/public-pilot-feed.js")
            self.assertEqual(js.status_code,200)
            self.assertIn("application/javascript",js.headers["content-type"])
            self.assertIn("textContent",js.text)
            self.assertIn("replaceChildren",js.text)
            self.assertNotIn("innerHTML",js.text)
            self.assertNotIn("eth_sendTransaction",js.text)
            self.assertEqual(c.post("/api/pilot/interests").status_code,405)
            self.assertIn("/api/pilot/interests",c.get("/sitemap.xml").text)
            self.assertIn("/api/pilot/interests",c.get("/llms.txt").text)
            self.assertEqual(c.get("/api/install").json()["public_unverified_pilot_interests"],
                             m.PUBLIC_SERVER_URL.rstrip("/")+"/api/pilot/interests")

if __name__=="__main__":
    unittest.main()
