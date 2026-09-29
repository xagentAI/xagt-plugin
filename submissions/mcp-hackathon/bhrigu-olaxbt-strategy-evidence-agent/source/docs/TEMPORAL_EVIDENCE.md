# Temporal evidence contract

BHRIGU treats time as evidence, not as a prediction claim.

`FIELD → WINDOW → REALITY → MEMORY → NEXT WINDOW`

## SEP_10_2026

The original `lib/window.mjs` was committed before the boundary and remains byte-identical. CI pins its SHA-256:

`fd92dc8a578a2f5f393b87d3f0e65bdf2f8b9ff828ddccf21eabce66d6d39998`

Boundary: `2026-09-10T00:00:00Z`.

A post-boundary reality observation is now stored in `lib/evidence.mjs` and mirrored as `evidence/SEP_10_2026_POSTBOUNDARY.json`. CI pins the evidence artifact SHA-256 `80bc4e19efa6858371559815a08fbc6224a34c751658d410d6aa7d6ad3b57027`. It records the live runtime observation, exact runtime commit, direct Binance cross-check, and the limitation that an independent protocol-height probe timed out.

## SEP_17_2026

`lib/window-sep17.mjs` is the second genuine future precommit. Its public proof artifact `evidence/SEP_17_2026_PRECOMMIT.json` is pinned to SHA-256 `19a27baa6c5f55efbfda84782cf4920374c82323f13f6eabce7d63ed2f0a13f2`. Its baseline was captured on 2026-09-10, seven days before the boundary. No post-boundary evidence exists yet. After the boundary, any evidence must be appended; the baseline must not be rewritten.

## Agent value

An agent can ask:

1. What was fixed before the boundary?
2. What is true now?
3. What changed relative to the precommit?
4. What durable evidence exists?
5. What future precommit is next?

The server remains read-only. It never writes observations during an MCP call and has zero trading, wallet, payment, transfer, or private-account authority.
