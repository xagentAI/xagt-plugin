# Test evidence for the exact review source

Review source commit: `a5f0e4ffd5f5fb69323227cf85435c30dc6177f7`.
[GitHub Actions run 35689285147](https://github.com/HEchooo/agentonomy-commerce/actions/runs/35689285147) completed successfully on 2026-09-22. Both the test and container-smoke jobs passed.

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

Public deployment evidence accompanies this file: HTTPS health/proof commit binding, rejection of unauthenticated protected calls, authenticated simulated purchase with HTTP merchant delivery, idempotent replay, container restart and full VM stop/start persistence. The acceptance order consumed 0.30 of the initial 1.00 sandbox USDC budget, with one settlement and one delivery retained across restart.

Limits: simulated settlement only; no live-chain payment or real-funds test, formal penetration test, full security audit, or legal compliance certification is claimed. Reviewer credentials still require private handoff and manual rotation.
