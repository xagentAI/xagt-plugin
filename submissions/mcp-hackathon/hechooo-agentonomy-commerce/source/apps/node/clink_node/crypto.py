from __future__ import annotations

import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


@dataclass(frozen=True)
class DeviceKeyPair:
    device_id: str
    _private_key: X25519PrivateKey

    @classmethod
    def generate(cls, device_id: str) -> DeviceKeyPair:
        if not device_id.strip():
            raise ValueError("device_id is required")
        return cls(device_id, X25519PrivateKey.generate())

    @property
    def public_key(self) -> str:
        raw = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return _encode(raw)

    def derive_key(
        self,
        peer_public_key: str,
        *,
        context: bytes,
    ) -> bytes:
        peer = X25519PublicKey.from_public_bytes(
            _decode(peer_public_key)
        )
        shared = self._private_key.exchange(peer)
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"clink-link-v1:" + context,
        ).derive(shared)
