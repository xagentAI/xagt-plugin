# AlphaLitmus Release Readiness

**Public safe-mode deployment verified; final submission publication remains pending.**
The HTTPS service, container hardening and public review routes are recorded in
[VPS deployment](VPS-DEPLOYMENT.md). Separately authorized Studio backtests and
one read-only AlphaLitmus-to-Nexus MCP reconciliation are recorded in
[Nexus live evidence](NEXUS-LIVE-EVIDENCE.md). The public deployment keeps Nexus
and remote compute disabled; repository publication, official validation and the
submission PR are separate gates.

## Local Quality Gate

Run with Python 3.12 from the project root:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m mypy app
python -c "import app.main, app.mcp_server, app.lab, app.certificates"
python -m tools.local_smoke
```

Pytest checks its configuration/markers strictly. Ruff enables E4/E7/E9/F with no ignore list. Mypy checks all `app` modules in strict mode, without missing-import suppression or module overrides. Configuration alone is not evidence that a gate passes.

The inspected tooling is Ruff 0.16.6 and mypy 1.20.2. Runtime and development dependencies ship as pip-tools transitive SHA-256 hash locks (`requirements.in`/`requirements-dev.in` inputs, `requirements.txt`/`requirements-dev.txt` locked outputs); Docker installs with `--require-hashes`. A wheel-verified third-party license inventory is generated from downloaded artifacts without inventing project licensing or ownership. These locks were resolved on Windows; Linux/Docker installation still needs verification on the target platform, and the `python:3.12-slim` tag is mutable. See [dependencies](DEPENDENCIES.md).

## Required Acceptance Checks

Final local gates, Python 3.12.10, after the release-gate hardening:

```text
python -m pytest -q
680 passed, 1 warning in 71.30s

python -m ruff check .
All checks passed!

python -m mypy app
Success: no issues found in 18 source files

python -m pip check
No broken requirements found.

python tools/secret_scan.py
(exit 0, no findings)

python -m tools.local_smoke
(exit 0; 8 MCP tools including primary release gate, recorded replay, and fixed live pulse; REST/MCP hash-equivalent UNPROVEN synthetic report)
```

The release-gate upgrade adds `POST /v1/release-gate`, `GET /v1/release-gate/demo/{mixed,shock}`, MCP `evaluate_strategy_release` (primary, `readOnlyHint=true`), and the `app/release_gate.py` projection. Successful gate results are only issued from a source certificate accepted by the existing `verify_report` (`source_report_verified:true`); invalid sources fail closed with sanitized `REPORT_VERIFICATION_FAILED`. Verification replays the bounded reference/reconciliation calculations, so a gate call costs roughly one challenge plus one verification replay. Existing five tools and report verification remain authoritative and backward compatible. Synthetic demos remain `INSUFFICIENT_EVIDENCE`; `SURVIVED_BOUNDED_TESTS` is not deployment approval. See [agent call contract](AGENT-CALL-CONTRACT.md).

The recorded-replay upgrade adds `tools/capture_nexus_snapshot.py`, `app/recorded_nexus.py` (strict canonical loader plus real-engine replay), strict body/query-free `GET /v1/nexus/replay/candidate-v1`, MCP `replay_recorded_nexus_evidence` (seventh tool, strict empty args, `openWorldHint=false`), dashboard replay section, and production-image evidence packaging. Capture is locked to the fixed Candidate v1 identity and repository destination; the staged snapshot passes the complete repository secret scanner before atomic publication. Status: CAPTURED AND VERIFIED — capture `2026-09-19T18:45:48+00:00`, aggregate `3a086a1cbf392d15ae961227c091afa343fde5f21b3aebc2aa81ff9d33b389f8`. Genuine local REST/MCP replay is identical and yields `INCONSISTENT`/`BLOCK_DEPLOYMENT`/`DO_NOT_DEPLOY` with `TRADE_SYMBOLS MISMATCH` and `source_report_verified:true`. Hash verification is source-commit-bound content consistency, not independent source authenticity.

There were zero failures and zero skips in the final run. The warning is Starlette's use of AnyIO's deprecated BlockingPortal alias; it is not suppressed. Quantitative unchanged-fixture results recorded 2026-09-19 are historical and kept in [DEMO](DEMO.md). Full smoke evidence and its reproduction command are in [LOCAL-VERIFICATION](LOCAL-VERIFICATION.md). Smoke verifier artifacts are written only under the run's temporary directory, so a fresh clone with no ignored `reports/` directory passes.

`python -m pip_audit -r requirements.txt` is unavailable in the application environment (`No module named pip_audit`). The isolated release tooling environment (`tools/__pycache__/release-venv`, pip-audit 2.10.1) reported **no known vulnerabilities** for `requirements.txt`. That audit queries vulnerability services for locked third-party packages only; it is not a Nexus, deployment, or application-security certification.

Local health service and proof slug both returned `alpha-litmus`. The source reads only `ALPHALITMUS_COMMIT`, without a legacy fallback. Development reported `local-dev`, not an actual public review commit. Body handling is capped at 4,000,000 bytes, eight intake slots, a 10-second body deadline and two compute slots per process; `GET /health` bypasses upload intake and compute admission and never waits for body input.

A real local MCP stdio subprocess client discovered all eight tools (including primary `evaluate_strategy_release`, recorded replay, and fixed live pulse) and obtained the full mixed demo report. Its hash matched REST exactly. A separate Uvicorn subprocess served health over loopback TCP with HTTP 200. The offline verifier exited 0 for the valid exported report and 1 for its tampered counterpart. Provenance rejects `commit_reviewable=true` with `commit="abc123"` at generation, REST, MCP, and offline-verifier layers. These are local process/transport checks, not an external MCP host or public deployment.

A current Chromium pass on 2026-09-19 exercised the redesigned gate-first dashboard over public HTTPS. The mixed demo auto-loaded, the shock transition reached `INSUFFICIENT_EVIDENCE` with `COLLECT_MORE_EVIDENCE`, Copy/Download controls enabled only after a verified result, desktop and 390×844 mobile layouts had no document-level horizontal overflow, and no application console warning/error was observed. Static/TestClient and Node syntax checks remain in place. This is not formal accessibility conformance or broad cross-browser coverage.

The Windows Docker daemon remained unavailable, but the authorized target Linux
VPS subsequently built the image from the same Dockerfile and hash-locked runtime
requirements. The resulting container passed health as UID 10001 with a read-only
root filesystem, dropped capabilities, no-new-privileges, explicit resource
limits and no host port. Nexus remained disabled and no key was deployed. See
[VPS deployment](VPS-DEPLOYMENT.md). Public DNS/TLS and the final public
reviewed-commit binding are verified there.

- [x] Final source imports, tests, lint and strict types pass with recorded exact commands/environment.
- [x] REST OpenAPI and MCP `tools/list` match README request nesting, field domains and eight tool names (primary release gate, recorded replay, fixed live pulse, plus the existing five).
- [x] Synthetic examples cannot receive an eligible survival verdict; missing Nexus evidence remains unproven.
- [x] A certificate verifies offline; both an ordinary tamper and a rehashed inconsistent analysis fail verification.
- [x] Provenance contract enforced: reviewable requires nonzero lowercase 40-hex, unreviewable permits only `local-dev`; the rehashed `abc123` claim is rejected by generation, REST, MCP, and the offline verifier.
- [x] Production provenance rejects missing/invalid commit configuration; health and proof match the actual public reviewed commit.
- [x] A real named Nexus strategy completed one Studio backtest and was left stopped; its negative metrics and limitations are recorded without a profitability claim.
- [x] With explicit authorization and an in-memory strategy-bound key, AlphaLitmus consumed all four read-only Nexus MCP evidence surfaces and correctly returned `INCONSISTENT` for a cross-instrument trade mismatch. The default remains disabled and secret-free.
- [ ] The live window-compute path has not run. It retains its separate switch and per-request confirmation and is not required for the read-only reconciliation above.
- [x] Container builds on the target Linux VPS from Python 3.12, runs non-root, serves health, and includes MCP runtime dependencies.
- [x] Public DNS, automatic TLS, HTTP-to-HTTPS redirect, edge body limit, security headers and reviewer access are exercised in safe-mode deployment without regressing APIVouch health.
- [x] Fixed Candidate v1 live access is isolated from arbitrary Nexus routes, loads a bounded file-mounted secret, uses a 60-second cache, per-process rate/refresh/circuit bounds, and never substitutes recorded evidence.
- [ ] Caller authentication, per-principal distributed quotas and retention controls are still required before enabling arbitrary live Nexus access or remote compute.
- [ ] Actual source/data/branding/dependency rights and official submission artifacts are completed by authorized owners.

The healthy container is publicly reachable through verified HTTPS in safe mode
and bound to the public source commit. Official validator result, registration
proof, submission and rights clearance remain pending. Legacy negative reports
stay unchanged and labeled as described in
[BASELINE](BASELINE.md).

## Remaining Limits

- Nexus strategy and run identifiers plus one AlphaLitmus MCP snapshot have been captured, but metrics/signal lack run identifiers, trades are a 50-row recent subset versus the metric's 70, and Candidate v1 contains instruments outside the requested BTC pair. The EMA reference is separate and cannot validate the Nexus strategy. The opt-in window-stability path has never run against live Nexus; its fixtures are synthetic/documentation-derived and its reports cannot exceed `UNPROVEN`/`INCONSISTENT`.
- No complete metric/signal/run/window binding, attested closed-trade history or no-cash-flow proof. Numeric cross-surface comparisons remain insufficient even with equal values; explicit symbol/run contradictions still mismatch.
- No PSR, deflated Sharpe or selection-adjusted significance. Caller-declared variant counts do not repair selection bias; IID bootstrap and the 30-trade floor do not establish independence or future profit.
- No global multidimensional failure minimum. Cost/delay/EMA results are bounded grids and per-dimension discoveries, not a search over all joint perturbations.
- No selective sample exclusion to improve a result. Any out-of-domain bootstrap draw makes all bootstrap quantiles unavailable while other analyses remain; any replay cumulative or individual trade log return outside [-100,100] makes the entire reference analysis unavailable. Missing profit factors are never treated as passes, and later observed failures remain visible without a false bracket.
- The public source repository and matching safe-mode deployment exist, but there is no official validator result, registration proof, submission acceptance or final rights clearance yet. The public safe-mode deployment is intentionally unauthenticated because Nexus and remote compute are disabled; those capabilities must not be enabled without authentication and quotas.
