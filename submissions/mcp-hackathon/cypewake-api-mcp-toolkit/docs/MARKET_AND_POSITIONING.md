# Market and positioning

Why this problem is worth solving, who it helps, who else is working on it, and where MCPForge differs.

## Why now

| Signal | Implication |
|---|---|
| Anthropic introduced MCP in Nov 2024; by mid-2026 it is the de facto wiring standard between agents and production APIs | The protocol layer has settled. This is not a passing trend. |
| A traditional custom REST integration takes 2–8 weeks per system; the MCP path takes 2–4 hours | 5–10x faster per integration |
| M models × N data sources means M×N bespoke connectors; a common middle layer reduces that to M+N | Value compounds with the number of systems |
| Gartner expects 75% of API gateway vendors and 50% of iPaaS to support MCP natively by end of 2026, and >60% of AI systems to integrate APIs through MCP-style protocols by 2027 | High market certainty, and the window is open now |
| Enterprises report $150k+ saved per integration cycle and 70–80% less maintenance effort on mature deployments | The savings are concrete |

## Who it helps

| Audience | What changes |
|---|---|
| Agent developers, indie devs, small teams | Days of wiring becomes minutes to a deployable server |
| Platform, architecture, and internal-tooling teams | One factory, reused everywhere; an update propagates to every consumer |
| API product teams and DevRel | Ship an agent-ready MCP surface and raise adoption |
| Reviewers, ops, and compliance | Real call evidence, auditable metering, per-hop SSRF protection |

## The problem underneath: tool explosion

Loading GitHub + Slack + Sentry servers consumes 72% of a 200k token budget, and the MCP-Atlas benchmark attributes 36% of agent failures to the agent calling no tool at all. Exporting a 100-endpoint spec as 100 tools makes both worse.

Curation is MCPForge's answer: filter by tag, method, path, or semantic intent before generating. On Swagger Petstore, `{"include_tags":["pet"],"include_methods":["GET"]}` cuts 19 endpoints to 3 tools (84%), and `{"intent":"user order","top_n":5}` gives 5 tools (74%).

## Competitive landscape

The space is crowded. Being honest about that matters more than pretending otherwise.

| Competitor | Form | Strength relative to this entry |
|---|---|---|
| Speakeasy | Hosted multi-language generation | Better funded, enterprise-grade, has `x-speakeasy-mcp` curation |
| Gram (Speakeasy) | Fully hosted MCP service | 600 interfaces → 5–30 curated tools, sub-second cold start, OAuth 2.1 + DCR |
| liblab | Hosted MCP service | Zero-step deployment, 100 free calls/month |
| openapi-mcp-generator | Open-source TypeScript CLI (~630 stars) | Active community, full Node project, Zod + OAuth2 |
| AWS Labs openapi-mcp-server | Open-source Python runtime proxy | Dynamic tool generation, 70–75% token reduction |
| FastMCP | Python framework | The foundation MCPForge is built on |

## Where this entry actually differs

Curation is table stakes — Speakeasy and Gram both ship it. The difference is that the last two stages are real rather than decorative.

| Stage | What MCPForge does | Common state elsewhere |
|---|---|---|
| Build | OpenAPI spec → persisted registry | Comparable |
| Verify | Only real HTTP 2xx counts as a pass; 401/403/404/429/5xx classified separately | "Got a response, therefore callable" — the metric is always true and means nothing |
| MCPize | Generates callable tools with per-hop SSRF validation (`request_with_validated_redirects`) | Usually direct connect, exposed to redirect bypass |
| Monetize | Real per-call metering (atomic `usage.json`), tiered invoices, listing payload | Largely empty |

The showcase API matters too. Petstore proves the plumbing; the GitHub public REST API proves the tools do work an agent would actually want, and it needs no key.

## Monetization context

Per-call payment for agents is already running in production: the x402 ecosystem reports 165M+ transactions, $50M+ settled, and 480k+ agents, with Coinbase contributing and Linux Foundation governance, plus backing from Google, Microsoft, AWS, Visa, Stripe, and Circle. MCPForge meters in USD against that model and takes no position in any token.

## After the hackathon

Ranked by what unblocks real use first:

1. **Auth on the hosted demo** — currently keyless by design for the review window.
2. **Persistent metering store** — move `usage.json` to a real database so billing survives restarts.
3. **Hosted curation UI** — the filter builder exists in the walkthrough page; make it a product surface.
4. **More spec sources** — gRPC reflection, GraphQL introspection, Postman collections.
5. **Real x402 settlement** — replace the simulated invoice with an actual payment handshake.

## Open questions

- Scoring weights are not public, so differentiation is argued from the stated criteria, not from a guaranteed outcome.
- Reviewer preference for the four-stage framing is an assumption; it matches the official theme but is unconfirmed by feedback.
