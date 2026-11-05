"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

const workflow=JSON.parse(fs.readFileSync("templates/ai-market-n8n-real-agent-discovery.json","utf8"));
const names=new Set(workflow.nodes.map(n=>n.name));
assert.equal(workflow.active,false);
assert.equal(workflow.nodes.length,4);
assert.equal(names.size,4);
assert.deepEqual(workflow.nodes.map(n=>n.type),[
  "n8n-nodes-base.manualTrigger",
  "n8n-nodes-base.httpRequest",
  "n8n-nodes-base.httpRequest",
  "n8n-nodes-base.code"
]);
assert.deepEqual(workflow.nodes.filter(n=>n.type==="n8n-nodes-base.httpRequest").map(n=>[n.parameters.method,n.parameters.url]),[
  ["GET","https://aimarket-997u.onrender.com/api/agent/now"],
  ["GET","https://aimarket-997u.onrender.com/api/pilot/interests"]
]);
assert.deepEqual(Object.keys(workflow.connections).sort(),[
  "Read Public GitHub Interest","Read Signed Marketplace","Run Manually (No Schedule)"
].sort());
for(const [source,destination] of [
  ["Run Manually (No Schedule)","Read Signed Marketplace"],
  ["Read Signed Marketplace","Read Public GitHub Interest"],
  ["Read Public GitHub Interest","Separate Signed vs Unverified"]
]){
  assert.equal(workflow.connections[source].main[0][0].node,destination);
}
assert.deepEqual(workflow.pinData,{});
assert.equal(JSON.stringify(workflow).includes("credentials"),false);
assert.equal(JSON.stringify(workflow).includes("webhook"),false);
assert.equal(JSON.stringify(workflow).includes("scheduleTrigger"),false);
assert.equal(JSON.stringify(workflow).includes("http://"),false);
const js=workflow.nodes[3].parameters.jsCode;
assert.equal(typeof js,"string");
assert.doesNotMatch(js,/(fetch\s*\(|XMLHttpRequest|\.post\s*\(|secret|privateKey|sendTransaction)/i);

function evaluate(signed,pilot){
  const context={
    $:name=>{
      assert.equal(name,"Read Signed Marketplace");
      return {first:()=>({json:signed})};
    },
    $input:{first:()=>({json:pilot})}
  };
  const result=vm.runInNewContext(js,context,{timeout:1000});
  assert.equal(result.length,1);
  return result[0].json;
}
const signed={available_agents_count:0,signed_offline_offers_count:0,real_requests_count:0};
const publicInterest={
  source_status:"cached_public_github_read",count:2,
  interests:[
    {kind:"provider",title:"[Public provider interest] Vireo",url:"https://github.com/bracha55555-hue/aimarket/issues/76",github_author:"vireo-agent",body:"DO NOT SHOW SECRET"},
    {kind:"provider",title:"[Public provider interest] AuthiChain",url:"https://github.com/bracha55555-hue/aimarket/issues/94",github_author:"undone0603",body:"DO NOT SHOW SECRET"}
  ]
};
const good=evaluate(signed,publicInterest);
assert.equal(good.signed_online_agents,0);
assert.equal(good.signed_offline_service_offers,0);
assert.equal(good.genuine_signed_buyer_requests,0);
assert.equal(good.unsigned_public_interest_count,2);
assert.equal(good.independent_public_pilot_interest.length,2);
assert.equal(good.independent_public_pilot_interest[0].identity_verified_by_marketplace,false);
assert.equal(good.independent_public_pilot_interest[0].funded,false);
assert.equal(good.verified_settlements_inferred,false);
assert.doesNotMatch(JSON.stringify(good),/DO NOT SHOW SECRET/);
const outage=evaluate(signed,{source_status:"upstream_unavailable",count:null,interests:null});
assert.equal(outage.unsigned_public_interest_count,null);
assert.equal(outage.independent_public_pilot_interest,null);
const authentic=evaluate({available_agents_count:1,signed_offline_offers_count:2,real_requests_count:1},publicInterest);
assert.equal(authentic.genuine_signed_buyer_requests,1);
assert.equal(authentic.unsigned_public_interest_count,2);
assert.equal(authentic.signed_buyer_requests_are_unfunded,true);
assert.equal(authentic.funds_reserved,false);
console.log("Valid inactive n8n JSON; manual GET-only workflow; honest empty, signed and unavailable states; no secret or body copying.");
