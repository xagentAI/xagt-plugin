"""Conservative working-tree secret gate; reports locations/rules, never values."""

import re
import subprocess
from pathlib import Path

RULES = {
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "github-token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "aws-access-key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "signing-key-literal": re.compile(
        rb"RECEIPT_SIGNING_PRIVATE_KEY_B64[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9+/]{43}="
    ),
    "credential-url": re.compile(rb"(?:postgres(?:ql)?|https?)://[^\s/:]+:[^\s@${}<>]+@[^\s\"'/]+"),
}
# Exact synthetic rejection inputs only; never exempt an entire test file/rule.
TEST_URLS = {
    "backend/tests/test_core.py": {b"https://user:pass@" + b"example.com"},
    "backend/tests/test_deployment_verifier.py": {b"https://user:secret@" + b"example.com"},
    "backend/tests/test_readiness.py": {
        b"https://user:secret@" + b"example.com", b"postgres://user:secret@" + b"private"
    },
}


def scan(root):
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root
    ).split(b"\0")
    findings = []
    for name in sorted(set(names) - {b""}):
        path = root / name.decode("utf-8")
        if path.is_symlink():
            findings.append((name.decode("utf-8"), 0, "symlink-not-scanned"))
            continue
        if not path.exists():
            continue
        if path.stat().st_size > 2 * 1024 * 1024:
            findings.append((name.decode("utf-8"), 0, "file-too-large"))
            continue
        for number, line in enumerate(path.read_bytes().splitlines(), 1):
            for rule, pattern in RULES.items():
                matches = list(pattern.finditer(line))
                if rule == "credential-url":
                    matches = [m for m in matches if m.group() not in TEST_URLS.get(name.decode("utf-8"), set())]
                if matches:
                    findings.append((name.decode("utf-8"), number, rule))
    return findings


def main():
    try:
        findings = scan(Path(__file__).resolve().parents[1])
    except (OSError, UnicodeError, subprocess.SubprocessError):
        print("Secret scan failed: unable to inspect working tree")
        return 1
    for path, line, rule in findings:
        print(f"{path}:{line}: {rule}")
    print(f"Secret scan: {len(findings)} finding(s); values suppressed")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
