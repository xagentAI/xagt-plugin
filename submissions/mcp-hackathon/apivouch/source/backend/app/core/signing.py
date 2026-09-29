"""Environment-only receipt signing; configuration failures never prevent liveness."""

import base64
import hashlib
import os
import re
from dataclasses import dataclass, field

from cryptography.exceptions import InternalError, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException

from app.core.config import GIT_COMMIT


@dataclass(frozen=True)
class SigningConfig:
    required: bool = False
    error: str | None = None
    key_id: str | None = None
    _key: Ed25519PrivateKey | None = field(default=None, repr=False)

    @property
    def ready(self) -> bool:
        return self.error is None and (not self.required or self._key is not None)

    @property
    def enabled(self) -> bool:
        return self._key is not None

    def check_issuance(self) -> None:
        if not self.ready:
            raise HTTPException(503, "Receipt signing unavailable")

    def public_document(self) -> dict:
        self.check_issuance()
        if self._key is None:
            raise HTTPException(404, "Receipt signing not configured")
        return {"schemaVersion": 1, "slug": "apivouch", "algorithm": "Ed25519",
                "keyId": self.key_id, "publicKey": base64.b64encode(self._key.public_key().public_bytes_raw()).decode("ascii"),
                "commit": GIT_COMMIT}

    def sign(self, message: bytes) -> str:
        self.check_issuance()
        try:
            return base64.b64encode(self._key.sign(message)).decode("ascii")
        except (ValueError, TypeError, AttributeError, RuntimeError, InternalError, UnsupportedAlgorithm):
            raise HTTPException(503, "Receipt signing unavailable") from None


def load_signing_config() -> SigningConfig:
    flag = os.environ.get("REQUIRE_SIGNED_RECEIPTS", "false")
    if flag not in {"true", "false"}:
        return SigningConfig(error="invalid_requirement")
    required = flag == "true"
    secret = os.environ.get("RECEIPT_SIGNING_PRIVATE_KEY_B64")
    override = os.environ.get("RECEIPT_SIGNING_KEY_ID")
    if override is not None and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", override) is None:
        return SigningConfig(required, "invalid_key_id")
    if secret is None:
        return SigningConfig(required, "missing_key" if required or override is not None else None)
    try:
        if len(secret) != 44:
            raise ValueError
        raw = base64.b64decode(secret, validate=True)
        if len(raw) != 32 or base64.b64encode(raw).decode("ascii") != secret:
            raise ValueError
        key = Ed25519PrivateKey.from_private_bytes(raw)
    except (ValueError, TypeError, InternalError, UnsupportedAlgorithm):
        return SigningConfig(required, "invalid_private_key")
    key_id = override or "ed25519-" + hashlib.sha256(key.public_key().public_bytes_raw()).hexdigest()[:32]
    return SigningConfig(required, key_id=key_id, _key=key)


SIGNING_CONFIG = load_signing_config()
