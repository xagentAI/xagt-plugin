# PROJECT SSOT

Project: Agent Acceptance Gate
Chinese name: Agent 验收门禁
Status: local_repo_private_static_demo_public
Owner thread: product_distribution / cmd5
Created: 2026-07-02

## Purpose

Agent-first, human-readable acceptance gate for AI agent deliveries.

The service is designed for an agent marketplace flow:

```text
Seller Agent finishes work
Buyer Agent / Seller Agent / Evaluator Agent calls audit_agent_delivery
Service returns pass / needs_review / fail
Human reviews result and authorizes next gate
```

## Current state

Runnable prototype with public static demo:

- deterministic audit engine;
- CLI;
- local HTTP API;
- buyer-facing demo;
- OpenAPI draft;
- MCP-style tool manifest;
- agent discovery metadata;
- launch/billing drafts;
- public static demo at https://agent-acceptance-gate.pages.dev/.

## Not launched

The project is not:

- submitted to OKX.AI;
- connected to wallet/payment middleware;
- connected to API keys or credentials;
- pushed to GitHub;
- published on leolabs.

Only `demo/index.html` is publicly deployed as a static Cloudflare Pages demo.

## Hard gates

Require explicit Leo approval before:

- creating a public GitHub repo or changing visibility;
- adding remote origin / pushing;
- deploying public endpoint;
- OKX.AI Agentic Wallet login or ASP listing;
- adding wallet address / payment middleware / x402 / OKX Payment SDK;
- publishing leolabs or X announcement as an official launch;
- claiming security, legal, investment, or smart-contract audit coverage.

## Validation

Current local validation:

```bash
npm test
```

Expected:

```text
PASS 5/5 sample audit cases
PASS http smoke
```
