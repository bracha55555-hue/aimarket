import unittest
from fastapi.testclient import TestClient
import app as m

class PublicMarketEmbedTest(unittest.TestCase):
    def test_read_only_embeddable_guide_and_widget(self):
        with TestClient(m.app) as client:
            widget=client.get("/embed")
            self.assertEqual(widget.status_code,200)
            self.assertIn("text/html",widget.headers["content-type"])
            self.assertIn("frame-ancestors *",widget.headers["content-security-policy"])
            self.assertIn("no-referrer",widget.headers["referrer-policy"])
            self.assertIn("Unfunded",widget.text)
            self.assertIn("/client/market-embed.js",widget.text)
            self.assertNotIn("postMessage(",widget.text)
            script=client.get("/client/market-embed.js")
            self.assertEqual(script.status_code,200)
            self.assertIn('fetch("/api/agent/now"',script.text)
            self.assertIn("textContent",script.text)
            self.assertNotIn("innerHTML",script.text)
            self.assertNotIn("setInterval",script.text)
            guide=client.get("/embed-guide")
            self.assertEqual(guide.status_code,200)
            self.assertIn('frame-ancestors &#39;none&#39;',guide.text.replace("'","&#39;")) if False else None
            self.assertIn("frame-ancestors 'none'",guide.headers["content-security-policy"])
            self.assertIn("https://aimarket-997u.onrender.com/embed",guide.text)
            self.assertIn("loading=\"lazy\"",guide.text)
            sitemap=client.get("/sitemap.xml").text
            self.assertIn("/embed-guide",sitemap)
            self.assertNotIn("<loc>https://aimarket-997u.onrender.com/embed</loc>",sitemap)

if __name__=="__main__":
    unittest.main()
