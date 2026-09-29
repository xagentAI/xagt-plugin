"""Read hash-verified downloaded wheels, not guessed licenses or project ownership."""

import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import platform
import re
import zipfile


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_lock(path: Path) -> dict[str, dict[str, object]]:
    packages: dict[str, dict[str, object]] = {}
    text = path.read_text(encoding="utf-8").replace("\\\n", " ")
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([\w.-]+)==([^\s;]+)(?:\s*;\s*(.*?))?\s+--hash=", line)
        if not match:
            raise ValueError(f"Unsupported lock entry in {path.name}")
        name, version, marker = match.groups()
        key = normalize(name)
        if key in packages:
            raise ValueError(f"Duplicate lock entry: {key}")
        packages[key] = {"version": version, "marker": marker,
                         "hashes": re.findall(r"--hash=sha256:([a-f0-9]{64})", line)}
    if not packages:
        raise ValueError("Empty lock")
    return packages


def inventory(locks: list[Path], wheel_dir: Path) -> dict[str, object]:
    expected: dict[str, dict[str, object]] = {}
    for lock in locks:
        for name, pin in read_lock(lock).items():
            if name in expected and expected[name]["version"] != pin["version"]:
                raise ValueError(f"Conflicting locks: {name}")
            if name not in expected:
                expected[name] = {**pin, "locks": []}
            expected[name]["locks"].append(lock.name)
            # An artifact must be authorized by every lock containing the package.
            expected[name]["hashes"] = sorted(set(expected[name]["hashes"]) & set(pin["hashes"]))
    observed = {}
    for wheel in sorted(wheel_dir.glob("*.whl")):
        with wheel.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        with zipfile.ZipFile(wheel) as archive:
            members = [p for p in archive.namelist() if p.endswith(".dist-info/METADATA")]
            if len(members) != 1:
                raise ValueError(f"Invalid wheel metadata: {wheel.name}")
            metadata = BytesParser().parsebytes(archive.read(members[0]))
        name = normalize(str(metadata["Name"]))
        if name not in expected:
            raise ValueError(f"Untracked wheel: {name}")
        pin = expected[name]
        version = str(metadata["Version"])
        if version != pin["version"] or digest not in pin["hashes"]:
            raise ValueError(f"Wheel does not match lock: {name}")
        if name in observed:
            raise ValueError(f"Duplicate wheel: {name}")
        urls = metadata.get_all("Project-URL", [])
        homepage = metadata.get("Home-page")
        if not homepage:
            homepage = next((url.split(",", 1)[1].strip() for url in urls
                             if url.lower().startswith("homepage,")), None)
        observed[name] = {
            "name": name, "version": version, "locked_version": pin["version"],
            "version_matches_lock": True, "locks": pin["locks"], "marker": pin["marker"],
            "license_expression": metadata.get("License-Expression") or "UNKNOWN",
            "license": metadata.get("License") or "UNKNOWN",
            "license_classifiers": [c for c in metadata.get_all("Classifier", []) if c.startswith("License ::")],
            "homepage": homepage or "UNKNOWN", "project_urls": urls,
            "source_evidence": {"kind": "downloaded-wheel-metadata", "artifact": wheel.name,
                                "sha256": digest, "member": members[0], "hash_matches_lock": True},
        }
    missing = sorted(set(expected) - set(observed))
    if missing:
        raise ValueError("Missing wheel metadata: " + ", ".join(missing))
    return {
        "schema_version": 1,
        "provenance": {"method": "METADATA from pip-downloaded wheels verified against all supplied locks",
                       "python": platform.python_version(), "platform": platform.system(),
                       "scope": "All pins in supplied locks, including platform-specific pins; not installed versions",
                       "locks": [{"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                 for p in locks]},
        "packages": [observed[name] for name in sorted(observed)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheels", required=True, type=Path)
    parser.add_argument("--lock", action="append", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dependency-license-inventory.json"))
    args = parser.parse_args()
    result = inventory(args.lock or [Path("requirements.txt"), Path("requirements-dev.txt")], args.wheels)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Inventoried {len(result['packages'])} packages; all wheel versions and hashes match locks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
