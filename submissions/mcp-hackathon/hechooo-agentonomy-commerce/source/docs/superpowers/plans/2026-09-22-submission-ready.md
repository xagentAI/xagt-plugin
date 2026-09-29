# Agentonomy Commerce submission preparation implementation plan

> **For agentic workers:** Use subagent-driven-development for the bounded tasks below. Main owns architecture, security, integration and final acceptance.

**Goal:** Deliver a deployable, persistent HTTP review service and an honest, reproducible submission package without inventing public deployment, ownership or eligibility evidence.

**Architecture:** Keep imported Core and Marketplace as business authorities. Extend the explicit sandbox composition with restart-safe Core state, a real loopback HTTP merchant, durable result storage, and a single-tenant authenticated FastAPI facade. The merchant performs CSV reconciliation; payment remains simulated and is labelled in API responses. Package exactly the committed source for official review, with a separate blocked draft until owner-supplied fields are available.

**Tech stack:** Python 3.12, FastAPI, SQLite, httpx, standard-library CSV/HTTP, existing Core and Marketplace, Docker.

## Global constraints

- Do not modify the original Clink checkout.
- No real funds, wallet private-key persistence, forged deployment evidence or unsigned budget authorization.
- API is a single review tenant with mandatory bearer token; no public reset, top-up, grant-creation or merchant-URL input.
- Core is the sole authority for identity, signed grants, policy, budget and settlement.
- Existing demonstration remains compatible. The persistent review runtime never silently regenerates a grant on restart, revocation, expiry or corrupt state.
- Real HTTP merchant execution is distinct from simulated chain settlement. All public purchase responses state `real_funds: false` and `settlement_mode: simulated`.
- One server process owns one state directory. Reject duplicate ownership. Results and request inputs have documented retention; no raw input or credentials in logs.
- `GET /health` and `GET /.well-known/xagent-verification.json` are public and return configured exact 40-character source commit and slug. These responses alone are not claimed as deployment proof.
- No official PR or RIGHTS attestation until submission eligibility, public URLs and the submitter's identity/authorization are supplied.
- Use GitNexus impact before modifying existing symbols and detect-changes before committing. Tests must exercise behavior, not source strings.

## Task 1: Restart-safe sandbox Core (execution agent)

Files: `examples/commerce/core_worker.py`, `examples/commerce/core_bridge.py`, new `tests/commerce/test_core_persistence.py`.

Interface: `CoreBridge(state_dir: Path, *, persistent: bool = False)`; CLI worker accepts `--persistent`. Default local demo behavior stays unchanged. Persistent mode reuses signed wallet identity and grant from SQLite via a versioned metadata file; only public wallet address/identity/grant IDs are stored, never the wallet signing key. Receipt HMAC secret is generated and protected in local runtime state. Simulated RPC transactions/receipts are journaled durably, preserving transaction identity and submission count on restart. Bootstrap grant expires after 30 days; expiry/revocation never triggers replacement.

- [x] Write and run failing restart tests: initial identity/grant unchanged across process restart; depleted/revoked state retained; missing/corrupt metadata with existing DB fails closed; no wallet key in metadata; persisted simulated settlement evidence remains verifiable.
- [x] Implement persistent bootstrap and journal with atomic writes and one-owner lock; leave nonpersistent defaults intact.
- [x] Run `PYTHONPATH=. .venv/bin/python -m pytest -q tests/commerce/test_core_bridge.py tests/commerce/test_core_persistence.py` and report evidence.

## Task 2: Real HTTP CSV merchant (execution agent)

Files: new `agentonomy_commerce/merchant.py`, `tests/commerce/test_review_merchant.py`, `examples/data/expenses.csv`.

Interfaces: `reconcile_csv(csv_text: str) -> dict`; `ReviewMerchant(state_dir: Path, *, receipt_secret: str, network: str, token: str, pay_to: str, port: int)` context manager, with `endpoint` property `http://127.0.0.1:<port>/v1/reconcile`.

CSV columns: `transaction_id,date,description,amount,currency,category`. Accept at most 1000 rows, 128 KiB UTF-8, ISO dates, two-place signed Decimal amounts and one three-letter currency. Reject duplicate IDs with conflicting content. Return unique transaction count, input row count, duplicate IDs, income/expense/net decimal totals and per-category totals; disclose exact duplicate handling. Synthetic example is labelled.

- [x] Write failing tests for valid reconciliation, duplicates, invalid date/amount/header, mixed currencies and size limits.
- [x] Implement computation and real loopback HTTP POST server. Require verified Core receipt signature and exact merchant `commerce_analytics`, resource endpoint, network/token/payee, settled status and 0.30 price. Bind receipt input hash to body and Idempotency-Key to purchase scope. Store successful result per purchase with input hash atomically; same purchase with different input returns 409. Never trust client price or identity.
- [x] Test real httpx calls (no MockTransport), rejected/altered receipts, idempotent replay and merchant restart result recovery.

## Task 3: Submission draft and packaging (execution agent)

Files: new `submission/` draft files, `scripts/package_submission.py`, `tests/commerce/test_submission_package.py`; update only the two fake private-key-header test fixtures in `apps/facilitator/tests/test_config.py` and `packaging/linux/installer/internal/archive/archive_test.go` without weakening behavior.

Interface: CLI `python scripts/package_submission.py --output DIR [--api-base-url URL --health-url URL --submitter NAME --contact VALUE --rights-confirmed]`. Default creates a clearly blocked draft and `source/` from git-tracked reviewed source only. No `.git`, venv, runtime data, build artifacts, symlinks or secrets. Explicit metadata commit is the actual clean source HEAD; reject dirty tracked source for release-ready packages. Exclude generated submission/source recursion. Draft fields use null/explicit pending status; do not put a fake URL or rights assertion into official metadata.

- [x] Read current official template/validator with agent-reach GitHub tools; record reference URL/commit and prepare exact required documents with pending fields listed separately.
- [x] Implement deterministic source export and SHA-256 manifest; source reflects commit, retains applicable notices, public dependencies and provenance. Validate file counts/size and baseline patterns without printing secrets. Missing owner/deployment evidence yields an explicit blocked preflight, never success.
- [x] Test exclusion, dirty tree rejection, false fixture scan resolution and deterministic source hashes.
- [x] Document legal entity/rights/contact, API origin and deadline confirmation as owner inputs; no license is invented.

## Task 4: Persistent review runtime and HTTP API (main)

Files: new `agentonomy_commerce/{__init__,storage,runtime,worker,api,settings,verify}.py`, `tests/commerce/test_review_api.py`, `tests/commerce/test_review_restart.py`, `Dockerfile`, `compose.yaml`, `.dockerignore`, deployment/verification docs; update Makefile/CI/README.

Interfaces: `ReviewRuntime(state_dir, merchant_port)` wraps real Marketplace services and persistent CoreBridge. SQLite TTL store conforms to imported EphemeralStore methods and retains result mailboxes for 7 days. Purchase/preview identity stays server-owned. Worker has a fixed operation allowlist and bounded JSON frames; public API never imports incompatible legacy service namespaces into one process.

HTTP routes: public health/proof; authenticated `GET /v1/services`, `GET /v1/budget`, `POST /v1/previews` body `{offering_id,csv_text}`, `POST /v1/purchases` body `{preview_id}` and `GET /v1/purchases/{purchase_id}`. Strict schemas, bearer token comparison, body/rate limits, timeouts and redacted errors; no reset endpoint. OpenAPI describes side effects and sandbox limits.

- [x] Write failing API/auth/body-limit and restart acceptance tests.
- [x] Implement worker boundary, durable input/result storage, real merchant integration and preview idempotency. Expose only allowlisted public fields.
- [x] Verify a purchase and its result survive server restart without increasing used budget or settlement count. Verify expired/revoked grants, budget exhaustion, malformed/oversize inputs and unavailable merchant fail safely.
- [x] Provide Docker runtime with a persistent volume, non-root process and mandatory secret configuration; local launch command and sample curl verification. No public deployment is claimed.
- [x] Produce a short reproducible demo script/report against real local HTTP; compare health/proof commit to source and check duplicate execution, bad authentication and restart invariants.

## Task 5: Integration, release preparation and handoff (main)

- [ ] Review each task's diff and test evidence; run broad review of the integrated change.
- [ ] Run `make PYTHON=.venv/bin/python test-commerce test-workspace test-node test-e2e test-apps test-hosted`, Go and contracts where changed/relevant, plus official offline preflight on prepared artifacts. Classify missing public/rights evidence separately from code defects.
- [ ] Sync verified source into the sibling repo, commit/push preparation changes, confirm CI. Rebuild the submission draft from the final commit and record source hash manifest outside the repository to avoid recursive packages.
- [ ] Report actual local/CI results and a concise list of owner-dependent blocks. Never call the project deployed or officially submitted without evidence.

## Acceptance status before publication

The local implementation and code review are complete. The final publication
checks below must be bound to the final clean commit: GitHub regression and
container smoke, final local HTTP/restart evidence, and a committed-source
submission draft. Their machine-generated evidence belongs in the ignored
`.artifacts/` directory; the draft remains blocked on owner/deployment/eligibility
inputs even when code checks pass.
