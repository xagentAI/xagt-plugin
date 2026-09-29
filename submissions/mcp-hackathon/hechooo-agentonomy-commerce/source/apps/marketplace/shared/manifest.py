from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, field_validator

from shared.models import ClinkServiceManifest


SERVER_MANAGED_OFFERING_METADATA = frozenset(
    {
        "bazaar_info",
        "bazaar_targets",
        "last_verified_at",
        "quality",
        "trust_tier",
        "verification_source",
        "x402_version",
    }
)


def normalize_provider_domain(domain: str) -> str:
    return domain.strip().lower().rstrip(".")


def canonicalize_manifest(manifest: ClinkServiceManifest) -> ClinkServiceManifest:
    normalized_domain = normalize_provider_domain(manifest.provider.domain)
    if not normalized_domain:
        raise ValueError("provider domain is required")
    canonical_provider_id = manifest.provider.build_id(
        manifest.provider.source, normalized_domain
    )
    if manifest.provider.provider_id != canonical_provider_id:
        raise ValueError("provider_id does not match normalized domain")
    provider = manifest.provider.model_copy(
        update={
            "provider_id": canonical_provider_id,
            "domain": normalized_domain,
            "status": "discovered",
            "verified_wallets": [],
        }
    )
    offerings = [
        offering.model_copy(
            update={
                "metadata": {
                    key: value
                    for key, value in offering.metadata.items()
                    if key not in SERVER_MANAGED_OFFERING_METADATA
                }
            }
        )
        for offering in manifest.offerings
    ]
    return manifest.model_copy(
        update={"provider": provider, "offerings": offerings}
    )


def canonical_manifest_payload(manifest: ClinkServiceManifest) -> bytes:
    return json.dumps(
        manifest.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def manifest_hash(manifest: ClinkServiceManifest) -> str:
    return "0x" + hashlib.sha256(canonical_manifest_payload(manifest)).hexdigest()


class ManifestClaim(BaseModel):
    manifest_hash: str
    domain: str
    pay_to: list[str]
    nonce: str
    issued_at: datetime
    expires_at: datetime

    @field_validator("pay_to")
    @classmethod
    def require_recipients(cls, value: list[str]) -> list[str]:
        normalized = sorted({item.lower() for item in value if item})
        if not normalized:
            raise ValueError("manifest claim requires at least one payTo")
        return normalized

    def typed_data(self, chain_id: int = 137) -> dict[str, Any]:
        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                ],
                "ManifestClaim": [
                    {"name": "manifestHash", "type": "bytes32"},
                    {"name": "domain", "type": "string"},
                    {"name": "payToHash", "type": "bytes32"},
                    {"name": "nonce", "type": "string"},
                    {"name": "expiresAt", "type": "uint256"},
                ],
            },
            "primaryType": "ManifestClaim",
            "domain": {"name": "Clink Manifest", "version": "1", "chainId": chain_id},
            "message": {
                "manifestHash": self.manifest_hash,
                "domain": self.domain.lower(),
                "payToHash": "0x" + hashlib.sha256("|".join(self.pay_to).encode()).hexdigest(),
                "nonce": self.nonce,
                "expiresAt": int(self.expires_at.timestamp()),
            },
        }

    def assert_fresh(self, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        if self.expires_at <= current:
            raise ValueError("manifest claim expired")
        if self.issued_at > current:
            raise ValueError("manifest claim issued in the future")
