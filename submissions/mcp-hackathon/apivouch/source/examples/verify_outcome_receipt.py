"""Offline integrity and authenticity checks; v2 requires cryptography."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def fingerprint(receipt: dict[str, Any]) -> str:
    body = dict(receipt)
    body.pop("integrity", None)
    body.pop("receipt_id", None)
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def verify(receipt: dict[str, Any]) -> bool:
    expected = fingerprint(receipt)
    return (
        (receipt.get("integrity") or {}).get("fingerprint") == expected
        and receipt.get("receipt_id") == expected.split(":", 1)[1][:24]
    )


def authenticity(receipt: dict, public_document: dict | None = None) -> dict:
    if receipt.get("format") == "apivouch-outcome-receipt-v1" and "authenticity" not in receipt:
        return {"state": "unsigned", "valid": False}
    if public_document is None:
        return {"state": "unavailable", "valid": False}
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        auth = receipt["authenticity"]
        if (receipt["format"] != "apivouch-outcome-receipt-v2"
                or auth != {"state": "signed", "algorithm": "Ed25519", "key_id": public_document["keyId"]}
                or not isinstance(auth["key_id"], str) or not auth["key_id"]
                or type(public_document["schemaVersion"]) is not int or public_document["schemaVersion"] != 1
                or public_document["slug"] != "apivouch" or public_document["algorithm"] != "Ed25519"
                or public_document["commit"] != receipt["deployment_commit"]
                or receipt["integrity"].get("algorithm") != "SHA-256" or not verify(receipt)):
            return {"state": "invalid", "valid": False}
        public = base64.b64decode(public_document["publicKey"], validate=True)
        signature = base64.b64decode(receipt["integrity"]["signature"], validate=True)
        Ed25519PublicKey.from_public_bytes(public).verify(signature, (receipt["format"] + "\n" + fingerprint(receipt)[7:]).encode("utf-8"))
    except (KeyError, ValueError, TypeError, InvalidSignature):
        return {"state": "invalid", "valid": False}
    return {"state": "signed", "valid": True}


def main() -> int:
    if len(sys.argv) not in {2, 3}:
        print("usage: python examples/verify_outcome_receipt.py RECEIPT.json [PUBLIC_KEY.json]", file=sys.stderr)
        return 2
    try:
        receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        public = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")) if len(sys.argv) == 3 else None
        valid = verify(receipt)
        auth = authenticity(receipt, public)
    except (OSError, ValueError, TypeError, AttributeError, ImportError):
        print(json.dumps({"integrity_valid": False, "authenticity": {"state": "unavailable", "valid": False}}))
        return 1
    print(json.dumps({"receipt_id": receipt.get("receipt_id"), "integrity_valid": valid, "authenticity": auth}))
    return 0 if valid and auth["state"] in {"unsigned", "signed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
