# Security and data handling

BountyProof analyzes public GitHub metadata. It does not clone repositories, execute
issue instructions, install dependencies, open pull requests, or determine whether a
reward will actually be paid.

## Data flow

1. The caller sends a canonical public GitHub issue URL and optional expected reward or
   platform name.
2. The service requests public repository, issue, and timeline metadata from
   `api.github.com`.
3. The service returns bounded facts, warnings, relevant public URLs, and a conservative
   verdict. It never returns the issue body or matched suspicious text.
4. Identical checks are cached in memory for five minutes. The cache holds no secrets or
   private GitHub data and is lost on restart.

The public deployment uses GitHub without an API token. Operators may configure a
fine-grained read-only token through `GITHUB_API_TOKEN`, but it must remain outside Git,
logs, responses, and container images.

## Input and abuse boundaries

- Only `https://github.com/OWNER/REPO/issues/NUMBER` URLs are accepted.
- Bodies are streamed with a 16 KiB hard limit before JSON parsing.
- Unknown fields and non-JSON content types are rejected.
- GitHub calls use fixed hosts, validated path components, and eight-second timeouts.
- The reverse proxy rate-limits callers, caps connections and body size, and exposes only
  the loopback-bound container.
- The container is non-root, read-only, capability-free, and limited to 256 MiB / 1 CPU.
- Issue content is treated as untrusted data. High-risk patterns include secret
  exfiltration, wallet recovery material, instruction overrides, remote shell pipelines,
  and safeguard bypass requests.

## Interpretation boundary

`PROCEED_TO_MAINTAINER_CONFIRMATION` is not permission to code and not a payment promise.
`ADVERTISED_ONLY` means exactly that: a current issue or label mentions money, a token, or
a known platform. Platform eligibility, escrow, tax/KYC, assignment, acceptance, and
payout must be verified separately.

Report vulnerabilities through a private GitHub security advisory. Never include tokens,
session cookies, private repository content, or wallet material in a report.
