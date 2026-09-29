"""Bounded, offline heuristic scanner. Never print matching source text."""

import argparse
import json
import os
from pathlib import Path
import re

MAX_BYTES = 1_048_576
MAX_FILES = 20_000
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "node_modules", "docs", "images", "public", "catalog",
}
EXCLUDED_NAMES = {"nexus-docs.txt", "dependency-license-inventory.json"}
RULES = {
    "nexus-key": re.compile(r"\bnxk_[A-Za-z0-9_-]{20,}\b"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "assigned-secret": re.compile(
        r"(?i)\b(?:[a-z][a-z0-9]*_)*(?:api_key|secret|password|access_token|auth_token)"
        r"\b[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_+/=.!-]{24,})"
    ),
}


def scan(root: Path) -> list[dict[str, str | int]]:
    findings: list[dict[str, str | int]] = []
    count = 0
    if not root.is_dir():
        return [{"rule": "scan-error", "path": ".", "line": 0}]
    def walk_error(error: OSError) -> None:
        findings.append({"rule": "scan-error", "path": ".", "line": 0})

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS
                         and not (Path(directory) / d).is_symlink()
                         and not (Path(directory) / d).is_junction())
        for name in sorted(files):
            path = Path(directory) / name
            if (path.is_symlink() or name in EXCLUDED_NAMES or name.endswith(".lock")
                    or (name.startswith("requirements") and path.suffix == ".txt")
                    or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".pdf", ".woff2"}):
                continue
            relative = path.relative_to(root).as_posix()
            count += 1
            if count > MAX_FILES:
                findings.append({"rule": "file-limit", "path": ".", "line": 0})
                return findings
            try:
                with path.open("rb") as stream:
                    data = stream.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    findings.append({"rule": "size-limit", "path": relative, "line": 0})
                    continue
                if b"\0" in data:
                    continue
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            except OSError:
                findings.append({"rule": "scan-error", "path": relative, "line": 0})
                continue
            for number, line in enumerate(text.splitlines(), 1):
                for rule, pattern in RULES.items():
                    for match in pattern.finditer(line):
                        if rule == "assigned-secret":
                            value = match.group(1)
                            if (len(set(value)) < 10 or not any(c.isalpha() for c in value)
                                    or not any(c.isdigit() for c in value)
                                    or any(word in value.lower() for word in
                                           ("example", "placeholder", "replace", "changeme"))):
                                continue
                        findings.append({"rule": rule, "path": relative, "line": number})
                        break
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    findings = scan(args.root)
    for finding in findings:
        print(json.dumps(finding, ensure_ascii=True))
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
