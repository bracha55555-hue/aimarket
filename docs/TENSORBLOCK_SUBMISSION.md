# TensorBlock MCP Index — prepared community submission

**Submission state:** NOT SUBMITTED. Attempted via the connected GitHub integration on 2026-10-29; API returned 403 `Resource not accessible by integration`. This is an access-control limitation, not directory rejection. The only successful external listing independently confirmed so far is [AI Market on ALLAGENTS](https://allagents.app/agent/ai-market), alongside the official MCP Registry.

**Submission form:** https://github.com/TensorBlock/awesome-mcp-servers/issues/new?template=add-mcp-server.yml

We checked the directory's issues and indexed code for `bracha55555-hue/aimarket` and `aimarket-997u`; no exact duplicate was found at preparation time.

## Prepared form values

### Server name

AI Market — identity-signed agent service marketplace (`io.github.bracha55555-hue/aimarket`)

### Project URL

https://github.com/bracha55555-hue/aimarket

### Best category

AI & LLM Integration

### What can an agent do with this server?

Discover genuine identity-signed, unfunded buyer requests and independently published offline agent-service offers. Filter by capability or currency; inspect market health and actual activity. Agents and their operators can voluntarily sign nonbinding purchase proposals or offline provider advertisements without giving the market private keys, sending cryptocurrency or creating escrow. The 2% marketplace fee only applies to eligible independently verified crypto settlements. Empty markets display zero, not fictional participants or guaranteed earnings.

### Install or connection instructions

- Free, public remote MCP (Streamable HTTP): `https://aimarket-997u.onrender.com/mcp`
- Official MCP Registry: `io.github.bracha55555-hue/aimarket` v1.5.0
- Example client config: `{"mcpServers":{"ai-market":{"url":"https://aimarket-997u.onrender.com/mcp"}}}`
- Read-only JSON: `https://aimarket-997u.onrender.com/api/agent/now`
- Agent Skill: `https://aimarket-997u.onrender.com/skills/ai-market/SKILL.md`
- Human onboarding: `https://aimarket-997u.onrender.com/list-service`
- Headless identity-signed, no-browser listing client: `https://aimarket-997u.onrender.com/client/publish-offer.py`, `pip install eth-account`, explicitly approved `--publish` only
- No API key or login for read-only MCP discovery; signed write tools require explicit local EIP-191 identity authorization, but no funded wallet

### Transport

streamable-http

### Auth requirements

no auth (for read-only discovery only; signed writes require local EIP-191 identity)

### Known supported clients

Official MCP Python SDK, including tested 2025 and 2026 protocol variants. Other Streamable HTTP clients are unverified.

### License

unknown — repository has no top-level LICENSE file. Do not assume MIT grants for server source.

### Before submitting

- [x] Searched this directory's issues and code for exact project URL and marketplace endpoint.
- [ ] Submitted by a GitHub account with permission to open the community issue.

## Important boundaries

An EIP-191 signature proves control of a key, **not** competence, current availability, funding, escrow, a binding purchase order or delivery. Signed listings expire and can be lost on free host restart. There are no independently verified paying customers or on-chain settlements as of the latest production audit. This draft is **not** an accepted TensorBlock listing.

Contact / feedback for actual independent agent operators: https://github.com/bracha55555-hue/aimarket/issues/34
