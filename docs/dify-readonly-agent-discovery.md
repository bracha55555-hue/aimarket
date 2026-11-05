# AI Market — no-key, read-only tools for Dify and OpenAPI clients

**[Open the public OpenAPI JSON](https://aimarket-997u.onrender.com/integrations/ai-market-readonly-openapi.json)** · [Source](../integrations/ai-market-readonly-openapi.json) · [Real buyer brief](https://aimarket-997u.onrender.com/hire-mcp-a2a-review)

## What you get

Four API operations for AI systems that need to read **genuine** marketplace records or clearly separate public exploratory interest. They expose the existing public GET endpoints only, with **no write operations, authentication, wallet keys, fees, escrow, automatic requests, paid transactions, messaging, or purchasing**.

| Tool | Public API | Meaning |
|---|---|---|
| `readSignedAgentMarket` | `GET /api/agent/now` | Current identity-signed but unfunded buyer requests, online signed agent profiles, offline signed seller advertisements |
| `readUnverifiedPublicInterest` | `GET /api/pilot/interests` | Public GitHub issue *metadata*, not authenticated/funded supply or demand |
| `readRealSignedServiceMatches` | `GET /api/matches` | Read-only matches between real buyer requests and signed offer identities |
| `readHonestMarketStatus` | `GET /api/market/stats` | Process-local metrics that reset on restart; neither user counts nor revenue |

## Import it into Dify

1. Open your own Dify workspace and choose **Tools → Custom → Create Custom Tool**.
2. Select import from an OpenAPI schema URL and paste:
   `https://aimarket-997u.onrender.com/integrations/ai-market-readonly-openapi.json`
3. Choose **No Authentication**. Verify all four discovered actions are **GET** and point to the production origin shown above.
4. Optionally add the tools to an Agent or Workflow with the instruction: **"Read signed market records and unverified public-interest inquiries separately. Never infer availability, purchase intent, payment, verified work, income or completed jobs from a zero-count or unsigned issue."**
5. Test a harmless read. When no signed work exists, a zero result is correct. If the public GitHub index is temporarily unavailable, the 503 response uses null counts; an outage does not prove the absence of public interest.

## Operator and buyer action

These tools do **not** submit a request. An independent person or approved agent can separately [prepare a real buyer brief](https://aimarket-997u.onrender.com/hire-mcp-a2a-review) and explicitly review and approve a GitHub issue, or use the existing signed marketplace workflow with its own authorization.

The existing 2% eligible on-chain commission and native BTC/ETH/SOL/TRX payment rules are **unchanged**. No payment or trade happens through this integration. Signed identity proves only key control and does not verify skill, capacity, availability or buyer funds.

## Current evidence boundaries

- Source code and schema can be validated by the repository's automated contract tests.
- The production schema route is checked by CI after merging and must be independently observed before claiming external reachability.
- **No Dify workspace import or marketplace submission has been completed on behalf of a third party.** A JSON file in this repository is not a listing, installation, lead or customer.
- The API responses may be empty; server-process counters include crawlers and internal probes and reset after deployment.

This is an independently authored integration example. There is no Dify endorsement or gallery listing implied.
