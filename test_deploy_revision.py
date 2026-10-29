import os,unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as m

class ProductionDeployIdentityTest(unittest.TestCase):
    def test_explicit_render_revision_is_public_and_reliably_bounded(self):
        valid_sha="d"*40
        for input_sha,expected in ((valid_sha,valid_sha),
                                   ("f"*39,None),
                                   ("not-a-commit-sha",None),
                                   ("",None),
                                   ("f"*40+" SENSITIVE_TRAILING_DATA",None)):
            with self.subTest(input_sha=input_sha[:32]):
                with patch.dict(os.environ,{"RENDER_GIT_COMMIT":input_sha}):
                    with TestClient(m.app) as c:
                        health=c.get("/health")
                        self.assertEqual(health.status_code,200)
                        self.assertEqual(health.json()["deployed_git_sha"],expected)
                        self.assertFalse(health.json()["escrow"])
                        stats=c.get("/api/market/stats")
                        self.assertEqual(stats.status_code,200)
                        self.assertEqual(stats.json()["deployed_git_sha"],expected)
                        self.assertEqual(stats.json()["scope"],"current process only; resets on restart/redeploy")
                        self.assertEqual(stats.json()["events_since_start"]["settlements_verified"],0)
                        self.assertNotIn("SENSITIVE_TRAILING_DATA",health.text)
                        self.assertNotIn("SENSITIVE_TRAILING_DATA",stats.text)

    def test_public_sha_exact_main_comparison_is_required_by_live_audit(self):
        from pathlib import Path
        audit=Path(".github/workflows/market-live-audit.yml").read_text("utf-8")
        self.assertIn('os.getenv("GITHUB_REF")=="refs/heads/main"',audit)
        self.assertIn('expected_sha==live_sha',audit)
        self.assertIn('"status":("unknown"',audit)
        self.assertIn('"lagging"',audit)
        self.assertIn('Only exact full SHA proves current revision.',audit)
        self.assertNotIn('GITHUB_TOKEN',audit)
        self.assertNotIn('RENDER_API_KEY',audit)

if __name__=="__main__":
    unittest.main()
