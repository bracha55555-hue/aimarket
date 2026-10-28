/* AI Market buyer-only browser client. No funds or private keys leave the browser. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const post = $("post"), cancel = $("cancel"), status = $("status");
  const storeKey = "ai-market:last-buyer-need";
  let socket = null, busy = false, mode = "publish", last = null, identity = null;
  function notify(text, kind = "info") {
    status.textContent = text;
    status.dataset.kind = kind;
  }
  function refreshLast() {
    try { last = JSON.parse(localStorage.getItem(storeKey) || "null"); }
    catch (_) { last = null; }
    if (last && last.id) {
      $("last").textContent = "Your last request ID: " + last.id + ". Requests expire after one hour.";
      cancel.hidden = false;
    } else {
      $("last").textContent = "Requests expire after one hour. No funds are reserved.";
      cancel.hidden = true;
    }
  }
  function done() { busy = false; post.disabled = false; cancel.disabled = false; }
  function closeSocket() {
    if (!socket) return;
    try { socket.close(); } catch (_) {}
    socket = null;
  }
  function send(data) {
    if (!socket || socket.readyState !== WebSocket.OPEN) throw new Error("Connection is not open");
    socket.send(JSON.stringify(data));
  }
  async function connect(action) {
    if (busy) return;
    if (!window.ethereum || typeof window.ethereum.request !== "function") {
      notify("No EVM wallet detected. To publish, install a compatible browser wallet. You can browse jobs without one.", "error");
      return;
    }
    const capability = $("capability").value.trim();
    const details = $("details").value.trim();
    const budget = Number($("budget").value);
    if (action === "publish" && (
      !capability || capability.length > 64 || details.length < 12 || details.length > 500 ||
      !Number.isFinite(budget) || budget < 0.00000001 || budget > 100000
    )) {
      notify("Supply a capability, real job description (12–500 characters) and positive budget.", "error");
      return;
    }
    if (action === "cancel" && !(last && last.id)) return;
    mode = action; busy = true; post.disabled = true; cancel.disabled = true;
    notify("Opening wallet for identity verification only. No transaction will be requested.");
    try {
      const accounts = await window.ethereum.request({method:"eth_requestAccounts"});
      if (!Array.isArray(accounts) || !/^0x[0-9a-fA-F]{40}$/.test(accounts[0] || ""))
        throw new Error("Wallet did not return a valid EVM address");
      identity = accounts[0];
      if (action === "cancel" && last.buyer && last.buyer.toLowerCase() !== identity.toLowerCase())
        throw new Error("Reopen the same wallet identity used to post your request");
      closeSocket();
      const host = location.host;
      socket = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + host + "/ws/registry");
      socket.addEventListener("open", () => {
        try { send({agent_id:identity, capabilities:[], pricing:{}}); }
        catch (error) { notify(error.message,"error"); closeSocket(); done(); }
      });
      socket.addEventListener("message", async (event) => {
        let msg;
        try { msg = JSON.parse(event.data); } catch (_) { return; }
        try {
          if (msg.event === "auth_challenge") {
            notify("Approve the domain-bound identity message in your wallet. This is not a payment.");
            const bytes = new TextEncoder().encode(msg.message);
            const hex = "0x" + Array.from(bytes, (n) => n.toString(16).padStart(2,"0")).join("");
            const signature = await window.ethereum.request({method:"personal_sign",params:[hex,identity]});
            if (typeof signature !== "string" || !/^0x[0-9a-fA-F]+$/.test(signature))
              throw new Error("Invalid wallet signature");
            send({action:"authenticate",signature});
          } else if (msg.status === "registered" && msg.identity_verified === true) {
            if (mode === "cancel") send({action:"cancel_need",request_id:last.id});
            else send({action:"publish_need",capability,details,currency:$("currency").value,max_budget:budget});
          } else if (msg.event === "request_published" && msg.request && msg.request.id) {
            last = {id:msg.request.id,buyer:identity,capability:msg.request.capability};
            try { localStorage.setItem(storeKey,JSON.stringify(last)); } catch (_) {}
            refreshLast();
            notify("Published! Your identity-signed request is visible for one hour. No funds are reserved. Check offers carefully.", "success");
            closeSocket(); done();
            $("refresh").click();
          } else if (msg.event === "request_cancelled") {
            if (msg.removed) {
              try { localStorage.removeItem(storeKey); } catch (_) {}
              refreshLast();
              notify("Request cancelled.", "success");
            } else notify("Request not found. It may have expired or been cleared by a server restart.");
            closeSocket(); done(); $("refresh").click();
          } else if (msg.error) {
            notify("Publication rejected: " + msg.error,"error");
            closeSocket(); done();
          }
        } catch (error) {
          notify("Could not finish: " + (error.message || String(error)),"error");
          closeSocket(); done();
        }
      });
      socket.addEventListener("close", () => {
        if (busy) { notify("Socket closed before completing. Retry when ready.","error"); done(); }
      });
      socket.addEventListener("error", () => {
        if (busy) { notify("Connection failed; please retry.","error"); closeSocket(); done(); }
      });
    } catch (error) {
      notify("Wallet access cancelled or failed: " + (error.message || String(error)), "error");
      done();
    }
  }
  $("buyer").addEventListener("submit", (event) => {event.preventDefault();connect("publish");});
  cancel.addEventListener("click", () => connect("cancel"));
  $("refresh").addEventListener("click", async () => {
    try {
      const response = await fetch("/api/requests",{cache:"no-store"});
      if (!response.ok) throw new Error("HTTP " + response.status);
      const data = await response.json();
      $("count").textContent = String(data.count || 0);
      const ul = $("needs"); ul.replaceChildren();
      for (const item of (data.verified_buyer_requests || []).slice(0,30)) {
        const li = document.createElement("li");
        li.textContent = String(item.capability || "Service") + " · " +
          String(item.max_budget) + " " + String(item.currency) +
          (item.details ? " — " + String(item.details) : "");
        ul.appendChild(li);
      }
      if (!ul.children.length) {
        const li = document.createElement("li");
        li.textContent = "No real buyer requests currently. Post a genuine need and help start the market.";
        ul.appendChild(li);
      }
    } catch (error) { notify("Could not load demand: " + error.message,"error"); }
  });
  refreshLast();
  $("refresh").click();
})();