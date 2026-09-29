# Progress status

Date: 2026-09-12

## Current state

Local project prepared under `/opt/horse-lab/agents/xagent-powered-site`.

Implemented:

* FastAPI application with `POST /v1/qualify`.
* `GET /health` returning `{"status":"ok","commit":...}`.
* `GET /.well-known/xagent-verification.json` returning schema version, slug, and commit.
* Deterministic, explainable Bitcoin Mining and AI/Data Center scoring.
* Explicit missing-information, blocker, next-question, and classification output.
* Pydantic request validation with unknown-field rejection.
* Dockerfile and loopback-only Docker Compose configuration.
* Examples, API schema, README, and unit tests.

Build phase completed on 2026-09-12:

* Isolated `.venv` created with pinned `requirements.txt` and generated `requirements.lock.txt`.
* FastAPI/Uvicorn API smoke tests passed on `127.0.0.1:8787`.
* Docker image `powered-site-qualifier:local-review` built successfully.
* Container smoke tests passed on `127.0.0.1:8787` with 1 CPU, 1 GiB RAM, read-only rootfs, dropped capabilities, no privileged mode, no host networking, no host mounts, and no Docker socket.
* The service performs normal scoring without an external network dependency; scoring code uses local deterministic logic only.
* X-Agent preview package prepared under `xagent-submission/submissions/mcp-hackathon/tamer-powered-site-qualifier/`.

## Hedera x402 phase

Implemented locally, without accounts or payment execution:

* `POST /v1/paid/qualify` with x402 v2 `402` challenge and `PAYMENT-REQUIRED` header.
* Hedera testnet `exact` native-HBAR requirements (`hedera:testnet`, asset `0.0.0`, default `100000` tinybars).
* Remote facilitator adapter for Blocky402 `/verify` and `/settle`, fail-closed unless `X402_MODE=remote` and seller configuration are present.
* Explicit local mock mode and Python consuming client.
* Future real-testnet Node consuming client using official `@x402/hedera` and `@x402/fetch` packages.
* `.env.example`, evidence structure, architecture, wallet approval gate, and bounty checklist in `HEDERA-X402.md`.

Local mock flow passed: initial HTTP `402`, Hedera testnet payment requirement, consuming-agent retry, HTTP `200`, and `READY` qualification. The separate real proof below completed the facilitator and Hedera transaction steps.

The x402 implementation commit is `306a8b2c0828eb65e7e51e4f2725057b00ef536d`. The repository remains local and clean.

## Real Hedera testnet proof gate

Read-only Blocky402 check completed on 2026-09-12:

* Endpoint: `https://api.testnet.blocky402.com/supported`
* Result: Hedera testnet advertised.
* Result: x402 v2 `exact` advertised.
* Result: facilitator fee payer `0.0.7162784` advertised.
* Result: no testnet API key required according to the current Blocky402 documentation.
* Native HBAR route: selected using asset `0.0.0`, which is documented by the official Hedera x402 mechanism.

This was the pre-proof gate state and is superseded by the real proof recorded below. The buyer/seller accounts and protected secret were supplied locally for the single TESTNET run; the secret was never printed or stored in evidence.

## Local verification

Scoring, API, container, x402 mock-flow, and example-contract verification completed with:

```text
Ran 3 tests in 0.000s
OK
```

The ready example returned Bitcoin `100`, AI/data-center `100`, and `READY`. API and container checks also returned HTTP 422 for unknown fields and negative numeric input.

The project-local virtual environment contains only the pinned application dependency set. The host system Python was not modified.

## X-Agent rules verified

Official repository: `https://github.com/xagentAI/xagt-plugin`

Submission directory: `submissions/mcp-hackathon/<team-or-builder>-<project-slug>/`

Required artifacts: `SUBMISSION.md`, `submission.json`, `RIGHTS.md`, complete source under `source/`, and `verification/README.md`.

The public API must expose the exact reviewed 40-character commit at `/health`, plus same-origin `/.well-known/xagent-verification.json` with schema version, slug, and commit. A deployed API, pinned public commit, public source, reproducible instructions, and one real API call are required.

The official event page states the registration/build/submission period is September 2–19, 2026, with technical review September 20–October 1 and winners October 2–4.

## ETHOnline / Hedera x402 adaptation boundary

The same qualification endpoint now has a local x402 wrapper. Minimum additional work is:

1. Use the real Hedera testnet and Blocky402 facilitator/testnet flow.
2. Run the consuming agent with a dedicated testnet identity and payment proof.
4. Create only the minimum testnet identity/funding after explicit approval; no wallet or secret exists in this project now.
5. Demonstrate at least one successful paid request and settlement, with redacted evidence.
6. Add the public GitHub/demo links and any exact ETHGlobal submission artifacts required by the live bounty page.

Official references checked: [X-Agent repository](https://github.com/xagentAI/xagt-plugin), [X-Agent submission guide](https://github.com/xagentAI/xagt-plugin/blob/main/docs/agent-submission-guide.md), [ETHOnline 2026 Hedera bounty page](https://ethglobal.com/events/ethonline2026/prizes/hedera), [Hedera x402 overview](https://hedera.com/blog/hedera-and-the-x402-payment-standard/), and [Blocky402 API reference](https://blocky402.com/docs/api-reference/).

## Not done after the single proof

* No Hedera account, wallet, or private key created.
* No direct API port is public; only proxy ports 80/443 are exposed.
* No additional real/testnet payment or facilitator call will be made in this run.
* No Blocky402 registration or external account created.
* No GitHub fork, branch, push, PR, or X-Agent submission.
* Public deployment and HTTPS endpoint are now live; GitHub publication remains pending.
* Real paid-request evidence is complete; demo video remains outstanding.

## Before submission

1. Publish the sanitized repository only after final rights/license review.
2. Record the demo only after approval; do not repeat a payment without approval.
3. Submit only after explicit ETHOnline/X-Agent authorization.

## Local review binding

The exact core-service review commit is `f70b48d862d1d78b9f3e25346c44409e5b687a44`. It is inserted into the X-Agent preview metadata. The local runtime must receive it through `XAGENT_REVIEW_COMMIT`; the public deployment must expose the same 40-character value from both proof endpoints.

## Public deployment completed

* Public base URL: `https://qualifier.cryptoleaks.agency`.
* Health: `https://qualifier.cryptoleaks.agency/health`.
* Proof: `https://qualifier.cryptoleaks.agency/.well-known/xagent-verification.json`.
* Paid endpoint: `https://qualifier.cryptoleaks.agency/v1/paid/qualify`.
* Application: reviewed image on a private Docker network, with no host port mapping for 8787.
* Reverse proxy: Caddy, terminating automatic Let's Encrypt HTTPS and proxying internally to the API.
* Firewall: effective default-deny INPUT policy with TCP 22, 80, and 443 allowed; no 8787 rule.
* Fail2ban: active with the `sshd` jail.
* The buyer key is not present in the API container environment.

## Priority

1. ETHOnline/Hedera deadline: freeze the base API, decide the paid route, then implement and test the x402/Blocky402/Hedera testnet wrapper and consuming agent.
2. X-Agent deadline: deploy the same core service only after the payment branch is stable or keep the X-Agent submission on the unpaid core API; verify the exact reviewed commit and prepare the public submission package before September 19.

Current estimated ETHOnline/Hedera readiness: 75%. The single real Hedera TESTNET payment proof and public HTTPS service are complete; public repository, demo, and final submission remain outstanding.

## Real Hedera TESTNET proof completed

On 2026-09-12, exactly one payment was executed through the official `@x402/hedera` consuming client against the loopback API. The API returned the initial HTTP 402, Blocky402 verification succeeded, Blocky402 settlement succeeded, and the retry returned HTTP 200 with classification `READY`.

* Buyer: `0.0.10488940`
* Seller/pay-to: `0.0.10489770`
* Network: `hedera:testnet`
* Asset: native HBAR `0.0.0`
* Amount: `100000` tinybars (`0.001` HBAR)
* Fee payer: `0.0.7162784`
* Transaction: `0.0.7162784@1789186391.831327025`
* Consensus timestamp: `2026-09-12T04:13:18Z`
* Hedera Mirror Node result: `SUCCESS`; transfers show `100000` tinybars from buyer to seller.

Redacted evidence is in `evidence/hedera-real/`. No private key or raw signed payload was stored. The API remains private to Docker; no GitHub push, external submission, or mainnet action occurred.

Remaining blockers before submission: public GitHub publication, five-minute-or-less demo video, final rights confirmation, final public links, and explicit submission authorization.

## Public deployment preparation and result

Preparation completed without external exposure:

* Added `deploy/docker-compose.prod.yml` with a private internal network, API limits of 1 vCPU/1 GiB, restart policies, non-root API image, read-only filesystems, dropped capabilities, no host networking, and no Docker socket.
* Added `deploy/Caddyfile` for automatic HTTPS, HTTP-to-HTTPS redirect, 256 KB request-body limit, security headers, and rotated access logs.
* Added `deploy/README.md`, `deploy/.env.example`, and `DEMO-SCRIPT.md`.
* Tightened `.gitignore` and `.dockerignore` for secrets, keys, logs, caches, node modules, and raw payment payloads.
* `qualifier.cryptoleaks.agency` resolves to `89.58.39.50` and is now the approved public FQDN.
* Let’s Encrypt certificate is valid from 2026-09-12 through 2026-12-11; Caddy will renew automatically.
* Public health/proof/qualification checks passed; unpaid paid endpoint returned HTTP 402 with the expected Hedera TESTNET terms.
* External connection to `89.58.39.50:8787` failed as expected.

Updated readiness estimates: ETHOnline `85%`; X-Agent `85%`. The sanitized public package is committed locally. Remaining actions are GitHub publication, rights/license confirmation, demo recording, and external submissions.
