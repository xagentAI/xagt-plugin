# AlphaLitmus Threat Model

## Trust Boundaries

Caller OHLCV, historical labels, attempted-variant counts and `as_of` timestamps are untrusted. Nexus is an external service accessed with a private strategy-bound key. Certificates may contain sensitive caller datasets even when they contain no credentials. The HTTP service is not an identity provider or credential vault. MCP stdio inherits the launching process's environment and host permissions.

| Threat | Implemented constraint / operating requirement | Residual limitation |
| --- | --- | --- |
| Fabricated market data or rehashed reports | Strict schemas, deterministic replay and content hashes | Consistent forged inputs still verify; no authenticity claim |
| Look-ahead or overstated returns | Prior-close features, next-open fills, training-only calibration and costs | Repeated test inspection, selection bias and data revisions remain |
| Incomplete Nexus evidence | Typed surface allowlist and explicit unavailable/insufficient checks | Equal counts and run IDs do not attest complete history |
| Secret disclosure | Server-side key, sanitized surfaces, secret-like source rejection, build exclusions | Pattern filters are not general DLP; logs, environment access and operators remain trusted |
| SSRF / transport surprises | Fixed Nexus URL; redirects off, environment proxies ignored | DNS/TLS and upstream service remain external dependencies |
| Oversized upstream responses | 2,000,000-byte cap per response, depth 32, row cap 10,000; identity encoding only | Upstream availability and aggregate concurrent load still matter |
| Numeric / parser abuse | Finite bounded values, strict candle domains and certificate size/depth bounds | Runtime resource exhaustion still needs proxy limits and concurrency controls |
| Unauthenticated strategy disclosure | Nexus disabled unless explicitly enabled; authenticated reverse proxy required | Application-local auth, account isolation and billing are not claimed |
| Fixed public live pulse abuse | Exact strategy/symbol, no body/query, four read-only calls, bounded file secret, 60 s cache, 30 requests/minute/process, 10 s minimum refresh and 3-failure/120 s circuit | Limits are per process, not per principal or distributed; public result intentionally discloses sanitized strategy evidence |
| Unbounded remote backtest compute | Dual enable switches, per-request boolean confirmation, 3-run cap, per-process lock, 5-60 s deadline, call ceiling, no retries | Lock is per process; Studio/other processes can race; timed-out experiments may leave remote jobs running; gateway-wide quotas still required |
| Misleading provenance | Production commit configuration and health/proof binding | A claimed hash is not independently proven build provenance |
| Dependency compromise | pip-tools SHA-256 hash locks, wheel-verified license inventory, isolated pip-audit gate | Windows-resolved locks, mutable container base tag, publisher-supplied license metadata; no SBOM or external certification |

Nexus transport uses connect/write/pool timeouts of 5 seconds and read timeout of 15 seconds, and performs four read-only calls. These are per-operation timeout settings, not a guaranteed total request wall-clock budget. Sanitized numeric values are bounded to absolute 1e15. Missing or rejected upstream data must not become a success claim.

Offline sanitization is pure and independent of local secret environment variables. Live ingestion explicitly passes its key to the sanitizer for additional redaction. Invalid rows remain empty records rather than being excluded from the sample. Cross-surface numerical agreement or discrepancy remains insufficient evidence without complete metric/run/window binding; explicit run/symbol contradictions still mismatch.

## Deployment Policy

Use TLS and an authenticated reverse proxy for all capability routes, especially Nexus reads and returned reports. There is no persisted report-retrieval API. Apply request/body/rate/concurrency limits and bounded upstream timeouts. Keep only the required health and deployment-proof endpoints public. Do not publish private datasets in logs or reviewer artifacts; built-in demos use only synthetic data. Use a secret manager or process environment injection; `.env.example` is not a loader. Rotate a disclosed key and inspect logs rather than relying on Git ignore rules to remove history.

Set `ALPHALITMUS_ENV=production` and the actual reviewed `ALPHALITMUS_COMMIT`. The fixed pulse uses only `ALPHALITMUS_ENABLE_LIVE_NEXUS=true` plus `NEXUS_API_KEY_FILE`; keep `ALPHALITMUS_ENABLE_NEXUS=false` to prevent caller-selected reads. Enable the arbitrary switch only behind authenticated access. Container UID 10001 is non-root; the live deployment mounts only the dedicated read-only secret file, never a host credential directory. A read-only filesystem and resource limits remain required operational controls.

Report retention, backup, tenant isolation, access revocation, observability and incident response require operator design. No execution route, wallet signing, order placement, billing, or custody capability is claimed. Bounded backtest submission exists only as explicitly confirmed opt-in compute and never trades. Do not turn a research verdict into an automatic order decision.

The current HTTP transport caps request bodies at 4,000,000 bytes and JSON depth at 32 and rejects duplicate keys. Eight intake slots per process are held through dispatch, limiting retained uploads; the complete body must arrive within 10 seconds or receives 408 `BODY_TIMEOUT`. A separate gate admits two expensive operations per process. Exhausted gates reject immediately with 429. `GET /health` never reads or waits for an upload and bypasses both gates: declared bodies are rejected, undeclared bytes are neither read nor buffered. Multiple workers multiply capacity. The body deadline is not a total computation timeout. These bounds supplement, not replace, authenticated proxy controls and end-to-end timeouts.

MCP raw stdio frames are size/depth/duplicate-key checked before SDK decoding; invalid frames close the session without trusting an ID. The HTTP intake deadline is not an MCP idle-read timeout. Bootstrap bound failures suppress the entire bootstrap distribution rather than excluding samples; replay numeric failures suppress the entire reference analysis. Neither condition is evidence of robustness.

## Verification Limits

Certificate verification is integrity and deterministic consistency checking, not a digital signature, ownership check, timestamp attestation, data-source authentication or proof of profit. Creation time is excluded from the report digest. Nexus freshness uses caller-provided time. Commit metadata is not proof of source-to-image reproducibility. No penetration test, production deployment, live secret test or external security certification was performed for this documentation task.
