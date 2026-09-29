from __future__ import annotations

import hashlib
from urllib.parse import urlsplit, urlunsplit
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.security import validate_public_https_url


USDC_ASSETS = {
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
    "epjfwdd5aufqssqem2qn1xzybapc8g4wegkgzwytD1v".lower(),
}


def _stable_id(prefix: str, *parts: str) -> str:
    canonical = "|".join(part.strip().lower() for part in parts)
    return f"{prefix}_{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"


class PaymentOption(BaseModel):
    model_config = ConfigDict(extra="allow")

    scheme: str
    network: str
    asset: str
    amount_atomic: str
    pay_to: str
    max_timeout_seconds: int | None = None
    price_usd: Decimal | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("amount_atomic")
    @classmethod
    def validate_amount(cls, value: str) -> str:
        try:
            amount = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("payment amount must be numeric") from exc
        if amount <= 0:
            raise ValueError("payment amount must be positive")
        return value

    @field_validator("pay_to")
    @classmethod
    def validate_pay_to(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("payment recipient is required")
        return value

    @model_validator(mode="after")
    def infer_usdc_price(self) -> "PaymentOption":
        if self.price_usd is None and self.asset.lower() in USDC_ASSETS:
            self.price_usd = Decimal(self.amount_atomic) / Decimal(1_000_000)
        return self


class Provider(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider_id: str | None = None
    name: str
    domain: str
    source: str
    status: Literal["discovered", "wallet_verified", "domain_verified", "active", "suspended"] = "discovered"
    verified_wallets: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def build_id(source: str, domain: str) -> str:
        del source
        return _stable_id("provider", domain.strip().lower().rstrip("."))

    @model_validator(mode="after")
    def assign_id(self) -> "Provider":
        if not self.provider_id:
            self.provider_id = self.build_id(self.source, self.domain)
        return self


class ServiceOffering(BaseModel):
    model_config = ConfigDict(extra="allow")

    offering_id: str | None = None
    provider_id: str
    source: str
    source_id: str
    name: str
    description: str = ""
    endpoint: str
    method: str = "GET"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    payment_options: list[PaymentOption] = Field(default_factory=list)
    status: Literal["discovered", "submitted", "verifying", "registry_verified", "verified", "stale", "rejected", "disabled"] = "discovered"
    last_synced_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def build_id(source: str, source_id: str) -> str:
        del source
        method, separator, endpoint = source_id.partition(" ")
        if not separator:
            endpoint, method = method, "GET"
        parts = urlsplit(endpoint)
        normalized = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))
        return _stable_id("offering", method.upper(), normalized)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        return validate_public_https_url(value)

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        method = value.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("unsupported HTTP method")
        return method

    @model_validator(mode="after")
    def assign_id(self) -> "ServiceOffering":
        if not self.offering_id:
            self.offering_id = self.build_id(self.source, self.source_id)
        return self


class ManifestOffering(BaseModel):
    name: str
    description: str = ""
    endpoint: str
    method: str = "GET"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    payment_options: list[PaymentOption] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        return validate_public_https_url(value)

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        return ServiceOffering.normalize_method(value)


class ClinkServiceManifest(BaseModel):
    provider: Provider
    offerings: list[ManifestOffering]

    @field_validator("offerings")
    @classmethod
    def require_offering(cls, value: list[ManifestOffering]) -> list[ManifestOffering]:
        if not value:
            raise ValueError("manifest must include at least one offering")
        return value

    def to_offerings(self) -> list[ServiceOffering]:
        return [
            ServiceOffering(
                provider_id=self.provider.provider_id,
                source=self.provider.source,
                source_id=f"{item.method} {item.endpoint}",
                **item.model_dump(),
            )
            for item in self.offerings
        ]
