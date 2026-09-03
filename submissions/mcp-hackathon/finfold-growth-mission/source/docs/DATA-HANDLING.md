# Data handling

| Data | Stored | Retention | Notes |
|---|---|---:|---|
| Raw review key | No | None | Displayed once by the issuance script; SHA-256 hash only in D1. |
| Raw source HTML | No | None | Streamed, bounded, parsed, then discarded. |
| Source URL and digest | Yes | 30 days | Required for provenance and repeatability. |
| Exact evidence snippets | Yes | 30 days | Only snippets selected for the delivered mission. |
| Generated mission and asset | Yes | 30 days | Needed for retrieval and verdict comparison. |
| Tracking clicks | Daily aggregate | 30 days with mission | Anonymous raw count only. No IP address, user agent, cookie, fingerprint, or bot classification is stored. Clicks alone do not turn a closed mission into `lost`. |
| Outcome events | Yes | 30 days with mission | Caller event ID, type, quantity/value, currency, and time; no required PII fields. Events must fall inside the measurement window; revenue uses one mission target currency. |
| Structured operational logs | Yes | Cloudflare log policy | No raw page, key, prompt, evidence, or outcome payload. |

The daily retention job removes expired idempotency records, missions, and cascaded attribution. Callers should use non-identifying event IDs and avoid sending personal information. The API does not provide free-form metadata fields, which reduces accidental PII collection.
