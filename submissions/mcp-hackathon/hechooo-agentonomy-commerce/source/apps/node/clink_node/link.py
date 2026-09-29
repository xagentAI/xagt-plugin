from __future__ import annotations

import base64
import json
import secrets
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .crypto import DeviceKeyPair


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class LinkMessage:
    version: int
    envelope_id: str
    request_id: str
    sender_device_id: str
    sender_public_key: str
    recipient_device_id: str
    created_at: str
    expires_at: str
    nonce: str
    ciphertext: str

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        sender: DeviceKeyPair,
        recipient_public_key: str,
        recipient_device_id: str,
        payload: dict[str, Any],
        now: datetime | None = None,
        ttl: timedelta = timedelta(minutes=5),
    ) -> LinkMessage:
        created_at = (now or datetime.now(UTC)).astimezone(UTC)
        expires_at = created_at + ttl
        envelope_id = f"link_{secrets.token_hex(12)}"
        metadata = {
            "version": 1,
            "envelope_id": envelope_id,
            "request_id": request_id,
            "sender_device_id": sender.device_id,
            "sender_public_key": sender.public_key,
            "recipient_device_id": recipient_device_id,
            "created_at": _iso(created_at),
            "expires_at": _iso(expires_at),
        }
        nonce = secrets.token_bytes(12)
        context = f"{envelope_id}:{request_id}".encode("utf-8")
        key = sender.derive_key(
            recipient_public_key,
            context=context,
        )
        ciphertext = AESGCM(key).encrypt(
            nonce,
            _canonical(payload),
            _canonical(metadata),
        )
        return cls(
            **metadata,
            nonce=_encode(nonce),
            ciphertext=_encode(ciphertext),
        )

    def metadata(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("nonce")
        value.pop("ciphertext")
        return value

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, encoded: str) -> LinkMessage:
        return cls(**json.loads(encoded))

    def tamper_ciphertext_for_test(self) -> LinkMessage:
        raw = bytearray(_decode(self.ciphertext))
        raw[-1] ^= 1
        return replace(self, ciphertext=_encode(bytes(raw)))


class LinkInbox:
    def __init__(self, device: DeviceKeyPair) -> None:
        self.device = device
        self._consumed: set[str] = set()
        self._revoked = False

    def revoke(self) -> None:
        self._revoked = True

    def open(
        self,
        message: LinkMessage,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if self._revoked:
            raise ValueError("device is revoked")
        if message.recipient_device_id != self.device.device_id:
            raise ValueError("envelope belongs to a different device")
        if message.envelope_id in self._consumed:
            raise ValueError("envelope already consumed")
        current = (now or datetime.now(UTC)).astimezone(UTC)
        expires_at = datetime.fromisoformat(message.expires_at)
        if expires_at <= current:
            raise ValueError("envelope expired")
        context = (
            f"{message.envelope_id}:{message.request_id}".encode("utf-8")
        )
        key = self.device.derive_key(
            message.sender_public_key,
            context=context,
        )
        plaintext = AESGCM(key).decrypt(
            _decode(message.nonce),
            _decode(message.ciphertext),
            _canonical(message.metadata()),
        )
        payload = json.loads(plaintext)
        self._consumed.add(message.envelope_id)
        return payload
