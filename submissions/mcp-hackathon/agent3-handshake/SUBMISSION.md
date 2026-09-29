# Agent3 Handshake

## Capability

- **One-line description:** turns an entry in the Agent3 registry into the request an agent would actually send, and when the entry does not support that, names every field that stops it.
- **Who it helps:** an agent that has found a candidate partner in a registry and now has to call it. Discovery returns a directory row; calling needs an address, a method, a body shape and a price. The gap between those is where delegation fails.
- **Capability boundary:** it reads what a registry publishes and reports what can be built from it. It does not send the request, does not hold anyone's credentials, does not rank partners by quality, and does not judge whether a partner is trustworthy. A missing value is reported as missing; it is never filled in with a plausible default.

## Live API

- **API base URL:** https://agent3-handshake-production.up.railway.app/v1
- **Health-check URL:** https://agent3-handshake-production.up.railway.app/health
- **Authentication:** none. Every endpoint is open, which is deliberate: the upstream registry is public, so nothing here needs a credential that could expire during review.
- **Rate limits / known limits:** no rate limit. One upstream read serves every caller for a 120-second window, so repeated calls cost nothing additional. Upstream reads time out at 15 seconds; when the registry cannot be read the response says so rather than returning a partial answer.
- **API contract:** `tools.json` in `source/`, generated from `source/src/tools.ts`. Five tools, each reachable at a REST path under `/v1` and through JSON-RPC at `POST https://agent3-handshake-production.up.railway.app/mcp`.

## What it found in the live registry

Read at 2026-09-17T17:07:14.989Z, digest `8a4b7dd527759c19eef9ce9ced0a504c922992e8e95a7b0b58febc432b6fbb64`: **9 entries, 5 of which a request can be built from, 4 of which cannot.**

| Defect | Entries |
| --- | --- |
| `payment_kind_under_legacy_key` | 3 |
| `operation_without_binding` | 2 |
| `payment_kind_not_stated` | 1 |
| `gateway_on_retired_host` | 1 |
| `relative_interface_url` | 1 |

The largest single class is the payment field. The registry states the payment kind under two different key names: 5 entries use one, 3 use the other, and 1 state it under neither. A caller that reads only the first key sees nothing for 3 entries; one that reads only the second sees nothing for 5. In both directions the miss is silent, because an absent key and a free service are the same value.

`payment_readings` reports both readings side by side rather than picking a winner, so the caller can see which entries their own parser would have skipped.

## Source and reproducibility

- **Source repository:** https://github.com/agent3-666/agent3-handshake
- **Review commit:** `2571a1be25c6595d871b060c510767dd0ed0ce84`
- **Source submitted in this PR:** `source/`
- **Run tests:** `npm install && npm test`
- **Run locally:** `npm install && PORT=8080 REVIEW_COMMIT=2571a1be25c6595d871b060c510767dd0ed0ce84 npm start`
- **Deploy:** any Node 20 host that sets `PORT` and `REVIEW_COMMIT`. No build step; `tsx` runs the TypeScript directly.
- **Version binding:** the process reads `REVIEW_COMMIT` at startup and reports it from both `/health` and `/.well-known/xagent-verification.json`, which are served from the same origin as the API.

```json
// GET https://agent3-handshake-production.up.railway.app/health
{
  "status": "ok",
  "commit": "2571a1be25c6595d871b060c510767dd0ed0ce84",
  "slug": "agent3-handshake",
  "upstream": {
    "source": "https://a2a-hub-chi.vercel.app/api/resources?limit=200",
    "fetchedAt": "2026-09-17T17:07:14.989Z",
    "digest": "8a4b7dd527759c19eef9ce9ced0a504c922992e8e95a7b0b58febc432b6fbb64",
    "entryCount": 9,
    "entryIds": [
      "546105e1-9aa3-4622-b913-8727e45c6631",
      "646de76b-7366-45a8-b125-cc34f87223f2",
      "d0db231b-cf0a-416c-88bb-f3d4e601f39c",
      "b04926a6-5428-47da-854b-ca26cedd2655",
      "agent3-google-search-api-paid--1767630350903",
      "agent3-google-search-api-free--1767119359904",
      "agent3-x-api-free--1767014101000",
      "cp_agent-1763234336023",
      "pizza_seller_agent-1758695398234"
    ],
    "ageSeconds": 1,
    "ttlSeconds": 120,
    "refreshCount": 6
  },
  "cache": {
    "ageSeconds": 1,
    "ttlSeconds": 120,
    "refreshCount": 6
  }
}
```

```json
// GET https://agent3-handshake-production.up.railway.app/.well-known/xagent-verification.json
{
  "schemaVersion": 1,
  "slug": "agent3-handshake",
  "commit": "2571a1be25c6595d871b060c510767dd0ed0ce84",
  "apiBaseUrl": "https://agent3-handshake-production.up.railway.app/v1",
  "healthCheckUrl": "https://agent3-handshake-production.up.railway.app/health",
  "mcpEndpoint": "https://agent3-handshake-production.up.railway.app/mcp",
  "tools": [
    "registry_audit",
    "entry_describe",
    "call_plan",
    "payment_readings",
    "registry_snapshot"
  ]
}
```

## Verification

Reproducible calls and captured responses are in `verification/README.md`.

- **Health-check result:** `status: "ok"` with commit `2571a1be25c6595d871b060c510767dd0ed0ce84`, plus a live read of the upstream registry so a healthy envelope around a broken service is distinguishable from a working one.
- **Capability call:** `GET /v1/plan?entry=546105e1-9aa3-4622-b913-8727e45c6631&operation=search-content` returns `POST https://agent3-x-api.vercel.app/api/v1/telegram-search/bot-search` with the published body schema and its required fields.
- **Expected error behavior:** an entry that cannot be called returns 404 with every blocking field named — `Agent3 Google Search API (Paid)` returns `gateway_on_retired_host` on `payment.gateway`. An unknown entry returns 404 and lists the ids that do exist. Over JSON-RPC, an unknown method returns -32601 and an unknown tool returns -32602, while a tool that ran and declined returns a result with `isError: true`. The two channels are never mixed, so a caller can tell a malformed question from a valid one with a negative answer.

`source/verify.mjs` is an independent verifier: it talks to a running service over HTTP and imports nothing from `src/`, so it cannot pass by sharing a bug with the code it checks. Against the deployed service at this commit it makes 97 assertions. `source/scripts/control.sh` breaks six specific things and requires the verifier to go red on the named assertion each time, so the verifier's green is evidence rather than a default.

## Security and data handling

- **Data collected:** none. No account, no request logging, no persistence of caller input.
- **Purpose and retention:** the only state is an in-memory copy of the public registry listing, replaced every 120 seconds and never written to disk.
- **Third parties / outbound network calls:** one, to the public Agent3 registry listing at `a2a-hub-chi.vercel.app`. Nothing else leaves the process, and the service never sends the requests it describes.
- **Secrets:** No secrets are committed. Review access is supplied only through an approved private channel when required.
- **Known risks / restrictions:** the findings describe the registry as published, not as intended. An entry reported as blocked may be reachable by a caller with private knowledge the registry does not carry. The defect list is what a caller can determine from public data alone, which is the position an unfamiliar agent is actually in.

## Support

- **Team / builder:** Joey, Agent3
- **Contact:** joey@agent3.website, or https://github.com/agent3-666/agent3-handshake/issues
- **License / rights:** MIT. The submitter can authorize review and deployment; see `RIGHTS.md`.
