# MCP interface specification

## Goal

Expose Docket as a real agent capability while preserving the same domain rules as the HTTP API and web application.

An agent should be able to create an agreement, submit evidence, request an AI review, receive a proportional settlement recommendation, inspect the case, and challenge a finding without gaining payment authority.

## Protocol and SDK

- Use the stable v2 official TypeScript MCP packages and pin exact versions in `package-lock.json`.
- Remote transport: stateless Streamable HTTP at `/mcp` using the official server factory/handler API.
- Local transport: stdio through a dedicated entrypoint.
- Client tests: official MCP client package over in-memory transport, stdio, and Streamable HTTP.
- Let the official SDK negotiate supported protocol eras. Do not implement handshakes manually.
- Use structured tool output and concise text content.

Relevant official references:

- https://github.com/modelcontextprotocol/typescript-sdk/blob/main/docs/server.md
- https://github.com/modelcontextprotocol/typescript-sdk/blob/main/docs/serving/http.md
- https://github.com/modelcontextprotocol/typescript-sdk/blob/main/docs/serving/authorization.md
- https://github.com/modelcontextprotocol/typescript-sdk/blob/main/docs/clients/connect.md

## Server identity

```json
{
  "name": "docket",
  "version": "1.0.0"
}
```

Server instructions must state:

- Docket recommends proportional settlements.
- It does not move funds.
- Agreement activation freezes financial criteria.
- Evidence and AI findings may be incomplete or disputed.
- Manual-review responses are valid outcomes, not transport errors.

## Tool design principles

- One tool equals one meaningful user intent.
- Tool handlers call application services; they do not contain domain logic.
- Descriptions must state material side effects.
- Mutating tools require `idempotencyKey`.
- Every persistent object includes tenant-scoped identifiers and a version.
- Responses include `requestId`, object version, and next valid actions.
- Errors distinguish invalid input, unauthorized access, state conflict, retryable failure, and valid manual-review outcomes.
- No argument accepts credentials, private keys, seed phrases, or transaction signatures.

## Initial tool surface

### `docket_draft_agreement`

Purpose: convert a task brief into an editable proposed agreement.

Side effect: creates a draft only when persistence is enabled; never activates it.

Input:

```json
{
  "taskBrief": "string",
  "amountAtomic": 250000000,
  "asset": { "symbol": "USDC", "decimals": 6 },
  "constraints": ["string"],
  "idempotencyKey": "string"
}
```

Output includes proposed criteria, weights, evidence requirements, critical flags, ambiguities, and `status: draft`. It must clearly say that human/party approval is required.

Required scope: `docket:agreements:write`.

### `docket_validate_agreement`

Purpose: deterministically validate a proposed agreement without persistence or AI.

Input: complete agreement object.

Output:

- `valid`;
- normalized agreement;
- validation issues;
- atomic allocation per criterion;
- total weight and reconciliation result.

Required scope: `docket:agreements:read` or anonymous sandbox.

### `docket_activate_agreement`

Purpose: freeze an approved agreement version.

Side effect: persistent and immutable; requires idempotency and expected draft version.

Input:

- agreement ID;
- expected version;
- approval attestations or configured approval reference;
- idempotency key.

Output includes activated version, digest, state, and next actions.

Required scope: `docket:agreements:activate`.

### `docket_submit_evidence`

Purpose: attach evidence metadata and bounded allowed content to one criterion.

Side effect: persistent; requires idempotency.

Input:

- case ID and expected version;
- criterion ID;
- evidence kind;
- digest;
- source label/URI;
- optional bounded text content;
- data classification and provider-sharing consent;
- idempotency key.

Output includes evidence ID, accepted content size, digest, case version, missing evidence, and next actions.

Required scope: `docket:evidence:write`.

### `docket_review_case`

Purpose: run AI review over evidence for eligible criteria.

Side effect: creates a review run and findings; requires idempotency.

Input:

- case ID and expected version;
- optional criterion IDs;
- review policy reference;
- idempotency key.

Output includes review status, structured findings, gaps, conflicts, provider provenance safe for the caller, and whether the case is ready to resolve.

If asynchronous execution is required, return an operation ID and expose status through `docket_get_case`; do not hold a request indefinitely.

Required scope: `docket:reviews:run`.

### `docket_resolve_case`

Purpose: calculate the proportional settlement from the frozen agreement and accepted findings.

Side effect: stores a versioned recommendation when persistence is enabled; it never moves funds.

Input:

- case ID and expected version, or a complete stateless agreement/findings package in sandbox mode;
- idempotency key for persistent mode.

Output:

```json
{
  "decision": "release_partial",
  "asset": { "symbol": "USDC", "decimals": 6 },
  "amountAtomic": 250000000,
  "recommendedReleaseAtomic": 230000000,
  "recommendedHoldAtomic": 20000000,
  "settlementRatioBps": 9200,
  "requiresHumanReview": false,
  "criteria": [],
  "reasonCodes": [],
  "recommendationOnly": true,
  "fundsMoved": false
}
```

Required scope: `docket:settlements:recommend` or anonymous sandbox with strict limits.

### `docket_challenge_finding`

Purpose: challenge one accepted finding with a reason and optional new evidence references.

Side effect: persistent; opens a challenge and may require a new review. It never edits the original finding.

Input:

- case ID, finding ID, expected version;
- challenge rationale;
- evidence IDs;
- idempotency key.

Output includes challenge ID, case state, required next action, and whether the current recommendation is superseded.

Required scope: `docket:challenges:write`.

### `docket_get_case`

Purpose: return the caller-authorized case snapshot and next valid actions.

Input: case ID and optional projection fields.

Output includes agreement version, case state/version, evidence summary, review summary, current recommendation, supersession status, and provenance links.

Required scope: `docket:cases:read`.

### `docket_export_recommendation`

Purpose: return an unsigned, machine-readable recommendation artifact.

The artifact includes digests and provenance but never a transaction, signature request, wallet credential, or execution command.

Required scope: `docket:settlements:export`.

## Hackathon minimum tool set

If delivery time is constrained, the minimum credible MCP slice is:

1. `docket_validate_agreement`
2. `docket_review_case` in stateless fixture mode
3. `docket_resolve_case` in stateless mode
4. `docket_get_case` for the demo case

The demo must use a real SDK client and must not describe unavailable persistent behavior.

## Resources

Resources are read-only and authorization-scoped.

Suggested URIs:

- `docket://cases/{caseId}` — current case summary
- `docket://cases/{caseId}/agreement` — frozen agreement version
- `docket://cases/{caseId}/evidence` — evidence metadata, not unrestricted private bodies
- `docket://cases/{caseId}/reviews/{reviewRunId}` — findings and provenance
- `docket://cases/{caseId}/evaluations/{evaluationId}` — criterion ledger and recommendation

Do not make tenant case resources listable across principals. Resource templates must authorize before resolving content.

## Prompt templates

Optional MCP prompts may guide hosts through:

- drafting a fair acceptance contract;
- preparing evidence for review;
- explaining a proportional recommendation;
- challenging a criterion finding.

Prompts do not replace tool validation or permissions.

## Structured tool result

Every successful tool call returns:

- `structuredContent` matching its output schema;
- short text content summarizing the outcome for model readability;
- resource links where useful;
- `_meta` only for non-sensitive operational context allowed by the protocol.

Text content must not be the only copy of financial fields.

## Error taxonomy

| Code | Meaning | Retry |
| --- | --- | --- |
| `INVALID_ARGUMENT` | Input failed schema or domain validation | Fix input |
| `UNAUTHENTICATED` | Missing or invalid token | Reauthorize |
| `PERMISSION_DENIED` | Principal lacks tenant/scope access | Do not retry unchanged |
| `NOT_FOUND` | Authorized object does not exist | Do not retry unchanged |
| `VERSION_CONFLICT` | Expected case version is stale | Reload and reconcile |
| `IDEMPOTENCY_CONFLICT` | Key was reused with different input | Use original result or a new key |
| `INVALID_STATE` | Operation is not allowed in current state | Follow next actions |
| `EVIDENCE_REQUIRED` | Case lacks required evidence | Submit evidence |
| `CLARIFICATION_REQUIRED` | Review cannot safely score | Supply requested clarification |
| `MANUAL_REVIEW_REQUIRED` | Conflict or policy gate blocks recommendation | Escalate |
| `AI_PROVIDER_UNAVAILABLE` | Upstream provider failed after bounded retry | Retry later/manual review |
| `RATE_LIMITED` | Tenant or provider limit reached | Respect retry time |
| `INTERNAL_ERROR` | Unexpected safe server failure | Retry only if marked retryable |

Manual review is normally a successful structured case outcome, not a protocol error.

## Authentication and authorization

Production remote MCP acts as an OAuth resource server:

- verify bearer access tokens before `/mcp`;
- publish protected-resource metadata;
- validate issuer, audience/resource, expiry, and scopes;
- use a dedicated identity provider rather than implementing an authorization server inside Docket;
- pass verified principal and scopes into the MCP request context;
- enforce tenant membership in every application service;
- support machine-to-machine client credentials for autonomous agents;
- return standards-compatible 401/403 challenges.

Local stdio trusts the local process boundary but still requires explicit tenant/config context for persistent production data.

## Transport behavior

### HTTP

- Endpoint: `POST/GET/DELETE /mcp` as required by the official handler.
- Stateless handler factory per request for the initial remote deployment.
- Bounded body size and request deadline.
- Host/Origin validation.
- JSON or SSE response mode selected through the official SDK; do not create a custom SSE protocol.
- No in-memory session map in serverless deployment.

### stdio

- No logging to stdout; protocol messages only.
- Logs go to stderr with sensitive fields removed.
- Clean shutdown closes the server.
- The package exposes a stable executable command.

## Idempotency

Every mutating tool accepts `idempotencyKey`.

The server stores:

- tenant and principal;
- operation name;
- key;
- canonical request digest;
- response or terminal error;
- expiry.

Repeating the same key and digest returns the original result. Reusing the key with a different digest returns `IDEMPOTENCY_CONFLICT`.

## MCP acceptance tests

- Server discovery returns expected identity, instructions, tools, and resources.
- Every tool succeeds with a valid fixture.
- Every schema rejects malformed input.
- Stdio and HTTP produce equivalent structured results.
- A real client receives the 230/20 USDC canonical result.
- Manual-review outcome preserves null financial fields.
- Unauthorized, insufficient-scope, and cross-tenant calls fail correctly.
- Duplicate mutation retries return the same result.
- Provider timeout becomes a bounded, actionable result.
- Tool output never contains secrets, wallet authority, or raw unrestricted evidence.
- Shutdown and cancellation do not leave committed partial mutations.
