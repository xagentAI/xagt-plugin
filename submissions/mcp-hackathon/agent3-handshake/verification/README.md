# Verification

Every response below was captured from the deployed service at commit
`2571a1be25c6595d871b060c510767dd0ed0ce84`. Nothing here is hand-written: the assembler calls the live service
and pastes what comes back.

The registry moves, so the counts in a fresh run may differ from the ones
recorded here. The digest and read time in each response say which registry
state produced it.

## 1. Health, bound to the reviewed commit

```bash
curl -s https://agent3-handshake-production.up.railway.app/health
```

```json
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

The `upstream` block is a live read of the registry. A service that returned
`status: ok` while unable to read anything would look identical from the outside
without it.

## 2. Deployment proof, same origin

```bash
curl -s https://agent3-handshake-production.up.railway.app/.well-known/xagent-verification.json
```

```json
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

## 3. The capability: build a request

```bash
curl -s "https://agent3-handshake-production.up.railway.app/v1/plan?entry=546105e1-9aa3-4622-b913-8727e45c6631&operation=search-content"
```

```json
{
  "resourceId": "546105e1-9aa3-4622-b913-8727e45c6631",
  "resourceName": "Telegram Content Search",
  "operationId": "search-content",
  "operationName": "Search Content",
  "method": "POST",
  "url": "https://agent3-x-api.vercel.app/api/v1/telegram-search/bot-search",
  "headers": {
    "content-type": "application/json"
  },
  "bodySchema": {
    "type": "object",
    "required": [
      "query"
    ],
    "properties": {
      "bot": {
        "enum": [
          "jisou",
          "teletop"
        ],
        "type": "string",
        "description": "Search bot: jisou=极搜 media/post content (default), teletop=中文索引 channel/group index"
      },
      "query": {
        "type": "string",
        "description": "Search keyword (Chinese supported)"
      }
    }
  },
  "requiredFields": [
    "query"
  ],
  "payment": {
    "kind": "free",
    "amount": 0,
    "currency": null,
    "gateway": null,
    "supportsX402": null,
    "statedVia": "model",
    "raw": {
      "model": "free",
      "amount": 0
    }
  },
  "warnings": [
    {
      "code": "payment_kind_under_legacy_key",
      "severity": "warning",
      "field": "payment.model",
      "detail": "the payment kind is published under \"model\"; a caller that reads \"mode\" finds nothing there and would treat a priced entry as free"
    }
  ]
}
```

That is a complete request: absolute URL, method, headers, the body schema as
published, and which fields are required.

## 4. The capability: refuse, and say why

```bash
curl -s "https://agent3-handshake-production.up.railway.app/v1/plan?entry=agent3-google-search-api-paid--1767630350903&operation=google-search"
```

```json
{
  "ok": false,
  "code": "not_callable",
  "detail": {
    "resourceId": "agent3-google-search-api-paid--1767630350903",
    "resourceName": "Agent3 Google Search API (Paid)",
    "operationId": "google-search",
    "blockers": [
      {
        "code": "gateway_on_retired_host",
        "severity": "blocker",
        "field": "payment.gateway",
        "detail": "the settlement gateway points at agent3.space, whose registration has lapsed, so this priced call cannot be paid for"
      }
    ],
    "warnings": []
  }
}
```

Returned with HTTP 404. Each blocker names the field that should have carried
the value and what its absence costs the caller.

## 5. The payment field, read both ways

```bash
curl -s https://agent3-handshake-production.up.railway.app/v1/payments
```

Summary across the registry:

```json
{
  "entries": 9,
  "statedUnderMode": 5,
  "statedUnderModel": 3,
  "statedNowhere": 1,
  "missedByAModeOnlyReader": 3,
  "missedByAModelOnlyReader": 5
}
```

The per-entry rows in the full response show, for each entry, what a reader of
each key alone would have seen.

## 6. Error behavior

An entry that does not exist, with the available ids returned so a caller can
correct itself:

```bash
curl -s -o /dev/null -w '%{http_code}\n' "https://agent3-handshake-production.up.railway.app/v1/plan?entry=__no_such_entry__&operation=__none__"
```

```json
{
  "status": 404,
  "body": "entry_not_found"
}
```

Over JSON-RPC, an unknown tool is a protocol fault:

```bash
curl -s -X POST https://agent3-handshake-production.up.railway.app/mcp -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"__nope__"}}'
```

```json
{
  "code": -32602,
  "message": "Unknown tool: __nope__"
}
```

An unknown method returns -32601. A tool that ran and declined returns a result
with `isError: true` and no JSON-RPC error, so a caller can tell "your question
was malformed" from "your question was fine and the answer is no".

## 7. Reproduce the whole thing

```bash
git clone https://github.com/agent3-666/agent3-handshake
cd agent3-handshake
git checkout 2571a1be25c6595d871b060c510767dd0ed0ce84
npm install
npm test                                     # assertions against the pinned snapshot
node verify.mjs https://agent3-handshake-production.up.railway.app 2571a1be25c6595d871b060c510767dd0ed0ce84          # assertions against the live service
bash scripts/control.sh                      # proves the verifier goes red when it should
```

`verify.mjs` imports nothing from `src/`. `scripts/control.sh` breaks six
specific things and requires the verifier to fail on the named assertion each
time; it restores the tree from a copy taken before the first edit.
