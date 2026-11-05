import json
import unittest
from fastapi.testclient import TestClient
import app

PATH="/integrations/ai-market-readonly-openapi.json"
EXPECTED={
    "/api/agent/now":"readSignedAgentMarket",
    "/api/pilot/interests":"readUnverifiedPublicInterest",
    "/api/matches":"readRealSignedServiceMatches",
    "/api/market/stats":"readHonestMarketStatus",
}

class DifyReadOnlyDiscoveryImportTest(unittest.TestCase):
    def test_public_schema_only_exports_existing_no_key_get_endpoints(self):
        with TestClient(app.app) as client:
            response=client.get(PATH)
            self.assertEqual(response.status_code,200,response.text)
            self.assertIn("application/json",response.headers["content-type"])
            self.assertEqual(response.headers["x-content-type-options"],"nosniff")
            self.assertEqual(response.headers["access-control-allow-origin"],"*")
            spec=response.json()
            self.assertEqual(spec["openapi"],"3.0.3")
            self.assertEqual(spec["servers"],[{"url":app.PUBLIC_SERVER_URL.rstrip("/")}])
            self.assertEqual(spec["security"],[])
            self.assertEqual(set(spec["paths"]),set(EXPECTED))
            ids=set()
            for path,expected in EXPECTED.items():
                methods=spec["paths"][path]
                self.assertEqual(set(methods),{"get"})
                operation=methods["get"]
                self.assertEqual(operation["operationId"],expected)
                ids.add(expected)
                self.assertIn("200",operation["responses"])
                self.assertNotIn("security",operation)
                for parameter in operation.get("parameters",[]):
                    self.assertEqual(parameter["in"],"query")
                    self.assertFalse(parameter["required"])
                for value in operation["responses"].values():
                    self._verify_openapi_schema(value)
            self.assertEqual(len(ids),4)
            self.assertIn("503",spec["paths"]["/api/pilot/interests"]["get"]["responses"])
            upstream=spec["paths"]["/api/pilot/interests"]["get"]["responses"]["503"]
            props=upstream["content"]["application/json"]["schema"]["properties"]
            self.assertTrue(props["count"]["nullable"])
            self.assertTrue(props["interests"]["nullable"])
            self.assertIn(PATH,client.get("/sitemap.xml").text)
            self.assertIn("signed marketplace",spec["info"]["description"].lower())
            self.assertNotIn('"post"',json.dumps(spec).lower())
            self.assertNotIn("private_key",json.dumps(spec).lower())

    def _verify_openapi_schema(self,obj):
        if isinstance(obj,dict):
            if "type" in obj:
                self.assertIn(obj["type"],{"array","boolean","integer","number","object","string"})
            for child in obj.values():
                self._verify_openapi_schema(child)
        elif isinstance(obj,list):
            for child in obj:self._verify_openapi_schema(child)

if __name__=="__main__":
    unittest.main()
