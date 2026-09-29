# Test evidence for the exact review source

Review commit: `029cd0ba9aff3c25fffa33ae27f94615c1eebe2b`.
[GitHub Actions run 35704400429](https://github.com/HEchooo/agentonomy-commerce/actions/runs/35704400429) finished successfully on 2026-09-22. The full test job passed on attempt 2; the container-smoke job passed on attempt 1 and was retained when the test job was rerun. Both use the same unchanged source commit.

| Suite | Observed CI result |
| --- | --- |
| Workspace | 12 passed |
| Node | 841 passed, 1 skipped |
| End-to-end | 2 passed |
| Core | 2,095 passed |
| Marketplace | 320 passed |
| Hosted | 522 passed, 4 skipped |
| Commerce | 4 + 6 + 6 passed |
| Review, visitor sessions and API | 58 + 18 passed |
| Submission package | 6 passed |
| Solidity | 27 passed, 0 failed |
| Go | configured packages passed |

The workflow also ran doctor, application smoke checks, the demo, Python compilation and Docker purchase/restart verification. Container checks now include two isolated public visitor sessions, private API rejection, original-order replay, and public cookie-session restoration after restart. Counts describe suite executions, not distinct unique test cases across targets; skips were not verified.

## Browser and live deployment

Fresh public HTTPS browser verification passed: no manual token or registration, start, quote, purchase, read-only reload, idempotent replay, second-visitor isolation, restoring a pending new preview alongside a prior order, HttpOnly cookie, and explicit restart of an expired browser session. Public API acceptance verifies a single 0.30 report with 0.70 remaining, one settlement and one merchant delivery. The browser additionally purchases a second edited report in a separate session to check restored-preview correctness.

Deployment verification preserves the original private acceptance order and its 0.30/0.70 budget across VM stop/start and source upgrade. Public visitor session and purchase replay survive a container restart over HTTPS. See public-demo-evidence.json, public-https-evidence.json and upgrade-evidence.json. No credential or raw verifier state is published.

## Retry record and scope

Attempt 1 was unusually slow and was cancelled before its pytest traceback summary became available. Its progress output contained one failure marker mapped by collection order to the existing Core nonce-allocation concurrency test. The exact first-attempt cause is unconfirmed. No Core source or tests were changed: the focused test passed ten local runs, the complete local Core/Marketplace suite passed, and the unchanged full CI test job passed on attempt 2. The initial run is not reported as passing.

Local verification of the committed version also passed 76 Review tests, 2,095 Core tests, 320 Marketplace tests and application smoke checks. The first sandboxed local application run could not capture the runner process identity; rerunning with the required local process/loopback permissions passed. No checks were skipped or weakened to resolve that environment restriction.

Limits: simulated settlement only; no live-chain payment, real-funds test, formal penetration test, comprehensive security audit or legal compliance certification is claimed.
