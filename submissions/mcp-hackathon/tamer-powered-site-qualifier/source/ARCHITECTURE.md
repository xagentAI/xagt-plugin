# Architecture

## Runtime

```text
Internet
   │ TCP 80/443
   ▼
Caddy
   │ private Docker network
   ▼
FastAPI / Uvicorn :8787
   │ outbound HTTPS when a paid request needs facilitator access
   ▼
Blocky402 TESTNET facilitator
   │
   ▼
Hedera TESTNET
```

The API has no host port mapping. Caddy is the only public application-facing component. SSH remains on TCP 22. The host firewall defaults to DROP for inbound traffic and allows only TCP 22, 80, and 443.

## Request paths

1. `POST /v1/qualify` validates the site schema and runs deterministic local scoring.
2. `POST /v1/paid/qualify` returns x402 v2 HTTP 402 requirements when no payment header is present.
3. The consuming agent signs a Hedera TESTNET native-HBAR payment using the official `@x402/hedera` client.
4. The API sends the canonical v2 payload and requirements to Blocky402 `/verify`, then `/settle`.
5. Only after successful settlement does the API return the qualification result with HTTP 200.

## Security boundaries

- Buyer private key exists only in the consuming-agent runtime and is not needed by the API.
- The API receives seller/pay-to and facilitator configuration only.
- Docker runs the API as UID/GID `10001:10001` with a read-only root filesystem, no privilege, all capabilities dropped, a process limit, and resource limits.
- Caddy stores certificate state in named volumes and rotates access logs. No directory browsing is configured.
- Evidence contains only account IDs, transaction metadata, status values, and the qualification classification; no private key or signed payload.
