# API verification and offline reproduction

Use this workflow to verify the business API, session isolation and independently reproducible evidence. The [validation report](../source/docs/VALIDATION.md) describes behavior coverage and the environment of each recorded check.

| File | Evidence scope |
| --- | --- |
| `worker-evidence.json` | Exported local Worker experiment with English output and exact offline reproduction |
| `workers-checks.json` | Local concurrency, quota, 5,000-point, security and restart checks |
| `workers-ui-checks.json` | Chinese workbench observations with the English API |
| `local-evidence.json` | Fixed v1 compatibility fixture used by regression tests; original exported bytes retained |

Runtime and browser reports identify the measured source fingerprint and local execution environment. The compatibility fixture verifies support for v1 evidence without a language marker.

## Offline reproduction

Run from `source/`:

```sh
python3 -m app.reproduce ../verification/worker-evidence.json
python3 -m app.reproduce ../verification/local-evidence.json
```

Only the Python standard library is required; no API server, network or credentials are used. Successful output includes `verified: true`, the experiment ID, method version and payload hash. New API responses and evidence use English presentation text. The verifier also reproduces the original Chinese presentation in older v1 evidence without changing its stored bytes or weakening the result comparison.

## Select the API

Use the public origin `https://strategy-increment.raspy-boat-dbb0.workers.dev`, or follow [DEPLOYMENT.md](../source/docs/DEPLOYMENT.md) to start the same Worker locally at `http://127.0.0.1:8787`.

The request examples default to the public origin. Set `XAGT_VERIFY_ORIGIN=http://127.0.0.1:8787` to verify local Wrangler execution.

## Complete request workflow

Run in a second terminal from `source/`. The cookie jar keeps requests in the same session. The temporary directory contains only this verification run's local files.

```sh
set -eu
XAGT_VERIFY_DIR="$(mktemp -d "${TMPDIR:-/tmp}/xagt-verify.XXXXXX")"
XAGT_VERIFY_ORIGIN="${XAGT_VERIFY_ORIGIN:-https://strategy-increment.raspy-boat-dbb0.workers.dev}"

curl --fail-with-body --silent --show-error \
  --cookie-jar "$XAGT_VERIFY_DIR/cookies.txt" \
  "$XAGT_VERIFY_ORIGIN/health" --output "$XAGT_VERIFY_DIR/health.json"
curl --fail-with-body --silent --show-error \
  "$XAGT_VERIFY_ORIGIN/v1/demo-cases/aimm-weight" --output "$XAGT_VERIFY_DIR/case.json"

uv run python - "$XAGT_VERIFY_DIR" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
case = json.loads((root / "case.json").read_text())
for side in ("baseline", "candidate"):
    (root / f"{side}-input.json").write_text(json.dumps({"curve": case[side]}))
PY

for side in baseline candidate; do
  curl --fail-with-body --silent --show-error \
    --cookie "$XAGT_VERIFY_DIR/cookies.txt" \
    --header 'Content-Type: application/json' \
    --data-binary "@$XAGT_VERIFY_DIR/$side-input.json" \
    "$XAGT_VERIFY_ORIGIN/v1/data-snapshots" --output "$XAGT_VERIFY_DIR/$side-snapshot.json"
done

uv run python - "$XAGT_VERIFY_DIR" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
pair = {
    f"{side}_snapshot_id": json.loads((root / f"{side}-snapshot.json").read_text())["snapshot_id"]
    for side in ("baseline", "candidate")
}
(root / "pair-input.json").write_text(json.dumps(pair))
(root / "experiment-input.json").write_text(json.dumps({
    **pair, "criteria": None, "data_seen": True, "mode": "historical_exploration"
}))
PY

curl --fail-with-body --silent --show-error \
  --cookie "$XAGT_VERIFY_DIR/cookies.txt" --header 'Content-Type: application/json' \
  --data-binary "@$XAGT_VERIFY_DIR/pair-input.json" \
  "$XAGT_VERIFY_ORIGIN/v1/comparison-inputs/validate" --output "$XAGT_VERIFY_DIR/pair.json"
uv run python -c 'import json,sys; assert json.load(open(sys.argv[1]))["comparable"] is True' \
  "$XAGT_VERIFY_DIR/pair.json"
curl --fail-with-body --silent --show-error \
  --cookie "$XAGT_VERIFY_DIR/cookies.txt" --header 'Content-Type: application/json' \
  --data-binary "@$XAGT_VERIFY_DIR/experiment-input.json" \
  "$XAGT_VERIFY_ORIGIN/v1/experiments" --output "$XAGT_VERIFY_DIR/experiment.json"
XAGT_EXPERIMENT_ID="$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1]))["experiment_id"])' "$XAGT_VERIFY_DIR/experiment.json")"
curl --fail-with-body --silent --show-error \
  --cookie "$XAGT_VERIFY_DIR/cookies.txt" \
  "$XAGT_VERIFY_ORIGIN/v1/experiments/$XAGT_EXPERIMENT_ID/evidence" \
  --output "$XAGT_VERIFY_DIR/evidence.json"
uv run python -m app.reproduce "$XAGT_VERIFY_DIR/evidence.json"
```

Expected results: health is `ok`; validation returns `comparable: true`; the experiment is `comparison_only`; offline reproduction returns `verified: true`. A shorter equivalent workflow is available:

```sh
uv run python scripts/smoke.py --base-url "$XAGT_VERIFY_ORIGIN"
```

## Error behavior and release identity

| Scenario | Expected response |
| --- | --- |
| Create a valid snapshot or experiment | HTTP 201 |
| Invalid curve or experiment using incomparable inputs | HTTP 422 with field issues |
| Compatibility precheck with different currency or cost models | HTTP 200, `comparable: false`; no experiment is created |
| Reference a record from another session | HTTP 404 |
| Disabled external Nexus import | HTTP 503 |
| Proof without a bound release commit | HTTP 503, `release_not_bound` |

Using the same cookie jar and output directory, send invalid JSON. It must return HTTP 422 with `invalid_json` and create no snapshot:

```sh
XAGT_ERROR_HTTP="$(curl --silent --show-error \
  --cookie "$XAGT_VERIFY_DIR/cookies.txt" \
  --header 'Content-Type: application/json' --data-binary '{' \
  --output "$XAGT_VERIFY_DIR/invalid-json.json" --write-out '%{http_code}' \
  "$XAGT_VERIFY_ORIGIN/v1/data-snapshots")"
test "$XAGT_ERROR_HTTP" = "422"
uv run python - "$XAGT_VERIFY_DIR/invalid-json.json" <<'PY'
import json, sys
body = json.load(open(sys.argv[1]))
assert body["error"]["code"] == "invalid_json"
assert body["error"]["issues"] == []
print(body)
PY
```

Expected body:

```json
{"error":{"code":"invalid_json","message":"Invalid JSON, duplicate fields, or non-finite numbers.","issues":[]}}
```

Check the proof endpoint on the same origin:

```sh
curl --silent --show-error --write-out '\nHTTP %{http_code}\n' \
  "$XAGT_VERIFY_ORIGIN/.well-known/xagent-verification.json"
```

Local development builds have no release commit: health returns `commit: null` and `release_bound: false`. A production build embeds the actual Git HEAD. Both health and proof must identify that same publicly readable source commit. See [RELEASE.md](../source/docs/RELEASE.md) for formal validation.

The review package's generated `submission.json` records `reviewCommit` and the public API, health and proof addresses. The independent source repository keeps service configuration in `submission-config.json`; the [packager](../source/docs/RELEASE.md) adds the actual clean Git HEAD to the review manifest. Check that its revision matches both public endpoints.

The official `--online` validator must also confirm the public source commit, HTTPS endpoints, slug and version agreement. Cookie jars and private upload files are local verification materials and must not enter the public review package.

## Hosted release verification

The [hosted check report](hosted-checks.json) records actual Cloudflare API responses for review commit `040c70f5ca044a8c38610952b4ba174b559474ba`. It covers the AIMM workflow, a 5,000-point generated simulation, session isolation, safe errors, and unchanged stored records across deployment. The persistence section distinguishes the original record provenance from the currently deployed revision. Durations are HTTPS wall times, not CPU measurements.

Reproduce the [hosted AIMM export](hosted-evidence.json) from `source/`:

```sh
python3 -m app.reproduce ../verification/hosted-evidence.json
```

The tested default Python urllib User-Agent received Cloudflare error 1010. The included smoke client uses `StrategyIncrement-Verification/1.0`, which passed the hosted checks. Local verification of previously saved sessions used TLS 1.2 with normal certificate and hostname verification after a local TLS 1.3 handshake failed.
