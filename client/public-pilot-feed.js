/* Public GitHub pilot metadata only. No wallet, private keys, payments or auto-posting. */
(() => {
  "use strict";
  const list=document.getElementById("pilot-items");
  const state=document.getElementById("pilot-status");
  if (!list || !state) return;
  async function read() {
    try {
      const resp=await fetch("/api/pilot/interests",{credentials:"omit",cache:"no-store",headers:{"Accept":"application/json"}});
      if (!resp.ok) throw new Error("GitHub issue index unavailable");
      const data=await resp.json();
      if (data.signed_marketplace_records !== false || !Array.isArray(data.interests)) throw new Error("Untrusted result shape");
      list.replaceChildren();
      for (const entry of data.interests) {
        if (!entry || !Number.isInteger(entry.issue_number) || entry.issue_number<1 ||
            !["buyer","provider"].includes(entry.kind) ||
            entry.url!=="https://github.com/bracha55555-hue/aimarket/issues/"+entry.issue_number ||
            typeof entry.title!=="string" || typeof entry.github_author!=="string") continue;
        const row=document.createElement("li");
        const link=document.createElement("a");
        link.href=entry.url; link.rel="noopener noreferrer";
        link.textContent=entry.title.slice(0,160);
        const note=document.createElement("small");
        note.textContent=" — public "+entry.kind+" interest by GitHub @"+entry.github_author+" (unverified)";
        row.append(link,note);
        list.append(row);
      }
      state.textContent=list.children.length
        ? "Public externally posted interests only. No identity, availability, work or payment is independently verified."
        : "No matching public GitHub pilot issues are visible in the latest read. This does not describe signed market activity.";
    } catch (_) {
      list.replaceChildren();
      state.textContent="Public GitHub interests cannot be verified right now. Open the repository's public issues directly; an unavailable feed does not mean zero interest.";
    }
  }
  read();
})();
