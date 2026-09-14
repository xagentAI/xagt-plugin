# Public deployment preparation

This profile keeps the API private to the Docker network and exposes only Caddy on TCP 80/443. The application port is not published to the host. Caddy obtains and renews the HTTPS certificate automatically after the chosen FQDN resolves to the VPS and ports 80/443 are approved.

Before deployment, replace `PUBLIC_DOMAIN` with the approved FQDN in a VPS-only `deploy/.env` file. Do not commit that file. Required DNS is:

```text
<chosen-fqdn>  A  89.58.39.50
```

Then validate and start only after explicit approval. Supply the exact reviewed commit being deployed so `/health` and the proof endpoint bind to the same source revision:

```bash
XAGENT_REVIEW_COMMIT=<40-character-reviewed-commit> docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml config
XAGENT_REVIEW_COMMIT=<40-character-reviewed-commit> docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml up -d --build powered-site-qualifier
```

The API uses only the seller/pay-to account ID and Blocky402 testnet configuration. The buyer key stays outside the API container and is not required by this service.

The current template provides request-body limits, security headers, automatic HTTP-to-HTTPS redirect, rotated Caddy access logs, Docker log rotation, non-root API execution, read-only filesystems, dropped capabilities, no Docker socket, no host networking, and 1 vCPU/1 GiB API limits. Caddy's standard image is used without third-party rate-limit plugins; rate limiting remains an explicit edge/firewall approval item before public exposure.
