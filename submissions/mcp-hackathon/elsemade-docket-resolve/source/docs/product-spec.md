# Docket product specification

## Product definition

Docket is the settlement control plane for agent-to-agent work.

It evaluates delivered work against the agreement that existed before delivery, then recommends a proportional release and hold amount with an auditable explanation.

Primary message:

> Docket reviews agent work and turns evidence into explainable, proportional settlements.

Supporting message:

> AI reasons about the evidence. Docket's settlement rules calculate the amount. A human or authorized payment system decides whether to execute it.

Avoid leading with:

- deterministic API;
- JSON evaluator;
- automated escrow;
- AI judge;
- on-chain arbitration.

These either hide the user value or overstate authority.

## Problem

Agent work is often paid as if delivery were binary. Real work is not. A result may satisfy the core task while missing documentation, edge cases, or polish. Releasing everything ignores incomplete work; releasing nothing ignores delivered value.

Docket makes the acceptance contract explicit and assigns value to each criterion before delivery. After delivery, it uses evidence-grounded review findings to calculate how much value was earned.

## Users

### Commissioning agent

Defines the task, amount, acceptance criteria, evidence requirements, and settlement policy. Needs confidence that payment recommendations follow the original agreement.

### Worker agent

Delivers work and attaches evidence. Needs protection from requirements introduced after delivery and needs every deduction explained.

### Reviewer agent

Assesses evidence against one criterion at a time. Needs a strict scope, evidence references, and a structured finding contract.

### Human operator

Approves agreements, handles ambiguous disputes, and decides whether a recommendation is accepted. Needs a concise case record rather than raw model output.

### Payment authority

Consumes an unsigned recommendation after separate authorization. It is outside Docket's trust boundary.

## Core concepts

### Agreement

The approved contract for a unit of work: parties, amount, asset, weighted criteria, critical requirements, required evidence, and review policy.

### Criterion allocation

Each criterion's weight maps to a specific portion of the total amount. A 30 percent criterion in a 500 USDC agreement controls 150 USDC.

### Evidence

A supplied artifact, test result, receipt, attestation, screenshot, text excerpt, or external reference with a digest and criterion association.

### Finding

A structured assessment of one criterion: score, confidence, cited evidence, rationale, missing evidence, and contradiction flags.

### Evaluation

The settlement kernel's calculation over an immutable agreement version and accepted findings.

### Recommendation

The release/hold result, criterion ledger, reason codes, provenance, and review state. It is not a payment instruction with execution authority.

## Case lifecycle

```text
draft
  -> awaiting_approval
  -> active
  -> evidence_open
  -> review_ready
  -> reviewing
  -> clarification_required | manual_review | recommendation_ready
  -> accepted | rejected | superseded
```

Rules:

- Only draft agreements can change weights or evidence requirements.
- Activation freezes an agreement version.
- Evidence can be added while evidence collection is open.
- A review always names the agreement and evidence versions it assessed.
- New accepted evidence after a recommendation creates a new review/evaluation and supersedes the prior result; it does not rewrite history.
- Payment execution is never a Docket case state.

## Primary workflow

### 1. Draft

The commissioning agent submits a task brief, amount, asset, and optional constraints. Docket may suggest criteria, weights, critical flags, and evidence requirements.

The screen must label these as suggestions. The user can edit every item.

### 2. Approve

Both sides inspect:

- what “done” means;
- how much value each criterion controls;
- which criteria are critical;
- what proof is expected;
- when manual review is triggered.

Activation requires explicit approval. The UI presents a final allocation check that totals 100 percent and the full amount.

### 3. Submit evidence

The worker attaches evidence to criteria. The UI shows missing required evidence before review starts. Evidence bodies are bounded and may be redacted before AI review.

### 4. Review

Docket's AI reviews evidence against the frozen agreement. It cannot add requirements. Findings display score, confidence, rationale, citations, gaps, and contradictions.

### 5. Resolve gaps

If evidence is missing or confidence is low, Docket asks a narrow clarification question. If reviewers materially disagree, the case goes to manual review.

### 6. Calculate

Accepted findings pass to the settlement kernel. The output highlights:

- release amount;
- hold amount;
- settlement percentage;
- amount earned per criterion;
- amount held per criterion;
- caps or conflict rules applied.

### 7. Explain

The interface answers “Why this amount?” in plain language while retaining the exact ledger underneath.

### 8. Export

Docket exports an unsigned, versioned recommendation for a human or authorized payment system. Exporting does not execute anything.

## Canonical demo case

Agreement value: 250 USDC.

| Criterion | Weight | Score | Allocation | Earned |
| --- | ---: | ---: | ---: | ---: |
| Production API | 50% | 100% | 125 USDC | 125 USDC |
| Reproducible documentation | 30% | 90% | 75 USDC | 67.5 USDC |
| Safe edge cases | 20% | 75% | 50 USDC | 37.5 USDC |

Result:

- Release: 230 USDC
- Hold: 20 USDC
- Settlement: 92 percent

This result must be the visual center of the demo. The interface should make it immediately clear which criteria produced the 20 USDC hold.

## Case workspace

### Header

- case name and state;
- agreement version;
- total amount and asset;
- participant identities;
- last review time;
- primary action appropriate to the current state.

### Settlement summary

The largest visual element:

```text
Recommended release     230 USDC
Remaining on hold        20 USDC
Settlement ratio             92%
```

Include a persistent “Recommendation only — no funds moved” label.

### Criterion ledger

Each row shows:

- criterion and critical status;
- weight and allocated amount;
- score and confidence;
- earned and held amount;
- evidence count;
- finding status;
- reason codes.

Selecting a row opens its evidence and rationale.

### Evidence panel

- evidence grouped by criterion;
- type, digest, source, timestamp, and submitter;
- preview for allowed bounded content;
- missing-evidence requirements;
- contradiction warnings;
- redaction/provider-sharing status.

### AI review panel

- review state and progress;
- model and prompt provenance in an advanced section;
- finding rationale and citations;
- confidence and uncertainty;
- clarification requests;
- challenge action.

Never present AI prose without its criterion and citations nearby.

### Activity trace

Chronological events:

- agreement drafted;
- agreement approved and frozen;
- evidence submitted;
- review started/completed/failed;
- clarification requested;
- finding challenged or accepted;
- recommendation calculated/superseded/exported.

### Integration panel

- MCP endpoint and connection status;
- local stdio configuration;
- available tools and scopes;
- copyable, redacted examples;
- API/OpenAPI links.

## User stories and acceptance criteria

### Draft a fair agreement

As a commissioning agent, I can turn a task brief into suggested weighted criteria so value is allocated before work begins.

Acceptance:

- suggestions are editable and clearly marked;
- weights and atomic allocations reconcile exactly;
- activation fails if weights do not total 100;
- activated versions cannot be silently edited.

### Submit evidence

As a worker agent, I can attach evidence to a criterion and see whether the case is ready for review.

Acceptance:

- evidence requires a criterion, kind, digest, and source/provenance;
- duplicate submissions are idempotent;
- unsupported types and oversized content fail with actionable errors;
- the system shows missing required evidence.

### Receive an AI review

As a reviewer, I can inspect evidence-grounded findings without allowing the model to change the contract.

Acceptance:

- every scored finding cites valid evidence;
- unknown criteria or evidence IDs are rejected;
- missing evidence produces a gap, not invented support;
- low confidence is visible and may block settlement.

### Understand a proportional result

As either party, I can see why an exact amount is released or held.

Acceptance:

- the sum of earned criterion amounts equals the recommended release;
- the sum of held criterion amounts equals the recommended hold;
- every adjustment names its criterion and rule;
- the explanation cannot contradict the ledger.

### Challenge a finding

As either party, I can challenge one finding with a reason and additional evidence.

Acceptance:

- the original finding remains in history;
- the challenge is criterion-scoped;
- accepted new evidence creates a new review version;
- the previous recommendation becomes superseded rather than overwritten.

## UX language

Prefer:

- recommended release;
- amount on hold;
- evidence required;
- clarification required;
- manual review;
- criterion allocation;
- recommendation only;
- no funds moved.

Avoid:

- guilty/innocent;
- final judgment;
- guaranteed truth;
- automatic payout;
- legally binding;
- AI decided your payment.

## Product metrics

- Agreement activation success rate.
- Percentage of criteria with sufficient evidence before review.
- AI finding acceptance/challenge rate.
- Citation validation failure rate.
- Clarification and manual-review rate.
- Time from evidence-ready to recommendation.
- Percentage of cases ending in partial settlement.
- Recommendation supersession rate.
- MCP tool success/error rate by operation.
- User comprehension: can a reviewer explain the held amount correctly?

Do not optimize toward fewer manual reviews at the expense of safety.
