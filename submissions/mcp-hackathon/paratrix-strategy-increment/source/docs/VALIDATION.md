# Functional validation

Method: `fixed-initial-80-20/v1`. Each runtime report identifies the exact source fingerprint that was checked.

## Verification evidence

The [runtime report](../../verification/workers-checks.json) records Python Workers, FastAPI and SQLite-backed Durable Objects running in local workerd. The [exported experiment](../../verification/worker-evidence.json) contains its structured inputs and calculated results. The [browser report](../../verification/workers-ui-checks.json) records workbench interaction with that runtime. Each report identifies its environment and observation time; local measurements do not establish hosted execution performance.

| Check | Observed result |
| --- | --- |
| Python behavior suite | Passed; command results and test counts are recorded in the runtime report |
| Ruff, JavaScript syntax, local dependency lock | Passed |
| AIMM example import → experiment → export → offline reproduction | Passed |
| 8 simultaneous experiments on one unseen interval | Exactly 1 declared holdout and 7 historical explorations |
| 98 existing snapshots followed by 8 concurrent writes | Exactly 2 creations and 6 HTTP 429 responses |
| 5,000 daily points per curve | 2,278,883-byte result and 3,837,779-byte evidence; exact read-back and offline reproduction passed |
| Process restart using the same state | Ordinary and large-record history and evidence hashes remained identical |
| Session and request boundaries | Foreign records/references 404; cross-origin write 403; duplicate JSON key 422; unlisted asset 404 |
| API diagnostics | Technical error messages are ASCII English |
| Robustness regressions | Malformed cookie signatures rotate safely; malformed evidence structures and duplicate JSON fields return explicit verification failures; stale history responses cannot replace newer results |
| Evidence compatibility | The fixed `local-evidence.json` regression fixture verifies unchanged; altered conclusions, labels, limitations and numbers are rejected even after rehashing |
| Workbench | Chinese errors, criteria/report text, chart switching, download and history restoration passed |

## Behavior coverage

| Area | Verified behavior |
| --- | --- |
| Model and criteria | Duplicate-A identity, cash-control identity, return/drawdown tradeoffs, no automatic pass from low correlation, and unrounded threshold boundaries |
| Input | Complete daily grid, duplicate/missing/out-of-order timestamps, incompatible clocks, incomplete costs/initial valuation/cash-flow declarations, original decimal precision, and the 2 MiB request limit |
| Records | Immutable snapshots, derived experiments, exploration labels for overlapping intervals, session isolation, and failed-save handling |
| Timestamp boundaries | Fractional-second overlap, separation, exact contact, and a one-microsecond overlap |
| Reproduction | Matching input and result, hash/normalization verification, rejection of tampering, and preservation of method version |
| Source boundaries | Complete-curve validation, preserved source declarations, and disabled external Nexus imports |
| Packaging | Exclusion of generated directories; rejection of key patterns, credential files, LFS pointers, and symlinks; destination protection and failure cleanup |

Acceptance definitions are in [ACCEPTANCE.md](ACCEPTANCE.md). The service does not make external Nexus calls; these checks do not establish hosted Nexus integration.

## Repeat the checks

Run from `source/`:

```sh
uv run pytest -q
uv run ruff check app tests scripts worker.py
node --check web/app.js
node --test tests/test_web.mjs
uv lock --check --offline
```

The local runtime suite runs in two phases:

```sh
uv run python scripts/smoke_worker.py --phase before-restart
# Restart the same local Wrangler instance, preserving its state directory.
uv run python scripts/smoke_worker.py --phase after-restart
```

The suite creates disposable local sessions and fills one snapshot quota to test its boundary. It accepts only local HTTP origins and stores private cookie state under ignored `runtime/` with mode 0600. Reproduce the supplied evidence independently:

```sh
python3 -m app.reproduce ../verification/worker-evidence.json
python3 -m app.reproduce ../verification/local-evidence.json
```

The compatibility fixture contains a v1 result without `display_language`. The verifier reproduces its Chinese presentation and compares the complete result, including labels and limitations. English results declare `display_language=en` and receive the same complete comparison.

## Runtime observations

The macOS development runtime emitted file-watcher `EMFILE` warnings. Startup, HTTP flows and restart persistence passed; automatic hot reload was not used. TestClient emits one upstream httpx deprecation warning. Recorded durations are local wall times, not CPU measurements or hosted performance guarantees.

The [API verification guide](../../verification/README.md) covers the public service, input rejection, session isolation and evidence reproduction. The [release guide](RELEASE.md) describes source-version agreement and official submission validation. User comprehension is evaluated separately through AC16 in the acceptance criteria.
