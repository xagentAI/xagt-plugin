# Security policy

## Supported version

The latest commit on `main` is the supported review version during the
hackathon. Deployment and source must be bound by the exact commit returned by
`/health` and `/.well-known/xagent-verification.json`.

## Reporting a vulnerability

Do not open a public issue containing an exploit, credential, private endpoint,
or customer data. Use GitHub's private vulnerability reporting for this
repository. If that channel is unavailable, open a public issue requesting a
private contact channel without including sensitive details.

## Security boundaries

- APIVouch accepts credential-free public provider URLs in the current release.
- Credentials embedded in URLs are rejected.
- Private, loopback, link-local, metadata, multicast, reserved, and unspecified
  targets are blocked by default, including after redirects.
- Each HTTP hop validates the entire IPv4/IPv6 DNS answer (mixed public/private,
  empty, malformed, and scoped answers fail closed). A hop-local httpcore pool
  connects only to those validated numeric addresses, including connection
  fallback; it never resolves the original hostname again to connect. Pools are
  not shared across requests or redirects, even for same-origin redirects.
  TLS SNI and certificate hostname verification retain the original URL host,
  as does HTTP Host (caller Host overrides are ignored). Environment proxies
  and environment TLS overrides are disabled with `trust_env=False`.
  This is pre-connect pinning, not a post-connect peer-address check.
- `ALLOW_PRIVATE_NETWORK=true` deliberately relaxes address policy for local
  development, but does not disable pinning. DNS uses the system resolver;
  resolver latency is not covered by the HTTP connect timeout. Pinning cannot
  defend against host-level routing/NAT changes or a public upstream that itself
  proxies private resources; production egress controls remain necessary.
- Automatic provider and generated-tool calls are limited to read-only HTTP
  methods; state-changing operations require explicit confirmation elsewhere.
- Network concurrency, timeouts, retries, redirects, response bytes, project
  count, endpoint count, MCP request bytes, proof pages, and proof records are
  bounded.
- Receipt URLs redact query values, payloads are content-digested, and only
  bounded scalar previews are retained.

## Deployment guidance

Keep `ALLOW_PRIVATE_NETWORK=false` in public deployments. Use PostgreSQL,
authentication, tenant isolation, quotas, and retention policies before storing
customer evidence. Rotate any credential that is accidentally exposed and do
not include it in a vulnerability report.

## Receipt Trust

SHA-256 integrity is not authentication: anyone can edit an unsigned receipt and
recompute its hash. Signed v2 authenticates relative to a trusted Ed25519 public
key, not independent upstream observation. Same-origin discovery establishes
deployment consistency only. Pin keys through a trusted channel. There is one
active key, no historical registry or revocation feed; archive old public
documents before rotation. See [signing](docs/signed-receipts.md).

## Operator Controls

The API has no authentication, project ownership, or tenant isolation. Signing
does not fix these boundaries. Do not store sensitive customer evidence. VPS
exposes only Caddy TCP 80/443; DB networking is internal, while app retains
internet egress separately. Docker-published ports may bypass UFW, so enforce
provider firewall rules too. Body/time/concurrency/log caps are not DDoS
protection or per-user rate limits. See [operations](docs/deployment.md).

Keep private seeds in the runtime secret environment, never source, build
arguments, CI artifacts, or logs. Host/Docker administrators can inspect them.
Do not dump real Compose configuration; use `config --quiet`. Encrypt backups,
restrict access, keep off-host copies, and test restores. No generated keys ship.

`python scripts/scan_secrets.py` checks tracked and unignored working-tree files
for private-key blocks, selected tokens, literal signing keys and credential
URLs. It prints path/line/rule only and fails on inspection errors/oversized
files. CI runs it. This heuristic does not scan history, ignored files, or every
credential format. Review staged diffs and revoke any exposed credentials.
