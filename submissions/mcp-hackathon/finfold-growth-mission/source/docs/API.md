# API and MCP contract

## Authentication and idempotency

All mission and usage endpoints require `Authorization: Bearer <key>`. Required scopes are documented per route. `POST` routes also require an `Idempotency-Key` of 8–128 safe characters.

Reusing a key with the same normalized request returns the original status and body with `Idempotent-Replayed: true`. Reusing it with a different request returns `409 IDEMPOTENCY_CONFLICT`. A concurrent duplicate returns `409 REQUEST_IN_PROGRESS` and is safe to retry later with the same key.

## Typed source errors

| Code | Meaning | Retry? |
|---|---|---|
| `SOURCE_URL_BLOCKED` | URL, network target, port, or redirect violates policy | No |
| `SOURCE_FETCH_FAILED` | Timeout, upstream failure, redirect problem, or non-2xx source | Sometimes |
| `SOURCE_TOO_LARGE` | Response exceeds the streaming byte limit | No |
| `SOURCE_INVALID_MIME` | Source is not public HTML/XHTML | No |
| `SOURCE_NEEDS_RENDERING` | Page is a thin JavaScript shell | No; provide a server-rendered page |
| `INSUFFICIENT_EVIDENCE` | Static page lacks enough semantic evidence | No; provide a richer page |
| `EVIDENCE_VALIDATION_FAILED` | Generated quote is not an exact section substring | No content is delivered |
| `QUALITY_VALIDATION_FAILED` | Objective/platform/CTA/length/number/guarantee gate failed | No content is delivered |

Every error includes `code`, `message`, `retryable`, and `requestId`.

## MCP tools

| Tool | Scope | Mutation | External side effects | Retry rule |
|---|---|---|---|---|
| `finfold_create_growth_mission` | `mission:create` | Persists one mission | Fetches public source and calls configured model; never publishes | Same `idempotencyKey` |
| `finfold_get_growth_mission` | `mission:read` | None | None | Freely repeatable |
| `finfold_record_growth_outcome` | `outcome:write` | Persists one event | None | Same `eventId` and `idempotencyKey` |

MCP client transport URL: `https://api.finfold.app/mcp`. Send the review key as a Bearer Authorization header. The transport is stateless; no session cookie or server-held client session is required.

The complete machine-readable HTTP contract is available at `/openapi.json`.
