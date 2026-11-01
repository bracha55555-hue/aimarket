import os
import subprocess
import sys
import time
import unittest
import uuid
from datetime import datetime, timezone
from n4pgstore import N4PostgresStore

@unittest.skipUnless(os.getenv("AIMARKET_TEST_POSTGRES_URL"), "PostgreSQL test URL required")
class N4DurablePostgresTest(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ["AIMARKET_TEST_POSTGRES_URL"]
        self.db=N4PostgresStore(self.dsn)
        self.ids=[]

    def tearDown(self):
        for kind,ident in self.ids:
            self.db.delete(kind,ident)
        self.db.close()

    def test_atomic_roundtrip_index_upsert_and_expiry(self):
        now=time.time()
        ident="ci-"+uuid.uuid4().hex
        self.ids.append(("offer",ident))
        record={"agent_id":"0x"+"a"*40,"capability":"public-claim-check",
                "currency":"ETH","price":0,"scope":"Verify one public claim",
                "expires_at_unix":int(now+3600)}
        self.db.put("offer",ident,record,"public-claim-check","ETH",now+3600)
        second=N4PostgresStore(self.dsn)
        self.assertEqual(second.scan("offer","public-claim-check","ETH")[ident],record)
        updated={**record,"scope":"Verify one dated public claim"}
        second.put("offer",ident,updated,"public-claim-check","ETH",now+7200)
        self.assertEqual(self.db.scan("offer","public-claim-check","ETH")[ident],updated)
        self.assertEqual(self.db.count("offer"),1)
        self.assertNotIn(ident,self.db.scan("offer",now=now+7201))
        self.assertGreaterEqual(self.db.purge(now+7201),1)
        self.assertNotIn(ident,second.scan("offer"))
        second.close()

    def test_application_restores_signed_need_across_processes(self):
        ident="ci-"+uuid.uuid4().hex
        self.ids.append(("need",ident))
        deadline=time.time()+3600
        row={"id":ident,"buyer":"0x"+"b"*40,"capability":"source-check",
             "currency":"ETH","max_budget":0,"details":"One actual authorized request",
             "created_at":datetime.now(timezone.utc).isoformat(),
             "expires_at":datetime.fromtimestamp(deadline,timezone.utc).isoformat(),
             "created_monotonic":time.monotonic()}
        self.db.put("need",ident,row,"source-check","ETH",deadline)
        env={**os.environ,"AIMARKET_N4_DATABASE_URL":self.dsn}
        code="""import app,os
app.restore_n4_records()
item=app.open_needs[os.environ['RECORD_ID']]
assert item['max_budget']==0
assert item['capability']=='source-check'
assert app.n4_store.count('need')>=1
"""
        result=subprocess.run([sys.executable,"-c",code],env={**env,"RECORD_ID":ident},
                              capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stderr)
        self.db.delete("need",ident)
        self.assertNotIn(ident,N4PostgresStore(self.dsn).scan("need"))

    def test_invalid_record_and_connection_url_rejected(self):
        with self.assertRaises(ValueError):
            N4PostgresStore("https://not-a-database.example")
        with self.assertRaises(ValueError):
            self.db.put("payment","id",{},expires_at=time.time()+20)
        with self.assertRaises(ValueError):
            self.db.put("need","id",{},expires_at=float("nan"))

if __name__=="__main__":
    unittest.main()
