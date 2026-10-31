import unittest
from pathlib import Path
from fastapi.testclient import TestClient
import app as m

KEY="f37a1f8f9550946afe81256013058e21"

class SearchIndexNotificationTest(unittest.TestCase):
    def test_public_key_and_indexable_true_pages(self):
        with TestClient(m.app) as c:
            r=c.get("/"+KEY+".txt")
            self.assertEqual(r.status_code,200)
            self.assertEqual(r.text,KEY)
            self.assertIn("text/plain",r.headers["content-type"])
            self.assertIn("nosniff",r.headers["x-content-type-options"])
            self.assertNotIn("/"+KEY+".txt",c.get("/sitemap.xml").text)
            paths=("/","/hire-ai-agent","/sell-ai-services")
            for path in paths:
                with self.subTest(path=path):
                    response=c.get(path,headers={"Accept":"text/html",
                        "User-Agent":"AI-Market-Official-Business-Audit/1.0"})
                    self.assertEqual(response.status_code,200)
                    self.assertIn("<html",response.text.lower())
                    self.assertNotIn('name="robots" content="noindex"',response.text)
            self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)
        workflow=Path(".github/workflows/indexnow-new-pages.yml").read_text("utf-8")
        self.assertIn("api.indexnow.org/indexnow",workflow)
        self.assertIn("EXPECTED_SHA",workflow)
        self.assertIn('"keyLocation":root+"/"+key+".txt"',workflow)
        self.assertIn('"/hire-ai-agent","/sell-ai-services"',workflow)
        self.assertNotIn("schedule:",workflow)

if __name__=="__main__":
    unittest.main()
