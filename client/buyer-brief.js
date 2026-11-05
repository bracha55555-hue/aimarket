"use strict";
(() => {
  const link=document.getElementById("buyer-brief-open");
  const capability=document.getElementById("buyer-brief-capability");
  const deliverable=document.getElementById("buyer-brief-deliverable");
  const status=document.getElementById("buyer-brief-status");
  if(!link||!capability||!deliverable||!status)return;
  for(const field of [capability,deliverable])field.addEventListener("input",()=>{status.textContent="";});
  link.addEventListener("click",event=>{
    const name=capability.value.trim();
    const details=deliverable.value.trim();
    if(name.length<3||name.length>60||details.length<30||details.length>1400){
      event.preventDefault();
      status.textContent="Enter a real capability (3–60 characters) and a non-sensitive, verifiable deliverable (30–1400 characters).";
      return;
    }
    const query=new URLSearchParams({
      template:"independent-buyer-pilot.yml",
      title:"[Public buyer interest] "+name,
      capability:name,
      details,
      response:"Please reply publicly in this issue with your own scoped proposal. No work, credentials or payment is authorized by posting."
    });
    const url="https://github.com/bracha55555-hue/aimarket/issues/new?"+query.toString();
    if(url.length>5000){
      event.preventDefault();
      status.textContent="Shorten the public task description before continuing.";
      return;
    }
    link.href=url;
    status.textContent="Review the GitHub form, select a budget option and approve its acknowledgment before posting. Nothing has been published yet.";
  });
})();
