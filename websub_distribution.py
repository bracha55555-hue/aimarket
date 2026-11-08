"""Opt-in WebSub syndication for actually published public marketplace changes."""
import asyncio
import logging
import os
import time
import urllib.parse
import urllib.request

HUB_URL = "https://pubsubhubbub.appspot.com/"
ATOM_NS = "http://www.w3.org/2005/Atom"
MIN_PING_SECONDS = 300
logger = logging.getLogger("aimarket.websub")


def hub_headers(origin):
    topic = origin.rstrip("/") + "/feed.xml"
    return {
        "Link": f'<{HUB_URL}>; rel="hub", <{topic}>; rel="self"',
        "Cache-Control": "public, max-age=30",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'",
    }


def publish_ping(topic):
    data = urllib.parse.urlencode({"hub.mode": "publish", "hub.url": topic}).encode("ascii")
    request = urllib.request.Request(
        HUB_URL, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "AI-Market-Real-Opportunity-WebSub/1.0"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        if response.status not in (200, 202, 204):
            raise ValueError("WebSub hub declined the feed update")
        return response.status


class OpportunityWebSub:
    def __init__(self, min_interval=MIN_PING_SECONDS):
        self.min_interval = min_interval
        self.last_attempt = 0.0
        self.pending = None

    def schedule(self, origin):
        # Never notify from CI, localhost, tests, unapproved hosts or disabled deployments.
        if os.getenv("AIMARKET_WEBSUB_ENABLED", "1") != "1":
            return False
        if os.getenv("RENDER_SERVICE_ID") != "srv-dbeuks0m7kps73f597f0":
            return False
        if origin.rstrip("/") != "https://aimarket-997u.onrender.com":
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        if self.pending is not None and not self.pending.done():
            return True
        self.pending = loop.create_task(self._notify(origin.rstrip("/") + "/feed.xml"))
        return True

    async def _notify(self, topic):
        remaining = self.min_interval - (time.monotonic() - self.last_attempt)
        if remaining > 0:
            await asyncio.sleep(remaining)
        # Rate-limit attempts, including failed calls. Never block a marketplace write.
        self.last_attempt = time.monotonic()
        try:
            status = await asyncio.to_thread(publish_ping, topic)
            logger.info("WEBSUB_PUBLIC_FEED_PING_ACCEPTED status=%d; subscriptions_not_verified", status)
        except (OSError, ValueError, TimeoutError) as exc:
            logger.warning("WEBSUB_PUBLIC_FEED_PING_FAILED reason=%s", type(exc).__name__)


notifier = OpportunityWebSub()
