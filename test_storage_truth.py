import asyncio
import json
import unittest
from unittest.mock import patch
import app as market

class HonestDurabilityStatusTest(unittest.TestCase):
    def test_memory_is_never_reported_as_durable(self):
        with patch.object(market,"n4_store",None):
            value=market.signed_record_storage_status()
            self.assertEqual(value["mode"],"process_memory")
            self.assertFalse(value["survives_app_redeploy"])
            health=asyncio.run(market.health_check())
            stats=asyncio.run(market.public_market_stats())
            discovery=asyncio.run(market.agent_fast_start())
            self.assertEqual(health["signed_record_storage"],value)
            self.assertEqual(stats["signed_record_storage"],value)
            self.assertEqual(discovery["signed_record_storage"],value)
            self.assertIn("restart",discovery["persistence"])
            self.assertFalse(health["durable_trades"])
            self.assertFalse(health["escrow"])

    def test_local_sqlite_does_not_survive_host_replacement(self):
        with patch.object(market,"n4_store",market.N4Store.__new__(market.N4Store)):
            value=market.signed_record_storage_status()
            self.assertEqual(value["mode"],"local_sqlite_n4")
            self.assertFalse(value["survives_app_redeploy"])

    def test_optional_external_database_is_not_a_durable_order_ledger(self):
        with patch.object(market,"n4_store",market.N4PostgresStore.__new__(market.N4PostgresStore)):
            value=market.signed_record_storage_status()
            self.assertEqual(value["mode"],"external_postgres_n4")
            self.assertTrue(value["survives_app_redeploy"])
            self.assertIn("not financial settlement",value["scope"])
            self.assertNotIn("postgresql://",json.dumps(value))
            self.assertFalse(asyncio.run(market.health_check())["durable_trades"])
            self.assertFalse(asyncio.run(market.health_check())["escrow"])


    def test_request_and_match_storage_contract(self):
        stores=(None,market.N4Store.__new__(market.N4Store),
                market.N4PostgresStore.__new__(market.N4PostgresStore))
        for store in stores:
            with self.subTest(store=type(store).__name__),patch.object(market,"n4_store",store),patch.object(market,"expire_stale_trades",return_value=0):
                expected=market.signed_record_storage_status()
                note=market.signed_record_persistence_note()
                requests=asyncio.run(market.public_requests())
                matches=asyncio.run(market.compute_public_matches())
                for response in (requests,matches):
                    self.assertEqual(response["signed_record_storage"],expected)
                    self.assertEqual(response["persistence"],note)
                    self.assertFalse(response.get("payment_verified",False))
                self.assertEqual(matches["trade_fee_rate"],0.02)
                self.assertFalse(requests["funds_reserved"])
                self.assertFalse(matches["escrow"])

if __name__=="__main__":
    unittest.main()
