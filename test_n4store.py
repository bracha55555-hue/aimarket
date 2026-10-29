import os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from n4store import N4Store,encode,decode

class N4ReloadTest(unittest.TestCase):
    def test_nibble_roundtrip_corruption_and_folding(self):
        record={"id":"abc","buyer":"0xabc","details":"שלום עולם "*100,
                "capability":"translation","currency":"ETH","max_budget":0.01}
        encoded=encode(record)
        self.assertEqual(decode(encoded),record)
        self.assertLess(len(encoded),len(str(record).encode("utf-8")))
        with self.assertRaises(ValueError):decode(encoded[:26]+b"!" +encoded[27:])

    def test_true_process_restart_and_multidimensional_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/"market.n4db")
            code='''import os,time,app
from n4store import N4Store
if os.environ["N4_STAGE"]=="write":
    st=app.n4_store
    now=time.time()
    for i in range(120):
        st.put("need",str(i),{"id":str(i),"buyer":"0xabc","capability":"translation" if i%2 else "code-review",
            "currency":"ETH","details":"שלום "*100,"max_budget":0.01,
            "expires_at":"2030-01-01T00:00:00+00:00","created_monotonic":0.0},
            "translation" if i%2 else "code-review","ETH",now+86400)
    st.put("offer","agent1",{"agent_id":"agent1","capability":"translation",
        "currency":"ETH","price":0.01,"expires_at_unix":int(now+86400)},
        "translation","ETH",now+86400)
    assert st.count("need")==120
else:
    app.restore_n4_records()
    assert len(app.open_needs)==120
    assert len(app.signed_offers)==1
    assert len(app.n4_store.scan("need","translation","ETH"))==60
    assert app.open_needs["1"]["details"]=="שלום "*100
    app.n4_store.delete("need","1")
    assert "1" not in app.n4_store.scan("need")
'''
            env={**os.environ,"AIMARKET_N4_PATH":path}
            for stage in ("write","reload"):
                out=subprocess.run([sys.executable,"-c",code],env={**env,"N4_STAGE":stage},
                                   capture_output=True,text=True,timeout=35)
                self.assertEqual(out.returncode,0,out.stderr)
            s=N4Store(path)
            self.assertEqual(s.count("need"),119)
            self.assertEqual(s.count("offer"),1)
            s.close()
if __name__=="__main__":unittest.main()
