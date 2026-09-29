import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from tools.license_inventory import inventory, read_lock
from tools.secret_scan import MAX_BYTES, scan

ROOT = Path(__file__).resolve().parents[1]


def test_secret_rules_and_redacted_cli(tmp_path):
    token = "nx" + "k_" + "aB3dE6gH9jK2mN5pQ8sT1vW4"
    private = "-----BEGIN " + "PRIVATE KEY-----"
    assigned = "api_" + 'key = "' + "aB3dE6gH9jK2mN5pQ8sT1vW4" + '"'
    (tmp_path / "config.txt").write_text("\n".join([token, private, assigned]), encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "tools/secret_scan.py"), str(tmp_path)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert token not in result.stdout + result.stderr
    assert private not in result.stdout + result.stderr
    assert assigned not in result.stdout + result.stderr
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert {r["rule"] for r in records} == {"nexus-key", "private-key", "assigned-secret"}
    assert all(set(r) == {"rule", "path", "line"} for r in records)
    assert [r["line"] for r in records] == [1, 2, 3]


def test_scanner_exclusions_and_placeholders(tmp_path):
    token = "nx" + "k_" + "aB3dE6gH9jK2mN5pQ8sT1vW4"
    for folder in ("docs", "__pycache__", "images", "public", ".venv"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "ignored.txt").write_text(token)
    (tmp_path / "requirements.txt").write_text(token)
    (tmp_path / "binary.dat").write_bytes(b"\x00" + token.encode())
    (tmp_path / "safe.py").write_text('api_key = "replace_with_your_example_key1234"\npassword = os.getenv("PASSWORD")')
    assert scan(tmp_path) == []


def test_scan_limits_fail_closed(tmp_path, monkeypatch):
    (tmp_path / "large.txt").write_bytes(b"a" * (MAX_BYTES + 1))
    assert scan(tmp_path) == [{"rule": "size-limit", "path": "large.txt", "line": 0}]
    monkeypatch.setattr("tools.secret_scan.MAX_FILES", 0)
    assert scan(tmp_path) == [{"rule": "file-limit", "path": ".", "line": 0}]
    assert scan(tmp_path / "missing")[0]["rule"] == "scan-error"


def wheel_fixture(tmp_path, version="1.0"):
    wheel = tmp_path / "sample-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("sample-1.0.dist-info/METADATA", f"Name: sample\nVersion: {version}\n")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    lock = tmp_path / "requirements.txt"
    lock.write_text(f"sample==1.0 \\\n    --hash=sha256:{digest}\n", encoding="utf-8")
    return lock, wheel


def test_inventory_unknown_and_provenance(tmp_path):
    lock, wheel = wheel_fixture(tmp_path)
    result = inventory([lock], tmp_path)
    package = result["packages"][0]
    assert package["version"] == package["locked_version"] == "1.0"
    assert package["license_expression"] == package["license"] == package["homepage"] == "UNKNOWN"
    assert package["license_classifiers"] == []
    assert package["source_evidence"]["artifact"] == wheel.name
    assert package["source_evidence"]["hash_matches_lock"] is True


@pytest.mark.parametrize("failure", ["version", "hash", "missing", "conflict"])
def test_inventory_rejects_incomplete_or_mismatched_evidence(tmp_path, failure):
    lock, wheel = wheel_fixture(tmp_path, "2.0" if failure == "version" else "1.0")
    locks = [lock]
    if failure == "hash":
        wheel.write_bytes(wheel.read_bytes() + b"changed")
    elif failure == "missing":
        wheel.unlink()
    elif failure == "conflict":
        other = tmp_path / "dev.txt"
        other.write_text(lock.read_text().replace("==1.0", "==2.0"))
        locks.append(other)
    with pytest.raises(ValueError):
        inventory(locks, tmp_path)


def test_locks_coherent_and_inventory_current():
    runtime = read_lock(ROOT / "requirements.txt")
    dev = read_lock(ROOT / "requirements-dev.txt")
    assert runtime.keys() <= dev.keys()
    assert all(pin["version"] == dev[name]["version"] for name, pin in runtime.items())
    assert all(pin["hashes"] for pin in dev.values())
    assert runtime["pywin32"]["marker"] == 'sys_platform == "win32"'
    stored = json.loads((ROOT / "dependency-license-inventory.json").read_text())
    assert {p["name"]: p["version"] for p in stored["packages"]} == {
        name: pin["version"] for name, pin in dev.items()
    }
    for lock in stored["provenance"]["locks"]:
        assert hashlib.sha256((ROOT / lock["path"]).read_bytes()).hexdigest() == lock["sha256"]
