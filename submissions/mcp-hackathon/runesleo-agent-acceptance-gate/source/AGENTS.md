# Agent Instructions

Default communication: Chinese.

## Scope

This repo is a local-only prototype for `Agent Acceptance Gate`.

It should stay agent-first and human-readable:

- agents call the API/tool;
- humans review the result and authorize next gates.

## Allowed local work

- Edit source, docs, schemas, discovery metadata, demo files, and tests.
- Run `npm test`.
- Run `npm run serve` locally.
- Add more sample inputs/outputs from public-safe or local worker writebacks.

## Hard gates

Do not do these without explicit Leo approval:

- push to any remote;
- create public GitHub repo or change repo visibility;
- deploy a public endpoint;
- submit OKX.AI ASP listing;
- connect OKX Agentic Wallet, API credentials, wallet address, x402, or payment middleware;
- publish to leolabs / X as official launch;
- claim legal, investment, smart-contract security, or guaranteed correctness.

## Product boundary

This is not an observability platform, full code review tool, security auditor, wallet tool, or general AI evaluation framework.

Primary positioning:

```text
Can this agent delivery be accepted?
```
