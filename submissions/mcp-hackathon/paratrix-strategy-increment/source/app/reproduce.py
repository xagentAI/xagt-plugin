"""Run: python -m app.reproduce path/to/evidence.json (no network)."""

import argparse
import json
import sys
from pathlib import Path

from app.domain.engine import InputError
from app.evidence import EvidenceError, reproduce


def reject_constant(_value):
    raise ValueError("non-finite JSON")


def main():
    parser = argparse.ArgumentParser(description="Reproduce a strategy increment evidence bundle offline")
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    try:
        if args.evidence.stat().st_size > 16 * 1024 * 1024:
            raise EvidenceError("Evidence bundle exceeds 16 MiB")
        bundle = json.loads(args.evidence.read_text(encoding="utf-8"), parse_constant=reject_constant)
        result = reproduce(bundle)
    except (OSError, ValueError, InputError, RecursionError):
        print(
            json.dumps(
                {
                    "verified": False,
                    "error": "Evidence is invalid, hashes do not match, or reproduction failed",
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
