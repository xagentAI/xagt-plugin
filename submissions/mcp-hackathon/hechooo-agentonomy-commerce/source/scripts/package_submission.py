#!/usr/bin/env python3
"""Build a reproducible, explicitly blocked X-Agent submission draft.

The package is exported from a Git commit with ``git ls-tree`` and
``git cat-file``.  It never copies the working tree, so ignored runtime data
and untracked files cannot silently enter the review artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence
from urllib.parse import urlsplit, urlunsplit


PACKAGE_NAME = "Agentonomy Commerce"
PACKAGE_SLUG = "hechooo-agentonomy-commerce"
SOURCE_REPOSITORY = "https://github.com/HEchooo/agentonomy-commerce"
OFFICIAL_REPOSITORY_URL = "https://github.com/xagentAI/xagt-plugin"
OFFICIAL_SUBMISSIONS_URL = (
    "https://github.com/xagentAI/xagt-plugin/tree/"
    "239140cc04dc82a121e9c31199bc8a12b510e130/submissions"
)
OFFICIAL_REFERENCE_COMMIT = "239140cc04dc82a121e9c31199bc8a12b510e130"
OFFICIAL_VALIDATOR_URL = (
    "https://github.com/xagentAI/xagt-plugin/blob/"
    "239140cc04dc82a121e9c31199bc8a12b510e130/scripts/validate-submission.mjs"
)

MAX_SOURCE_FILES = 2_000
MAX_SOURCE_FILE_BYTES = 5 * 1024 * 1024
MAX_SOURCE_TOTAL_BYTES = 20 * 1024 * 1024

_EXCLUDED_TOP_LEVEL = frozenset(
    {
        ".git",
        ".gitnexus",
        ".venv",
        ".venv-node",
        ".runtime",
        ".demo_runtime",
        "build",
        "dist",
        "node_modules",
        "out",
        ".artifacts",
        "submission",
        "submissions",
        "__pycache__",
        ".pytest_cache",
        "cache",
    }
)

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key_header",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
)


class PackageError(RuntimeError):
    """Raised when a package cannot be created without making a false claim."""


@dataclass(frozen=True)
class GitFile:
    path: str
    mode: str
    object_id: str


def _git(repo_root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            detail = exc.stderr.decode("utf-8", errors="replace").strip()
        else:
            detail = str(exc)
        raise PackageError(f"git command failed: {' '.join(args)}: {detail}") from exc
    return result.stdout


def git_head(repo_root: Path) -> str:
    """Return the full commit used as the package source."""

    commit = _git(repo_root, "rev-parse", "HEAD").decode("ascii", errors="strict").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PackageError("HEAD is not a full 40-character commit SHA")
    return commit


def tracked_worktree_changes(repo_root: Path) -> list[str]:
    """Return tracked changes, excluding untracked files by design."""

    raw = _git(repo_root, "status", "--porcelain=v1", "--untracked-files=no")
    return [line for line in raw.decode("utf-8", errors="replace").splitlines() if line]


def _tracked_files(repo_root: Path, commit: str) -> list[GitFile]:
    raw = _git(repo_root, "ls-tree", "-r", "-z", "--full-tree", commit)
    files: list[GitFile] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split()
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise PackageError("HEAD contains an unreadable Git tree entry") from exc
        if object_type != "blob":
            raise PackageError(f"submodules or non-file entries are not exportable: {path}")
        if mode == "120000":
            raise PackageError(f"symbolic links are not allowed in the source export: {path}")
        if mode not in {"100644", "100755"}:
            raise PackageError(f"unsupported tracked file mode {mode} for {path}")
        parts = PurePosixPath(path).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise PackageError(f"invalid tracked path: {path}")
        if any(part in _EXCLUDED_TOP_LEVEL or part.endswith(".egg-info") for part in parts):
            continue
        files.append(GitFile(path=path, mode=mode, object_id=object_id))
    return sorted(files, key=lambda entry: entry.path)


def _blob(repo_root: Path, object_id: str) -> bytes:
    return _git(repo_root, "cat-file", "blob", object_id)


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _write_file(path: Path, data: bytes, mode: str = "100644") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o755 if mode == "100755" else 0o644)


def _export_source(repo_root: Path, commit: str, source_root: Path) -> list[dict[str, object]]:
    manifest_files: list[dict[str, object]] = []
    for entry in _tracked_files(repo_root, commit):
        data = _blob(repo_root, entry.object_id)
        destination = source_root / Path(*PurePosixPath(entry.path).parts)
        _write_file(destination, data, entry.mode)
        manifest_files.append(
            {
                "mode": entry.mode,
                "path": entry.path,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    return manifest_files


def scan_content(content: str, relative_path: str) -> list[tuple[str, str]]:
    """Return redacted path/class findings for one source file."""

    findings: list[tuple[str, str]] = []
    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(content):
            findings.append((relative_path, label))
    return findings


def scan_source(source_root: Path) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for path in sorted(item for item in source_root.rglob("*") if item.is_file()):
        relative_path = path.relative_to(source_root).as_posix()
        name = path.name.lower()
        if (name.startswith(".env") and "example" not in name) or name.endswith(
            (".pem", ".p12", ".pfx", ".key")
        ):
            findings.append((relative_path, "secret_file_type"))
        content = path.read_bytes().decode("utf-8", errors="replace")
        findings.extend(scan_content(content, relative_path))
    return sorted(set(findings))


def _normalise_source_repository(value: str | None, repo_root: Path) -> str | None:
    if value:
        candidate = value.removesuffix(".git").rstrip("/")
        if candidate != SOURCE_REPOSITORY:
            raise PackageError(
                "source repository must be the configured public repository "
                f"{SOURCE_REPOSITORY}"
            )
    return SOURCE_REPOSITORY


def _proof_url(api_base_url: str | None) -> str | None:
    if not api_base_url:
        return None
    parsed = urlsplit(api_base_url)
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if parsed.hostname is None:
        return None
    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if port is not None:
        netloc += f":{port}"
    return urlunsplit((parsed.scheme, netloc, "/.well-known/xagent-verification.json", "", ""))


def _url_problems(api_base_url: str | None, health_url: str | None) -> list[str]:
    problems: list[str] = []
    parsed_api = urlsplit(api_base_url) if api_base_url else None
    parsed_health = urlsplit(health_url) if health_url else None
    for label, parsed in (("api_base_url", parsed_api), ("health_check_url", parsed_health)):
        if parsed is None:
            continue
        try:
            port = parsed.port
        except ValueError:
            problems.append(f"{label}_must_use_a_valid_port")
            port = None
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            problems.append(f"{label}_must_be_public_https")
        if port not in (None, 443):
            problems.append(f"{label}_must_not_use_custom_port")
        if parsed.hostname in {"localhost", "127.0.0.1", "::1"} or (
            parsed.hostname and parsed.hostname.endswith(".local")
        ):
            problems.append(f"{label}_must_not_be_local")
    if parsed_api and parsed_health:
        try:
            api_port = parsed_api.port or 443
        except ValueError:
            api_port = None
        try:
            health_port = parsed_health.port or 443
        except ValueError:
            health_port = None
        api_origin = (parsed_api.scheme, parsed_api.hostname, api_port)
        health_origin = (
            parsed_health.scheme,
            parsed_health.hostname,
            health_port,
        )
        if api_origin != health_origin:
            problems.append("api_health_origin_mismatch")
    return problems


def _owner_inputs(
    *,
    submitter: str | None,
    contact: str | None,
    source_repository: str | None,
    api_base_url: str | None,
    health_url: str | None,
    rights_confirmed: bool,
) -> dict[str, object]:
    return {
        "api_base_url": api_base_url,
        "contact": contact,
        "health_check_url": health_url,
        "rights_confirmed": rights_confirmed,
        "source_repository": source_repository,
        "submitter": submitter,
    }


def _render_submission(
    *,
    review_commit: str,
    source_repository: str | None,
    api_base_url: str | None,
    health_url: str | None,
    submitter: str | None,
    contact: str | None,
    rights_confirmed: bool,
) -> dict[str, str]:
    api_value = api_base_url or "PENDING_OWNER_INPUT"
    health_value = health_url or "PENDING_OWNER_INPUT"
    repository_value = source_repository or "PENDING_OWNER_INPUT"
    submitter_value = submitter or "PENDING_OWNER_INPUT"
    contact_value = contact or "PENDING_OWNER_INPUT"
    proof_value = _proof_url(api_base_url) or "PENDING_OWNER_INPUT"
    metadata = {
        "apiBaseUrl": api_base_url,
        "deploymentProofUrl": _proof_url(api_base_url),
        "healthCheckUrl": health_url,
        "name": PACKAGE_NAME,
        "reviewCommit": review_commit,
        "schemaVersion": 1,
        "slug": PACKAGE_SLUG,
        "sourceRepository": source_repository,
    }
    submission = f"""# {PACKAGE_NAME}

> BLOCKED DRAFT: owner, rights, public deployment, and eligibility evidence are pending. This file is not an official submission.

## Capability

- **One-line description:** Reconcile a supplied expense CSV through the Agentonomy Commerce review API.
- **Who it helps:** Agents operating a user-authorized commerce budget.
- **Capability boundary:** The review runtime validates identity, policy, budget, payment evidence, and merchant delivery. The merchant call is real loopback HTTP: the signed logical resource `https://merchant.agentonomy.invalid/v1/reconcile` is routed to a local `http://127.0.0.1:<port>/v1/reconcile` listener. Chain settlement is simulated, `real_funds` remains false, and no real funds are spent.

## Live API

- **API base URL:** {api_value}
- **Health-check URL:** {health_value}
- **Browser access:** When AGENTONOMY_DEMO_ORIGIN is configured, open the site and click “开始演示”. No manual token or registration is required; an HttpOnly cookie identifies an isolated visitor sandbox with 1.00 simulated USDC. Session lifetime is 7 days, up to 128 sessions and 10 new sessions/minute.
- **Operator API:** `/v1` retains private Bearer authentication; the browser uses `/demo/session` and `/demo/v1` with a same-origin cookie. No credential is committed.
- **Rate limits / known limits:** 60 authenticated requests per minute by default; 256 KiB maximum HTTP body; 128 KiB maximum UTF-8 CSV; at most 1,000 rows including duplicates; one three-letter currency per CSV; each amount must be a two-place decimal with absolute value at most 1,000,000,000,000; 0.30 sandbox USDC per delivered report; 1.00 sandbox USDC initial budget; signed bootstrap grant valid for 30 days; previews expire after 300 seconds; result payloads are retained for 7 days; the SQLite review state and settlement journal persist across restart.
- **API contract:** `GET /health` and `GET /.well-known/xagent-verification.json` are public. Bearer-authenticated `GET /v1/services`, `GET /v1/budget`, `POST /v1/previews` (JSON `{{\"offering_id\":\"csv-reconciliation-v1\",\"csv_text\":\"...\"}}` plus an `Idempotency-Key` header), `POST /v1/purchases` (JSON `{{\"preview_id\":\"...\"}}`), and `GET /v1/purchases/{{purchase_id}}` are implemented in `source/`.

## Source and reproducibility

- **Source repository:** {repository_value}
- **Review commit:** `{review_commit}`
- **Source submitted in this draft:** `source/`
- **Run tests:** `make PYTHON=.venv/bin/python test-commerce test-review test-submission`
- **Run locally:** `make PYTHON=.venv/bin/python demo` (simulated settlement only)
- **Deploy:** See [deployment instructions](source/docs/deployment.md). A public deployment is still owner-supplied evidence for this draft.
- **Version binding:** The deployed health endpoint and `/.well-known/xagent-verification.json` must expose this exact commit before review.

The API must expose, after owner deployment evidence is supplied:

```json
// GET {health_value}
{{"status":"ok","commit":"{review_commit}"}}
```
```json
// GET {proof_value}
{{"schemaVersion":1,"slug":"{PACKAGE_SLUG}","commit":"{review_commit}"}}
```

## Verification

Repeatable health, quote, purchase, read, replay, and safe-failure calls are
documented in `verification/README.md`. They remain pending until a public
origin and short-lived review access are supplied. The checked verifier is
`source/scripts/verify_review_api.py`:

```bash
BASE_URL='PENDING_OWNER_INPUT'
export AGENTONOMY_API_TOKEN='<short-lived-review-token>'
.venv/bin/python source/scripts/verify_review_api.py \\
  --base-url "$BASE_URL" \\
  --expected-commit "{review_commit}"
```

- **Health-check result:** PENDING_OWNER_INPUT
- **Capability call:** PENDING_OWNER_INPUT
- **Expected error behavior:** Invalid authentication, malformed input, limits, expired authorization, and unavailable merchant fail closed without retrying a settled payment.

## Security and data handling

- **Data collected:** Review purchase inputs, bounded CSV contents, authorization state, and redacted result metadata.
- **Purpose and retention:** Preview/input records expire after 300 seconds; delivered result payloads are retained for 7 days; persistent SQLite review state and the simulated settlement journal survive restart. Credentials and raw secrets are not logged.
- **Third parties / outbound network calls:** The merchant uses an internal logical `.invalid` resource routed to a fixed loopback HTTP listener. Core and Marketplace run in the local composition; tests make no production outbound calls.
- **Secrets:** No secrets are committed. Review access is supplied only through an approved private channel when required.
- **Known risks / restrictions:** This draft is blocked. Local settlement is explicitly simulated and is not evidence of a live blockchain transaction.

## Support

- **Team / builder:** {submitter_value}
- **Contact:** {contact_value}
- **License / rights:** PENDING_OWNER_INPUT; no license or ownership assertion is made by this draft.
"""
    if rights_confirmed and submitter:
        rights = f"""# Submission rights declaration

Project: `{PACKAGE_NAME}`
Submission slug: `{PACKAGE_SLUG}`
Submitter: `{submitter}`
Date: `PENDING_OWNER_INPUT`

rights_confirmed: true

The submitter supplied the explicit `--rights-confirmed` input for this draft. Before an official pull request, the submitter must confirm that they own, or have sufficient authorization for, the source code, dependencies, service, data, branding, and other materials submitted.

Subject to the official program terms, the submitter must authorize X-Agent to retain, reproduce, audit, test, archive, and publish the submitted program artifact for judging, fraud prevention, dispute handling, ecosystem submission, and post-award accountability.

Third-party components and their licenses: `PENDING_OWNER_INPUT`
Exceptions or restrictions: `PENDING_OWNER_INPUT`

This draft records an owner input; it is not an official rights attestation until identity, authorization, terms, and eligibility are reviewed.
"""
    else:
        rights = f"""# Submission rights declaration (BLOCKED DRAFT)

Project: `{PACKAGE_NAME}`
Submission slug: `{PACKAGE_SLUG}`
Submitter: `PENDING_OWNER_INPUT`
Date: `PENDING_OWNER_INPUT`

rights_confirmed: false

The submitter must confirm that they own, or have sufficient authorization for, the source code, dependencies, service, data, branding, and other materials submitted. This draft makes no ownership, license, or archive-rights assertion.

Third-party components and their licenses: `PENDING_OWNER_INPUT`
Exceptions or restrictions: `PENDING_OWNER_INPUT`

This template is an operational declaration, not a substitute for event terms reviewed by qualified counsel.
"""
    verification = f"""# Verification evidence (BLOCKED DRAFT)

Replace the pending values only after the owner supplies a public deployment and approved review access.

## Prerequisites

- Review commit: `{review_commit}`
- API base URL: `{api_value}`
- Authentication: short-lived access supplied through an approved private channel; no secret belongs in Git.

## 1. Health check

```bash
curl --fail --silent --show-error {health_value}
```

Expected response:

```json
{{"status":"ok","commit":"{review_commit}"}}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error {proof_value}
```

Expected response:

```json
{{"schemaVersion":1,"slug":"{PACKAGE_SLUG}","commit":"{review_commit}"}}
```

## 3. Reproducible API walkthrough

Set `BASE_URL` to the deployed root origin and provide the short-lived review
token through the environment. The API base is the origin; `/v1/` is the
capability path.

```bash
BASE_URL='PENDING_OWNER_INPUT'
export AGENTONOMY_API_TOKEN='<short-lived-review-token>'
CSV='transaction_id,date,description,amount,currency,category
t1,2026-09-01,Hosting,-12.50,USD,software
t2,2026-09-02,Invoice,40.00,USD,revenue
t1,2026-09-01,Hosting,-12.50,USD,software'

curl --fail --silent --show-error "$BASE_URL/v1/services" \\
  --header "authorization: Bearer $AGENTONOMY_API_TOKEN"
curl --fail --silent --show-error "$BASE_URL/v1/budget" \\
  --header "authorization: Bearer $AGENTONOMY_API_TOKEN"

PREVIEW=$(curl --fail --silent --show-error \\
  --request POST "$BASE_URL/v1/previews" \\
  --header "authorization: Bearer $AGENTONOMY_API_TOKEN" \\
  --header "content-type: application/json" \\
  --header "Idempotency-Key: review-preview-1" \\
  --data "$(python3 -c 'import json,sys; print(json.dumps(dict(offering_id=\"csv-reconciliation-v1\", csv_text=sys.argv[1])))' "$CSV")")
PREVIEW_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["preview_id"])' <<<"$PREVIEW")

PURCHASE=$(curl --fail --silent --show-error \\
  --request POST "$BASE_URL/v1/purchases" \\
  --header "authorization: Bearer $AGENTONOMY_API_TOKEN" \\
  --header "content-type: application/json" \\
  --data "$(python3 -c 'import json,sys; print(json.dumps(dict(preview_id=sys.argv[1])))' "$PREVIEW_ID")")
PURCHASE_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["purchase_id"])' <<<"$PURCHASE")
curl --fail --silent --show-error "$BASE_URL/v1/purchases/$PURCHASE_ID" \\
  --header "authorization: Bearer $AGENTONOMY_API_TOKEN"

# Replay the same preview key and verify the same purchase/result is returned.
REPLAY=$(curl --fail --silent --show-error \\
  --request POST "$BASE_URL/v1/previews" \\
  --header "authorization: Bearer $AGENTONOMY_API_TOKEN" \\
  --header "content-type: application/json" \\
  --header "Idempotency-Key: review-preview-1" \\
  --data "$(python3 -c 'import json,sys; print(json.dumps(dict(offering_id=\"csv-reconciliation-v1\", csv_text=sys.argv[1])))' "$CSV")")
REPLAY_PURCHASE=$(curl --fail --silent --show-error \\
  --request POST "$BASE_URL/v1/purchases" \\
  --header "authorization: Bearer $AGENTONOMY_API_TOKEN" \\
  --header "content-type: application/json" \\
  --data "$(python3 -c 'import json,sys; print(json.dumps(dict(preview_id=sys.argv[1])))' "$PREVIEW_ID")")
curl --fail --silent --show-error \\
  "$BASE_URL/v1/purchases/$PURCHASE_ID" \\
  --header "authorization: Bearer $AGENTONOMY_API_TOKEN"
REPLAY_BUDGET=$(curl --fail --silent --show-error \\
  "$BASE_URL/v1/budget" \\
  --header "authorization: Bearer $AGENTONOMY_API_TOKEN")
```

The preview response identifies `csv-reconciliation-v1` and the 0.30 sandbox
USDC price. The purchase response must report `state: delivered`,
`service_transport: http`, `real_funds: false`, and
`settlement_mode: simulated`; the sample CSV has two unique transactions,
duplicate ID `t1`, and a USD net total of `27.50`. A replay must preserve the
purchase/result and leave the budget's used amount at `0.30` with one
settlement submission. The final `REPLAY_BUDGET` response is the value to
compare with the budget response immediately after the first purchase.
The loopback merchant is HTTP, but the simulated settlement is not a live
blockchain transaction.

The same verifier used for review can run this sequence and check the commit:

```bash
export AGENTONOMY_API_TOKEN='<short-lived-review-token>'
.venv/bin/python source/scripts/verify_review_api.py \\
  --base-url "$BASE_URL" \\
  --expected-commit "{review_commit}" \\
  --purchase-id "$PURCHASE_ID" \\
  --preview-id "$PREVIEW_ID"
```

## 4. Safe failure checks

```bash
curl --silent --show-error \\
  --request POST "$BASE_URL/v1/previews" \\
  --header "authorization: Bearer <invalid-token>" \\
  --header "content-type: application/json" \\
  --header "Idempotency-Key: invalid-auth" \\
  --data '{{"offering_id":"csv-reconciliation-v1","csv_text":"bad"}}'
```

Expected failures include 401 for invalid authentication, 422 for malformed
input or a missing/invalid `Idempotency-Key`, 413 for a body over 256 KiB, and
400 for a CSV over 128 KiB, 1,000 rows, mixed currencies, or an amount whose
absolute value exceeds 1,000,000,000,000.
Expired authorization and unavailable merchant conditions fail closed without
retrying a settled payment.
"""
    return {
        "RIGHTS.md": rights,
        "SUBMISSION.md": submission,
        "submission.json": _canonical_json(metadata).decode("utf-8"),
        "verification/README.md": verification,
    }


def _official_rules(validator_path: Path | None = None) -> str:
    validator_reference = (
        f"Local validator supplied by caller: `{validator_path.resolve()}`"
        if validator_path is not None
        else f"Official validator reference: {OFFICIAL_VALIDATOR_URL}"
    )
    return f"""# Official submission references

This draft was prepared against the public X-Agent submission contract at:

- Repository: {OFFICIAL_REPOSITORY_URL}
- Submission templates and rules: {OFFICIAL_SUBMISSIONS_URL}
- Reference `main` commit fetched on 2026-09-22: `{OFFICIAL_REFERENCE_COMMIT}`
- {validator_reference}

The package script does not open an official pull request, claim deployment, or
make an ownership assertion. The validator's required metadata is intentionally
pending until the owner supplies the public repository, public API/health/proof
URLs, identity, rights authorization, and confirmation that the current
submission window and late-submission rules permit entry.
"""


def _owner_inputs_document() -> str:
    return """# Owner inputs required before an official submission

Supply and independently verify each item before copying this draft into an
official pull request:

- Legal submitter identity or entity and a support contact.
- Public source repository URL and the exact clean review commit that is deployed.
- Public HTTPS API base URL, health URL, and standard deployment-proof response.
- Rights to submit, reproduce, audit, test, archive, and publish the source,
  dependencies, service, data, branding, and any third-party components.
- Review the automated dependency inventory at
  `source/docs/python-dependency-license-inventory.json` as a starting point;
  confirm complete third-party licenses, notices, exceptions, and restrictions
  through legal/owner review. The inventory is not a complete rights grant.
- Review-window and late-submission eligibility, including the applicable
  deadline and confirmation from the program owner if needed.
- Repeatable health and capability calls with short-lived review access shared
  only through the approved private channel.

Until these fields are filled and verified, `preflight.json` must remain
`blocked` and this directory is only a local draft.
"""


def _preflight(
    *,
    review_commit: str,
    tracked_changes: Sequence[str],
    owner: dict[str, object],
    manifest_files: Sequence[dict[str, object]],
    manifest_sha256: str,
    secret_findings: Sequence[tuple[str, str]],
) -> dict[str, object]:
    submitter = owner["submitter"]
    contact = owner["contact"]
    source_repository = owner["source_repository"]
    api_base_url = owner["api_base_url"]
    health_url = owner["health_check_url"]
    rights_confirmed = bool(owner["rights_confirmed"])
    reasons: list[str] = []
    if not submitter:
        reasons.append("submitter_identity_pending")
    if not contact:
        reasons.append("support_contact_pending")
    if not source_repository:
        reasons.append("source_repository_pending")
    if not rights_confirmed or not submitter:
        reasons.append("rights_confirmation_pending")
    if not api_base_url:
        reasons.append("api_base_url_pending")
    if not health_url:
        reasons.append("health_check_url_pending")
    reasons.extend(_url_problems(api_base_url, health_url))
    if not api_base_url or not health_url:
        reasons.append("deployment_verification_pending")
    else:
        # This script is offline by design; URL presence does not prove a live service.
        reasons.append("deployment_verification_pending")
    if tracked_changes:
        reasons.append("tracked_source_changes_present")
    if len(manifest_files) > MAX_SOURCE_FILES:
        reasons.append("source_file_count_exceeded")
    total_bytes = sum(int(item["size"]) for item in manifest_files)
    if total_bytes > MAX_SOURCE_TOTAL_BYTES:
        reasons.append("source_total_size_exceeded")
    if any(int(item["size"]) > MAX_SOURCE_FILE_BYTES for item in manifest_files):
        reasons.append("source_file_size_exceeded")
    if secret_findings:
        reasons.append("secret_scan_findings")
    reasons.append("deadline_eligibility_pending")
    return {
        "blockedReasons": sorted(set(reasons)),
        "manifestSha256": manifest_sha256,
        "ownerInputs": owner,
        "reviewCommit": review_commit,
        "secretFindings": [list(finding) for finding in secret_findings],
        "source": {
            "fileCount": len(manifest_files),
            "totalBytes": total_bytes,
            "trackedChanges": list(tracked_changes),
        },
        "status": "ready" if not reasons else "blocked",
    }


def _prepare_output(output: Path) -> None:
    if output.exists():
        if output.is_symlink() or not output.is_dir():
            raise PackageError("output must be a directory")
        if any(output.iterdir()):
            raise PackageError("output directory must be absent or empty")
    else:
        output.mkdir(parents=True, exist_ok=False)


def create_package(
    *,
    output: Path,
    repo_root: Path,
    api_base_url: str | None = None,
    health_url: str | None = None,
    submitter: str | None = None,
    contact: str | None = None,
    rights_confirmed: bool = False,
    source_repository: str | None = None,
    validator_path: Path | None = None,
) -> dict[str, object]:
    """Create the package and return its redacted preflight report."""

    repo_root = repo_root.resolve()
    output = Path(output)
    if output.exists() and output.is_symlink():
        raise PackageError("output must not be a symbolic link")
    output = output.resolve()
    if not (repo_root / ".git").exists():
        raise PackageError(f"not a Git repository: {repo_root}")
    commit = git_head(repo_root)
    tracked_changes = tracked_worktree_changes(repo_root)
    source_repository = _normalise_source_repository(source_repository, repo_root)
    owner = _owner_inputs(
        submitter=submitter,
        contact=contact,
        source_repository=source_repository,
        api_base_url=api_base_url,
        health_url=health_url,
        rights_confirmed=rights_confirmed,
    )
    release_ready_shape = all(
        (
            submitter,
            contact,
            source_repository,
            api_base_url,
            health_url,
            rights_confirmed,
        )
    )
    if release_ready_shape and tracked_changes:
        raise PackageError(
            "tracked source changes must be committed before a release-ready package"
        )

    _prepare_output(output)
    source_root = output / "source"
    source_root.mkdir()
    manifest_files = _export_source(repo_root, commit, source_root)
    manifest = {
        "commit": commit,
        "fileCount": len(manifest_files),
        "files": manifest_files,
        "schemaVersion": 1,
        "sourceRepository": source_repository,
        "totalBytes": sum(int(item["size"]) for item in manifest_files),
    }
    manifest_bytes = _canonical_json(manifest)
    _write_file(output / "source-manifest.json", manifest_bytes)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    _write_file(
        output / "source-manifest.sha256",
        f"{manifest_sha256}  source-manifest.json\n".encode("ascii"),
    )
    secret_findings = scan_source(source_root)
    report = _preflight(
        review_commit=commit,
        tracked_changes=tracked_changes,
        owner=owner,
        manifest_files=manifest_files,
        manifest_sha256=manifest_sha256,
        secret_findings=secret_findings,
    )
    rendered = _render_submission(
        review_commit=commit,
        source_repository=source_repository,
        api_base_url=api_base_url,
        health_url=health_url,
        submitter=submitter,
        contact=contact,
        rights_confirmed=rights_confirmed,
    )
    for relative_path, content in rendered.items():
        _write_file(output / relative_path, content.encode("utf-8"))
    _write_file(output / "OFFICIAL_RULES.md", _official_rules(validator_path).encode("utf-8"))
    _write_file(output / "OWNER_INPUTS.md", _owner_inputs_document().encode("utf-8"))
    _write_file(output / "preflight.json", _canonical_json(report))
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-base-url")
    parser.add_argument("--health-url")
    parser.add_argument("--submitter")
    parser.add_argument("--contact")
    parser.add_argument("--rights-confirmed", action="store_true")
    parser.add_argument(
        "--source-repository",
        help="optional canonical source URL; it must match the configured public repository",
    )
    parser.add_argument(
        "--validator-path",
        type=Path,
        help="optional local validator path to record in OFFICIAL_RULES.md",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, repo_root: Path | None = None) -> int:
    args = _parser().parse_args(argv)
    root = repo_root.resolve() if repo_root is not None else Path(__file__).resolve().parents[1]
    report = create_package(
        output=args.output,
        repo_root=root,
        api_base_url=args.api_base_url,
        health_url=args.health_url,
        submitter=args.submitter,
        contact=args.contact,
        rights_confirmed=args.rights_confirmed,
        source_repository=args.source_repository,
        validator_path=args.validator_path,
    )
    print(
        json.dumps(
            {
                "blockedReasons": report["blockedReasons"],
                "manifestSha256": report["manifestSha256"],
                "reviewCommit": report["reviewCommit"],
                "status": report["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PackageError as exc:
        print(f"package submission failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
