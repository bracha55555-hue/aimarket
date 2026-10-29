import unittest
from fastapi.testclient import TestClient
from eth_account import Account
from eth_account.messages import encode_defunct
import app as market

class MultiSignedOffersTest(unittest.TestCase):
    def test_multiple_offers_updates_capacity_and_mcp_replay(self):
        seller=Account.create()
        headers={"accept":"application/json, text/event-stream","content-type":"application/json",
                 "mcp-protocol-version":"2025-11-25"}
        with TestClient(market.app) as client:
            def tool(name,args):
                return client.post("/mcp",headers=headers,json={"jsonrpc":"2.0","id":1,
                    "method":"tools/call","params":{"name":name,"arguments":args}})
            def publish(capability,currency,price):
                data={"agent_id":seller.address,"capability":capability,"currency":currency,
                      "price":price,"contact_url":"https://provider.example/intake"}
                prep=tool("prepare_signed_offer",data)
                self.assertEqual(prep.status_code,200,prep.text)
                challenge=prep.json()["result"]["structuredContent"]
                message=challenge["sign_this_message_exactly"]
                signature=Account.sign_message(encode_defunct(text=message),seller.key).signature.hex()
                args={"message":message,"challenge_proof":challenge["challenge_proof"],
                      "signature":signature}
                result=tool("publish_signed_offer",args)
                return result,args
            first,proof=publish("Translation","ETH",0.02)
            self.assertEqual(first.status_code,200,first.text)
            a=first.json()["result"]["structuredContent"]["listing"]
            self.assertEqual(a["capability"],"translation")
            self.assertEqual(a["offer_id"],seller.address.lower()+":translation:ETH")
            second,_=publish("code-review","SOL",0.03)
            self.assertEqual(second.status_code,200,second.text)
            self.assertEqual(client.get("/api/signed-offers").json()["count"],2)
            updated,_=publish("translation","ETH",0.05)
            self.assertEqual(updated.status_code,200,updated.text)
            directory=client.get("/api/signed-offers").json()
            self.assertEqual(directory["count"],2)
            self.assertEqual(market.signed_offers[a["offer_id"]]["price"],0.05)
            self.assertEqual(market.signed_offers[seller.address.lower()+":code-review:SOL"]["price"],0.03)
            self.assertEqual(tool("publish_signed_offer",proof).status_code,400)
            for i in range(6):
                result,_=publish("skill-"+str(i),"BTC",0.01)
                self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(client.get("/api/signed-offers").json()["count"],8)
            full,_=publish("ninth-skill","TRX",0.01)
            self.assertEqual(full.status_code,400)
            self.assertEqual(client.get("/api/signed-offers").json()["count"],8)
            self.assertEqual(client.get("/api/agents").json()["count"],0)
            self.assertFalse(client.get("/api/matches").json()["payment_verified"])
            market.signed_offers.clear()

if __name__=="__main__":
    unittest.main()
