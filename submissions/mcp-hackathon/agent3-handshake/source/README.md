# Agent3 Handshake

Turns an entry in the Agent3 registry into the request an agent would actually
send — and when the entry does not support that, names every field that stops it.

Discovery hands an agent a directory row. Calling needs an address, a method, a
body shape, and a price. Those are not the same thing, and the gap between them
is where delegation fails: not at "I could not find a partner" but at "I found
one and could not call it".

## What it does

| Tool | Answers |
| --- | --- |
| `registry_audit` | For every entry: can a request be built from what is published? If not, which field is missing? |
| `entry_describe` | One entry, normalized: operations flattened to id/method/path, payment resolved across both spellings. |
| `call_plan` | The exact request for one operation — absolute URL, method, headers, body schema, required fields, payment — or a refusal naming each blocker. |
| `payment_readings` | What a reader of each payment key alone would see, and how many entries each one silently misses. |
| `registry_snapshot` | Source, read time, entry ids and a sha256 digest, so an answer can be pinned to the registry state it came from. |

## Why the refusals matter

A caller that fills in a plausible default produces a request indistinguishable
from one the registry really supports. The sender only finds out by sending it.
So `call_plan` never guesses a host, a method or a price: a missing value is
reported as missing, with the field that should have carried it.

## Two doors, one implementation

`POST /mcp` speaks JSON-RPC (`initialize`, `tools/list`, `tools/call`). The REST
paths under `/v1` take the same arguments. Both call the same functions in
`src/operations.ts`, so the two cannot answer differently.

A tool that ran and declined reports through `result.isError`. Protocol faults —
unknown method, unknown tool — use JSON-RPC error codes. The two channels are
never mixed, so a caller can tell "your question was malformed" from "your
question was fine and the answer is no".

## Cost of calling it

One upstream read serves every caller for the cache window, and the upstream
endpoint is public and free. Calling this ten thousand times costs what calling
it once costs. Nothing here holds a credential that can expire.

## Running it

```bash
npm install
npm test          # assertions against the pinned snapshot
npm start         # PORT and REVIEW_COMMIT from the environment
```

`GET /health` reports the reviewed commit. `GET /.well-known/xagent-verification.json`
reports the same commit, the API base and the MCP endpoint, on the same origin.

## Source of truth

`src/registry.ts` is the only module that knows the hub's field names.
`src/tools.ts` is the only declaration of the tool set — the MCP listing, the
REST routes and `tools.json` are all derived from it, so they cannot drift.
