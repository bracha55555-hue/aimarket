"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const source=fs.readFileSync("client/buyer-brief.js","utf8");
function setup(name,details){
  function field(value){
    return {value,handlers:{},addEventListener(event,callback){this.handlers[event]=callback;}};
  }
  const elements={
    "buyer-brief-open":field(""),
    "buyer-brief-capability":field(name),
    "buyer-brief-deliverable":field(details),
    "buyer-brief-status":{textContent:""}
  };
  elements["buyer-brief-open"].href="https://github.com/bracha55555-hue/aimarket/issues/new?template=independent-buyer-pilot.yml";
  vm.runInNewContext(source,{document:{getElementById(id){return elements[id];}},URLSearchParams},{timeout:1000});
  const click={cancelled:false,preventDefault(){this.cancelled=true;}};
  elements["buyer-brief-open"].handlers.click(click);
  return {elements,click};
}
const details="Review a public endpoint I control and deliver a dated, reproducible Markdown report with verifiable outcomes and explicitly unknown checks.";
const ok=setup("mcp-a2a-review",details);
assert.equal(ok.click.cancelled,false);
const url=new URL(ok.elements["buyer-brief-open"].href);
assert.equal(url.origin,"https://github.com");
assert.equal(url.pathname,"/bracha55555-hue/aimarket/issues/new");
assert.equal(url.searchParams.get("template"),"independent-buyer-pilot.yml");
assert.equal(url.searchParams.get("title"),"[Public buyer interest] mcp-a2a-review");
assert.equal(url.searchParams.get("capability"),"mcp-a2a-review");
assert.equal(url.searchParams.get("details"),details);
assert.match(url.searchParams.get("response"),/publicly/);
assert.equal(url.searchParams.has("pilot_budget"),false);
assert.equal(url.searchParams.has("confirmation"),false);
assert.match(ok.elements["buyer-brief-status"].textContent,/Nothing has been published yet/);
const empty=setup("",details);
assert.equal(empty.click.cancelled,true);
const short=setup("mcp-a2a-review","Review it.");
assert.equal(short.click.cancelled,true);
const tooLong=setup("mcp-a2a-review","x".repeat(1401));
assert.equal(tooLong.click.cancelled,true);
assert.doesNotMatch(source,/fetch\s*\(|XMLHttpRequest|sendBeacon|localStorage|sessionStorage/);
console.log("Buyer brief URL prefill, manual consent gate and no-tracking assertions passed.");
