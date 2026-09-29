# Sumplus Model Desk

Prices one job against every offer in a live model catalogue, and says which offers can actually take it.

**A model id is not a price.** In the catalogue this desk reads, 93 offers carry only 72 distinct
ids: 16 of those ids are sold on more than one line, at up to **15 times** the price. "Use gpt-5.5"
is not a choice anyone has finished making.

```
gpt-5.5           3 offers    $5.00 /M in (jinwang)   $5.00 (arklin)   $75.00 (mixai)    15x
deepseek-v4-pro   2 offers    $0.435 /M in            $1.74                              4x
claude-opus-4-8   3 offers    $5.00 /M in             $15.00                             3x
```

And an offer whose context window or output ceiling is too small for the job does not refuse it.
It truncates the answer, and bills for it.

So the desk takes a **job** (how many input tokens, how many output tokens, what the work needs)
and returns a **decision**: which offers can take it, what each one charges for this exact job,
sorted, and for the ones that cannot, which single number ruled them out.

## Try it

```bash
curl -s https://sumplus-model-desk-production.up.railway.app/v1/plan_call \
  -H 'content-type: application/json' \
  -d '{"inputTokens":100000,"outputTokens":10000,"baselineModelId":"gpt-5.5","limit":5}'
```

Every endpoint is read-only, needs no credentials, and costs the caller nothing.

| Endpoint | What it answers |
|---|---|
| `POST /v1/plan_call` | Which offers can take this job, priced and sorted, and why the rest cannot |
| `POST /v1/quote` | What one named id costs for this job, on each line that carries it |
| `GET /v1/resolve?modelId=` | Every offer behind one id, and the spread between them |
| `GET /v1/catalogue` | The catalogue being priced against |
| `GET /v1/catalogue/diff` | What has moved since this build was submitted |
| `GET /v1/tools.json` | Tool surface: inputs, outputs, errors, limits, side effects |
| `POST /mcp` | The same five tools over JSON-RPC 2.0, for an agent runtime |
| `GET /health` | Liveness, the commit this build was cut from, and cache observability |

## Calling it as an agent runtime

The same five tools answer over JSON-RPC 2.0 at `POST /mcp`:

```bash
curl -s https://sumplus-model-desk-production.up.railway.app/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

curl -s https://sumplus-model-desk-production.up.railway.app/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"plan_call","arguments":{"inputTokens":100000,"outputTokens":10000}}}'
```

`tools/list` is generated from the same `tools.json` served over HTTP, and `tools/call` runs the
same operation as the matching REST route, so the two doors cannot answer differently. The tests
assert that a call through JSON-RPC matches the REST answer byte for byte.

A malformed request comes back as a JSON-RPC error object. A tool that refuses comes back as a
result carrying `isError`, with the refusal inside it, because the request was well formed and the
refusal is the answer.

## What a refusal looks like

A refusal carries the number that caused it and what to relax:

```json
{
  "modelId": "glm-5.1",
  "line": "nube",
  "reason": "Its context window holds 128000 tokens, and this job needs 4000000 for the prompt plus its answer.",
  "bindingConstraint": "context",
  "requiredValue": 4000000,
  "actualValue": 128000
}
```

When nothing can take the job at all, the error carries the largest window and output ceiling that
exist, so the caller knows what would work.

## What it will not put in front of you

**Offers that are not sold by the token.** The same catalogue carries video and image models, which
have no context window and no output ceiling. Their per-million fields are zero because the field
does not apply, not because they are free. A job measured in tokens cannot be placed on one, so
they are refused by name, with `bindingConstraint: "not_token_priced"`.

**Offers that are not live.** Two offers are marked `preview`, and one of them is a real text model
with a million-token window at a competitive price, so it would otherwise sit high in a list sorted
by price with nothing to say it is a preview. They are excluded by default and refused with
`bindingConstraint: "availability"`. Pass `includePreview: true` to consider them on purpose.

**A zero it cannot explain.** Some offers are listed at zero, and those rows carry
`listedAtZero: true`. The desk reports the figure the catalogue gives and makes no claim beyond it:
a price of zero and a price nobody has filled in are the same value in that field.

## Running it

```bash
npm install
npm start                 # http://localhost:4400
npm test                  # offline: the network is removed for the whole run
npm run verify responses/plan_call.json
npm run check:upstream    # the one script that needs a network, and is not part of npm test
```

`npm test` runs against the catalogue snapshot committed in `snapshots/`, and the first thing it
asserts is that the network is unavailable. A test that quietly reaches a live service passes here
and fails in an isolated review environment, which makes it evidence of nothing.

## How the numbers can be checked

**Recompute them.** `verify.mjs` reads a saved response plus the snapshot and recomputes every
figure with its own arithmetic, written out separately. It imports nothing from the service: a
checker that calls the code it is checking only proves that code agrees with itself. It confirms
each accepted offer really fits the job, each refusal really is out of reach, and each total
matches the catalogue.

**Watch it move.** The catalogue as it stood at submission is committed here, and
`/v1/catalogue/diff` compares today's catalogue against it. That shows the upstream catalogue is
live and changing. It does not independently confirm that any price is correct: both readings come
from the same source.

**Arithmetic discipline.** Prices are held as integers in micro-dollars and every calculation stays
in integers. Costs round up and savings round down, so a displayed figure is never below what
would actually be charged. The tests assert this over every offer in the catalogue at several token
counts.

**Snapshot identity.** Each response names the `snapshotId` it priced against: a sha256 over one
JSON array per offer, sorted, newline separated. The canonical form is spelled out in the source
and reimplemented independently in `verify.mjs`, so the id can be reproduced by reading either.

## Staying up

The catalogue snapshot ships inside the image. On a cold start the desk answers from it
immediately, reporting honestly how old it is in `staleSeconds`, and replaces it as soon as a
refresh succeeds. Reviewer traffic never reaches the upstream gateway: this service reads the
catalogue on its own schedule and serves its own copy, so an upstream wobble changes the freshness
number rather than taking the service down.

`/health` reports cache age, how many refreshes have succeeded, whether it is still serving the
shipped snapshot, and the last refresh error if there was one.

## Where the prices come from

`https://router.sumplus.xyz/v1/models`, the public catalogue of the Sumplus gateway. The gateway
runs in an AMD SEV-SNP confidential machine and posts its own build measurement to the Sigstore
Rekor public transparency log.

That attestation covers the gateway's build and its internal model configuration. The digest inside
it is **not** recomputable from the public catalogue, so it is background on where these prices come
from, not a proof that any published price is correct.

## Scope

Procurement and pricing for model calls. This service does not inspect wallets, transactions,
contracts, or security posture.

## Licence

MIT. Built by Jakob for the X-Agent AI MCP Hackathon.
