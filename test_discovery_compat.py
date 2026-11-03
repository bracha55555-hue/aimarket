import unittest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from discovery_compat import ALIASES, install_discovery_compat


class CompatRouteUnitTest(unittest.TestCase):
    def test_existing_get_handler_exposed_as_alias(self):
        app = FastAPI()

        @app.get("/api/agents")
        def agents():
            return {"agents": {}, "count": 0}

        for path in ALIASES:
            if path != "/api/agents":
                app.add_api_route(path, lambda: {"source": "public"}, methods=["GET"])
        install_discovery_compat(app)
        with TestClient(app) as client:
            for original, aliases in ALIASES.items():
                expected = client.get(original)
                self.assertEqual(expected.status_code, 200)
                for alias in aliases:
                    response = client.get(alias)
                    self.assertEqual(response.status_code, 200, alias)
                    self.assertEqual(response.json() if original != "/llms.txt" else response.text,
                                     expected.json() if original != "/llms.txt" else expected.text)

    def test_fail_closed_for_missing_canonical_handler(self):
        with self.assertRaisesRegex(RuntimeError, "Missing GET"):
            install_discovery_compat(FastAPI())

    def test_reject_conflicting_alias(self):
        app = FastAPI()
        for path in ALIASES:
            app.add_api_route(path, lambda: {}, methods=["GET"])
        app.add_api_route("/agents.json", lambda: {}, methods=["GET"])
        with self.assertRaisesRegex(RuntimeError, "conflicts"):
            install_discovery_compat(app)


class RealAppDiscoveryAliasTest(unittest.TestCase):
    def test_existing_public_metadata_and_offline_market_truth_are_preserved(self):
        import app as market
        with TestClient(market.app) as client:
            for canonical, aliases in ALIASES.items():
                expected = client.get(canonical)
                self.assertEqual(expected.status_code, 200)
                for alias in aliases:
                    response = client.get(alias)
                    self.assertEqual(response.status_code, 200, alias)
                    self.assertEqual(response.content, expected.content, alias)
            agents = client.get("/agents.json").json()
            self.assertEqual(agents["count"], len(agents["agents"]))
            self.assertTrue(all(row.get("identity_verified") for row in agents["agents"].values()))
            self.assertFalse(client.get("/.well-known/mcp.json").json()["escrow"])
            self.assertEqual(client.get("/mcp.json").json(),
                             client.get("/.well-known/mcp.json").json())


if __name__ == "__main__":
    unittest.main()
