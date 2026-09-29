"""Tests for the reproducible, deliberately blocked submission draft."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import package_submission


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(output: Path, *args: str) -> int:
    return package_submission.main(
        ["--output", str(output), *args],
        repo_root=REPO_ROOT,
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_default_draft_exports_review_commit_and_blocks_missing_owner_evidence(
    tmp_path: Path,
) -> None:
    output = tmp_path / "draft"

    assert _run(output) == 0

    metadata = _read_json(output / "submission.json")
    preflight = _read_json(output / "preflight.json")
    head = package_submission.git_head(REPO_ROOT)

    assert metadata["reviewCommit"] == head
    assert metadata["slug"] == "hechooo-agentonomy-commerce"
    assert metadata["sourceRepository"] == (
        "https://github.com/HEchooo/agentonomy-commerce"
    )
    assert metadata["apiBaseUrl"] is None
    assert metadata["healthCheckUrl"] is None
    assert metadata["deploymentProofUrl"] is None
    assert preflight["status"] == "blocked"
    assert {
        "submitter_identity_pending",
        "rights_confirmation_pending",
        "api_base_url_pending",
        "health_check_url_pending",
        "deadline_eligibility_pending",
    }.issubset(preflight["blockedReasons"])

    assert (output / "SUBMISSION.md").is_file()
    assert (output / "RIGHTS.md").is_file()
    assert (output / "verification" / "README.md").is_file()
    guide = (REPO_ROOT / "submission" / "README.md").read_text(encoding="utf-8")
    guide_one_line = " ".join(guide.split())
    assert (
        "--output .artifacts/submissions/mcp-hackathon/"
        "hechooo-agentonomy-commerce"
    ) in guide_one_line
    assert "submissions/mcp-hackathon/hechooo-agentonomy-commerce/" in guide
    submission = (output / "SUBMISSION.md").read_text(encoding="utf-8")
    verification = (output / "verification" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "csv-reconciliation-v1" in submission
    assert "60 authenticated requests per minute" in submission
    assert "source/scripts/verify_review_api.py" in submission
    assert "source/docs/deployment.md" in submission
    assert "csv-reconciliation-v1" in verification
    assert "Idempotency-Key: review-preview-1" in verification
    assert "POST \"$BASE_URL/v1/purchases\"" in verification
    assert "REPLAY_PURCHASE=$(curl" in verification
    assert "REPLAY_BUDGET=$(curl" in verification
    assert "--purchase-id \"$PURCHASE_ID\"" in verification
    assert "--preview-id \"$PREVIEW_ID\"" in verification
    assert "missing/invalid `Idempotency-Key`" in verification
    assert "commerce_analytics" not in verification
    assert "/private/tmp" not in (output / "OFFICIAL_RULES.md").read_text(
        encoding="utf-8"
    )
    head_readme = package_submission._git(REPO_ROOT, "show", "HEAD:README.md")
    assert (output / "source" / "README.md").read_bytes() == head_readme


def test_source_export_is_git_tracked_deterministic_and_non_recursive(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    _run(first)
    _run(second)

    assert (first / "source-manifest.json").read_bytes() == (
        second / "source-manifest.json"
    ).read_bytes()
    first_files = sorted(
        path.relative_to(first / "source").as_posix()
        for path in (first / "source").rglob("*")
        if path.is_file()
    )
    second_files = sorted(
        path.relative_to(second / "source").as_posix()
        for path in (second / "source").rglob("*")
        if path.is_file()
    )
    assert first_files == second_files
    assert not any(
        path.startswith(
            (".git/", ".venv/", ".runtime/", ".artifacts/", "submission/")
        )
        for path in first_files
    )

    manifest = _read_json(first / "source-manifest.json")
    readme_entry = next(item for item in manifest["files"] if item["path"] == "README.md")
    head_readme = package_submission._git(REPO_ROOT, "show", "HEAD:README.md")
    assert readme_entry["sha256"] == hashlib.sha256(head_readme).hexdigest()
    assert readme_entry["size"] == len(head_readme)


def test_explicit_owner_inputs_are_recorded_without_claiming_deployment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "owner-inputs"
    monkeypatch.setattr(package_submission, "tracked_worktree_changes", lambda _repo_root: [])

    _run(
        output,
        "--api-base-url",
        "https://review.example.invalid",
        "--health-url",
        "https://review.example.invalid/health",
        "--submitter",
        "Owner pending verification",
        "--contact",
        "owner@example.invalid",
        "--rights-confirmed",
        "--source-repository",
        "https://github.com/HEchooo/agentonomy-commerce.git",
    )

    metadata = _read_json(output / "submission.json")
    preflight = _read_json(output / "preflight.json")
    rights = (output / "RIGHTS.md").read_text(encoding="utf-8")

    assert metadata["sourceRepository"] == (
        "https://github.com/HEchooo/agentonomy-commerce"
    )
    assert metadata["apiBaseUrl"] == "https://review.example.invalid"
    assert metadata["healthCheckUrl"] == "https://review.example.invalid/health"
    assert metadata["deploymentProofUrl"] == (
        "https://review.example.invalid/.well-known/xagent-verification.json"
    )
    assert preflight["status"] == "blocked"
    assert "deployment_verification_pending" in preflight["blockedReasons"]
    assert "deadline_eligibility_pending" in preflight["blockedReasons"]
    assert "rights_confirmed: true" in rights
    assert "Owner pending verification" in rights


def test_release_ready_shape_rejects_tracked_dirty_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        package_submission,
        "tracked_worktree_changes",
        lambda _repo_root: [" M README.md"],
    )

    with pytest.raises(package_submission.PackageError, match="tracked source"):
        _run(
            tmp_path / "dirty",
            "--api-base-url",
            "https://review.example.invalid",
            "--health-url",
            "https://review.example.invalid/health",
            "--submitter",
            "Owner",
            "--contact",
            "owner@example.invalid",
            "--rights-confirmed",
            "--source-repository",
            "https://github.com/HEchooo/agentonomy-commerce",
        )


def test_secret_scan_reports_only_path_and_pattern_class() -> None:
    private_key_header = "-----BEGIN " + "PRIVATE KEY-----"
    private_key_footer = "-----END " + "PRIVATE KEY-----"
    findings = package_submission.scan_content(
        f"{private_key_header}\nsecret\n{private_key_footer}\n",
        "source/fake.txt",
    )

    assert findings == [("source/fake.txt", "private_key_header")]
    assert "secret" not in " ".join(finding[1] for finding in findings)


def test_rewritten_fake_private_key_fixtures_do_not_trigger_baseline_scan(
    tmp_path: Path,
) -> None:
    output = tmp_path / "fixture-scan"
    _run(output)

    for relative_path in (
        "source/apps/facilitator/tests/test_config.py",
        "source/packaging/linux/installer/internal/archive/archive_test.go",
    ):
        assert (output / relative_path).is_file()
    for relative_path in (
        "apps/facilitator/tests/test_config.py",
        "packaging/linux/installer/internal/archive/archive_test.go",
    ):
        assert package_submission.scan_content(
            (REPO_ROOT / relative_path).read_text(encoding="utf-8"), relative_path
        ) == []
