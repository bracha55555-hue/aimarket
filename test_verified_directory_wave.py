import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE=Path("scripts/verified_directory_wave.py")
spec=importlib.util.spec_from_file_location("verified_directory_wave",MODULE)
wave=importlib.util.module_from_spec(spec)
spec.loader.exec_module(wave)

class IndependentFreeDirectoryDistributionTests(unittest.TestCase):
    def test_submit_only_after_exact_real_production_sha_and_live_interfaces(self):
        fake={"deployed_git_sha":"a"*40}
        card={"supportedInterfaces":[{"url":wave.ROOT+"/a2a",
                                      "protocolBinding":"JSONRPC","protocolVersion":"1.0"}],
              "capabilities":{"streaming":False}}
        install={"read_only_mcp_url":wave.MCP,"no_api_key_required_for_read_only":True}
        with patch.dict(os.environ,{"EXPECTED_MAIN_SHA":"a"*40}),patch.object(
                wave,"read_json",side_effect=[(200,fake),(200,card),(200,install)]) as fetch:
            wave.exact_live_release()
            self.assertEqual(fetch.call_count,3)
        with patch.dict(os.environ,{"EXPECTED_MAIN_SHA":"b"*40}),patch.object(
                wave,"read_json",return_value=(200,fake)) as fetch,patch.object(
                wave.time,"sleep",return_value=None):
            with self.assertRaisesRegex(RuntimeError,"not confirmed"):
                wave.exact_live_release()
            self.assertEqual(fetch.call_count,48)

    def test_agentsearch_submits_only_exact_public_card_and_no_wallet(self):
        with patch.object(wave,"read_json",return_value=(202,{"status":"pending_review"})) as fetch:
            wave.submit_agentsearch()
            self.assertEqual(fetch.call_args.kwargs["payload"],{"wellKnownURI":wave.CARD})
            self.assertEqual(fetch.call_args.kwargs["method"],"POST")
        with patch.object(wave,"read_json",return_value=(400,{"error":"invalid"})):
            with self.assertRaisesRegex(RuntimeError,"not confirmed"):
                wave.submit_agentsearch()

    def test_a2a_registry_preflight_does_not_write_if_live_scan_rejected(self):
        with patch.object(wave,"read_json",return_value=(400,{"error":"bad manifest"})) as fetch:
            with self.assertRaisesRegex(RuntimeError,"scan not accepted"):
                wave.submit_a2a_registry()
            self.assertEqual(fetch.call_count,1)
        with patch.object(wave,"read_json",side_effect=[
                (200,{"ok":True}),(202,{"status":"UNCLAIMED","package_name":"example.agent"})]) as fetch:
            wave.submit_a2a_registry()
            self.assertEqual(fetch.call_count,2)
            self.assertEqual(fetch.call_args.kwargs["payload"],{"url":wave.CARD})

    def test_claude_code_agents_is_exact_real_mcp_listing_not_payment(self):
        schema={"method":"POST","fields":{"name":{},"description":{},"remoteUrl":{}}}
        receipt={"status":"accepted","url":"https://www.claudecodeagents.com/mcp/ai-market"}
        with patch.object(wave,"read_json",side_effect=[(200,schema),(201,receipt)]) as fetch:
            wave.submit_claude_code_agents()
            payload=fetch.call_args.kwargs["payload"]
            self.assertEqual(payload["remoteUrl"],wave.MCP)
            self.assertEqual(payload["repoUrl"],wave.REPO)
            self.assertEqual(payload["auth"],"none")
            self.assertIn("No escrow",payload["description"] if "No escrow" in payload["description"] else payload["description"].replace("no escrow","No escrow"))
            self.assertNotIn("private_key",str(payload))
        with patch.object(wave,"read_json",side_effect=[
                (200,schema),(201,{"status":"accepted","url":"https://wrong.example/mcp/ai-market"})]):
            with self.assertRaisesRegex(RuntimeError,"Official public listing URL"):
                wave.submit_claude_code_agents()

    def test_workflow_is_one_time_source_verified_without_external_spam(self):
        yml=Path(".github/workflows/verified-directory-wave-20261103.yml").read_text("utf-8")
        self.assertIn("paths:",yml)
        self.assertIn("- .github/workflows/verified-directory-wave-20261103.yml",yml)
        self.assertIn("EXPECTED_MAIN_SHA:",yml)
        self.assertIn("agentsearch",yml)
        self.assertIn("claudecodeagents",yml)
        self.assertNotIn("schedule:",yml)
        self.assertNotIn("workflow_dispatch:",yml)
        self.assertNotIn("issues: write",yml)
        source=MODULE.read_text("utf-8")
        self.assertNotIn("fake buyer",source.lower())
        self.assertNotIn("private_key",source)
        self.assertNotIn("payment_wallet",source)

if __name__=="__main__":
    unittest.main()
