# Security model

## Source fetch

Only `http:` and `https:` source URLs without credentials are accepted. The validator blocks localhost, private/link-local IPv4, IPv4-mapped private IPv6, loopback, unique-local, link-local and multicast IPv6, metadata endpoints, internal suffixes, non-standard ports, HTTPS downgrade redirects, and more than three redirects. Every redirect target is revalidated. Responses must be HTML/XHTML and are streamed with a 1.5 MB hard limit and a 10-second timeout.

Tracked destinations are stricter than source reads: they must use HTTPS and remain on the source host, its subdomain, or its canonical `www`/apex equivalent. This prevents review-key holders from turning the Finfold tracking domain into an arbitrary public redirector without depending on an incomplete public-suffix guess.

Cloudflare's outbound network boundary is an additional control. As with any hostname-based allow model, DNS rebinding is a residual risk; the Worker never sends credentials or internal headers to a source and Cloudflare Workers do not expose the account's private network by default.

## Prompt injection and evidence

Scripts, styles, iframes, templates, SVG, comments, and noscript blocks are excluded. Remaining source sections are labeled untrusted in the system and user instructions. The model cannot authorize tools or side effects. Every cited quote must be an exact substring of its stored section. Every mapped claim must resolve to a validated evidence ID and occur verbatim in both the delivered text and at least one cited quote. Absolute asset sentences that contain neither exact evidence nor an exact claim are rejected unless explicitly framed as a test or hypothesis.

## Authentication

Review keys contain 256 bits of randomness. D1 stores only a SHA-256 hash. Lookup is followed by a timing-safe hash comparison. Keys carry space-delimited scopes, an expiry, and an atomic daily allowance. Mutations additionally require an idempotency key bound to the request hash.

## Logs

Structured logs contain request ID, route, method, status, latency, provider attempt count, and validation booleans. They never include Authorization headers, raw keys, raw HTML, prompts, model output, outcome payloads, or evidence text.

## Side effects

The capability persists its own mission and anonymous attribution data. It does not publish content, authenticate to social platforms, modify third-party accounts, or initiate payments. Tracking links redirect only to a same-site HTTPS destination validated when the mission is created. Raw click counts are not treated as credible conversion outcomes by themselves.

Report vulnerabilities privately to `support@finfold.app`. Do not include active keys or customer data in a report subject line.
