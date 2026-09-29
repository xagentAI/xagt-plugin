# SETTLE — Product Brief

> **Payment truth for autonomous agents.**

**Hackathon:** X-Agent AI MCP Hackathon 2026  
**Track:** Open Innovation Challenge  
**Product type:** API-first agent capability  
**Working name:** Settle  
**MVP network:** Base  
**MVP asset:** USDC  

---

## 1. Executive Summary

Settle is an API-first payment reconciliation service for AI agents and automated workflows.

It answers a deceptively simple but important question:

> **Did the expected crypto payment actually arrive?**

An autonomous agent can create an expected payment, continue doing other work, and later ask Settle whether that payment has been received. Settle checks the blockchain, reconciles matching transfers against the expected payment, and returns structured evidence such as status, amount received, remaining amount, transaction hashes, confirmations, timestamps, and matching confidence.

The MVP focuses on **USDC payments on Base**.

Settle does not custody funds, hold private keys, execute trades, score wallet risk, perform compliance analysis, or decide whether a transaction is “safe.” It is a deterministic reconciliation layer.

The core product loop is:

```text
Agent creates expected payment
        ↓
User / agent sends USDC
        ↓
Settle observes Base
        ↓
Settle reconciles transfer(s)
        ↓
Agent receives structured result
        ↓
Agent continues workflow
```

Example:

```json
{
  "status": "paid",
  "expectedAmount": "850.00",
  "receivedAmount": "850.00",
  "remainingAmount": "0.00",
  "asset": "USDC",
  "chain": "base",
  "payer": "0x...",
  "recipient": "0x...",
  "transactions": [
    {
      "hash": "0x...",
      "amount": "850.00",
      "confirmations": 37
    }
  ],
  "paidAt": "2026-09-17T14:31:02Z"
}
```

Settle is designed to become a clean MCP primitive later:

```text
create_payment_intent()
check_payment()
list_payment_evidence()
```

---

# 2. Problem

AI agents are increasingly able to:

- research;
- write;
- negotiate;
- call APIs;
- purchase services;
- issue invoices;
- coordinate work;
- interact with wallets;
- trigger multi-step workflows.

But payment introduces a hard state transition.

An agent may know that it **requested** payment. That is not the same as knowing that payment **settled**.

Today, developers often solve this by:

- manually checking a block explorer;
- polling generic blockchain APIs;
- writing custom token-transfer parsers;
- trusting screenshots or user claims;
- wiring payment-provider-specific webhooks;
- building one-off reconciliation logic for each product.

That creates duplicated infrastructure.

The underlying problem is not “how do I send crypto?”

It is:

> **How can software reliably establish that a specific expected payment has been satisfied?**

This is especially important for autonomous agents because a payment result often controls what happens next.

Examples:

```text
payment confirmed
→ release generated report

payment confirmed
→ provide API access

payment confirmed
→ start compute job

payment confirmed
→ mark invoice paid

payment confirmed
→ unlock premium workflow

payment confirmed
→ fulfill digital service
```

A prompt alone cannot reliably establish this state.

The answer must come from verifiable external evidence.

---

# 3. Product Thesis

Payment reconciliation should be an infrastructure primitive.

Developers should not need to understand event logs, token decimals, confirmation depth, partial payments, duplicate transfers, RPC quirks, or chain indexing just to answer:

> “Has invoice INV-204 been paid?”

Settle turns blockchain evidence into a small, typed, agent-friendly contract.

Instead of:

```text
fetch logs
→ decode Transfer events
→ normalize decimals
→ filter recipient
→ filter payer
→ inspect timestamps
→ aggregate transfers
→ handle duplicates
→ calculate balance due
```

an agent calls:

```text
check_payment(intent_id)
```

and receives:

```text
pending
partial
paid
overpaid
expired
ambiguous
```

plus the underlying evidence.

Settle therefore sits between:

```text
ONCHAIN PAYMENT DATA
        ↓
      SETTLE
        ↓
AGENT BUSINESS LOGIC
```

---

# 4. Vision

The long-term vision is to become the **payment truth layer for the agent economy**.

Agents will increasingly transact with:

- humans;
- other agents;
- paid APIs;
- compute providers;
- data services;
- digital merchants;
- creators;
- contractors.

Those systems need a neutral way to verify whether payment obligations were fulfilled.

Settle should eventually answer:

```text
Was it paid?
How much was received?
Who paid?
Which transactions satisfied it?
Was it partial?
Was it late?
Was it overpaid?
Has it reached sufficient confirmation depth?
```

without controlling the funds themselves.

---

# 5. Product Positioning

## Primary positioning

> **Settle — payment truth for autonomous agents.**

## Alternate lines

> **Know when the money actually arrived.**

> **Onchain payment reconciliation as an API.**

> **From “payment requested” to “payment verified.”**

> **A clean payment state primitive for agents.**

---

# 6. Target Users

## 6.1 AI agent developers

Developers building agents that:

- sell generated outputs;
- gate access behind payment;
- coordinate paid tasks;
- purchase external services;
- invoice users;
- wait for payment before continuing.

Their problem:

> “I don't want to build and maintain blockchain reconciliation infrastructure.”

---

## 6.2 Agent marketplaces

Marketplaces need to determine:

```text
service requested
→ payment made
→ service delivered
```

Settle can provide the payment-state layer without becoming the marketplace itself.

---

## 6.3 Crypto-native SaaS products

Products that accept USDC may need:

- invoice matching;
- deposit confirmation;
- access gating;
- subscription-like payment verification;
- settlement history.

---

## 6.4 Freelancers and service agents

An agent acting for a freelancer could:

```text
issue payment request
→ monitor settlement
→ mark invoice paid
→ deliver files
```

without the freelancer checking a wallet manually.

---

## 6.5 Automation platforms

Workflow engines could use Settle as a trigger:

```text
IF payment.status == "paid"
THEN continue workflow
```

---

# 7. Jobs To Be Done

## Primary job

> When my system expects a crypto payment, tell me whether the obligation has actually been satisfied and provide evidence I can trust.

## Secondary jobs

- Tell me how much remains unpaid.
- Tell me if multiple transfers collectively satisfy the obligation.
- Give me the transaction evidence.
- Tell me whether the payment has enough confirmations.
- Give me a machine-readable status another agent can reason over.
- Avoid double-counting the same transfer.
- Let me reconcile without exposing a private key.

---

# 8. MVP Scope

The MVP is intentionally narrow.

## Supported

```text
Chain: Base
Asset: native USDC on Base
Mode: read-only reconciliation
Payment direction: payer → recipient
Matching: recipient + token + amount + time window
Strong matching: payer address supplied
Partial-payment aggregation: yes
Overpayment detection: yes
Confirmation threshold: configurable within safe bounds
```

## Core endpoints

```text
POST /v1/payment-intents
GET  /v1/payment-intents/:id
POST /v1/payment-intents/:id/reconcile
GET  /v1/payment-intents/:id/evidence

GET  /health
GET  /.well-known/xagent-verification.json
```

The public deployment must expose the X-Agent verification endpoints from the beginning, not as a last-minute submission patch.

---

# 9. Payment Intent

A payment intent represents an obligation.

Example request:

```json
{
  "externalReference": "INV-204",
  "chain": "base",
  "asset": "USDC",
  "amount": "850.00",
  "recipient": "0xRecipient",
  "payer": "0xPayer",
  "expiresAt": "2026-09-18T18:00:00Z",
  "requiredConfirmations": 3
}
```

Example response:

```json
{
  "id": "pi_01K...",
  "status": "pending",
  "externalReference": "INV-204",
  "expectedAmount": "850.00",
  "receivedAmount": "0.00",
  "remainingAmount": "850.00",
  "createdAt": "...",
  "expiresAt": "..."
}
```

The intent ID becomes the stable object an agent monitors.

---

# 10. Reconciliation States

Settle uses explicit state rather than vague language.

## `pending`

No matching confirmed payment has been observed.

## `detected`

A candidate transfer exists but has not reached the requested confirmation threshold.

## `partial`

One or more verified transfers have been received but do not yet satisfy the full amount.

Example:

```text
Expected: 850 USDC
Received: 500 USDC
Remaining: 350 USDC
```

## `paid`

Verified transfer(s) meet the obligation.

## `overpaid`

Verified transfer(s) exceed the expected amount.

## `expired`

The payment intent passed its expiry without full settlement.

## `ambiguous`

The system found candidate evidence but cannot deterministically associate it with the intent.

This is preferable to inventing certainty.

---

# 11. Deterministic Matching

Settle should be conservative.

The strongest MVP match uses:

```text
chain
+
token contract
+
recipient address
+
payer address
+
created-at / expiry window
```

and aggregates matching transfers.

If no payer address is provided, Settle may still inspect candidate payments, but it must avoid falsely claiming certainty when multiple plausible transfers exist.

For the hackathon, the recommended production path is:

> **Require or strongly encourage the payer wallet address for deterministic reconciliation.**

That keeps the capability reliable and easy to explain.

---

# 12. Why Base + USDC

The MVP needs one rail that is:

- cheap;
- fast;
- widely understood;
- stable in denomination;
- straightforward for a live demonstration.

Base + USDC provides a clean first environment.

It keeps the product focused on reconciliation instead of exchange-rate logic.

The design should remain chain-adapter based so more networks can be added later.

---

# 13. Primary User Stories

## Story A — Paid AI report

An agent generates a premium research report.

Before delivery:

```text
Agent:
"Payment required: 25 USDC."
```

The workflow creates:

```text
pi_report_104
```

The customer pays.

Agent calls Settle.

Response:

```json
{
  "status": "paid"
}
```

Agent releases the report.

---

## Story B — Partial invoice

Expected:

```text
1,000 USDC
```

Customer sends:

```text
600 USDC
```

Settle returns:

```json
{
  "status": "partial",
  "receivedAmount": "600.00",
  "remainingAmount": "400.00"
}
```

A second transfer of 400 USDC arrives.

Next reconciliation:

```json
{
  "status": "paid",
  "receivedAmount": "1000.00",
  "remainingAmount": "0.00"
}
```

---

## Story C — Agent-to-agent service

Agent A hires Agent B to perform a task.

Agent B says:

```text
Cost: 5 USDC
```

The orchestration layer:

```text
creates payment intent
→ sends payment
→ waits
→ asks Settle
→ receives proof
→ continues
```

Settle does not negotiate or transfer the money.

It establishes payment state.

---

# 14. What Settle Is Not

Clear product boundaries protect both the build and the hackathon eligibility.

Settle is **not**:

- a wallet;
- an exchange;
- a bridge;
- a custody provider;
- an escrow product;
- a payment execution engine;
- a fraud detector;
- a scam detector;
- a wallet-risk scorer;
- a compliance service;
- a transaction-security analyzer;
- a smart-contract auditor;
- a trading product.

It does not label a transfer “safe” or “unsafe.”

It only answers whether observable payment evidence matches a declared obligation.

This distinction is important because X-Agent explicitly excludes onchain security, wallet/transaction risk scoring, scam detection, compliance analysis, and similar security products from both hackathon tracks.

---

# 15. Product Experience

Settle is API-first.

The primary customer is software.

However, the hackathon should include a lightweight inspector/demo UI.

## Demo console

A minimal page can show:

```text
SETTLE

Payment Intent
INV-204

Expected
850.00 USDC

Received
500.00 USDC

Status
PARTIAL

Remaining
350.00 USDC

Transactions
0x8ab...   500 USDC   22 confirmations
```

Actions:

```text
[ Reconcile Now ]
[ View Evidence ]
[ Copy API Call ]
```

The UI is not the product's main value.

It makes the capability observable and easy for reviewers to understand.

---

# 16. API Design Principles

## Typed

Inputs and outputs should have explicit schemas.

## Idempotent

Repeated reconciliation must not double-count transfers.

## Evidence-first

Every positive result should include the transaction evidence behind it.

## Conservative

When evidence is insufficient, return `ambiguous` or `pending` rather than pretending certainty.

## Agent-friendly

Avoid prose-only responses.

Return structured values that can drive branching logic.

## Observable

Return useful request IDs, timestamps, provider state, and deterministic errors.

---

# 17. Example Agent Workflow

```text
AI SALES AGENT
      │
      │ create intent
      ▼
    SETTLE
      │
      ├── expected: 120 USDC
      └── intent: pi_123
      │
      ▼
CUSTOMER SENDS PAYMENT
      │
      ▼
   BASE CHAIN
      │
      ▼
AGENT CHECKS pi_123
      │
      ▼
    SETTLE
      │
      ├── status: paid
      ├── amount: 120
      └── tx: 0x...
      │
      ▼
AGENT DELIVERS SERVICE
```

---

# 18. X-Agent / MCP Productization

The hackathon does not require Settle to ship as a full MCP server.

That is an advantage.

For submission, the product should expose a clean online API with obvious future MCP boundaries.

Potential MCP tools:

```text
create_payment_intent
check_payment_status
get_payment_evidence
```

Example future tool contract:

```json
{
  "name": "check_payment_status",
  "description": "Check whether a declared USDC payment obligation has been satisfied onchain.",
  "input": {
    "paymentIntentId": "pi_..."
  }
}
```

That makes Settle particularly suitable for X-Agent's post-hackathon standardization path.

---

# 19. Why Settle Fits the X-Agent Open Innovation Challenge

The challenge rewards a genuinely useful, online-callable, API-backed capability.

Settle matches that directly.

It is:

```text
useful
→ payment reconciliation is a real workflow problem

online-callable
→ HTTP API

agent-native
→ structured outputs control workflow state

verifiable
→ blockchain evidence

productizable
→ maps cleanly to MCP tools

operable
→ narrow capability with clear SLAs

monetizable
→ natural per-call infrastructure service
```

It also avoids the explicitly excluded security/audit category.

---

# 20. Judging Alignment

X-Agent's review scorecard weights five areas.

## Real agent/user value — 30%

Settle completes a concrete task that cannot be solved reliably by prompting:

> verify payment settlement.

The result directly controls real workflows.

---

## Demonstrated capability quality — 25%

The product can demonstrate:

- real Base transactions;
- exact matching;
- partial payments;
- confirmation handling;
- deterministic error behavior;
- evidence links;
- repeatable API calls.

---

## Engineering & maintainability — 20%

The implementation should prioritize:

- typed schemas;
- tests;
- clear adapters;
- deterministic decimal handling;
- environment validation;
- structured logs;
- reproducible deployment;
- pinned dependencies;
- no secrets in source.

---

## MCP productization readiness — 15%

The capability naturally maps into small tools with:

- clear inputs;
- clear outputs;
- no hidden side effects;
- explicit errors;
- obvious authorization boundaries.

---

## Adoption & operating potential — 10%

Potential users include:

- agent marketplaces;
- agent builders;
- AI SaaS;
- automation products;
- crypto-native SaaS;
- paid API services.

The operating model is straightforward and can expand network-by-network.

---

# 21. Differentiation

## Versus block explorers

Explorers answer:

> “What transactions happened?”

Settle answers:

> “Did these transactions satisfy this payment obligation?”

---

## Versus generic RPC/indexing APIs

Indexers provide raw blockchain data.

Settle provides:

```text
intent
+
matching
+
aggregation
+
status
+
evidence
```

---

## Versus payment processors

Payment processors often own checkout, payment creation, or settlement rails.

Settle can remain neutral.

It verifies payments that happened independently.

---

## Versus custom application logic

Without Settle, every developer rebuilds reconciliation.

Settle turns that logic into infrastructure.

---

# 22. Competitive Moat

The initial code is not the moat.

The long-term defensibility comes from reliability and breadth:

```text
more networks
+
more assets
+
better reconciliation primitives
+
better payment-intent semantics
+
stronger observability
+
high reliability
+
agent ecosystem integrations
```

A payment-truth API becomes more valuable as developers trust it as infrastructure.

---

# 23. Business Model

The natural model is usage-based API pricing.

Potential tiers:

```text
FREE
500 reconciliation calls / month

BUILDER
$19–49 / month

PRO
higher volume + webhooks + retention

AGENT / MARKETPLACE
per-call billing
```

This is especially compatible with an MCP marketplace.

A future paid call could be priced at fractions of a cent to several cents depending on chain/indexing costs.

---

# 24. Success Metrics

## Hackathon metrics

- API deployed and reachable.
- All X-Agent hard gates pass.
- Real transaction successfully reconciled.
- Partial-payment case demonstrated.
- Zero duplicate counting.
- Public health endpoint reports exact Git commit.
- Verification endpoint reports exact slug + commit.
- Clean isolated reproduction instructions.
- Automated tests pass.

## Product metrics

Longer term:

```text
payment intents created
reconciliation calls
percentage automatically resolved
time-to-detection
false-positive rate
ambiguous-match rate
API error rate
developer retention
payments verified
```

The most important reliability metric:

> **False-positive paid status should approach zero.**

It is better to return ambiguity than incorrectly say an obligation is paid.

---

# 25. Security & Privacy Principles

Settle is intentionally read-only.

Never store:

```text
private keys
seed phrases
wallet signing keys
exchange credentials
```

A payer and recipient address are public blockchain identifiers, but their association with invoices may still be commercially sensitive.

Data retention should therefore be minimized.

The product should:

- avoid unnecessary personal information;
- encrypt sensitive stored metadata;
- separate API credentials from application data;
- rate-limit public endpoints;
- validate all addresses and amounts;
- never expose RPC/provider secrets;
- never claim to evaluate transaction safety.

---

# 26. Monetary Correctness

Money must never use binary floating-point arithmetic.

Internally:

```text
850 USDC
```

should be represented using:

- integer token units; or
- a decimal library.

For USDC:

```text
850.00 USDC
=
850000000 token units
```

All reconciliation comparisons should use exact integer values.

---

# 27. Error Philosophy

Errors are part of the product.

Examples:

```json
{
  "error": {
    "code": "INVALID_ADDRESS",
    "message": "payer must be a valid Base address"
  }
}
```

```json
{
  "error": {
    "code": "UPSTREAM_UNAVAILABLE",
    "message": "Blockchain provider is temporarily unavailable",
    "retryable": true
  }
}
```

```json
{
  "status": "ambiguous",
  "reason": "Multiple candidate transfers match the payment window and no payer address was supplied."
}
```

An agent needs to know whether it should:

```text
retry
ask user
wait
abort
continue
```

---

# 28. Reliability Expectations

Settle should degrade safely.

If the RPC/indexer is unavailable:

```text
do not change pending → paid
```

If evidence cannot be fetched:

```text
return retryable upstream error
```

If a candidate is under confirmation threshold:

```text
return detected
```

If there are multiple plausible matches:

```text
return ambiguous
```

Payment state should be monotonic where possible.

Once a payment is considered final at sufficient confirmation depth, later reconciliation should not casually regress it.

---

# 29. Hackathon Demo

The demo should be under two minutes.

## Scene 1 — Create intent

Show:

```text
Invoice INV-204
Expected: 25 USDC
Payer: Wallet A
Recipient: Wallet B
```

Call:

```text
POST /v1/payment-intents
```

Status:

```text
PENDING
```

---

## Scene 2 — Make real payment

Send a small real Base USDC transaction.

---

## Scene 3 — Reconcile

Call:

```text
POST /v1/payment-intents/:id/reconcile
```

Initially:

```text
DETECTED
1 confirmation
```

Then:

```text
PAID
```

UI updates.

Show tx hash.

---

## Scene 4 — Agent value

A sample agent workflow displays:

```text
Payment verified.
Releasing premium result...
```

That closes the story.

---

# 30. Submission Strategy

The X-Agent submission should be engineered into the product from the beginning.

Required public endpoints:

```text
/health

/.well-known/xagent-verification.json
```

The deployment must expose the exact 40-character reviewed Git commit.

The repository should include:

```text
README
API examples
curl verification
tests
deployment instructions
environment example
license
source
```

The final X-Agent PR must include the official submission package with:

```text
SUBMISSION.md
submission.json
RIGHTS.md
source/
verification/README.md
```

---

# 31. MVP Non-Goals

To hit the deadline, do not build:

- multi-chain support;
- fiat conversion;
- stablecoin swaps;
- wallet connection;
- transaction execution;
- escrow;
- refunds;
- merchant dashboard;
- subscription billing;
- identity/KYC;
- security scoring;
- compliance;
- machine-learning matching;
- elaborate frontend;
- full MCP server.

A narrow reliable capability will score better than a broad fragile product.

---

# 32. Post-Hackathon Roadmap

## Phase 1 — MVP

```text
Base + USDC
payment intents
reconciliation
partial payments
evidence
health + verification
```

## Phase 2 — Developer UX

```text
API keys
webhooks
SDKs
dashboard
request logs
usage analytics
```

## Phase 3 — More networks

```text
Ethereum
Arbitrum
Optimism
Polygon
X Layer
```

## Phase 4 — Agent commerce

```text
MCP packaging
pay-per-call
agent-to-agent settlement workflows
marketplace integrations
```

## Phase 5 — Advanced reconciliation

```text
batched obligations
recurring obligations
payment links
multi-asset invoices
smart account payments
```

---

# 33. Brand Direction

Settle should feel like infrastructure, not DeFi speculation.

Visual direction:

```text
minimal
dark/light neutral palette
monospace accents
transaction evidence
strong status typography
```

Avoid:

```text
candlestick charts
token-price graphics
neon “degen” styling
risk gauges
trading motifs
```

The emotional promise is:

> **certainty.**

---

# 34. Product Principles

1. **Evidence over inference.**
2. **Never claim paid without verifiable support.**
3. **Ambiguity is a valid result.**
4. **Read-only by default.**
5. **One capability, exceptionally reliable.**
6. **Structured outputs before prose.**
7. **Agent workflows are first-class users.**
8. **Payment data is state, not content.**
9. **No private keys. Ever.**
10. **The API is the product.**

---

# 35. Definition of Done

Settle's hackathon MVP is ready when:

```text
✓ deployed API is publicly reachable

✓ Base USDC payment intent can be created

✓ exact payer/recipient/amount can be reconciled

✓ partial payment is correctly represented

✓ multiple transfers can aggregate without double counting

✓ confirmation threshold works

✓ evidence includes real transaction hashes

✓ API is idempotent

✓ monetary calculations use exact units

✓ provider failure cannot create false paid status

✓ health endpoint reports exact reviewed commit

✓ X-Agent verification endpoint reports correct slug + commit

✓ clean checkout can reproduce tests

✓ public source contains no secrets

✓ one real verification curl is documented

✓ lightweight demo UI shows intent → payment → paid

✓ submission package passes X-Agent validation
```

---

# 36. One-Sentence Pitch

> **Settle is an API that tells autonomous agents whether an expected crypto payment actually arrived, with structured onchain evidence they can use to continue a workflow.**

---

# 37. Short Pitch

> AI agents can request payment, but most still need custom infrastructure to know whether that payment actually settled. Settle turns onchain USDC transfers into a clean payment-state API. Create an expected payment, check it later, and receive deterministic statuses such as pending, partial, paid, overpaid, or ambiguous together with the transaction evidence. The MVP supports USDC on Base and is built to become a reusable MCP payment primitive.

---

# 38. Closing Thesis

The agent economy does not only need ways to move money.

It needs reliable ways to understand **payment state**.

A service should not be released because a user says they paid.

An agent should not continue because a screenshot exists.

A workflow should not depend on someone manually refreshing a block explorer.

Settle makes payment completion machine-readable.

> **Requested is not paid. Settle proves the difference.**
