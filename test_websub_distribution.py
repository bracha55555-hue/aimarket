import asyncio
import os
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from fastapi.testclient import TestClient
import app as market
import websub_distribution as sub

ROOT = "https://aimarket-997u.onrender.com"
LOCAL_FEED = market.PUBLIC_SERVER_URL.rstrip("/") + "/feed.xml"


class GenuineWebSubSyndicationTests(unittest.TestCase):
    def test_real_market_feed_advertises_standard_hub_and_self_only_on_canonical_feed(self):
        with TestClient(market.app) as client:
            before=client.get("/api/market/stats").json()
            rss=client.get("/feed.xml")
            self.assertEqual(rss.status_code,200)
            self.assertIn(sub.HUB_URL,rss.headers["link"])
            self.assertIn(LOCAL_FEED,rss.headers["link"])
            channel=ET.fromstring(rss.content).find("channel")
            links=channel.findall("{"+sub.ATOM_NS+"}link")
            self.assertEqual([(x.get("rel"),x.get("href")) for x in links],[
                ("hub",sub.HUB_URL),("self",LOCAL_FEED)])
            self.assertEqual(channel.findall("item"),[])
            filtered=client.get("/feed.xml",params={"currency":"ETH"})
            self.assertEqual(filtered.status_code,200)
            self.assertNotIn("link",filtered.headers)
            self.assertEqual(ET.fromstring(filtered.content).find("channel").findall("{"+sub.ATOM_NS+"}link"),[])
            after=client.get("/api/market/stats").json()
            for field in ("signed_offline_offers","open_verified_buyer_requests"):
                self.assertEqual(before[field],after[field])
            self.assertEqual(before["events_since_start"]["settlements_verified"],
                             after["events_since_start"]["settlements_verified"])

    def test_no_unsolicited_hub_requests_from_tests_or_unknown_hosts(self):
        async def check():
            notifier=sub.OpportunityWebSub(min_interval=0)
            with patch.object(sub,"publish_ping") as ping:
                with patch.dict(os.environ,{"RENDER_SERVICE_ID":"not-the-market",
                                            "AIMARKET_WEBSUB_ENABLED":"1"}):
                    self.assertFalse(notifier.schedule(ROOT))
                with patch.dict(os.environ,{"RENDER_SERVICE_ID":"srv-dbeuks0m7kps73f597f0",
                                            "AIMARKET_WEBSUB_ENABLED":"1"}):
                    self.assertFalse(notifier.schedule("http://localhost:7860"))
                    self.assertFalse(notifier.schedule("https://another-market.example"))
                await asyncio.sleep(0)
                ping.assert_not_called()
        asyncio.run(check())

    def test_pings_are_coalesced_and_never_block_successful_business_writes(self):
        async def check():
            notifier=sub.OpportunityWebSub(min_interval=0)
            with patch.object(sub,"publish_ping",return_value=204) as ping:
                with patch.dict(os.environ,{"RENDER_SERVICE_ID":"srv-dbeuks0m7kps73f597f0",
                                            "AIMARKET_WEBSUB_ENABLED":"1"}):
                    self.assertTrue(notifier.schedule(ROOT))
                    self.assertTrue(notifier.schedule(ROOT))
                    await notifier.pending
                    self.assertEqual(ping.call_count,1)
                    ping.assert_called_once_with(ROOT+"/feed.xml")
                    with patch.dict(os.environ,{"AIMARKET_WEBSUB_ENABLED":"0"}):
                        self.assertFalse(notifier.schedule(ROOT))
        asyncio.run(check())

    def test_only_signed_offer_or_request_changes_trigger_notices(self):
        with patch.object(market.opportunity_websub,"schedule") as send:
            market.usage_event("mcp_calls")
            market.usage_event("catalog_reads")
            self.assertFalse(send.called)
            for kind in ("signed_offers_published","requests_published","requests_cancelled"):
                market.usage_event(kind)
            self.assertEqual(send.call_count,3)
            for call in send.call_args_list:
                self.assertEqual(call.args,(market.PUBLIC_SERVER_URL,))


if __name__=="__main__":
    unittest.main()
