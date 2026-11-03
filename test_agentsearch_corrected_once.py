import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path("scripts").resolve()))
spec=importlib.util.spec_from_file_location("agentsearch_corrected",Path("scripts/agentsearch-corrected-once.py"))
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class CorrectedAgentSearchMarketingTests(unittest.TestCase):
    def test_corrected_public_url_is_not_original_rejected_card_uri(self):
        with patch.object(m,"read_json",side_effect=[
                (200,{"score":0.8}),
                (200,{"status":"accepted","url":"https://agentsearch.luthersystems.com/agent/ai-market"})]) as read:
            m.submit_corrected_url()
            self.assertEqual(read.call_count,2)
            self.assertEqual(read.call_args.kwargs["payload"]["url"],m.ROOT)
            self.assertNotIn("wellKnownURI",read.call_args.kwargs["payload"])
            self.assertIn("No ",read.call_args.kwargs["payload"]["description"].replace("no ","No "))
            self.assertNotIn("wallet_private_key",str(read.call_args.kwargs["payload"]))

    def test_rejected_and_rate_limited_submissions_never_count_as_listings(self):
        with patch.object(m,"read_json",return_value=(429,{"message":"Too many requests"})) as read:
            with self.assertRaisesRegex(RuntimeError,"rate limited"):
                m.submit_corrected_url()
            self.assertEqual(read.call_count,1)
        with patch.object(m,"read_json",side_effect=[
                (200,{"ok":True}),(400,{"error":"Not accepted"})]):
            with self.assertRaisesRegex(RuntimeError,"not confirmed"):
                m.submit_corrected_url()

    def test_one_time_only_exact_deployed_main_no_paid_marketing(self):
        yml=Path(".github/workflows/agentsearch-corrected-once-20261103.yml").read_text()
        self.assertIn("EXPECTED_MAIN_SHA:",yml)
        self.assertIn("scripts/agentsearch-corrected-once.py",yml)
        self.assertIn("paths:",yml)
        self.assertNotIn("schedule:",yml)
        self.assertNotIn("workflow_dispatch:",yml)
        self.assertNotIn("issues: write",yml)
        source=Path("scripts/agentsearch-corrected-once.py").read_text()
        self.assertIn("exact_live_release()",source)
        self.assertIn('"url":ROOT',source)
        self.assertIn("AGENTSEARCH_CORRECTED_URL_SUBMISSION_HTTP",source)
        self.assertNotIn("send_email",source)
        self.assertNotIn("funded_wallet",source)

if __name__=="__main__":
    unittest.main()
