import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.certificates import canonical_hash, canonical_json, content_hash, verify_report
from app.contracts import ChallengeRequest
from app.lab import challenge
from app.verify import main


@pytest.fixture(scope="module")
def certificate() -> dict[str, Any]:
    return challenge(ChallengeRequest(mode="nexus")).model_dump(mode="json")


@pytest.mark.parametrize("left,right", [(1, 1.0), (-0., 0), ({"a": 1, "b": 2}, {"b": 2., "a": 1.})])
def test_numeric_canonical_equivalence(left: object, right: object) -> None:
    assert canonical_hash(left) == canonical_hash(right)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), {1: "a"}, (1, 2), {1, 2}, 1e101])
def test_non_json_and_unbounded_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        canonical_json(value)


def test_boolean_is_not_number() -> None:
    assert canonical_hash(True) != canonical_hash(1)


def test_canonical_keeps_precision() -> None:
    assert canonical_hash(1.0000000000000002) != canonical_hash(1)


def test_valid_certificate(certificate: dict[str, Any]) -> None:
    result = verify_report(certificate)
    assert result.valid, result.errors
    assert not result.authenticity_verified


def test_json_roundtrip(certificate: dict[str, Any]) -> None:
    assert verify_report(json.dumps(certificate)).valid


def test_timestamp_excluded(certificate: dict[str, Any]) -> None:
    changed = dict(certificate, created_at="2025-01-01T00:00:00+00:00")
    assert content_hash(changed) == certificate["report_id"]
    assert verify_report(changed).valid


def test_timestamp_calendar_validation(certificate: dict[str, Any]) -> None:
    assert not verify_report(dict(certificate, created_at="2025-99-99T00:00:00+00:00")).valid


@pytest.mark.parametrize("field,value", [("verdict", "ROBUST"), ("eligible", True),
    ("mode", "reference"),
    ("reason_codes", []), ("observed_failures", ["TEST_NOT_PROFITABLE"]),
    ("symbol", "ETH/USDT"), ("selection_adjustment", "not_estimated"),
    ("limitations", ["forged"]), ("nexus_validated", True), ("authenticity_claimed", True)])
def test_rehashed_policy_tampering(certificate: dict[str, Any], field: str, value: object) -> None:
    changed = dict(certificate, **{field: value})
    changed["report_id"] = content_hash(changed)
    changed["canonical_report_hash"] = changed["report_id"]
    assert not verify_report(changed).valid


def test_raw_tampering(certificate: dict[str, Any]) -> None:
    changed = dict(certificate, symbol="ETH/USDT")
    assert "CONTENT_HASH_MISMATCH" in verify_report(changed).errors


@pytest.mark.parametrize("value", ["null", "[]", "{", '{"a":1,"a":2}', '{"a":NaN}', b"\xff", 42])
def test_malformed(value: object) -> None:
    assert not verify_report(value).valid


def test_nested_extra_rejected(certificate: dict[str, Any]) -> None:
    changed = json.loads(json.dumps(certificate))
    changed["provenance"]["extra"] = 1
    assert not verify_report(changed).valid


def test_size_bound() -> None:
    assert not verify_report(" " * 4_000_001).valid


def test_cli_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["no-such-alphalitmus-certificate.json"]) == 1
    assert json.loads(capsys.readouterr().out)["valid"] is False


def test_cli_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 1
    assert "USAGE" in capsys.readouterr().out


def test_cli_exit_codes(tmp_path: Path, certificate: dict[str, Any]) -> None:
    path = tmp_path / "certificate.json"
    path.write_text(json.dumps(certificate), encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "app.verify", str(path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    path.write_text("{}", encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "app.verify", str(path)], capture_output=True, text=True, check=False)
    assert result.returncode == 1


def test_reference_recomputation() -> None:
    from app.research import Candle, ResearchRequest
    bars = [Candle(t=1_577_836_800_000 + i * 86_400_000, o=100 + i, h=101 + i,
                   l=99 + i, c=100 + i, v=1) for i in range(250)]
    report = challenge(ChallengeRequest(research=ResearchRequest(candles=bars, data_kind="historical"),
                                       bootstrap_iterations=50, additional_cost_max_bps=0))
    assert verify_report(report).valid
    changed = report.model_dump(mode="json")
    changed["analysis"]["folds"][2]["guarded"]["return_pct"] += 1
    changed["report_id"] = content_hash(changed)
    changed["canonical_report_hash"] = changed["report_id"]
    assert "REFERENCE_REPLAY_MISMATCH" in verify_report(changed).errors


def test_verifier_never_echoes_input(certificate: dict[str, Any]) -> None:
    secret = "private-secret-marker-DO-NOT-ECHO"
    changed = dict(certificate, verdict=secret)
    result = verify_report(changed)
    assert not result.valid
    assert secret not in result.model_dump_json()
    assert result.errors == ["INVALID_CERTIFICATE"]


def test_nexus_full_reconciliation_recomputed() -> None:
    evidence = {"signal": {"status": "received", "data": {"symbol": "ETH/USDT", "timestamp": 1700000000}}}
    report = challenge(ChallengeRequest(mode="nexus", as_of=1700000100.), evidence)
    assert verify_report(report).valid
    changed = report.model_dump(mode="json")
    changed["reconciliation"]["result"]["results"][0]["explanation"] = "invented"
    changed["reconciliation"]["result_sha256"] = canonical_hash(changed["reconciliation"]["result"])
    changed["report_id"] = content_hash(changed)
    changed["canonical_report_hash"] = changed["report_id"]
    assert "RECONCILIATION_INCONSISTENT" in verify_report(changed).errors


@pytest.mark.parametrize("field,value", [
    ("certificate_type", "Survival Report"), ("evidence_classification", "synthetic_reference"),
    ("dataset_sha256", "a" * 64), ("test_matrix", []), ("unavailable_tests", []),
])
def test_rehashed_metadata_rejected(certificate: dict[str, Any], field: str, value: object) -> None:
    changed = dict(certificate, **{field: value})
    changed["report_id"] = content_hash(changed)
    changed["canonical_report_hash"] = changed["report_id"]
    assert not verify_report(changed).valid


def test_hash_fields_excluded(certificate: dict[str, Any]) -> None:
    changed = dict(certificate, report_id="a" * 64, canonical_report_hash="b" * 64)
    assert content_hash(changed) == content_hash(certificate)
    assert not verify_report(changed).valid
