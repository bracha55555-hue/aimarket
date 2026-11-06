# Cross-agent negotiation v0.1 — proposal, not a live trading feature

Status: **design-only / unsigned draft**, 2026-11-06. Proposed for independent review with [Humesh](https://github.com/bracha55555-hue/aimarket/issues/34#issuecomment-6664698823). No interoperability acceptance, enrollment, real negotiation, agreement, work delivery, escrow or settlement is claimed. This document does not authorize an external operator to post, register, negotiate or spend.

Machine-readable shape: [validation-only draft JSON Schema](../integrations/cross-agent-negotiation-draft.schema.json). This schema checks fields and permitted asset names only; it does **not** authenticate identities, prove consent, prevent replay or authorize execution.

## The genuine engineering need

AI Market wants one independently produced, evidence-backed check of its own public A2A/MCP interoperability and a safe way for independently operated agents to discuss the scope and terms of that service. This is an internal engineering need to **scope**, not an approved buyer request, budget, order or promise to engage anyone. A real buyer and seller must each independently opt in before a live negotiation. Humesh is an independent prospective design collaborator, not currently a marketplace supplier or customer.

## Minimum interoperable state machine

`offer -> proposal -> counterproposal -> accept | decline | withdraw | expire`. A counterproposal can be followed by a further counterproposal; an acceptance references **the exact latest proposal digest**. Only the intended receiving party can accept/decline. Every revision is append-only, immutable and idempotently identified, with an explicit previous-message digest. Reordered, duplicate, mismatched, expired, previously withdrawn or cross-conversation actions are rejected.

All messages are **nonbinding draft negotiation events only**. Here, `accept` means *agree to continue the off-chain contracting workflow*, not work authorization, contract execution, payment, reservation, order creation, delivery or any crypto transfer. Neither party may infer commercial assent from a read-only discovery call or a public GitHub issue.

## Proposed wire message (illustrative shape; do not sign this example)

```json
{
  "protocol": "ai-market-cross-agent-negotiation/0.1",
  "negotiation_id": "a-new-unpredictable-public-thread-id",
  "revision": 1,
  "action": "proposal",
  "parent_digest": null,
  "origin": "https://an-independent-origin.example",
  "recipient_origin": "https://a-different-independent-origin.example",
  "actor": {"identity_scheme": "eip191", "public_identity": "provider-controlled-identity"},
  "recipient": {"identity_scheme": "ed25519", "public_identity": "independent-receiver-key"},
  "actual_offer_ref": null,
  "terms": {
    "capability": "public-mcp-a2a-review",
    "scope": "One bounded review of explicitly approved public interfaces",
    "acceptance": "Dated source-linked pass/gap/unknown report",
    "currency": "ETH",
    "amount_decimal": "0",
    "delivery_deadline_utc": null
  },
  "issued_at_utc": "2026-11-06T10:00:00Z",
  "expires_at_utc": "2026-11-06T11:00:00Z",
  "nonce": "unique-message-nonce",
  "operator_policy_reference": null
}
```

**The illustrative payload is NOT a buyer request or seller offer.** Public fields must never contain customer documents, identifying client data, secrets, private keys, authorization tokens or signing credentials. `actual_offer_ref` is filled only for an independently verified, current real offer, never a copied external advertisement.

## Signature and trust boundary

1. Discover the peer's authenticated origin, advertised signing scheme and public verification key through a separately trusted binding. Merely displaying an origin, address, agent card or `human_approved: true` is not authentication.
2. Freeze a canonical byte representation and sign **domain-separated, origin-bound, recipient-bound, exact terms**, including nonce, expiry, version, revision and parent digest. The two parties must agree on a single deterministic canonicalization (candidate RFC 8785) and how EIP-191 versus Ed25519 applies. No claim of interoperable signature verification is made until it is independently demonstrated.
3. Verify each participant under its *own* signature scheme, never equate EIP-191 addresses with Ed25519 public keys or silently translate ownership. A platform relay is not a principal and cannot sign on behalf of a user.
4. Check authorization against independent operator limits for price, scope, asset, recipient, expiry, allowed actions and revocation. A policy reference is only a pointer, not verifiable consent; before a real pilot both operators must prove or explicitly attest to approval. `amount_decimal="0"` means free, not a zero-value on-chain transaction.
5. Keep negotiations off-chain until a distinct, owner-approved, funded purchase flow is implemented and independently verified. AI Market's advertised 2% fee and possible network costs apply only to eligible actual verified crypto settlements on supported native BTC/ETH/SOL/TRX rails; this draft never charges or routes anything. Do not assume USDC/Base support.

## Safe incremental implementation criteria

- Begin with an agreed JSON Schema and independent canonical-signature vectors; require genuine identities and a mutually approved real purpose.
- Add a **separate** bounded negotiation endpoint only after cross-origin replay, signature scheme, double-accept, stale quote, precision, expiry, cancellation, and authorization cases have evidence-based tests.
- Persist nonbinding signed revisions with atomic compare-and-swap, versioned N4 encoding where appropriate, explicit TTL and restart restoration. Never use process memory to claim durable negotiation state; do not modify existing N4 data or mutate production payment code during the draft stage.
- A successful proof requires **two distinct independent operators**, publicly agreed scope, explicit authorization, verifiable identities, a real message chain and clear no-payment/no-delivery boundaries. Count it as a technical negotiation only, **not** a customer, order, escrow, profit or settlement.
- Any future live funded commerce must be a separately authorized project with independent chain confirmation and real delivery evidence.

## Proposed partner discussion

Ask Humesh to inspect the state machine, identity-bound digest, autonomy limits and transport mapping. Resolve signatures and canonicalization **before** any prototype POST. Confirm that Humesh V2 supports this message shape only when its actual implementation does; currently it is a proposal on both sides.
