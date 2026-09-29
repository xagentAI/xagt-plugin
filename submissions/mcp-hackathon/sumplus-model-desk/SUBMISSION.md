# Sumplus Model Desk

An agent about to run a job has to answer two questions before it spends anything:
which offer can actually do this job, and what will this job cost. Model Desk answers
both from the live catalogue and returns the decision, including the offers it ruled
out and the constraint that ruled each one out.

**Track:** General Challenge (Open Innovation)

## The problem

A model id is not an offer.

In a real routing catalogue the same id is served by several upstream lines, at
different prices and different limits. Asking for `claude-opus-4-8` does not say
which one you get: in the catalogue behind this service, read at 2026-09-16T19:14:01.003Z, that
id resolves to 3 offers whose input price spans 3.0x.
16 of the 72 distinct ids carry more than one offer.
Those counts move as the catalogue moves; `resolve` returns the current state.

The second half fails silently. An offer whose context window or maximum output is too
small for the job does not refuse the job. It truncates the answer, and the caller
finds out after paying for it.

Neither question can be answered from a language model's own knowledge. Catalogue
prices and limits move week to week, and a model's internal picture of them is a
snapshot from training time. Every figure this service returns is read from the live
catalogue and carries the time it was read.

This shape is not particular to one catalogue. Any aggregator, router, or capability
marketplace ends up with the same structure: one name, several providers behind it,
different prices and different limits, and a caller who names the capability rather than
the offer. The catalogue read here is one instance of it, and the service is written
against the shape rather than against the instance. A different catalogue is a different
reader; `plan_call`, `quote`, and `resolve` do not change.

## Capability

- **One-line description:** Given a job in tokens and its requirements, return the
  offers that can serve it, priced for that exact job and ranked by cost, together with
  the offers that cannot and the constraint that rules each one out.
- **Who it helps:** An agent or orchestrator choosing where to send a call, and the
  person who pays for that call.
- **Capability boundary:** It reads a public model catalogue and computes costs from
  the caller's token counts. It does not run inference, move money, hold funds, or
  execute the call. It is procurement and pricing. It does not inspect wallets,
  transactions, contracts, or security posture, and produces no risk assessment.
- **What it declines to put in front of you:** offers that are not priced per token are
  refused by name rather than quoted at zero; offers still in preview are left out
  unless the caller asks for them; and an offer the catalogue lists at zero is returned
  marked as listed at zero, not described as free.

### Tools

| Tool | Endpoint | Input | Output | Named errors |
|---|---|---|---|---|
| `plan_call` | POST /v1/plan_call | `inputTokens`, `outputTokens`, `minContext`?, `minMaxOutput`?, `requireLines`?, `excludeLines`?, `baselineModelId`?, `includePreview`?, `limit`? | `eligible` Offers that can take the job, cheapest first: modelId, line, lineCode, inputCost, outputCost, totalCost, context, maxOutput, availability; `rejected` Offers that cannot, each with reason, bindingConstraint, requiredValue, actualValue. bindingConstraint is one of context, max_output, min_context, min_max_output, line, availability, not_token_priced; `listedAtZero` Set on a row the catalogue prices at zero. It reports what the catalogue says and makes no claim that the call is free: a zero price and an unfilled price are the same value in that field; `truncated` True when rows were cut by limit. eligibleCount is always the real total; `savingsVsBaseline` Present when baselineModelId was given. Carries baselineIneligible when the id you had in mind cannot take this job; `snapshotId` Content address of the catalogue these numbers came from; `pricedAt` When that catalogue was read; `staleSeconds` How old it is | `invalid_token_counts`, `unknown_model`, `no_offer_meets_requirements`, `catalogue_unavailable`, `rate_limited` |
| `quote` | POST /v1/quote | `modelId`, `line`?, `inputTokens`, `outputTokens`, `cachedInputTokens`? | quotes[], cheapest first, each with input, output, cached and total cost. | `unknown_model`, `invalid_token_counts` |
| `resolve` | GET /v1/resolve?modelId=<id> | `modelId` | offers[] sorted by input price, plus spread as a multiple. | `unknown_model` |
| `catalogue` | GET /v1/catalogue?line=&minContext=&limit= | `line`?, `minContext`?, `limit`? | offers[], totalOffers, uniqueModelIds, snapshotId, pricedAt, staleSeconds. | `catalogue_unavailable`, `rate_limited` |
| `catalogue_diff` | GET /v1/catalogue/diff | none | added, removed, repriced, rewindowed, and counts. | `catalogue_unavailable`, `rate_limited` |

This table is generated from the live `https://sumplus-model-desk-production.up.railway.app/v1/tools.json`, which carries the full
schemas, shared limits, authentication, and side effects for every tool.

Costs round up and savings round down. A quote is never lower than the arithmetic it
came from.

## Live API

- **API base URL:** https://sumplus-model-desk-production.up.railway.app/v1
- **Health-check URL:** https://sumplus-model-desk-production.up.railway.app/health
- **Deployment proof:** https://sumplus-model-desk-production.up.railway.app/.well-known/xagent-verification.json
- **Authentication:** none. No key is needed to exercise any endpoint.
- **Rate limits:** 60 requests per minute per address. `inputTokens` and `outputTokens`
  accept up to 2,000,000 each. A listing returns at most 50 rows. Requests time out at
  30 seconds.
- **API contract:** `source/openapi.json`, and `https://sumplus-model-desk-production.up.railway.app/v1/tools.json` on the live
  service.

## Source and reproducibility

- **Source repository:** https://github.com/sumplus-real/sumplus-model-desk
- **Review commit:** `08b2edf8b5e14ac6702e2a27d56b36a5ce578a19`
- **Source submitted in this PR:** `source/`
- **Run tests:** `npm ci && npm test`
- **Run locally:** `REVIEW_COMMIT=08b2edf8b5e14ac6702e2a27d56b36a5ce578a19 npm start` (listens on `$PORT`, default 8080)
- **Deploy:** any container or Node host. The deployed instance sets `REVIEW_COMMIT`
  to the commit above and nothing else.
- **Version binding:** `/health` and `/.well-known/xagent-verification.json` both report
  `REVIEW_COMMIT`. They are served from the same origin as the API.

```json
// GET https://sumplus-model-desk-production.up.railway.app/health
{"status":"ok","commit":"08b2edf8b5e14ac6702e2a27d56b36a5ce578a19"}
```

```json
// GET https://sumplus-model-desk-production.up.railway.app/.well-known/xagent-verification.json
{"schemaVersion":1,"slug":"sumplus-model-desk","commit":"08b2edf8b5e14ac6702e2a27d56b36a5ce578a19"}
```

## Verification

Runnable calls and expected responses are in `verification/README.md`. Three of them
are worth naming here.

**Determinism.** Every response carries a `snapshotId`. The repository ships
`verify.mjs`, which recomputes every figure in a response from the matching snapshot
with no network access. A reviewer who does not want to trust the live service can
check the arithmetic offline and get the same numbers.

**Movement over time.** The catalogue snapshot taken at the review commit is committed
to the repository. `GET https://sumplus-model-desk-production.up.railway.app/v1/catalogue/diff` returns what changed between that
snapshot and the catalogue now. A reviewer opening it during the review window sees the
difference the intervening days produced. This shows the service reads live data. It
does not on its own establish that any individual price is correct, because the
snapshot and the live read come from the same upstream.

**Failure behaviour.** A job no offer can serve returns `no_offer_meets_requirements`
naming the binding constraint and the value that would unblock it, not an empty list.
An unknown id returns `unknown_model` with the nearest ids. An out-of-range token count
returns `invalid_token_counts`.

## Security and data handling

- **Data collected:** none. Inputs are token counts and filter values.
- **Purpose and retention:** requests are not stored. The only persisted state is the
  cached catalogue and the committed snapshot.
- **Third parties / outbound network calls:** one, a scheduled read of the public
  catalogue at `https://router.sumplus.xyz/v1/models`. A reviewer's request never
  reaches it.
- **Secrets:** none are committed and none are required. The service holds no
  credentials.
- **Known risks / restrictions:** figures are as fresh as `staleSeconds` says. If the
  upstream is unreachable the service answers from cache and marks the answer stale
  rather than failing.

The upstream gateway publishes an attestation of its own build at
`https://router.sumplus.xyz/attestation` and anchors it to Sigstore Rekor. That is
context for where these figures come from. The `models_digest` field in that
attestation covers the gateway's internal model configuration and is not recomputable
from the public catalogue, so it does not verify the price list this service returns,
and nothing here claims that it does.

## Operating during the review window

The service holds the catalogue in its own cache and refreshes it on a schedule, so a
reviewer's call never reaches the upstream gateway. There is no key to expire, no
balance to drain, and no per-call cost. How often reviewers exercise it does not change
what it costs to keep running.

## Reuse disclosure

Sumplus has entered other events with other projects. Model Desk is new code written
for this event. It reads the same public Sumplus endpoint those projects read, and
shares no implementation with them.

## Support

- **Team / builder:** Jakob, Sumplus
- **Contact:** j@sumplus.xyz
- **License / rights:** MIT. The submitter can authorize review and deployment; see
  `RIGHTS.md`.
