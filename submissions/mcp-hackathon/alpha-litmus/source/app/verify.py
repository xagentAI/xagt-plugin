"""Offline integrity check: python -m app.verify FILE."""
import json
import sys

from app.certificates import MAX_CERTIFICATE_BYTES, verify_report
from app.contracts import Verification


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        result = Verification(valid=False, errors=["USAGE: python -m app.verify FILE"])
    else:
        try:
            with open(args[0], "rb") as handle:
                value = handle.read(MAX_CERTIFICATE_BYTES + 1)
            result = verify_report(value)
        except OSError:
            result = Verification(valid=False, errors=["READ_ERROR"])
    print(json.dumps(result.model_dump(mode="json"), sort_keys=True, allow_nan=False))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
