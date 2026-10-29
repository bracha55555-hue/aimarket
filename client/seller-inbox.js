/* AI Market public seller inbox: wallet is an identity signer, not a payment wallet. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const status = $("status"), list = $("proposals");
  let busy = false;
  const validAddress = (x) => /^0x[0-9a-fA-F]{40}$/.test(x || "");
  const notify = (message, kind = "info") => {
    status.textContent = message;
    status.dataset.kind = kind;
  };
  const hexUtf8 = (value) => "0x" +
    Array.from(new TextEncoder().encode(value), (b) => b.toString(16).padStart(2,"0")).join("");
  async function jsonPost(path, payload) {
    const response = await fetch(path,{
      method:"POST",headers:{"Content-Type":"application/json","Accept":"application/json"},
      cache:"no-store",credentials:"omit",body:JSON.stringify(payload)
    });
    const result=await response.json();
    if(!response.ok) throw new Error(result.error || "HTTP "+response.status);
    return result;
  }
  const currentSeller = () => $("seller").value.trim();
  async function connectWallet() {
    if (!window.ethereum || typeof window.ethereum.request !== "function")
      throw new Error("Install a compatible EVM wallet for identity-only signing (no funds needed)");
    const addresses=await window.ethereum.request({method:"eth_requestAccounts"});
    if (!Array.isArray(addresses) || !validAddress(addresses[0]))
      throw new Error("Wallet did not return an identity address");
    return addresses[0];
  }
  async function refresh() {
    const seller=currentSeller();
    if(!validAddress(seller)) {
      notify("Enter a valid public seller identity or connect your wallet.", "error");
      return;
    }
    const response=await fetch("/api/purchase-intents?seller="+encodeURIComponent(seller),{
      credentials:"omit",cache:"no-store",headers:{"Accept":"application/json"}
    });
    const result=await response.json();
    if (!response.ok) throw new Error(result.error || "Could not load real proposals");
    list.replaceChildren();
    const items=(result.intents || []).slice(0,100).filter(
      (v) => (v.seller || "").toLowerCase()===seller.toLowerCase()
    );
    if (!items.length) {
      const p=document.createElement("p");
      p.textContent="No genuine buyer-signed proposals for this seller identity right now. This is not a simulated inbox.";
      list.appendChild(p);
      notify("0 current proposals. No customers or payments are being claimed.");
      return;
    }
    for(const intent of items) {
      const article=document.createElement("article");
      article.className="proposal";
      const h=document.createElement("h3");
      h.textContent=String(intent.capability || "Agent service");
      article.appendChild(h);
      const summary=document.createElement("p");
      summary.textContent="Quoted price: "+String(intent.price)+" "+String(intent.currency)+
        " | status: "+String(intent.status);
      article.appendChild(summary);
      const details=document.createElement("p");
      details.className="meta";
      details.textContent="Buyer identity: "+String(intent.buyer)+" | proposal: "+String(intent.id)+
        " | expires: "+String(intent.expires_at_unix);
      article.appendChild(details);
      if(intent.status==="proposed" && /^[a-f0-9]{64}$/.test(intent.id || "")) {
        const approve=document.createElement("button");
        approve.type="button";
        approve.textContent="Review and sign nonbinding acknowledgement";
        approve.addEventListener("click",() => acknowledge(intent,approve));
        article.appendChild(approve);
      } else {
        const note=document.createElement("small");
        note.textContent="Already acknowledged or no longer actionable; not a paid order.";
        article.appendChild(note);
      }
      list.appendChild(article);
    }
    notify(String(items.length)+" genuine buyer proposal(s) found. Review each independently.");
  }
  async function acknowledge(intent,button) {
    if(busy || !validAddress(currentSeller()))return;
    busy=true;button.disabled=true;$("refresh").disabled=true;$("connect").disabled=true;
    try {
      notify("Checking the seller identity. No funds will move.");
      const who=await connectWallet();
      if(who.toLowerCase()!==currentSeller().toLowerCase() ||
         (intent.seller || "").toLowerCase()!==who.toLowerCase())
        throw new Error("The connected wallet must match the identity that signed this seller listing");
      if(!window.confirm(
        "You are acknowledging a nonbinding buyer proposal only.\n"+
        "Capability: "+String(intent.capability)+"\n"+
        "Price: "+String(intent.price)+" "+String(intent.currency)+"\n"+
        "Buyer: "+String(intent.buyer)+"\n"+
        "No funds reserved, transaction, escrow, legally binding order or verified delivery. Sign exact terms?"
      )) {
        notify("Not acknowledged; no changes made.");
        return;
      }
      const prepared=await jsonPost("/api/purchase-intents/accept/prepare",{intent_id:intent.id});
      const message=prepared.sign_this_message_exactly;
      if (typeof message!=="string" || typeof prepared.challenge_proof!=="string")
        throw new Error("Invalid server identity challenge");
      notify("Your wallet will sign an identity-only acknowledgement. It will not broadcast a payment.");
      const signature=await window.ethereum.request({
        method:"personal_sign",params:[hexUtf8(message),who]
      });
      if(typeof signature!=="string" || !/^(0x)?[a-fA-F0-9]{130}$/.test(signature))
        throw new Error("Invalid identity signature");
      const result=await jsonPost("/api/purchase-intents/accept/publish",{
        message,challenge_proof:prepared.challenge_proof,signature
      });
      if(result.accepted!==true || result.two_identities_signed!==true ||
         result.payment_verified!==false || result.binding_order!==false ||
         result.escrow!==false || result.funds_reserved!==false)
        throw new Error("Safe nonbinding acknowledgement was not confirmed");
      notify("Acknowledged genuine buyer terms. Two identities signed, but no money, order or delivery has been verified.", "success");
      await refresh();
    } catch(error) {
      notify("Acknowledgement not recorded: "+(error.message || String(error)), "error");
    } finally {
      busy=false;button.disabled=false;$("refresh").disabled=false;$("connect").disabled=false;
    }
  }
  $("connect").addEventListener("click",async()=>{
    try {
      const who=await connectWallet();
      $("seller").value=who;
      await refresh();
    } catch(error) {
      notify(error.message || String(error),"error");
    }
  });
  $("refresh").addEventListener("click",async()=>{
    try { await refresh(); }
    catch(error) { notify(error.message || String(error),"error"); }
  });
  const params=new URLSearchParams(location.search);
  const querySeller=params.get("seller");
  if(validAddress(querySeller)) {
    $("seller").value=querySeller;
    refresh().catch(error=>notify(error.message || String(error),"error"));
  }
})();