# Verification record — 2026-09-22

Environment: macOS, Python 3.12.7, independent virtual environment installed from
this export's declared dependencies. `requirements.lock` was subsequently
resolved universally for Python 3.12, including Linux platform dependencies.
PyPI was unreachable from this host; installation used the Tsinghua public PyPI
mirror with TLS verification enabled. No original Clink virtualenv is needed
for the final checkout.

Imported regression results on the exported source and independent environment:

| Suite | Result |
| --- | --- |
| Core | 2,095 passed, including real SQLite commit-contention coverage |
| Marketplace | 320 passed, including 6 new grant/policy handoff cases |
| Node | 841 passed, 1 skipped |
| Hosted + profile tests | 522 passed, 4 skipped |
| Workspace | 12 passed |
| Node profile e2e | 2 passed |
| Prediction compatibility | 16 smoke scripts passed |
| Solidity executor | 27 passed; formatting check passed |
| Go installer | 4 packages passed; vet and Linux build passed |

Five imported tests are intentionally skipped by their existing environment
gates; they are not counted as verified live infrastructure. These local suites
do not demonstrate a deployed PostgreSQL/Redis/Vault stack or live-chain payment.
Existing dependency deprecation warnings remain.

During initial checks, a Core lifecycle test could not inspect processes inside
the restricted sandbox; the full Core suite then passed outside that restriction.
A concurrent SQLite grant-test transaction error occurred intermittently during
validation and was subsequently reproduced deterministically and fixed below.
The export initially omitted Marketplace's `.dockerignore`; it was restored and
the complete Marketplace suite passed with the virtualenv on PATH.

The test command for app suites is `make PYTHON=.venv/bin/python test-apps`.
Core and Marketplace use separate processes because their legacy top-level
`services` and `shared` module names overlap. The Commerce rehearsal preserves
that process boundary.

Commerce acceptance: 16 passed (4 Core bridge, 6 purchase flow, 6 MCP/transport).
The demo ran over an actual stdio MCP client session against the imported Node
gateway. A 0.30 purchase under a signed 1.00 budget returned order count 3, total
22.25, category totals books=15.00 and food=7.25. Core reported used=0.30,
reserved=0.00, remaining=0.70, one settlement and one delivery after replay.
The existing purchase result was retrieved without payment. Negative cases
verified BUDGET_EXCEEDED, revoked grant rejection and paid-but-undelivered
terminal replay without an additional debit. Worker timeout/mismatched-response
tests ensure a broken transport cannot reuse an old reply for a new operation.

The initial grant concurrency anomaly passed 20 separate repeat invocations,
but returned during full regression. A real reader-lock test then reproduced
`PendingRollbackError` deterministically: ORM commit invalidated its transaction
after SQLite returned BUSY. The SQLite helper now flushes changes, retries the
explicit SQL COMMIT while its transaction remains valid, and finalizes ORM state
after success. Two real contention cases verify successful retry and bounded
exhaustion with complete rollback and subsequent recovery. Both failed before
the fix; the wallet identity and spending grant suites then passed (93 tests).
PostgreSQL transaction handling is unchanged.

Public MCP responses use a purchase/preview field allowlist. Black-box checks reject
nested identity overrides and verify that previews, purchases and results do not
expose internal user/agent/grant/policy identifiers or receipt signing keys.

The first GitHub Linux run exposed the per-argument limit for JavaScript passed
to `node -e`. Nine large-script invocations in six Core test files now pass their
unchanged scripts through stdin; all 249 affected tests passed locally.

The Linux lifecycle check also exposed a foreground `sleep 5` delaying Bash
TERM traps beyond the stop timeout. The Core runner now waits on a background
sleep and explicitly terminates/reaps it during cleanup. A behavioral Bash
reproduction measured approximately 5.0 seconds before and 0.2 seconds after.
