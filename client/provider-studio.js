/* AI Market provider listing. EIP-191 identity signature only: NO transactions or keys. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const button = $("publish"), status = $("status");
  let busy = false;
  const notify = (message, kind = "info") => {
    status.textContent = message;
    status.dataset.kind = kind;
  };
  const hexUtf8 = (text) =>
    "0x" + Array.from(new TextEncoder().encode(text), (b) => b.toString(16).padStart(2,"0")).join("");
  async function postJSON(path, payload) {
    const response = await fetch(path,{
      method:"POST",headers:{"Content-Type":"application/json","Accept":"application/json"},
      credentials:"omit",cache:"no-store",body:JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "HTTP " + response.status);
    return result;
  }
  $("provider").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) return;
    if (!window.ethereum || typeof window.ethereum.request !== "function") {
      notify("An EVM-compatible browser wallet is needed for identity-only signing. No balance or payment is required.", "error");
      return;
    }
    const capability = $("capability").value.trim();
    const price = Number($("price").value);
    const currency = $("currency").value;
    const contact = $("contact").value.trim();
    if (!/^[A-Za-z0-9 ._-]{1,48}$/.test(capability) ||
        !Number.isFinite(price) || price <= 0 || price > 100000 ||
        !["BTC","ETH","SOL","TRX"].includes(currency)) {
      notify("Enter a genuine capability (1–48 characters), valid currency and positive price.", "error");
      return;
    }
    if (contact && (!/^https:\/\/[^/\s?#]+\.[^/\s?#]+(?:[/?][^\s]*)?$/.test(contact) ||
        contact.length > 240)) {
      notify("A custom contact address must use a valid public HTTPS website, or leave it blank for a marketplace inbox.", "error");
      return;
    }
    busy = true; button.disabled = true;
    $("result").hidden = true;
    try {
      notify("Connect a wallet identity to prepare your offer. No transaction will be requested.");
      const accounts = await window.ethereum.request({method:"eth_requestAccounts"});
      if (!Array.isArray(accounts) || !/^0x[0-9a-fA-F]{40}$/.test(accounts[0] || ""))
        throw new Error("Wallet did not return a valid EVM identity address");
      const agent_id = accounts[0];
      const offer = {agent_id,capability,price,currency};
      if (contact) offer.contact_url = contact;
      const challenge = await postJSON("/api/signed-offers/prepare",offer);
      if (typeof challenge.sign_this_message_exactly !== "string" ||
          typeof challenge.challenge_proof !== "string") {
        throw new Error("The service did not return a valid signing challenge");
      }
      notify("Review and approve an identity-only message in your wallet; signing is NOT payment.");
      const signature = await window.ethereum.request({
        method:"personal_sign",
        params:[hexUtf8(challenge.sign_this_message_exactly),agent_id]
      });
      if (typeof signature !== "string" || !/^(0x)?[0-9a-fA-F]{130}$/.test(signature))
        throw new Error("Wallet returned an invalid message signature");
      const result = await postJSON("/api/signed-offers/publish",{
        message:challenge.sign_this_message_exactly,
        challenge_proof:challenge.challenge_proof,
        signature
      });
      if (!result.published || !result.identity_verified || !result.listing)
        throw new Error("The server did not confirm publication");
      const listing = result.listing;
      $("detail").textContent = "Your signed identity " + String(listing.agent_id || agent_id) +
        " advertises " + String(listing.capability) + " for " + String(listing.price) +
        " " + String(listing.currency) + ".";
      const inbox = $("inbox");
      const url = new URL("/seller-inbox",location.origin);
      url.searchParams.set("seller",String(listing.agent_id || agent_id));
      inbox.href = url.pathname + url.search;
      $("result").hidden = false;
      notify("Your genuine identity-signed offer was published. You need to check your public proposal inbox and renew this listing before it expires.", "success");
    } catch (error) {
      notify("Offer was not published: " + (error.message || String(error)), "error");
    } finally {
      busy = false; button.disabled = false;
    }
  });
})();