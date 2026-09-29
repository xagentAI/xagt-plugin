# Grid Witness

## Capability

- **Track:** General Challenge (Open Innovation).
- **One-line description:** Give an agent a reproducible numerical witness when a simplified grid-upgrade screen is too optimistic.
- **Who it helps:** Developers testing whether an agent can challenge a proposed plan instead of blindly accepting its optimizer output; educators demonstrating model mismatch.
- **Capability boundary:** One fixed synthetic six-line radial chain, 64 upgrade plans and three demand scales. No arbitrary network ingestion or real-world design advice. Reports AC operating-point residuals and violations; does not certify physical infeasibility or an AC global optimum.

A cost-18 plan `111000` passes the rational lossless screen but has a minimum-voltage violation after AC power flow at high load. Budget comparison finds two cost-20 plans with accepted operating points across all three scenarios. Costs are synthetic units, not money. The capability returns the actual violation magnitude and residuals, alongside an explicit unresolved state when a check cannot be trusted.

## Live API

- **API base:** https://bestdeeplearning-grid-witness.hf.space/v1
- **Health:** https://bestdeeplearning-grid-witness.hf.space/health
- **Authentication:** none, no reviewer secrets.
- **Limits:** six integer bits or integer budget 0–27, 2048-byte JSON request limit. Bounded 64-plan catalogue. No dedicated per-user rate limiter; hosting platform limits and cold starts apply; no SLA.
- **Contract:** source/README.md; `POST /v1/inspect-plan`, `POST /v1/compare-budget`, `GET /v1/benchmark`. Invalid input returns HTTP 400; unknown routes return 404.
- **Demo:** https://bestdeeplearning-grid-witness.hf.space/

## Source and reproducibility

- **Repository:** https://github.com/alexsolonsky/grid-witness
- **Review commit:** `9102fa95b06ec90b43d7c8dc397e2a03fbd0bf35`
- **Complete reviewed source:** source/
- **Tests:** `cd source && python -m pip install -r requirements-test.txt && python -m unittest discover -v` (16 tests).
- **Run locally:** install Gradio 6.27.0 and spaces in addition to requirements.txt; set SOURCE_COMMIT to the reviewed SHA; `python app.py`.
- **Deploy:** public Hugging Face Gradio Space with README configuration, free ZeroGPU allocation; set public variable SOURCE_COMMIT and upload reviewed files. All grid work uses CPU; optional one-second scheduler diagnostics satisfy the free-hosting runtime requirement. No paid hardware or external model API.
- **Version binding:** health and same-origin proof expose the public deployment SHA. Verification additionally compares all uploaded source file SHA-256 hashes against GitHub at that commit; self-reported health alone is not proof of provenance.

The classical benchmark predates the API packaging, and is identified in BENCHMARK.md. The full catalogue and all 512 encoded surrogate states are exhaustively checked; no quantum computation was performed. The original baseline has not been represented as a newly invented numerical method.

## Verification

See verification/README.md for exact commands, recorded responses and expected errors. The live API must match the declared commit before submission.

## Security and data

- **Collected:** only user-supplied binary upgrade decisions or a bounded budget for the fixed example.
- **Purpose/retention:** calculations in memory; no application database, input/output logs or stored run history. The hosting provider may retain platform access logs.
- **Third parties:** Hugging Face hosting and Gradio runtime/assets. Scientific computation has no outbound requests, model calls or paid API dependencies.
- **Secrets:** none needed or included.
- **Restrictions:** no real network or personal data should be sent. Numerical limitations are explicit in API output and README. HTTP API and numerical solver have validation tests; no claim of a production security audit.

## Support

- **Builder:** Alex SOLONSKY / Aleksei Solonskii.
- **Contact:** https://github.com/alexsolonsky/grid-witness/issues
- **License:** MIT; dependencies retain their licenses. See RIGHTS.md.
- **Registration:** Luma registration confirmed on 2026-09-12. The submitter confirmed joining the official X-Agent Telegram community on 2026-09-12.
