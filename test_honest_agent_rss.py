import time
import unittest
from datetime import datetime,timezone,timedelta
from xml.etree import ElementTree as ET
from fastapi.testclient import TestClient
from eth_account import Account
import app as m

class HonestRSSForIndependentAgents(unittest.TestCase):
    def test_empty_public_feed_claims_nothing(self):
        with TestClient(m.app) as c:
            result=c.get("/feed.xml")
            self.assertEqual(result.status_code,200,result.text)
            self.assertIn("application/rss+xml",result.headers["content-type"])
            self.assertEqual(result.headers["x-content-type-options"],"nosniff")
            self.assertIn("max-age=30",result.headers["cache-control"])
            rss=ET.fromstring(result.content)
            self.assertEqual(rss.tag,"rss")
            self.assertEqual(rss.attrib["version"],"2.0")
            channel=rss.find("channel")
            self.assertEqual(channel.findall("item"),[])
            desc=channel.findtext("description")
            self.assertIn("unfunded",desc)
            self.assertIn("No escrow",desc)
            self.assertNotIn("guaranteed income",result.text.lower())
            self.assertEqual(c.get("/feed.xml?currency=FAKE").status_code,422)
            self.assertEqual(c.get("/feed.xml?capability=%3Cscript%3E").status_code,422)
            self.assertEqual(c.post("/feed.xml").status_code,405)

    def test_only_live_genuine_market_records_and_correctly_escaped_xml(self):
        seller=Account.create()
        buyer=Account.create()
        identity=buyer.address.lower()
        offer=m.validated_offer_fields(seller.address,"Code-review","ETH",0.015,
                                       "https://provider.example/contact")
        offer.update({"offer_id":m.signed_offer_key(offer),
                      "expires_at_unix":int(time.time())+7200})
        need={"id":"c"*32,"buyer":identity,"capability":"CODE-REVIEW",
              "currency":"ETH","max_budget":0.03,
              "details":"Review JSON payload <script>alert('bad')</script> & check escaping.",
              "created_at":datetime.now(timezone.utc).isoformat(),
              "expires_at":(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat(),
              "created_monotonic":time.monotonic()}
        key=offer["offer_id"]
        try:
            m.open_needs[need["id"]]=need
            m.signed_offers[key]=offer
            with TestClient(m.app) as c:
                r=c.get("/feed.xml?capability=code-review&currency=ETH")
                self.assertEqual(r.status_code,200,r.text)
                self.assertIn("&lt;script&gt;",r.text)
                self.assertNotIn("<script>",r.text)
                rss=ET.fromstring(r.content)
                items=rss.findall("./channel/item")
                self.assertEqual(len(items),2)
                self.assertIn("Unfunded buyer request",items[0].findtext("title"))
                self.assertIn("not a funded order",items[0].findtext("description"))
                self.assertIn("<script>alert",items[0].findtext("description"))
                self.assertIn("identity",items[0].findtext("description").lower())
                self.assertIn("No escrow",items[0].findtext("description"))
                self.assertIsNotNone(items[0].find("pubDate"))
                self.assertIn("Self-declared offline service",items[1].findtext("title"))
                self.assertIn("Not an online provider",items[1].findtext("description"))
                self.assertIn("0.015 ETH",items[1].findtext("description"))
                self.assertEqual(len({x.findtext("guid") for x in items}),2)
                self.assertIn("isPermaLink",items[1].find("guid").attrib)
                self.assertEqual(len(rss.findall("./channel/item")),2)
                self.assertEqual(len(ET.fromstring(c.get("/feed.xml?currency=SOL").content).findall("./channel/item")),0)
                self.assertEqual(len(ET.fromstring(c.get("/feed.xml?capability=translation").content).findall("./channel/item")),0)
                self.assertEqual(c.get("/api/market/stats").json()["events_since_start"]["settlements_verified"],0)
                need["created_monotonic"]=time.monotonic()-m.NEED_TTL_SECONDS-1
                offer["expires_at_unix"]=0
                self.assertEqual(ET.fromstring(c.get("/feed.xml").content).findall("./channel/item"),[])
        finally:
            m.open_needs.pop(need["id"],None)
            m.signed_offers.pop(key,None)

    def test_feed_is_both_human_and_agent_discoverable(self):
        with TestClient(m.app) as c:
            self.assertIn("/feed.xml",c.get("/",headers={"accept":"text/html"}).text)
            self.assertIn("/feed.xml",c.get("/sitemap.xml").text)
            self.assertIn("/feed.xml",c.get("/llms.txt").text)
            root=m.PUBLIC_SERVER_URL.rstrip("/")
            self.assertEqual(c.get("/api/install").json()["real_opportunities_rss"],root+"/feed.xml")
            self.assertEqual(c.get("/.well-known/ai-market.json").json()["real_opportunities_rss"],root+"/feed.xml")

if __name__=="__main__":
    unittest.main()
