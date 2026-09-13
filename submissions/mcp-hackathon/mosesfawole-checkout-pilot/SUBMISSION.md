# Checkout Pilot

Checkout Pilot is a hosted payment-link and settlement demo for small merchants. It lets an agent create a payable link, inspect its status, and simulate settlement without handling private keys or moving funds.

## Capability

- **One-line description:** Create and manage payment links through a safe demo or server-side Moove Receive API adapter.
- **Who it helps:** Freelancers, tutors, consultants, event organizers, and small digital sellers.
- **Capability boundary:** Creates links and reads/settles demo records; live mode only calls Moove Receive payment-link endpoints. It does not custody keys, swap, bridge, stake, withdraw, or manufacture volume.

## Live API

- **API base URL:** https://checkout-pilot.onrender.com/v1
- **Health-check URL:** https://checkout-pilot.onrender.com/health
- **Authentication:** None in demo mode.
- **Rate limits / known limits:** Render free instances may cold-start; demo state is in-memory and resets on restart.
- **API contract:** `source/openapi.json`

## Source and reproducibility

- **Source repository:** https://github.com/mosesfawole/checkout-pilot
- **Review commit:** `1c4740857de59595f8d2bb4501f6e44d00a160f4`
- **Source submitted in this PR:** `source/`
- **Run tests:** `npm test`
- **Run locally:** `node server.mjs`
- **Deploy:** Use the included `Dockerfile` or `render.yaml`.
- **Version binding:** `SOURCE_COMMIT` is set to the review commit and is exposed by `/health` and `/.well-known/xagent-verification.json`.

## Verification

See `verification/README.md` for reproducible calls and expected responses.

## Security and data handling

- **Data collected:** Demo payment-link metadata and optional payer/merchant labels supplied in requests.
- **Purpose and retention:** In-memory demo operation only; no durable retention is intended.
- **Third parties / outbound network calls:** Live mode optionally calls the configured Moove Receive API over HTTPS.
- **Secrets:** No secrets are committed; Moove credentials remain server-side environment variables.
- **Known risks / restrictions:** Demo state is not production accounting. Reviewers should use test values and leave live credentials unset.

## Support

- **Team / builder:** Moses Fawole
- **Contact:** GitHub: https://github.com/mosesfawole
- **License / rights:** MIT; submitter can authorize review and deployment.
