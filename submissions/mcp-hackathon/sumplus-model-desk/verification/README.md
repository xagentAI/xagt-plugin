# Verification evidence

Every response below was captured from the deployed service at `2026-09-16T19:14:01.003Z`. Price
figures move as the upstream catalogue moves, so a reviewer running these later will see
different numbers in the same shape. The `snapshotId` and `pricedAt` fields in each
response say which read the numbers came from.

## Prerequisites

- Review commit: `08b2edf8b5e14ac6702e2a27d56b36a5ce578a19`
- API base URL: https://sumplus-model-desk-production.up.railway.app/v1
- Authentication: none. No key, header, or account is required for any call here.

## 1. Health check

```bash
curl --fail --silent --show-error https://sumplus-model-desk-production.up.railway.app/health
```

Captured response:

```json
{
  "status": "ok",
  "commit": "08b2edf8b5e14ac6702e2a27d56b36a5ce578a19",
  "slug": "sumplus-model-desk",
  "catalogue": {
    "snapshotId": "c4675be6df4d0a9bf65d8c70eb3e2a37f5509bf0d22b42b8ea17382316fab64b",
    "pricedAt": "2026-09-16T19:12:49.759Z",
    "staleSeconds": 111,
    "offers": 93,
    "cacheAgeSeconds": 111,
    "refreshCount": 1,
    "servingShippedSnapshot": false,
    "lastRefreshAttemptAt": "2026-09-16T19:12:49.761Z",
    "lastRefreshError": null
  }
}
```

`commit` must equal the review commit above.

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://sumplus-model-desk-production.up.railway.app/.well-known/xagent-verification.json
```

Captured response:

```json
{
  "schemaVersion": 1,
  "slug": "sumplus-model-desk",
  "commit": "08b2edf8b5e14ac6702e2a27d56b36a5ce578a19"
}
```

## 3. Capability call

A job with a 200,000 token prompt that needs 30,000 tokens of output. Many offers in the
catalogue cannot serve it, and the ones that can differ in price.

```bash
curl --fail --silent --show-error \
  --request POST https://sumplus-model-desk-production.up.railway.app/v1/plan_call \
  --header "content-type: application/json" \
  --data '{"inputTokens":200000,"outputTokens":30000}'
```

Captured response, truncated to the first entries of each list:

```json
{
  "request": {
    "inputTokens": 200000,
    "outputTokens": 30000
  },
  "eligible": [
    {
      "modelId": "gemini-2.5-flash-lite",
      "name": "gemini-2.5-flash-lite [M]",
      "line": "mixai",
      "lineCode": "M",
      "inputCost": {
        "microUsd": 20000,
        "display": "$0.02"
      },
      "outputCost": {
        "microUsd": 12000,
        "display": "$0.012"
      },
      "totalCost": {
        "microUsd": 32000,
        "display": "$0.032"
      },
      "context": 1000000,
      "maxOutput": 65536,
      "availability": "live"
    },
    {
      "modelId": "deepseek-v4-flash",
      "name": "deepseek-v4-flash-0731 [C]",
      "line": "cm",
      "lineCode": "C",
      "inputCost": {
        "microUsd": 28000,
        "display": "$0.028"
      },
      "outputCost": {
        "microUsd": 8400,
        "display": "$0.0084"
      },
      "totalCost": {
        "microUsd": 36400,
        "display": "$0.0364"
      },
      "context": 1000000,
      "maxOutput": 384000,
      "availability": "live"
    }
  ],
  "rejected": [
    {
      "modelId": "glm-5.1",
      "line": "nube",
      "lineCode": "N",
      "reason": "Its context window holds 128000 tokens, and this job needs 230000 for the prompt plus its answer.",
      "bindingConstraint": "context",
      "requiredValue": 230000,
      "actualValue": 128000
    },
    {
      "modelId": "glm-5.2",
      "line": "nube",
      "lineCode": "N",
      "reason": "Its context window holds 128000 tokens, and this job needs 230000 for the prompt plus its answer.",
      "bindingConstraint": "context",
      "requiredValue": 230000,
      "actualValue": 128000
    }
  ],
  "eligibleCount": 47,
  "rejectedCount": 46,
  "truncated": false,
  "omittedCount": 0,
  "snapshotId": "c4675be6df4d0a9bf65d8c70eb3e2a37f5509bf0d22b42b8ea17382316fab64b",
  "pricedAt": "2026-09-16T19:12:49.759Z",
  "staleSeconds": 111,
  "eligible_truncated": "45 more entries omitted from this document; the live call returns all 47",
  "rejected_truncated": "44 more entries omitted from this document; the live call returns all 46"
}
```

Read it as: `eligible` is every offer that can actually serve this job, priced for this
job, cheapest first. `rejected` is every offer that cannot, each naming the constraint
that ruled it out, the value it has, and the value it would need. `staleSeconds` says
how long ago the catalogue was read.

## 4. The same id, more than one offer

```bash
curl --fail --silent --show-error "https://sumplus-model-desk-production.up.railway.app/v1/resolve?modelId=claude-opus-4-8"
```

Captured response:

```json
{
  "modelId": "claude-opus-4-8",
  "offerCount": 3,
  "offers": [
    {
      "line": "mixai",
      "lineCode": "M",
      "inputPerMillion": "$5.00",
      "outputPerMillion": "$25.00",
      "context": 200000,
      "maxOutput": 64000,
      "availability": "live"
    },
    {
      "line": "arklin",
      "lineCode": "A",
      "inputPerMillion": "$5.00",
      "outputPerMillion": "$25.00",
      "context": 200000,
      "maxOutput": 64000,
      "availability": "live"
    },
    {
      "line": "jinwang",
      "lineCode": "J",
      "inputPerMillion": "$15.00",
      "outputPerMillion": "$75.00",
      "context": 200000,
      "maxOutput": 64000,
      "availability": "live"
    }
  ],
  "spread": "3x",
  "snapshotId": "c4675be6df4d0a9bf65d8c70eb3e2a37f5509bf0d22b42b8ea17382316fab64b",
  "pricedAt": "2026-09-16T19:12:49.759Z",
  "staleSeconds": 112
}
```

This is the case the capability exists for. One id, several offers, different prices.

## 5. Safe failure: no offer can serve the job

```bash
curl --silent --show-error \
  --request POST https://sumplus-model-desk-production.up.railway.app/v1/plan_call \
  --header "content-type: application/json" \
  --data '{"inputTokens":5000000,"outputTokens":900000}'
```

Captured response:

```json
{
  "error": "invalid_token_counts",
  "message": "inputTokens is 5000000, above the ceiling of 2000000 this desk will price.",
  "field": "inputTokens",
  "received": 5000000,
  "maximum": 2000000
}
```

The service names the binding constraint and the value that would make the job
servable, rather than returning an empty list.

## 6. Safe failure: unknown id

```bash
curl --silent --show-error "https://sumplus-model-desk-production.up.railway.app/v1/resolve?modelId=gpt-nonexistent-9"
```

Captured response:

```json
{
  "error": "unknown_model",
  "message": "No offer in this catalogue carries the id gpt-nonexistent-9.",
  "requested": "gpt-nonexistent-9",
  "nearest": [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5-mini"
  ],
  "closestIds": [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5-mini"
  ],
  "staleSeconds": 113
}
```

## 7. Safe failure: invalid token counts

```bash
curl --silent --show-error \
  --request POST https://sumplus-model-desk-production.up.railway.app/v1/plan_call \
  --header "content-type: application/json" \
  --data '{"inputTokens":-1,"outputTokens":10}'
```

Captured response:

```json
{
  "error": "invalid_token_counts",
  "message": "inputTokens must be a whole number of tokens, zero or more.",
  "field": "inputTokens",
  "received": -1
}
```

## 8. Check the arithmetic without the network

```bash
cd source
npm ci
node verify.mjs snapshots/08b2edf8b5e14ac6702e2a27d56b36a5ce578a19.json
```

This recomputes every figure from the committed snapshot and compares it against the
values the service returns for the same inputs. It makes no network calls, so a
reviewer can confirm the arithmetic without trusting the running service.

## 9. What changed since the review commit

```bash
curl --fail --silent --show-error https://sumplus-model-desk-production.up.railway.app/v1/catalogue/diff
```

Returns the difference between the snapshot committed at `08b2edf8b5e14ac6702e2a27d56b36a5ce578a19` and the catalogue
as read now: offers added, offers removed, and prices or limits that moved. A reviewer
opening this during the review window sees what the intervening days produced, which is
how the service shows it reads live data rather than a fixture.

This compares two reads of the same upstream. It shows the catalogue moves and that the
service tracks it. It does not on its own establish that any individual price is
correct.

## 10. Tool contract

```bash
curl --fail --silent --show-error https://sumplus-model-desk-production.up.railway.app/v1/tools.json
```

Returns each tool with its input schema, output schema, named errors, limits, and
side effects. Every tool in this service is read-only and has no side effects.
