# VenueClock

## Capability

- **One-line description:** Return the market session state (pre-market, regular, after-hours, holiday, weekend, or closed) and next open/close for NYSE, Nasdaq, LSE, and 24/7 crypto.
- **Who it helps:** AI agents and tools that must not hallucinate trading hours, DST, or 2026 exchange holidays when scheduling or explaining market availability.
- **Capability boundary:** Session calendars only. No orders, prices, wallet scoring, exploit detection, or financial advice. Named holidays are encoded for 2026.

## Live API

- **API base URL:** https://kele0929.github.io/v1
- **Health-check URL:** https://kele0929.github.io/health.json
- **Authentication:** none
- **Rate limits / known limits:** Public GitHub Pages. Keep request volume modest. JSON bodies are small. Unknown static paths return GitHub Pages HTML 404; the Node server in `source/` returns JSON 404/400 instead.
- **API contract:** `source/openapi.json` and `source/README.md`

## Source and reproducibility

- **Source repository:** https://github.com/kele0929/venueclock
- **Review commit:** `d1b84e00cb87b7e8811a020f497855b67bc00303`
- **Source submitted in this PR:** `source/`
- **Run tests:** `npm test`
- **Run locally:** `REVIEW_COMMIT=$(git rev-parse HEAD) npm start` then `curl http://127.0.0.1:8787/health.json`
- **Deploy:** `REVIEW_COMMIT=<review commit> npm run generate -- --out ./site` and publish `site/` to the GitHub Pages user site `kele0929/kele0929.github.io` on `main`
- **Version binding:** `GET /health.json` and `GET /.well-known/xagent-verification.json` both report commit `d1b84e00cb87b7e8811a020f497855b67bc00303`

The API exposes:

```json
// GET https://kele0929.github.io/health.json
{"status":"ok","commit":"d1b84e00cb87b7e8811a020f497855b67bc00303"}
```

```json
// GET https://kele0929.github.io/.well-known/xagent-verification.json
{"schemaVersion":1,"slug":"kele0929-venueclock","commit":"d1b84e00cb87b7e8811a020f497855b67bc00303"}
```

## Verification

The reproducible call instructions and redacted example responses are in `verification/README.md`.

- **Health-check result:** HTTP 200 JSON `status=ok` with the review commit
- **Capability call:** `GET /v1/resolve/xnys/2026-09-04.json` returns Friday sessions including regular 09:30–16:00 America/New_York
- **Expected error behavior:** `GET /v1/resolve/xnys/2026-09-07.json` is Labor Day (`status=holiday`, empty sessions). Invalid dates / unknown venues on the Node server return JSON 400/404.

## Security and data handling

- **Data collected:** none
- **Purpose and retention:** none
- **Third parties / outbound network calls:** none at runtime (static JSON). Holiday tables were compiled from public Nasdaq/NYSE and GOV.UK calendars at build time.
- **Secrets:** No secrets are committed. Review access is supplied only through an approved private channel when required.
- **Known risks / restrictions:** Calendars can change if an exchange publishes an unscheduled close. This snapshot is the 2026 schedule encoded in source. Not trading advice.

## Support

- **Team / builder:** kele0929
- **Contact:** GitHub @kele0929 · 1253719405@qq.com
- **License / rights:** MIT. The submitter authored this source and authorizes review, archival, and deployment under the program terms.
