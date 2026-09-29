# Security

## Scope

Opportunity Lens is an advisory-only text classification API. It does not authenticate users, read private systems, make outbound network calls, persist data, access wallets, sign transactions, execute commands, or mutate external accounts.

## Supported deployment boundary

A supported public deployment must:

- use the version-and-digest-pinned Dockerfile;
- run as the configured non-root numeric user;
- expose the service only through managed HTTPS;
- apply edge rate limiting and platform CPU, memory, PID, concurrency, and request-duration limits;
- use a read-only root filesystem and drop Linux capabilities where the platform supports it;
- keep request logging disabled unless a reviewed operational need requires it;
- set `APP_COMMIT` to the exact reviewed public Git commit and `APP_SLUG` to the submitted slug.

## Input and data handling

Requests are limited to 65,536 bytes and a closed JSON schema. The application processes request bodies in memory and does not retain them. Do not submit secrets, credentials, private keys, personal data, private research, or private URLs. Hosting providers and reverse proxies may retain operational metadata under their own policies.

## Security properties

- Fixed request-size, field-length, evidence-count, socket-timeout, concurrency, and JSON-depth boundaries.
- No dynamic evaluation, shell execution, subprocesses, file reads, external API calls, or persistence.
- Restrictive response headers and no Python runtime version disclosure.
- Default request and exception logging disabled.
- Health and same-origin verification fail closed when deployment identity is invalid.
- All execution, capital, account, notification, routing, and public-publish authority flags remain false.

## Reporting

Report vulnerabilities through the repository's private security-advisory channel rather than a public issue. Include reproduction steps, affected commit, impact, and a proposed mitigation when available.
