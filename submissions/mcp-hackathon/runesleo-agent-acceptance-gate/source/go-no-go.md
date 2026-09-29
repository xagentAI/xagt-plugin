# Go / No-Go

Status: local_decision_packet

## Current decision

Go for local prototype and demo.

No-go for OKX.AI production launch today.

## Why local prototype is worth doing

- The buyer problem is real in any agent marketplace: accepting an Agent delivery requires evidence review.
- The service can be expressed as one sentence.
- The output can be structured, scored, and priced per call.
- Leo already has historical writebacks that expose the exact failure modes: deferred validation, hard gates, dirty state, writer locks, rollback, and unclear release gates.
- A2MCP is a better fit than A2A because the service is repeatable.

## Why production launch is not approved yet

- No public endpoint exists.
- Demand inside OKX.AI is unproven.
- Marketplace listing requires account / Agentic Wallet / endpoint / pricing decisions.
- Live monetization needs wallet/payment setup and likely OKX production configuration.
- The local package is a spec and sample set, not an executable service yet.

## Go criteria for next step

Proceed to a local executable prototype only if:

1. The five sample outputs feel useful enough that Leo would use one before accepting a worker delivery.
2. The schema does not need free-form negotiation to make sense.
3. The service catches at least three meaningful risks across the sample set.
4. The product remains narrow: delivery acceptance audit, not general consulting.

## No-go / kill criteria

Stop or park if:

- the output feels like generic prose instead of a decision aid;
- buyers would still need the same amount of manual review after using it;
- the service cannot distinguish `task failed safely` from `agent failed the task`;
- OKX.AI demand appears too thin after marketplace observation;
- production launch would require paid resources or wallet actions before demand proof.

## Next recommended build

Build a local CLI or MCP stub that:

```text
input: sample-inputs/*.json
output: sample-outputs/*.json-shaped verdict
```

First implementation can be deterministic plus LLM-assisted later. The immediate goal is not model quality; it is product usefulness and repeatable output shape.

## Hard gates still closed

- OKX account / Agentic Wallet login;
- API key / credential setup;
- receiving wallet address;
- wallet funding / signing / transaction / staking;
- public endpoint deploy;
- ASP listing submission;
- website publication;
- repo commit / push / deploy.

