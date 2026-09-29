# Test evidence for the exact review source

Review source commit: `79b657e7c63158fafc657cf6370048bcde384c57`.
[GitHub Actions run 35699277965](https://github.com/HEchooo/agentonomy-commerce/actions/runs/35699277965) completed successfully on 2026-09-22. Both the test and container-smoke jobs passed.

| Suite | Observed result |
| --- | --- |
| Workspace | 12 passed |
| Node | 841 passed, 1 skipped |
| End-to-end | 2 passed |
| Core | 2,095 passed |
| Marketplace | 320 passed |
| Hosted | 522 passed, 4 skipped |
| Commerce | 4 + 6 + 6 passed |
| Review API and HTTP transport | 32 + 18 passed |
| Submission package | 6 passed |
| Solidity | 27 passed, 0 failed |
| Go | configured packages passed |

The workflow also ran doctor, the demo, Python compilation, and Docker container purchase/restart smoke verification. Counts describe suite executions, not a claim of distinct unique test cases across all targets. Skipped tests were not verified by this CI run.

Public deployment evidence accompanies this file: HTTPS health/proof commit binding, rejection of unauthenticated protected calls, authenticated simulated purchase with HTTP merchant delivery, idempotent replay, container restart and VM stop/start and source-upgrade persistence. Original-version acceptance evidence is labelled under history/a5f0e4f; current-version deployment evidence is in upgrade-evidence.json. The acceptance order consumed 0.30 of the initial 1.00 sandbox USDC budget, with one settlement and one delivery retained across restart.

Limits: simulated settlement only; no live-chain payment or real-funds test, formal penetration test, full security audit, or legal compliance certification is claimed. Reviewer credentials still require private handoff and manual rotation.

## Local targeted verification

The same 18-file, 67-occurrence sample-identity change passed Commerce, Node, end-to-end, Review API and submission-package targets locally, plus 14 changed Prediction Markets mock/unit smoke scripts. A separate deployment upgrade harness passed eight offline tests for saved-order replay, changed results/counters, missing IDs, original evidence preservation and safe output. The harness is deployment tooling, not part of the product CI count above.
