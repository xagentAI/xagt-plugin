# Opportunity Lens API

[简体中文](README.zh.md)

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Mode](https://img.shields.io/badge/mode-advisory--only-6f42c1)

A deterministic, advisory-only API that converts an unstructured opportunity description into a cross-domain profile, signal maturity, evidence gaps, and one bounded next validation action.

## What you get

- Deterministic JSON output for agent workflows.
- Eight supported domains, including AI agents, crypto, Bitcoin-native systems, prediction markets, products, distribution, data infrastructure, and grants.
- Explicit evidence gaps instead of fabricated certainty.
- A bounded validation route such as `DATA_CHECK`, `STRATEGY_TEST`, `PRODUCT_TRIAL`, or `COMMERCIAL_REVIEW`.
- Hard-coded false authority for execution, capital, accounts, notifications, routing, and publishing.
- No outbound calls, persistent storage, API keys, wallets, signing, trading, or private data access.

## How it works

```text
caller-supplied description
        ↓
closed input validation
        ↓
deterministic keyword and evidence classification
        ↓
profile + evidence gaps + advisory validation action
```

Example request:

```json
{
  "headline": "Prediction market orderbook API with timestamped market data",
  "why_now": "The public endpoint is live.",
  "evidence": [
    {
      "source_id": "official:docs",
      "kind": "OFFICIAL_API_DOC",
      "first_party": true
    }
  ]
}
```

The response includes `profile`, `validation`, and `safety`. Every authority-bearing field remains `false`.

## API

- `GET /health`
- `GET /.well-known/xagent-verification.json`
- `GET /openapi.json`
- `POST /v1/profile`

Live deployment: `https://opportunity-lens-api.leolabs.me`

## Requirements and privacy

- Python 3.11 or newer.
- No third-party runtime dependencies.
- No API key or account is required.
- Request bodies are processed in memory and are not stored by the application.
- Do not send secrets, personal data, private research, credentials, private keys, or private URLs to a public deployment.
- A hosting provider or reverse proxy may retain operational metadata under its own policy.

## Quick start

```bash
git clone https://github.com/runesleo/opportunity-lens-api.git
cd opportunity-lens-api
export APP_COMMIT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export APP_SLUG=runesleo-opportunity-lens
python3 app.py
```

Then:

```bash
curl --fail --silent http://127.0.0.1:8080/health
curl --fail --silent http://127.0.0.1:8080/openapi.json
curl --fail --silent \
  --request POST http://127.0.0.1:8080/v1/profile \
  --header 'content-type: application/json' \
  --data '{"headline":"AI agent API for a builder bounty","why_now":"The official deadline is near."}'
```

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile app.py opportunity_lens.py tests/test_api.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

## Container

```bash
docker build -t opportunity-lens-api .
docker run --rm \
  --read-only \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  --pids-limit=64 \
  --memory=128m \
  --cpus=0.5 \
  -p 8080:8080 \
  -e APP_COMMIT=<exact-40-character-public-commit> \
  -e APP_SLUG=runesleo-opportunity-lens \
  opportunity-lens-api
```

## Verified

The local release gate covers compilation, deterministic classification, health and deployment-proof binding, closed OpenAPI schemas, request-size and JSON-depth limits, timeout and concurrency bounds, restrictive headers, non-root container configuration, and secret/private-path scanning.

See [`REVIEW-codex-pass.md`](REVIEW-codex-pass.md) for the independent release review once generated.

## Known limitations — v1.0.0

- Classification is deterministic and keyword-based; it is intentionally not an LLM or a factual verifier.
- The service does not fetch URLs or validate claims supplied by callers.
- It does not authenticate callers; public deployments require edge rate limiting and platform resource limits.
- The standard-library HTTP server is suitable for this bounded review API, not high-throughput multi-tenant workloads.
- A profile is research guidance, not investment, legal, security, or financial advice.

## Roadmap

- Add versioned domain vocabularies with fixture-based regression tests.
- Add optional signed evidence references without fetching remote content.
- Add deployment observability that preserves the no-persistence boundary.
- Standardize the capability as an MCP tool if selected by X-Agent.

## Security

Read [`SECURITY.md`](SECURITY.md). The release image is pinned by version and digest, runs as numeric non-root UID/GID `65532:65532`, and defaults to no request logging.

## About the author

Built by [Leo](https://leolabs.me/?utm_source=github&utm_medium=referral&utm_content=opportunity-lens-api), an independent builder working across AI agents, crypto research, prediction markets, and automation.

## License

MIT. See [`LICENSE`](LICENSE).
