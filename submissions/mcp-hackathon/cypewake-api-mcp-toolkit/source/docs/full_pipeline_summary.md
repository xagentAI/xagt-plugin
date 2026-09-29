# Full pipeline summary

Result of `POST /api/full-pipeline` against the public Swagger Petstore spec, with `pricing_tier: "basic"`. The full response is in `docs/full_pipeline_result.json`; this file is the readable summary.

| Stage | Result |
|---|---|
| build | Parsed Petstore OpenAPI 3.0: 19 operations, `base_url` resolved from a relative `servers.url` |
| verify | 12 endpoints probed concurrently. 3 passed on real 2xx; 8 reached but failed (auth required or placeholder parameters); 1 unreachable |
| mcpize | Generated 19 FastMCP tools into the output directory; the generated `server.py` compiles |
| register | 19 operations registered under the name `petstore`, persisted to the registry |
| call | Real call to `loginUser` with placeholder credentials returned HTTP 200, proving the registered tool is callable |
| monetize | Listing built on the basic tier: USD 2.00 per 1,000 calls |
| invoice preview | Projected from the observed call rate: USD 180.00 |

## What to read from it

Two things make this more than a happy-path demo:

1. **Verify does not pass everything.** Nine of twelve endpoints do not pass, and that is the correct verdict — Petstore's `/pet` endpoints declare security in the spec and return 401 without credentials. An implementation that counted any response as success would report 12/12 and tell you nothing.
2. **The invoice comes from metered calls.** The amount is computed from recorded usage against the tier, not printed from a static table.

## Reproduce

```bash
uvicorn demo_app:app --port 8000
curl -s -X POST http://127.0.0.1:8000/api/full-pipeline \
  -H 'Content-Type: application/json' \
  -d '{"spec_source":"https://petstore3.swagger.io/api/v3/openapi.json","pricing_tier":"basic"}'
```

Pass a `scope` object in the same payload to curate tools before generating — for example `{"include_tags":["pet"],"include_methods":["GET"]}` cuts 19 endpoints to 3 tools.
