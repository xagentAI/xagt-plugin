from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from shared.config import AppConfig


@dataclass(frozen=True)
class PolymarketApiCredentials:
    api_key: str
    api_secret: str
    api_passphrase: str
    signature_type: str = "3"
    funder_address: str | None = None
    wallet_address: str | None = None


@dataclass(frozen=True)
class CredentialRecord:
    user_id: str
    venue: str
    wallet_address: str
    api_key_fingerprint: str
    credential_source: str
    created_at: str
    updated_at: str


class CredentialStore:
    """Stores Polymarket L2 credentials encrypted at rest.

    Redis is used when REDIS_URL is configured. JSONL fallback keeps local
    development runnable without changing the production interface.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.from_env()
        self.storage_file = Path(self.config.credential_store_file)
        self.key_prefix = self.config.credential_store_key_prefix.rstrip(":")
        self._fernet = Fernet(self._encryption_key())
        self._redis = self._connect_redis()

    def save_polymarket_credentials(
        self,
        *,
        user_id: str,
        wallet_address: str,
        credentials: PolymarketApiCredentials,
        credential_source: str = "account_binding",
    ) -> CredentialRecord:
        now = self._format_time(self._utc_now())
        payload = {
            "user_id": user_id,
            "venue": "polymarket",
            "wallet_address": wallet_address,
            "api_key": credentials.api_key,
            "api_secret": credentials.api_secret,
            "api_passphrase": credentials.api_passphrase,
            "signature_type": credentials.signature_type,
            "funder_address": credentials.funder_address,
            "credential_source": credential_source,
            "created_at": now,
            "updated_at": now,
        }
        encrypted_payload = self._encrypt(payload)
        storage_payload = {
            "user_id": user_id,
            "venue": "polymarket",
            "wallet_address": wallet_address,
            "api_key_fingerprint": self._fingerprint(credentials.api_key),
            "credential_source": credential_source,
            "encrypted_payload": encrypted_payload,
            "created_at": now,
            "updated_at": now,
        }
        if self._redis is not None:
            self._redis.set(self._redis_key(user_id), json.dumps(storage_payload, ensure_ascii=False))
        else:
            self.storage_file.parent.mkdir(parents=True, exist_ok=True)
            with self.storage_file.open("a") as handle:
                handle.write(json.dumps(storage_payload, ensure_ascii=False) + "\n")
        return CredentialRecord(
            user_id=user_id,
            venue="polymarket",
            wallet_address=wallet_address,
            api_key_fingerprint=storage_payload["api_key_fingerprint"],
            credential_source=credential_source,
            created_at=now,
            updated_at=now,
        )

    def get_polymarket_credentials(self, user_id: str) -> PolymarketApiCredentials | None:
        record = self._load_record(user_id)
        if record is None:
            return None
        try:
            payload = self._decrypt(record["encrypted_payload"])
        except InvalidToken:
            return None
        return PolymarketApiCredentials(
            api_key=payload["api_key"],
            api_secret=payload["api_secret"],
            api_passphrase=payload["api_passphrase"],
            signature_type=str(payload.get("signature_type") or "3"),
            funder_address=payload.get("funder_address"),
            wallet_address=payload.get("wallet_address"),
        )

    def update_polymarket_funder_address(self, user_id: str, funder_address: str) -> CredentialRecord | None:
        credentials = self.get_polymarket_credentials(user_id)
        record = self.latest_record(user_id)
        if credentials is None or record is None:
            return None
        return self.save_polymarket_credentials(
            user_id=user_id,
            wallet_address=record.wallet_address,
            credentials=PolymarketApiCredentials(
                api_key=credentials.api_key,
                api_secret=credentials.api_secret,
                api_passphrase=credentials.api_passphrase,
                signature_type=credentials.signature_type,
                funder_address=funder_address,
                wallet_address=credentials.wallet_address or record.wallet_address,
            ),
            credential_source=record.credential_source,
        )

    def latest_record(self, user_id: str) -> CredentialRecord | None:
        record = self._load_record(user_id)
        if record is None:
            return None
        return CredentialRecord(
            user_id=record["user_id"],
            venue=record["venue"],
            wallet_address=record["wallet_address"],
            api_key_fingerprint=record["api_key_fingerprint"],
            credential_source=record["credential_source"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )

    def delete_polymarket_credentials(self, user_id: str) -> bool:
        if self._redis is not None:
            return bool(self._redis.delete(self._redis_key(user_id)))
        record = self._load_record(user_id)
        if record is None:
            return False
        now = self._format_time(self._utc_now())
        tombstone = {
            "user_id": user_id,
            "venue": "polymarket",
            "wallet_address": record.get("wallet_address", ""),
            "api_key_fingerprint": record.get("api_key_fingerprint", ""),
            "credential_source": "revoked",
            "deleted": True,
            "created_at": record.get("created_at", now),
            "updated_at": now,
        }
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_file.open("a") as handle:
            handle.write(json.dumps(tombstone, ensure_ascii=False) + "\n")
        return True

    def _load_record(self, user_id: str) -> dict[str, Any] | None:
        if self._redis is not None:
            raw = self._redis.get(self._redis_key(user_id))
            if raw is None:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return json.loads(raw)
        if not self.storage_file.exists():
            return None
        latest = None
        with self.storage_file.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("user_id") == user_id and record.get("venue") == "polymarket":
                    if record.get("deleted") is True:
                        latest = None
                        continue
                    latest = record
        return latest

    def _redis_key(self, user_id: str) -> str:
        return f"{self.key_prefix}:polymarket:{user_id}"

    def _connect_redis(self) -> Any | None:
        if not self.config.redis_url:
            return None
        try:
            import redis
        except Exception as exc:
            raise RuntimeError("REDIS_URL is configured but the redis package is not installed") from exc
        return redis.Redis.from_url(self.config.redis_url)

    def _encryption_key(self) -> bytes:
        raw = self.config.credential_encryption_key
        if raw:
            return raw.encode("utf-8")
        digest = hashlib.sha256(self.config.credential_store_dev_secret.encode("utf-8")).digest()
        return Fernet.generate_key() if self.config.credential_store_dev_secret == "" else self._urlsafe_fernet_key(digest)

    @staticmethod
    def _urlsafe_fernet_key(raw: bytes) -> bytes:
        import base64

        return base64.urlsafe_b64encode(raw)

    def _encrypt(self, payload: dict[str, Any]) -> str:
        return self._fernet.encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("utf-8")

    def _decrypt(self, token: str) -> dict[str, Any]:
        return json.loads(self._fernet.decrypt(token.encode("utf-8")).decode("utf-8"))

    @staticmethod
    def _fingerprint(value: str) -> str:
        return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}"

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.utcnow()

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.isoformat() + "Z"

    def describe(self) -> dict[str, Any]:
        return {
            "backend": "redis" if self._redis is not None else "jsonl",
            "redis_configured": bool(self.config.redis_url),
            "storage_file": str(self.storage_file),
            "key_prefix": self.key_prefix,
        }
