# 如何冲 OKX.AI 首个 $1M ARR OPC

Created: 2026-07-02
Status: strategy_local

## Signal

Star_OKX 发帖：

> Whoever becomes the first One Person Company (OPC) to generate US$1 million in annual revenue on OKX.AI, I will personally donate X BTC to celebrate the milestone. (X >= 1)

X Layer 同时宣布：

> OKX AI Genesis Hackathon is live. Build an Agent Service Provider for OKX.AI and compete for a share of $100,000 in prizes.

Interpretation:

OKX.AI is explicitly trying to create a market narrative around:

```text
one person company + agent service provider + real usage + onchain payment
```

## Revenue math

Target:

```text
$1,000,000 ARR = $83,333 MRR = about $2,740/day
```

If only per-call:

| Price per audit | Calls needed / year | Calls needed / day |
|---:|---:|---:|
| $0.10 | 10,000,000 | 27,397 |
| $0.25 | 4,000,000 | 10,959 |
| $1.00 | 1,000,000 | 2,740 |
| $2.00 | 500,000 | 1,370 |
| $5.00 | 200,000 | 548 |

Conclusion:

`Agent Acceptance Gate` cannot reach $1M ARR as a low-priced standalone micro-tool unless it becomes high-volume marketplace infrastructure.

To reach $1M, it needs one of these:

1. platform-level placement inside an agent marketplace;
2. high-value dispute / escrow / release gate usage;
3. ASP subscription or team plan;
4. bundle of multiple agent-market operations tools;
5. enterprise/marketplace integration.

## Product thesis

The product should not be:

```text
an audit tool people remember to open
```

It should become:

```text
the default acceptance gate agents call before delivery, payment, release, or dispute.
```

Human-facing phrasing:

```text
Can I accept this agent delivery?
```

Agent-facing phrasing:

```text
Call audit_agent_delivery before accepting, releasing payment, submitting delivery, or voting on dispute.
```

## Wedge

Current wedge:

```text
Agent Acceptance Gate
```

This is a strong wedge because every agent marketplace needs:

- delivery verification;
- missing evidence detection;
- hard-gate detection;
- buyer-ready summaries;
- dispute-ready fact packets.

But the wedge alone is not enough. It must expand into:

```text
Agent Market Trust Layer
```

## Expansion path

### Layer 1: Acceptance Gate

Current.

Inputs:

- task;
- delivery/writeback;
- artifacts;
- validation;
- hard gates;
- next gate.

Output:

- pass / needs_review / fail;
- missing evidence;
- risks;
- seller questions;
- buyer summary;
- evaluator notes.

### Layer 2: Seller Preflight

ASP calls before submitting work.

Value:

- fewer rejected deliveries;
- higher acceptance rate;
- better seller reputation.

Possible pricing:

- low-cost per call;
- bundled into ASP monthly plan.

### Layer 3: Buyer Release Gate

Buyer agent calls before accepting or releasing escrow.

Value:

- avoid paying for incomplete work;
- avoid unsafe deploys;
- evidence-backed rejection.

Possible pricing:

- per accepted task;
- percentage-adjacent fixed fee;
- marketplace-integrated fee.

### Layer 4: Dispute Packet

Evaluator agent calls during dispute.

Value:

- structured facts;
- faster arbitration;
- less subjective argument.

Possible pricing:

- higher per call;
- paid by dispute bounty;
- evaluator tooling subscription.

### Layer 5: Reputation / Credit

Aggregate outcomes:

- seller pass rate;
- missing evidence history;
- hard-gate breach history;
- dispute outcomes.

This is where defensibility starts.

## How to win the hackathon

The hackathon asks for ASPs that solve real problems and generate real usage.

So the submission should not say:

```text
We built an auditor.
```

It should say:

```text
We built the acceptance layer for OKX.AI agent commerce.
```

Demo flow:

1. Seller Agent submits delivery.
2. Acceptance Gate audits delivery.
3. Result is `needs_review`.
4. Seller Agent fixes missing evidence.
5. Gate returns `pass`.
6. Buyer Agent accepts.
7. Future version releases escrow / preserves dispute evidence.

## 7-day execution plan

### Day 0-1: Public signal

Done:

- static demo live;
- local repo;
- OpenAPI;
- MCP-style manifest;
- discovery metadata;
- buyer-facing packet.

Next:

- publish one X post or quote tweet;
- do not claim revenue or official OKX listing;
- frame as "building the acceptance layer for agent commerce."

### Day 1-2: Real A2MCP shape

Build:

- actual MCP server wrapper;
- tool call `audit_agent_delivery`;
- simple hosted API endpoint;
- request idempotency key;
- structured error responses.

Hard gates:

- public endpoint deploy;
- auth/rate limit;
- privacy note.

### Day 2-3: OKX.AI ASP package

Prepare:

- listing description;
- pricing;
- endpoint;
- demo video;
- sample calls;
- terms/boundaries.

Hard gates:

- Agentic Wallet / OKX account;
- receiving address;
- payment middleware;
- ASP listing submission.

### Day 3-5: Usage proof

Get 10-30 real audits from:

- Leo worker writebacks;
- Cursor/Claude/Codex task packets;
- public hackathon examples;
- other builders' ASP deliveries if possible.

Metrics:

- % needs_review;
- top missing evidence;
- time saved;
- pass-after-fix rate.

### Day 5-7: Hackathon submission

Submit as:

```text
Agent Acceptance Gate: the delivery acceptance layer for OKX.AI ASPs.
```

Include:

- demo URL;
- API docs;
- MCP manifest;
- 5 sample cases;
- live usage numbers;
- clear boundary: not wallet/security/legal advice.

## What would make this a $1M OPC

Not the demo.

Not one API.

The $1M version is:

```text
Default acceptance / dispute infrastructure for agent marketplaces.
```

It needs:

- marketplace-level distribution;
- trusted scoring standard;
- usage-based billing;
- seller reputation history;
- dispute integration;
- broad tool schemas beyond Leo's internal workflow.

## Kill criteria

Stop pushing if:

- OKX.AI ASP listing cannot expose this at the delivery/payment/dispute moment;
- agents cannot discover/call it automatically;
- buyers do not understand the result without explanation;
- the product remains a standalone audit page;
- no real users call it after public demo/hackathon exposure.

## Immediate next move

Publish a build-in-public post around the category, not the tool:

```text
Agent marketplaces do not just need more agents.
They need an acceptance layer.

I built a first prototype:
Agent Acceptance Gate.

It answers one question before payment/release/dispute:
Can this agent delivery be accepted?
```

Do not overclaim:

- no OKX.AI official listing yet;
- no payment integration yet;
- no wallet actions;
- no security guarantee.

