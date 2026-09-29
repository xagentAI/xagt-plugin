# Powered-Site Qualifier

Powered-Site Qualifier is a deterministic, machine-readable screening API for early powered-site diligence. Given structured site facts, it returns two separate readiness scores:

- **Bitcoin Mining Readiness** — power, capacity, price, utility status, land, commercial path, and operating inputs relevant to mining-scale deployment.
- **AI/Data Center Readiness** — power, capacity, fiber, water, land, permitting, expansion, and commercial inputs relevant to AI/data-center infrastructure.

It also reports positives, missing information, major blockers, next questions, and a classification such as `READY`. It is an initial qualification aid, not engineering, utility, legal, environmental, financial, or investment diligence.

## Live API

Public base URL: <https://qualifier.cryptoleaks.agency>

The live root URL is an interactive browser tool: <https://qualifier.cryptoleaks.agency/#tool>. It submits the form to the real `POST /v1/qualify` endpoint and renders the returned scores, blockers, missing information, and next questions.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Health and exact reviewed commit binding |
| `GET /.well-known/xagent-verification.json` | X-Agent deployment proof |
| `POST /v1/qualify` | Unpaid deterministic qualification |
| `POST /v1/paid/qualify` | x402-gated qualification |
| `GET /docs` | FastAPI OpenAPI documentation |

The public service is HTTPS-only in normal use; HTTP redirects to HTTPS. The API container is private to Docker and port 8787 is not published.

```bash
curl --fail --silent https://qualifier.cryptoleaks.agency/health
curl --fail --silent https://qualifier.cryptoleaks.agency/.well-known/xagent-verification.json
curl --fail --silent --request POST \
  https://qualifier.cryptoleaks.agency/v1/qualify \
  --header 'content-type: application/json' \
  --data @examples/site-ready.json
```

The live reviewed binding is supplied explicitly to the secure deployment at deploy time. The exact value is exposed by both `/health` and `/.well-known/xagent-verification.json`; verify it before a demo:

```json
{"status":"ok","commit":"<exact deployed reviewed commit>"}
```

## Example result

`examples/site-ready.json` produces `READY` with Bitcoin Mining Readiness `100` and AI/Data Center Readiness `100`. The response also includes the known-input basis, key positives, missing information, blockers, and recommended next questions. `examples/site-incomplete.json` demonstrates how unknowns become evidence gaps instead of guesses.

The browser's fictional Oklahoma demo site uses 20 MW, $0.055/kWh, grid power, 138 kV, and `interconnected` utility status; the live API returns Bitcoin `97`, AI/Data Center `98`, and `READY` for that example.

## Hedera x402 payment flow

The paid route uses x402 v2 `exact` on `hedera:testnet`, native HBAR asset `0.0.0`, and the hosted Blocky402 facilitator. An unpaid request returns HTTP 402 with the payment requirements. A consuming agent signs with the buyer key locally, retries with the payment header, and the service calls Blocky402 `/verify` and `/settle` before returning HTTP 200.

```text
Agent → API: POST /v1/paid/qualify
API → Agent: 402 PAYMENT-REQUIRED
Agent: sign Hedera TESTNET payment locally
API → Blocky402: /verify → /settle
Blocky402 → Hedera TESTNET: confirm settlement
API → Agent: 200 qualification + payment response
```

One real proof completed on Hedera TESTNET:

- Buyer: `0.0.10488940`
- Seller/pay-to: `0.0.10489770`
- Amount: `100000` tinybars (`0.001` testnet HBAR)
- Blocky402 verify: success
- Blocky402 settle: success
- Transaction: `0.0.7162784@1789186391.831327025`
- Final response: HTTP 200, classification `READY`

Only redacted evidence is included in [`evidence/hedera-real/`](evidence/hedera-real/). No private key or raw signed payload is included.

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
XAGENT_REVIEW_COMMIT=local-development \
  uvicorn app.main:app --host 127.0.0.1 --port 8787
```

The local Compose profile is loopback-only:

```bash
docker compose up --build
```

Run tests with:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The official consuming client is in `agent/consume.mjs`; install its pinned dependencies with `npm ci` in `agent/`. Never place the buyer key in the API container or repository.

## Production deployment

The reviewed VPS deployment uses [`deploy/docker-compose.prod.yml`](deploy/docker-compose.prod.yml) and Caddy. Caddy terminates HTTPS, redirects HTTP, limits request bodies to 256 KB, adds security headers, and rotates logs. The API runs non-root with a read-only filesystem, dropped capabilities, no privilege, no host networking, no Docker socket, one vCPU, and one GB RAM. Only TCP 22, 80, and 443 are intentionally exposed.

See [`deploy/README.md`](deploy/README.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), and [`SECURITY.md`](SECURITY.md).

## Public submission materials

- Hedera flow and proof: [`HEDERA-X402.md`](HEDERA-X402.md)
- Architecture: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- API contract: [`API-SCHEMA.md`](API-SCHEMA.md)
- Demo: [`DEMO-SCRIPT.md`](DEMO-SCRIPT.md)
- X-Agent package draft: [`xagent-submission/`](xagent-submission/)

The public source repository is live at <https://github.com/CryptoLeaks/powered-site-qualifier>. The interactive browser tool and HTTPS API are live at <https://qualifier.cryptoleaks.agency>. The successful Hedera testnet proof is redacted and documented in [`evidence/hedera-real/payment-proof-redacted.json`](evidence/hedera-real/payment-proof-redacted.json). No external hackathon submission or additional payment is implied by repository publication.

## License

MIT; see [`LICENSE`](LICENSE). Third-party dependencies retain their respective licenses.
