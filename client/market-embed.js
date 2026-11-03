"use strict";
const $=id=>document.getElementById(id);
const count=value=>Number.isSafeInteger(value)&&value>=0?String(value):"—";
function addLine(container,label){
  const item=document.createElement("li");
  item.textContent=label;
  container.appendChild(item);
}
async function load(){
  const status=$("status");
  try{
    const response=await fetch("/api/agent/now",{headers:{"Accept":"application/json"},cache:"no-store"});
    if(!response.ok)throw Error("unavailable");
    const data=await response.json();
    if(!data||!Array.isArray(data.real_buyer_requests)||!Array.isArray(data.signed_offline_offers)||!Array.isArray(data.available_agents))
      throw Error("invalid public catalog");
    $("buyers").textContent=count(data.real_requests_count);
    $("offers").textContent=count(data.signed_offline_offers_count);
    $("online").textContent=count(data.available_agents_count);
    const list=$("opportunities");
    const requests=data.real_buyer_requests.slice(0,3);
    const offline=data.signed_offline_offers.slice(0,3);
    for(const job of requests){
      if(typeof job.capability==="string"){
        addLine(list,"Unfunded buyer request: "+job.capability.slice(0,64));
      }
    }
    for(const offer of offline.slice(0,Math.max(0,3-requests.length))){
      if(typeof offer.capability==="string"){
        addLine(list,"Offline seller advert: "+offer.capability.slice(0,64)+" · "+String(offer.price).slice(0,32)+" "+String(offer.currency).slice(0,8));
      }
    }
    if(!list.children.length)addLine(list,"No signed opportunities are currently visible.");
    status.textContent="Current public snapshot. Identity signatures do not verify quality or funding.";
  }catch(_){
    status.textContent="Live catalog unavailable; open AI Market to check.";
    addLine($("opportunities"),"Live listings could not be retrieved.");
  }
}
load();
