"use strict";
(() => {
  const status=document.getElementById("copy-status");
  for (const button of document.querySelectorAll("button[data-copy]")) {
    button.addEventListener("click",async () => {
      const id=button.getAttribute("data-copy");
      const source=document.getElementById(id);
      if (!source) return;
      const text=source.textContent.trim();
      try {
        if (!navigator.clipboard?.writeText) throw new Error("unsupported");
        await navigator.clipboard.writeText(text);
        status.textContent="Copied. Review the command or agent message before using it.";
      } catch (_) {
        status.textContent="Copy unavailable in this browser. Select the text in the box above manually.";
      }
    });
  }
})();
