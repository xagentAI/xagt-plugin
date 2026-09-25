# Implementation contract v1

This document specifies the implemented fields, endpoints, numerical limits, and evidence format. [METHOD](METHOD.md) defines the financial formulas and research interpretation; [ARCHITECTURE](ARCHITECTURE.md) describes module relationships.

## Curve input

A Curve requires every top-level field below and rejects additional fields. Each valuation point contains exactly `timestamp` and `equity`.

```json
{
  "schema_version": 1,
  "name": "Example",
  "strategy_id": "strategy-a",
  "run_id": "backtest-a",
  "source_kind": "inline_simulation",
  "currency": "USDT",
  "frequency": "1d",
  "timezone": "UTC",
  "timestamp_convention": "valuation_boundary",
  "equity_kind": "mark_to_market",
  "completeness": "complete",
  "external_cash_flows": "none",
  "cost_model": "demo-zero-fees-v1",
  "initial": {"timestamp": "2026-01-01T00:00:00Z", "equity": "10000"},
  "points": [{"timestamp": "2026-01-02T00:00:00Z", "equity": "10100"}],
  "provenance": {"description": "Self-produced simulated data", "data_version": "v1", "observed_before": true}
}
```

| Field or limit | Rule |
| --- | --- |
| `schema_version` | Integer `1`; booleans and `1.0` are not equivalent |
| `name`, `strategy_id`, `run_id` | Nonempty strings, each at most 120 characters |
| `source_kind` | `inline_simulation`, `recorded_local_aimm`, `recorded_nexus`, or `synthetic`; live-account sources are not accepted |
| `currency` | 2–20 uppercase letters or digits, beginning with a letter |
| Semantic fields | Explicit `1d`, `UTC`, `valuation_boundary`, `mark_to_market`, `complete`, and `none`; incompatible declarations are not coerced |
| `cost_model` | An explicit cost convention of at most 200 characters; A and B must match exactly; unknown costs are not treated as zero |
| `initial`, `points` | A separate initial valuation plus 1–5,000 daily valuations |
| `timestamp` | UTC ISO time ending in `Z` or `+00:00`, at most six fractional-second digits and 40 characters; points are exactly 86,400 seconds apart from the initial valuation |
| `equity` | A positive finite number or decimal string; booleans, non-finite numbers, and non-positive equity are rejected |
| `provenance` | An object, possibly empty; only `description`, `data_version`, `engine_version`, `reference`, and `observed_before` are allowed |
| Provenance limits | `description`: 2,000 characters; `reference`: 500; `data_version`/`engine_version`: 120; `observed_before`: boolean |

After `strip` and `casefold`, `cost_model` rejects exact matches for `unknown`, `unspecified`, `n/a`, `na`, `none`, `null`, `unavailable`, `not specified`, `not provided`, and `?`, plus the Chinese input markers "未知", "不明", "未说明", "未提供", and "不清楚". These are accepted-language input checks, not localized error messages. Accepting another explicit identifier does not independently certify the declared costs.

Strings cannot contain non-display control characters or isolated Unicode surrogates. `description` may contain newlines, carriage returns, and tabs. `reference` is stored as text and is not downloaded. Provenance must not contain credentials or account information.

Normalization preserves point order. It does not sort, fill, interpolate, or remove points. UTC output uses `Z`, and equity uses decimal strings without unnecessary trailing zeros. Duplicates, ordering errors, gaps, and a drifting valuation clock produce issues. The complete input is validated first; selecting a subinterval cannot conceal an original gap.

## Numerical and domain interfaces

`app/domain/engine.py` uses only the Python standard library and accesses neither the network nor storage.

| Call | Return value and failure |
| --- | --- |
| `normalize_curve(raw)` | A normalized Curve; invalid input raises `InputError` |
| `validate_pair(a, b, start=None, end=None)` | `{comparable, issues, coverage}`; `coverage=null` when inputs are not comparable |
| `evaluate(a, b, *, start=None, end=None, criteria=None, display_language="en")` | A complete Result; malformed or incompatible input and incomplete criteria raise `InputError` |

`InputError.issues` contains at most 50 items in the form `[{code, path, message}]`, without echoing raw input or internal exceptions. A and B must use the same currency and cost model. By default, their complete intervals must have the same start and end boundaries. An explicitly chosen common interval is allowed, but `start` and `end` must be valuation points present in both curves, `start` must precede `end`, and at least one daily return is required. The application never silently selects an intersection.

The method version is `fixed-initial-80-20/v1`. Numerical text is limited to 160 characters and 40 significant digits. A nonzero Decimal's adjusted exponent must be from -30 to 30. Calculation uses an independent local Decimal context with 50-digit precision and `HALF_EVEN` rounding, without extra threshold tolerance. It neither inherits the caller's configuration nor changes global settings.

HTTP parsing preserves the original text of decimal JSON numbers as strings to avoid an intermediate binary float. When Python callers supply a `float` directly, only its existing string representation is available; previously lost digits cannot be recovered.

`criteria` is either `null` or contains exactly the following four non-negative, finite values, each at most 10,000 percentage points. Partial sets, additional criteria, and booleans are rejected:

- `min_drawdown_improvement_pp`
- `max_return_sacrifice_pp`
- `min_return_above_cash_pp`
- `max_drawdown_above_cash_pp`

Outcomes use calculation precision rather than rounded display values. Comparison directions are defined in METHOD.

## Result output

| Field | Contents |
| --- | --- |
| `method_version` | `fixed-initial-80-20/v1` |
| `display_language` | `en` for newly generated English API presentation; older evidence may omit this additive field |
| `status` | `comparison_only`, `criteria_met`, or `criteria_not_met` |
| `coverage` | `start`, `end`, `observations`, `currency`, and `frequency`; observations include the initial point |
| `model` | `weights={baseline:"0.8", candidate:"0.2"}`, `cash_return="0"`, and `rebalancing="none"` |
| `scenarios` | `baseline`, `candidate`, and `cash`, each containing `label`, `total_return_pct`, `max_drawdown_pct`, and `daily_volatility_pct` |
| `series` | `timestamp`, normalized `baseline`/`candidate`/`cash` equity, and three corresponding `*_drawdown_pct` values |
| `comparison_facts` | Four `{key, label, actual_pp}` items, including in facts-only mode |
| `criteria_results` | The four facts with `threshold_pp`, `operator`, and `met`; an empty array in facts-only mode |
| `diagnostics` | `return_correlation`, `joint_loss_count`, `return_observations`, and `duplicate_curves` |
| `summary`, `limitations` | English outcome text and data/method limitations; the workbench may localize presentation |

`baseline` means 100% A. `candidate` means initially 80% A + 20% B. `cash` means initially 80% A + 20% zero-return cash. All paths start at 1; `series` is not an account balance denominated in USDT.

Equity, returns, drawdowns, volatility, and criteria are decimal strings. Counts are integers; `met` and `duplicate_curves` are booleans. With only one daily return, `daily_volatility_pct` and `return_correlation` are `null`. With more observations, correlation remains `null` when either input has constant returns. Available correlation is a finite float and does not determine criteria outcomes. `return_observations` is one lower than `coverage.observations`.

## REST endpoints

Request objects reject additional fields. Snapshot IDs are `s_` followed by 32 lowercase hexadecimal characters; experiment IDs use `e_` with the same suffix length. Successful POST creation returns 201; other successful reads and validation return 200.

| Method and path | Request or response |
| --- | --- |
| `GET /v1/demo-cases` | `{cases:[{id,name,description,kind}]}` |
| `GET /v1/demo-cases/{id}` | `{id,name,description,kind,baseline:Curve,candidate:Curve,criteria}` |
| `POST /v1/data-snapshots` | Input `{curve:Curve}`; returns the Snapshot described below |
| `POST /v1/comparison-inputs/validate` | Input `baseline_snapshot_id`, `candidate_snapshot_id`, `start`, and `end`; returns `validate_pair`; incompatible inputs still return HTTP 200 with `comparable=false` |
| `POST /v1/experiments` | Input shown below; returns `experiment_id`, `created_at`, `config`, `provenance`, `result`, and `evidence_url` |
| `GET /v1/experiments` | An `experiments` array containing `experiment_id`, `created_at`, `status`, `baseline_name`, `candidate_name`, and `mode`, in descending creation order |
| `GET /v1/experiments/{id}` | The saved experiment record |
| `GET /v1/experiments/{id}/evidence` | An `application/json` attachment named after the experiment ID |
| `GET /v1/source-status` | `{local:{available:true},nexus:{configured,verified,public_refs,note}}` |
| `POST /v1/nexus/import` | Input `{strategy_ref:"reference"}`; returns HTTP 503 `source_unavailable` because external Nexus imports are disabled |
| `GET /health` | `status`, `commit`, `source_sha256`, `method_version`, and `release_bound`; `status=ok` after a successful storage check |
| `GET /.well-known/xagent-verification.json` | `schemaVersion=1`, `slug`, and `commit` with a valid release declaration; otherwise HTTP 503 |

```json
{
  "baseline_snapshot_id": "s_0123456789abcdef0123456789abcdef",
  "candidate_snapshot_id": "s_fedcba9876543210fedcba9876543210",
  "start": null,
  "end": null,
  "criteria": null,
  "mode": "historical_exploration",
  "data_seen": true,
  "parent_experiment_id": null
}
```

`start`, `end`, `criteria`, and `parent_experiment_id` default to `null`. `mode` defaults to `historical_exploration`; `data_seen` defaults to `true` and must be a JSON boolean. Saved configuration contains resolved valuation boundaries rather than unresolved null dates. A parent experiment must belong to the current session.

A Snapshot contains `snapshot_id`, `created_at`, `curve`, `content_hash`, `raw_curve`, `raw_content_hash`, and `normalization_version`, currently `complete-daily/v1`. `raw_curve` is structured input with decimal number text preserved, not the original uploaded file bytes. Hashes use canonical JSON; both curve hashes are checked again when reading.

Experiment `provenance` contains `requested_mode`, `effective_mode`, `data_seen`, `exploration_reasons`, `holdout_note`, `locked_at`, `application_version`, `source_sha256`, and `review_commit`. Its `baseline` and `candidate` entries contain `name`, `strategy_id`, `run_id`, `source_kind`, `cost_model`, `currency`, `snapshot_id`, `content_hash`, and `observed_before`.

A declaration of seen data, a source's observed marker, historical-exploration selection, a parent experiment, or an overlapping experiment in the same session makes `effective_mode` historical exploration. Otherwise, `declared_holdout` may be recorded, but unseen data is not certified. `locked_at` is not proof of registration before data existed, and a new session cannot recover prior research history.

## Source adapters

`demos.list_cases/get_case` provides `aimm-weight`, `duplicate`, `cash`, `missing-day`, and `tradeoff`. Unknown IDs raise `KeyError`. Every call returns independent objects. The missing-day example is intentionally invalid and must be rejected on import; the other four are evaluable. All have `observed_before=true`.

The Worker disables external Nexus imports in both local development and deployment. Source status reports `configured=false`, `verified=false` and no public references; `/v1/nexus/import` returns HTTP 503 with `source_unavailable`. Examples and simulated JSON imports are the service's supported input paths. Imported data with `source_kind=recorded_nexus` is a caller-supplied provenance declaration and must satisfy the same complete-curve validation; it does not establish a live connection or authenticate the upstream result.

## Sessions, limits, and errors

The `strategy_increment_session` cookie contains a random nonce and HMAC-SHA256 signature. It is HttpOnly, SameSite=Strict, and valid for 30 days; `COOKIE_SECURE` controls Secure. The Worker obtains a stable secret from the `SESSION_SECRET` binding; Wrangler provides the local development value through `.dev.vars`. The owner is the SHA-256 of the verified nonce. Snapshot, experiment, parent, and evidence access checks ownership; absent and cross-session records both return 404. Public examples are available to all visitors.

Write requests require `application/json` and have a total body limit of 2 MiB. The entrypoint rejects duplicate keys, non-finite numbers, unknown Hosts, cross-site browser requests, and mismatched Origins. Each session allows 100 snapshots and 100 experiments. Offline evidence files are limited to 16 MiB.

Application errors use `{error:{code,message,issues:[]}}`, with English messages:

| HTTP | Code |
| --- | --- |
| 400 | `host_rejected` |
| 403 | `origin_rejected` |
| 404 | `not_found` |
| 413 | `payload_too_large` |
| 415 | `json_required` |
| 422 | `invalid_json`, `invalid_input`, `not_evaluable`, `source_not_sufficient` |
| 429 | `session_quota` |
| 503 | `source_unavailable`, `storage_unavailable`, `stored_data_mismatch`, `release_not_bound` |
| 500 | `internal_error` |

Errors do not echo keys, complete inputs, or internal exceptions. Malformed input, incompatibility, source failure, hash mismatch, and persistence failure cannot become `criteria_not_met`. Framework responses such as unsupported HTTP methods and unknown routes are outside this business-error mapping.

Creation requests are not idempotent. A failed validation or rolled-back storage transaction creates no record, but a timeout or lost response can occur after a successful save. Clients should inspect session history before retrying an experiment request; repeating the POST can create another experiment.

## Evidence and reproduction

Current evidence packages contain `schema_version`, `method_version`, `experiment_id`, `created_at`, `config`, `provenance`, `raw_curves`, `normalization_version`, `curves`, `result`, and `integrity`. `curves` contains normalized baseline/candidate inputs; `raw_curves` contains the corresponding structured inputs. `method_version` comes from the saved result and is not rewritten to the running software's version.

`integrity` contains `algorithm=sha256-canonical-json-v1`, `payload_sha256`, `baseline_sha256`, and `candidate_sha256`. Canonical JSON uses UTF-8, sorted keys, compact separators, unescaped non-ASCII characters, and no NaN. The payload hash covers the complete package after removing `integrity`; the other two hashes cover the normalized curves. Raw inputs are covered by the payload hash.

`python -m app.reproduce evidence.json` verifies schema/method versions, the three hashes, and normalized curves offline. When `raw_curves` exists, it also requires `normalization_version=complete-daily/v1` and `normalize(raw)==curve`. It then recomputes the saved interval and criteria and compares the complete result. Earlier v1 packages may omit `raw_curves` or `comparison_facts`. Older results without `display_language` are recomputed using the legacy Chinese presentation; new results use English presentation. This compatibility preserves complete comparison of existing paths, metrics, conditions, state, and presentation text rather than ignoring them.

Success reports `verified=true`, experiment ID, method, state, and payload hash. Failure reports `verified=false` and exits with status 1. `source_sha256` and `review_commit` are saved provenance; the reproducer does not independently re-establish Git or deployment identity. Successful reproduction does not prove data authenticity, authorship, authorization, future performance, or an unseen out-of-sample declaration.
