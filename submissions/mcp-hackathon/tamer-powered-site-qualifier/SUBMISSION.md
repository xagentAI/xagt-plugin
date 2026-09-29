# Powered-Site Qualifier

## Capability

- One-line description: A deterministic, agent-callable first-pass screen for whether a powered site is ready for Bitcoin mining or AI/data-center deployment.
- Who it helps: Infrastructure investors, developers, utilities, site brokers, and AI agents that need a fast, explainable qualification before deeper diligence.
- Capability boundary: It scores structured facts; it is not engineering, utility, legal, permitting, environmental, financial, or investment diligence.

Powered-Site Qualifier addresses a practical infrastructure problem: site information is often incomplete, inconsistent, and difficult for an agent to compare. The API turns structured facts into separate Bitcoin Mining Readiness and AI/Data Center Readiness scores out of 100, an overall classification, key positives, major blockers, missing information, and recommended next questions. Scoring is deterministic and explainable; unknowns remain visible and are never guessed.

The public deployment includes a real browser UI at <https://qualifier.cryptoleaks.agency/> and a live qualification call. It also exposes an additional machine-to-machine paid capability at `/v1/paid/qualify`, protected by x402 v2 exact payment on Hedera Testnet using native HBAR. No confidential site data is required for the fictional example below.

## Live API

- API base URL: <https://qualifier.cryptoleaks.agency/v1>
- Health-check URL: <https://qualifier.cryptoleaks.agency/health>
- Deployment proof: <https://qualifier.cryptoleaks.agency/.well-known/xagent-verification.json>
- Authentication: No authentication for the unpaid route; x402 payment is required only for the paid route.
- Rate limits / known limits: The service is an initial screening aid. It accepts structured JSON and does not claim final diligence, deliverability, legal status, or investment suitability.
- API contract: <https://qualifier.cryptoleaks.agency/docs> and `source/API-SCHEMA.md`.

### Reproducible capability call

This uses the fictional, non-confidential example included in `source/examples/site-ready.json`:

```bash
curl --fail --silent --show-error \
  --request POST https://qualifier.cryptoleaks.agency/v1/qualify \
  --header 'content-type: application/json' \
  --data @source/examples/site-ready.json
```

The verified live response is HTTP 200 with Bitcoin Mining Readiness `100`, AI/Data Center Readiness `100`, and classification `READY`. The response also reports `deterministic: true`, `unknowns_are_not_guessed: true`, and `scores_are_not_advice: true`.

## Source and reproducibility

- Source repository: <https://github.com/CryptoLeaks/powered-site-qualifier>
- Review commit: `b2fc190fad8705c89ca2f07b0d0cb19c8c6c75ee`
- Source submitted in this PR: `source/`
- Run tests: `python3 -m unittest discover -s tests -v`
- Run locally: `docker compose up --build`
- Deploy: See `source/deploy/README.md`; the reviewed deployment uses the documented Docker Compose and Caddy configuration.
- Version binding: `GET /health` returns `{"status":"ok","commit":"b2fc190fad8705c89ca2f07b0d0cb19c8c6c75ee"}` and the same origin's `/.well-known/xagent-verification.json` returns schema version 1, slug `tamer-powered-site-qualifier`, and that exact commit.

## Verification

Repeatable public calls, expected results, incomplete-input behavior, and the unpaid x402 boundary are documented in `verification/README.md`.

- Health-check result: HTTP 200 and the exact reviewed commit.
- Capability call: HTTP 200, two readiness scores, positives, blockers, missing information, next questions, and classification.
- Expected error behavior: Incomplete input returns HTTP 200 while exposing missing information and blockers. Calling the paid route without a payment returns HTTP 402 and the x402 requirement.

## Security and data handling

- Data collected: JSON site facts supplied by the caller; the service does not require confidential data.
- Purpose and retention: Facts are used to calculate the response for the qualification request. No persistence is part of the reviewed application contract.
- Third parties / outbound network calls: The unpaid qualification is local deterministic scoring. The paid route uses Blocky402 verification/settlement on Hedera Testnet, as documented in `source/HEDERA-X402.md`.
- Secrets: No secrets are committed. Wallet keys and payment credentials are runtime-only and are not part of this submission.
- Known risks / restrictions: Scores are screening outputs, not professional diligence or advice. The included real Hedera proof is redacted; no new payment is required for review.

## Support

- Team / builder: Tamer / CryptoLeaks
- Contact: CryptoLeaks GitHub account and repository issues/discussion channel.
- License / rights: MIT-licensed project source; see `RIGHTS.md` for the rights declaration and third-party dependency treatment.
