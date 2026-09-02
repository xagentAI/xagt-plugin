# Architecture

Finfold Growth Mission is one stateless TypeScript Worker with a D1 binding. It deliberately keeps the synchronous path narrow: one bounded source fetch, one structured generation attempt, one optional repair attempt, validation, and one D1 write.

## Request path

1. Authenticate the SHA-256 hash of a Bearer review key with timing-safe verification.
2. Enforce scope and atomically increment the key's UTC-day allowance.
3. Reserve `(key, endpoint, Idempotency-Key)` against a canonical request hash.
4. Validate the source and every redirect; stream at most 1.5 MB of HTML.
5. Extract stable `s1…sN` semantic sections from title, metadata, headings, paragraphs, lists, links, and JSON-LD.
6. Send the sections as explicitly untrusted data in one structured Llama 3.3 70B Instruct Fast request through the in-process Workers AI binding. An OpenAI-compatible HTTP adapter is retained for portability and deterministic tests.
7. Resolve every selected section ID back to its canonical source text. A deterministic evidence compiler assembles the factual asset sentence and claim map from the selected quote; it does not run only on failures and cannot substitute unknown evidence. Validate the compiled result so each mapped claim appears verbatim in both the deliverable and cited source quote, then validate objective/platform, one CTA, length, numbers, and prohibited guarantees.
8. Repair once when generation or validation fails. A second failure returns a typed error and persists no mission.
9. Save evidence snippets, the validated result, the tracking destination, and the 30-day retention deadline.

## Attribution path

Tracking redirects aggregate anonymous daily click counts. Outcome writes are deduplicated by both the HTTP idempotency key and the caller-provided `eventId`. The read path computes objective totals and the verdict from D1:

- `won`: objective total reached target.
- `running`: target not reached and measurement window remains open.
- `lost`: window closed with attributable activity below target.
- `inconclusive`: window closed with no credible attribution.

## Failure semantics

Source failures and validation failures are first-class outputs. There is no mock content, template fallback, or silent substitution. The API marks retryable infrastructure failures separately from evidence or request failures.

## MCP

`POST /mcp` implements stateless Streamable HTTP JSON-RPC for protocol versions `2025-11-25` and `2025-03-26`. It supports `initialize`, `notifications/initialized`, `ping`, `tools/list`, and `tools/call`. Operational tool failures use MCP `isError: true`; malformed JSON-RPC uses protocol error codes.
