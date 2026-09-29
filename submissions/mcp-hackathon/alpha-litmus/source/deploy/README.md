# AlphaLitmus VPS deployment

The checked-in Compose configuration keeps arbitrary Nexus reads and remote
compute disabled. The separately gated fixed Candidate v1 live pulse defaults
off and reads its key only from a Docker-mounted secret file.

From the project root on the VPS:

```sh
ALPHALITMUS_COMMIT=local-dev ALPHALITMUS_ENV=development \
  docker compose -f deploy/compose.yml up -d --build
```

The service joins the existing external Docker network `apivouch_edge` and is
not published on a host port. Merge `Caddyfile.alphalitmus` into the existing
Caddy configuration, validate it, and reload Caddy. DNS must map
`alphalitmus.sklab.cc` to the VPS before Caddy can obtain its certificate.

This pre-public-commit deployment must report `local-dev` and
`commit_reviewable: false`. After GitHub is restored, rebuild from the reviewed
source using its exact nonzero lowercase 40-character commit and
`ALPHALITMUS_ENV=production`, then confirm health and proof expose the same
commit.

For an authorized live-candidate deployment, place the strategy-bound key in an
untracked root-owned file, point `ALPHALITMUS_NEXUS_KEY_FILE` at it, and set
`ALPHALITMUS_ENABLE_LIVE_NEXUS=true`. Keep `ALPHALITMUS_ENABLE_NEXUS=false` and
`ALPHALITMUS_ENABLE_NEXUS_BACKTEST=false`. The live endpoint is fixed to one
strategy/symbol, performs four read-only calls, caches for 60 seconds, and never
falls back to recorded evidence. `deploy/no-nexus-key` is only a blank default
mount target; never place a credential in the repository or Compose environment.
