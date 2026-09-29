# Pricing Draft

Status: local_pricing_hypothesis
Service: Agent Deliverable Auditor

## Pricing principle

Price the call by buyer risk and output depth, not by token count.

The buyer is paying to reduce acceptance risk: should they accept the Agent delivery, ask for more proof, or escalate?

## Tier 1: Quick Acceptance Check

Candidate price: `$0.05 - $0.25` per call

Use case:

- small writeback;
- one artifact;
- narrow task;
- buyer needs quick accept / needs-review / fail verdict.

Output:

- verdict;
- score;
- missing evidence;
- top risks;
- next gate.

Limit:

- no deep dispute notes;
- no line-level code review.

## Tier 2: Full Delivery Audit

Candidate price: `$0.50 - $2.00` per call

Use case:

- repo or website delivery;
- multiple files or artifacts;
- validation/deploy gates matter;
- buyer needs a structured acceptance packet.

Output:

- full dimension scores;
- positive evidence;
- missing evidence;
- risks;
- questions for seller;
- buyer summary;
- evaluator notes.

## Tier 3: Evaluator Support Packet

Candidate price: `$2.00 - $8.00` per call

Use case:

- dispute preparation;
- higher-value task;
- evaluator wants a structured fact map before voting.

Output:

- full audit;
- acceptance criteria map;
- dispute notes;
- seller/buyer position split;
- recommended evidence requests.

## Do not sell yet

Do not sell subscriptions, enterprise plans, or managed QA until the per-call product proves demand.

Do not include wallet, payment, credential, deploy, or staking setup in the first offer.

## First live pricing recommendation

If OKX.AI listing reaches hard-gate approval later:

- start with one A2MCP endpoint;
- choose Tier 1 or Tier 2 only;
- avoid Tier 3 until dispute demand is visible;
- cap the description to delivery acceptance, not broad security or legal judgment.

