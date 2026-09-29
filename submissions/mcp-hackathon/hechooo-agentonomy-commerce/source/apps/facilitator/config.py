from __future__ import annotations

import ipaddress
import os
import re
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pilot_gate import PilotGatePolicy
from shared.hosted_facilitator_protocol import (
    HOSTED_CHAIN_PROFILES_BY_ID,
    HOSTED_PRODUCTION_CHAIN_IDS,
)


_RAW_KEY_MATERIAL = re.compile(r"^[A-Za-z0-9+/=_-]{64,}$")
_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_BYTES32 = re.compile(r"^0x[0-9a-fA-F]{64}$")
_KMS_KEY_REFERENCE = re.compile(
    r"^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|"
    r"alias/[A-Za-z0-9/_+=,.@-]+|"
    r"arn:(?:aws|aws-us-gov|aws-cn):kms:[A-Za-z0-9-]+:[0-9]{12}:(?:key|alias)/"
    r"[A-Za-z0-9/_+=,.@-]+)$"
)


def _is_loopback_host(hostname: str) -> bool:
    host = hostname.rstrip(".").lower()
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback


def _url_host_is_loopback(value: str) -> bool:
    try:
        hostname = urlsplit(value).hostname
    except ValueError:
        return False
    return hostname is not None and _is_loopback_host(hostname)


def _validate_public_origin(value: object, *, environment: str) -> str:
    if not isinstance(value, str) or not value or value.endswith("/"):
        raise ValueError("public origin must be canonical")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("public origin is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("public origin must be canonical")
    if parsed.path == "/" or port == 80 and parsed.scheme == "http" or port == 443 and parsed.scheme == "https":
        # The explicit default port is not a canonical origin representation.
        raise ValueError("public origin must be canonical")
    if parsed.scheme == "https":
        return value
    if environment == "test" and _is_loopback_host(hostname):
        return value
    raise ValueError("public origin must use HTTPS")


class FacilitatorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    environment: Literal["production", "test"]
    public_origin: str
    postgres_url: str = Field(repr=False)
    redis_url: str = Field(repr=False)
    response_key_ref: str = Field(repr=False)
    core_authority_origin: str = ""
    core_internal_token: str = Field(default="", repr=False)
    chain_id: int
    asset_contract: str
    enrollment_ttl_seconds: int = 300
    dpop_ttl_seconds: int = 60
    max_request_body_bytes: int = 128 * 1024

    @field_validator("public_origin")
    @classmethod
    def public_origin_is_canonical(cls, value: str, info) -> str:
        return _validate_public_origin(value, environment=info.data.get("environment", "production"))

    @field_validator("postgres_url")
    @classmethod
    def postgres_is_persistent(cls, value: str) -> str:
        scheme = value.split(":", 1)[0].lower() if isinstance(value, str) else ""
        if scheme not in {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}:
            raise ValueError("postgres URL must use PostgreSQL")
        return value

    @field_validator("redis_url")
    @classmethod
    def redis_is_configured(cls, value: str) -> str:
        if not isinstance(value, str) or not value.startswith(("redis://", "rediss://")):
            raise ValueError("redis URL is required")
        return value

    @field_validator("response_key_ref")
    @classmethod
    def response_key_is_reference(cls, value: str) -> str:
        if not isinstance(value, str) or not value or "BEGIN " in value.upper():
            raise ValueError("response key reference is required")
        if value.startswith("0x") and len(value) >= 64:
            raise ValueError("response key reference must not contain raw key material")
        if _RAW_KEY_MATERIAL.fullmatch(value):
            raise ValueError("response key reference must not contain raw key material")
        return value

    @field_validator("core_authority_origin")
    @classmethod
    def core_origin_is_canonical(cls, value: str, info) -> str:
        if not value:
            return value
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Core authority origin is invalid") from exc
        environment = info.data.get("environment", "production")
        if (
            hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (parsed.scheme != "https" and not (environment == "test" and parsed.scheme == "http" and _is_loopback_host(hostname)))
            or parsed.path == "/"
            or (port == 80 and parsed.scheme == "http")
            or (port == 443 and parsed.scheme == "https")
        ):
            raise ValueError("Core authority origin must be canonical HTTPS")
        return value

    @field_validator("core_internal_token")
    @classmethod
    def core_token_is_bounded(cls, value: str) -> str:
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError("Core authority token is invalid")
        if any(ord(char) < 0x21 or ord(char) > 0x7E for char in value):
            raise ValueError("Core authority token is invalid")
        return value

    @field_validator("chain_id")
    @classmethod
    def supported_chain(cls, value: int) -> int:
        if type(value) is not int or value not in HOSTED_CHAIN_PROFILES_BY_ID:
            raise ValueError("Hosted execution chain is not supported")
        return value

    @field_validator("asset_contract")
    @classmethod
    def runtime_asset_address(cls, value: str) -> str:
        return _canonical_runtime_address(value, field_name="asset_contract")

    @field_validator("enrollment_ttl_seconds")
    @classmethod
    def enrollment_ttl_is_bounded(cls, value: int) -> int:
        if type(value) is not int or not 30 <= value <= 900:
            raise ValueError("enrollment TTL is unsafe")
        return value

    @field_validator("dpop_ttl_seconds")
    @classmethod
    def dpop_ttl_is_bounded(cls, value: int) -> int:
        if type(value) is not int or not 1 <= value <= 60:
            raise ValueError("dpop TTL is unsafe")
        return value

    @field_validator("max_request_body_bytes")
    @classmethod
    def body_limit_is_bounded(cls, value: int) -> int:
        if type(value) is not int or not 1024 <= value <= 1024 * 1024:
            raise ValueError("request body limit is unsafe")
        return value

    @model_validator(mode="after")
    def production_requires_explicit_secrets(self) -> "FacilitatorConfig":
        profile = HOSTED_CHAIN_PROFILES_BY_ID[self.chain_id]
        if self.environment == "production" and self.chain_id not in HOSTED_PRODUCTION_CHAIN_IDS:
            raise ValueError("production Hosted execution chain is not supported")
        if self.asset_contract != profile.token:
            raise ValueError("asset contract is not canonical USDC for configured chain")
        if self.environment == "production" and self.public_origin.startswith("http://"):
            raise ValueError("production public origin must use HTTPS")
        if self.environment == "production":
            if not self.core_authority_origin:
                raise ValueError("production Core authority origin is required")
            if not self.core_internal_token:
                raise ValueError("production Core authority token is required")
            if _KMS_KEY_REFERENCE.fullmatch(self.response_key_ref) is None:
                raise ValueError("production response key reference must be an AWS KMS key")
            if not _url_host_is_loopback(self.postgres_url):
                try:
                    sslmode = parse_qs(urlsplit(self.postgres_url).query).get(
                        "sslmode", [""]
                    )[-1]
                except (IndexError, ValueError):
                    sslmode = ""
                if sslmode not in {"require", "verify-ca", "verify-full"}:
                    raise ValueError("production PostgreSQL TLS is required")
            if not _url_host_is_loopback(self.redis_url) and not self.redis_url.startswith(
                "rediss://"
            ):
                raise ValueError("production Redis TLS is required")
        return self

    @property
    def chain(self) -> str:
        return HOSTED_CHAIN_PROFILES_BY_ID[self.chain_id].chain

    @property
    def finality_boundary(self) -> str:
        return HOSTED_CHAIN_PROFILES_BY_ID[self.chain_id].finality_boundary

    @classmethod
    def from_env(cls) -> "FacilitatorConfig":
        chain_id = _env_int("CLINK_HOSTED_CHAIN_ID")
        profile = (
            HOSTED_CHAIN_PROFILES_BY_ID.get(chain_id)
            if type(chain_id) is int
            else None
        )
        values = {
            "environment": os.environ.get("CLINK_FACILITATOR_ENV", "production"),
            "public_origin": os.environ.get("CLINK_HOSTED_PUBLIC_ORIGIN", ""),
            "postgres_url": os.environ.get("CLINK_HOSTED_POSTGRES_URL", ""),
            "redis_url": os.environ.get("CLINK_HOSTED_REDIS_URL", ""),
            "response_key_ref": os.environ.get("CLINK_HOSTED_RESPONSE_KEY_REF", ""),
            "core_authority_origin": os.environ.get("CLINK_CORE_AUTHORITY_ORIGIN", ""),
            "core_internal_token": os.environ.get("CLINK_CORE_INTERNAL_API_TOKEN", ""),
            "chain_id": chain_id,
            "asset_contract": os.environ.get(
                "CLINK_HOSTED_ASSET_CONTRACT",
                profile.token if profile is not None else "",
            ),
            "enrollment_ttl_seconds": int(os.environ.get("CLINK_HOSTED_ENROLLMENT_TTL_SECONDS", "300")),
            "dpop_ttl_seconds": int(os.environ.get("CLINK_HOSTED_DPOP_TTL_SECONDS", "60")),
            "max_request_body_bytes": int(os.environ.get("CLINK_HOSTED_MAX_REQUEST_BODY_BYTES", str(128 * 1024))),
        }
        return cls(**values)


class HostedWatcherConfig(BaseModel):
    """Minimal configuration for the independent Hosted watcher process.

    The watcher only reconciles persisted executions against one configured
    chain.  It must not load API, Core, Redis, KMS, signing, or submission
    configuration, even when those values happen to be present in the host
    environment.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    environment: Literal["production", "test"]
    postgres_url: str = Field(repr=False)
    chain_id: int
    asset_contract: str
    watcher_rpc_url: str = Field(repr=False)
    executor_address: str
    executor_admin_address: str
    executor_code_hash: str
    execution_signer_address: str
    signer_epoch: int = 1
    confirmation_depth: int = 2
    rpc_timeout_seconds: int = 20
    watcher_rpc_min_interval_ms: int = 0
    watch_batch_size: int = 100
    watch_poll_seconds: int = 5
    native_asset_usd_price_ceiling_micros: int
    max_in_flight_per_node: int = 10
    max_accepted_per_node_utc_day: int = 50
    max_accepted_per_node_lifetime: int = 250
    max_gas_usd_micros_per_node_utc_day: int = 1_000_000
    max_gas_usd_micros_platform_utc_day: int = 100_000_000

    @field_validator("postgres_url")
    @classmethod
    def postgres_is_persistent(cls, value: str) -> str:
        scheme = value.split(":", 1)[0].lower() if isinstance(value, str) else ""
        if scheme not in {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}:
            raise ValueError("postgres URL must use PostgreSQL")
        return value

    @field_validator("watcher_rpc_url")
    @classmethod
    def watcher_rpc_is_configured(cls, value: str, info) -> str:
        if not isinstance(value, str) or not value or len(value) > 2048:
            raise ValueError("watcher RPC URL is required")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            raise ValueError("watcher RPC URL is invalid")
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise ValueError("watcher RPC URL is invalid") from exc
        environment = info.data.get("environment", "production")
        if (
            hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or (parsed.path == "" and parsed.netloc == "")
            or port in {80, 443}
        ):
            raise ValueError("watcher RPC URL is invalid")
        if environment == "production" and parsed.scheme.lower() != "https":
            raise ValueError("production watcher RPC URL must use HTTPS")
        if environment == "test" and (
            parsed.scheme.lower() not in {"http", "https"}
            or parsed.scheme.lower() == "http"
            and not _is_loopback_host(hostname)
        ):
            raise ValueError("test watcher RPC URL must use loopback HTTP")
        return value

    @field_validator("chain_id")
    @classmethod
    def supported_chain(cls, value: int) -> int:
        if type(value) is not int or value not in HOSTED_CHAIN_PROFILES_BY_ID:
            raise ValueError("Hosted watcher chain is not supported")
        return value

    @field_validator("asset_contract")
    @classmethod
    def runtime_asset_address(cls, value: str) -> str:
        return _canonical_runtime_address(value, field_name="asset_contract")

    @field_validator("executor_address", "executor_admin_address")
    @classmethod
    def runtime_executor_addresses(cls, value: str, info) -> str:
        return _canonical_runtime_address(value, field_name=info.field_name)

    @field_validator("execution_signer_address")
    @classmethod
    def runtime_execution_signer_address(cls, value: str) -> str:
        return _canonical_runtime_address(value, field_name="execution_signer_address")

    @field_validator("executor_code_hash")
    @classmethod
    def runtime_code_hash(cls, value: str) -> str:
        return _canonical_runtime_hash(value, field_name="executor_code_hash")

    @field_validator("signer_epoch")
    @classmethod
    def runtime_signer_epoch(cls, value: int) -> int:
        if type(value) is not int or value <= 0:
            raise ValueError("signer epoch is unsafe")
        return value

    @field_validator("confirmation_depth")
    @classmethod
    def runtime_confirmation_depth(cls, value: int) -> int:
        if type(value) is not int or not 2 <= value <= 64:
            raise ValueError("confirmation depth is unsafe")
        return value

    @field_validator("rpc_timeout_seconds")
    @classmethod
    def runtime_rpc_timeout(cls, value: int) -> int:
        if type(value) is not int or not 1 <= value <= 60:
            raise ValueError("RPC timeout is unsafe")
        return value

    @field_validator("watcher_rpc_min_interval_ms")
    @classmethod
    def runtime_watcher_rpc_pacing(cls, value: int) -> int:
        if type(value) is not int or not 0 <= value <= 10_000:
            raise ValueError("watcher_rpc_min_interval_ms is unsafe")
        return value

    @field_validator("watch_batch_size")
    @classmethod
    def runtime_watch_batch(cls, value: int) -> int:
        if type(value) is not int or not 1 <= value <= 1000:
            raise ValueError("watch batch size is unsafe")
        return value

    @field_validator("watch_poll_seconds")
    @classmethod
    def runtime_watch_poll(cls, value: int) -> int:
        if type(value) is not int or not 1 <= value <= 3600:
            raise ValueError("watch poll interval is unsafe")
        return value

    @field_validator(
        "native_asset_usd_price_ceiling_micros",
        "max_in_flight_per_node",
        "max_accepted_per_node_utc_day",
        "max_accepted_per_node_lifetime",
        "max_gas_usd_micros_per_node_utc_day",
        "max_gas_usd_micros_platform_utc_day",
    )
    @classmethod
    def runtime_gate_limits(cls, value: int, info) -> int:
        if type(value) is not int or value <= 0:
            raise ValueError(f"{info.field_name} is unsafe")
        return value

    @model_validator(mode="after")
    def coherent_runtime(self) -> "HostedWatcherConfig":
        profile = HOSTED_CHAIN_PROFILES_BY_ID[self.chain_id]
        if self.environment == "production" and self.chain_id not in HOSTED_PRODUCTION_CHAIN_IDS:
            raise ValueError("production Hosted watcher chain is not supported")
        if self.asset_contract != profile.token:
            raise ValueError("asset contract is not canonical USDC for configured chain")
        if self.confirmation_depth < profile.min_confirmation_depth:
            raise ValueError("confirmation depth is below the configured chain finality minimum")
        if self.environment == "production" and not _url_host_is_loopback(self.postgres_url):
            try:
                sslmode = parse_qs(urlsplit(self.postgres_url).query).get(
                    "sslmode", [""]
                )[-1]
            except (IndexError, ValueError):
                sslmode = ""
            if sslmode not in {"require", "verify-ca", "verify-full"}:
                raise ValueError("production PostgreSQL TLS is required")
        return self

    @property
    def chain(self) -> str:
        return HOSTED_CHAIN_PROFILES_BY_ID[self.chain_id].chain

    @property
    def finality_boundary(self) -> str:
        return HOSTED_CHAIN_PROFILES_BY_ID[self.chain_id].finality_boundary

    @property
    def pilot_gate_policy(self) -> PilotGatePolicy:
        return PilotGatePolicy(
            native_asset_usd_price_ceiling_micros=(
                self.native_asset_usd_price_ceiling_micros
            ),
            max_in_flight_per_node=self.max_in_flight_per_node,
            max_accepted_per_node_utc_day=self.max_accepted_per_node_utc_day,
            max_accepted_per_node_lifetime=self.max_accepted_per_node_lifetime,
            max_gas_usd_micros_per_node_utc_day=(
                self.max_gas_usd_micros_per_node_utc_day
            ),
            max_gas_usd_micros_platform_utc_day=(
                self.max_gas_usd_micros_platform_utc_day
            ),
        )

    @classmethod
    def from_env(cls) -> "HostedWatcherConfig":
        chain_id = _env_int("CLINK_HOSTED_CHAIN_ID")
        profile = (
            HOSTED_CHAIN_PROFILES_BY_ID.get(chain_id)
            if type(chain_id) is int
            else None
        )
        values = {
            "environment": os.environ.get("CLINK_FACILITATOR_ENV", "production"),
            "postgres_url": os.environ.get("CLINK_HOSTED_POSTGRES_URL", ""),
            "chain_id": chain_id,
            "asset_contract": os.environ.get(
                "CLINK_HOSTED_ASSET_CONTRACT",
                profile.token if profile is not None else "",
            ),
            "watcher_rpc_url": os.environ.get("CLINK_HOSTED_WATCHER_RPC_URL", ""),
            "executor_address": os.environ.get("CLINK_HOSTED_EXECUTOR_ADDRESS", ""),
            "executor_admin_address": os.environ.get(
                "CLINK_HOSTED_EXECUTOR_ADMIN_ADDRESS", ""
            ),
            "executor_code_hash": os.environ.get("CLINK_HOSTED_EXECUTOR_CODE_HASH", ""),
            "execution_signer_address": os.environ.get(
                "CLINK_HOSTED_EXECUTION_SIGNER_ADDRESS", ""
            ),
            "signer_epoch": _env_int("CLINK_HOSTED_SIGNER_EPOCH", "1"),
            "confirmation_depth": _env_int(
                "CLINK_HOSTED_CONFIRMATION_DEPTH",
                str(profile.min_confirmation_depth) if profile is not None else "2",
            ),
            "rpc_timeout_seconds": _env_int("CLINK_HOSTED_RPC_TIMEOUT_SECONDS", "20"),
            "watcher_rpc_min_interval_ms": _env_int(
                "CLINK_HOSTED_WATCHER_RPC_MIN_INTERVAL_MS", "0"
            ),
            "watch_batch_size": _env_int("CLINK_HOSTED_WATCH_BATCH_SIZE", "100"),
            "watch_poll_seconds": _env_int("CLINK_HOSTED_WATCH_POLL_SECONDS", "5"),
            "native_asset_usd_price_ceiling_micros": _env_int(
                "CLINK_HOSTED_NATIVE_ASSET_USD_PRICE_CEILING_MICROS"
            ),
            "max_in_flight_per_node": _env_int(
                "CLINK_HOSTED_MAX_IN_FLIGHT_PER_NODE", "10"
            ),
            "max_accepted_per_node_utc_day": _env_int(
                "CLINK_HOSTED_MAX_ACCEPTED_PER_NODE_UTC_DAY", "50"
            ),
            "max_accepted_per_node_lifetime": _env_int(
                "CLINK_HOSTED_MAX_ACCEPTED_PER_NODE_LIFETIME", "250"
            ),
            "max_gas_usd_micros_per_node_utc_day": _env_int(
                "CLINK_HOSTED_MAX_GAS_USD_MICROS_PER_NODE_UTC_DAY", "1000000"
            ),
            "max_gas_usd_micros_platform_utc_day": _env_int(
                "CLINK_HOSTED_MAX_GAS_USD_MICROS_PLATFORM_UTC_DAY", "100000000"
            ),
        }
        return cls(**values)


def _canonical_runtime_address(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _ADDRESS.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    normalized = value.lower()
    if normalized == "0x" + "00" * 20:
        raise ValueError(f"{field_name} is invalid")
    return normalized


def _canonical_runtime_hash(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _BYTES32.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value.lower()


def _validate_runtime_reference(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError(f"{field_name} is required")
    if any(ord(char) < 0x21 or ord(char) > 0x7E for char in value):
        raise ValueError(f"{field_name} is invalid")
    if "BEGIN " in value.upper() or _RAW_KEY_MATERIAL.fullmatch(value):
        raise ValueError(f"{field_name} must be a reference")
    return value


def _env_int(name: str, default: str | None = None) -> int | str:
    value = os.environ.get(name, default if default is not None else "")
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValueError(f"{name} must be a boolean")


class HostedProductionConfig(FacilitatorConfig):
    """One coherent single-chain Hosted Facilitator runtime configuration.

    This is deliberately a flat model: the composition root can pass each
    validated value directly to its one production dependency without adding a
    configuration container or a second dependency-injection layer.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    executor_address: str
    executor_admin_address: str
    executor_code_hash: str
    execution_kms_key_id: str = Field(repr=False)
    execution_signer_address: str
    gas_kms_key_id: str = Field(repr=False)
    relayer_address: str
    signer_epoch: int = 1
    submission_rpc_url: str = Field(repr=False)
    watcher_rpc_url: str = Field(repr=False)
    rpc_timeout_seconds: int = 20
    max_gas_limit: int
    max_fee_per_gas_wei: int
    max_priority_fee_per_gas_wei: int
    max_total_fee_wei: int | None = None
    native_asset_usd_price_ceiling_micros: int
    max_in_flight_per_node: int = 10
    max_accepted_per_node_utc_day: int = 50
    max_accepted_per_node_lifetime: int = 250
    max_gas_usd_micros_per_node_utc_day: int = 1_000_000
    max_gas_usd_micros_platform_utc_day: int = 100_000_000
    confirmation_depth: int = 2
    max_rpc_head_skew: int = 2
    bind_host: str = "127.0.0.1"
    bind_port: int = 8081
    trusted_tls_terminator: bool = False
    watch_batch_size: int = 100
    watch_poll_seconds: int = 5

    @model_validator(mode="before")
    @classmethod
    def normalize_runtime_aliases(cls, values):
        if not isinstance(values, dict):
            return values
        values = dict(values)
        if not values.get("submission_rpc_url"):
            for alias in ("execution_rpc_url", "primary_rpc_url"):
                if values.get(alias):
                    values["submission_rpc_url"] = values[alias]
                    break
        values.pop("execution_rpc_url", None)
        values.pop("primary_rpc_url", None)
        legacy_response_ref = values.pop("response_kms_key_id", None)
        if legacy_response_ref is not None:
            if not isinstance(legacy_response_ref, str) or not legacy_response_ref:
                raise ValueError("response key reference is required")
            configured_response_ref = values.get("response_key_ref")
            if configured_response_ref and legacy_response_ref != configured_response_ref:
                raise ValueError("response key references conflict")
            values["response_key_ref"] = legacy_response_ref
        if "confirmation_depth" not in values:
            chain_id = values.get("chain_id")
            profile = (
                HOSTED_CHAIN_PROFILES_BY_ID.get(chain_id)
                if type(chain_id) is int
                else None
            )
            if profile is not None:
                values["confirmation_depth"] = profile.min_confirmation_depth
        return values

    @field_validator(
        "executor_address",
        "executor_admin_address",
        "execution_signer_address",
        "relayer_address",
    )
    @classmethod
    def runtime_addresses(cls, value: str, info) -> str:
        return _canonical_runtime_address(value, field_name=info.field_name)

    @field_validator("executor_code_hash")
    @classmethod
    def runtime_code_hash(cls, value: str) -> str:
        return _canonical_runtime_hash(value, field_name="executor_code_hash")

    @field_validator("execution_kms_key_id", "gas_kms_key_id")
    @classmethod
    def runtime_key_refs(cls, value: str, info) -> str:
        return _validate_runtime_reference(value, field_name=info.field_name)

    @field_validator("submission_rpc_url", "watcher_rpc_url")
    @classmethod
    def runtime_rpc_urls(cls, value: str, info) -> str:
        if not isinstance(value, str) or not value or len(value) > 2048:
            raise ValueError(f"{info.field_name} is required")
        return value

    @field_validator("rpc_timeout_seconds")
    @classmethod
    def runtime_rpc_timeout(cls, value: int) -> int:
        if type(value) is not int or not 1 <= value <= 60:
            raise ValueError("RPC timeout is unsafe")
        return value

    @field_validator(
        "max_gas_limit",
        "max_fee_per_gas_wei",
        "max_priority_fee_per_gas_wei",
        "native_asset_usd_price_ceiling_micros",
        "max_in_flight_per_node",
        "max_accepted_per_node_utc_day",
        "max_accepted_per_node_lifetime",
        "max_gas_usd_micros_per_node_utc_day",
        "max_gas_usd_micros_platform_utc_day",
    )
    @classmethod
    def positive_runtime_limits(cls, value: int, info) -> int:
        if type(value) is not int or value <= 0:
            raise ValueError(f"{info.field_name} is unsafe")
        return value

    @field_validator("max_total_fee_wei")
    @classmethod
    def optional_total_fee_limit(cls, value: int | None) -> int | None:
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError("total fee limit is unsafe")
        return value

    @field_validator("signer_epoch")
    @classmethod
    def runtime_epoch(cls, value: int) -> int:
        if type(value) is not int or value <= 0:
            raise ValueError("signer epoch is unsafe")
        return value

    @field_validator("confirmation_depth")
    @classmethod
    def runtime_confirmation_depth(cls, value: int) -> int:
        if type(value) is not int or not 2 <= value <= 64:
            raise ValueError("confirmation depth is unsafe")
        return value

    @field_validator("max_rpc_head_skew")
    @classmethod
    def runtime_head_skew(cls, value: int) -> int:
        if type(value) is not int or not 0 <= value <= 256:
            raise ValueError("RPC head skew is unsafe")
        return value

    @field_validator("bind_host")
    @classmethod
    def runtime_bind_host(cls, value: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 255:
            raise ValueError("bind host is invalid")
        if any(ord(char) < 0x21 or ord(char) > 0x7E for char in value):
            raise ValueError("bind host is invalid")
        return value

    @field_validator("bind_port")
    @classmethod
    def runtime_bind_port(cls, value: int) -> int:
        if type(value) is not int or not 1 <= value <= 65535:
            raise ValueError("bind port is invalid")
        return value

    @field_validator("watch_batch_size")
    @classmethod
    def runtime_watch_batch(cls, value: int) -> int:
        if type(value) is not int or not 1 <= value <= 1000:
            raise ValueError("watch batch size is unsafe")
        return value

    @field_validator("watch_poll_seconds")
    @classmethod
    def runtime_watch_poll(cls, value: int) -> int:
        if type(value) is not int or not 1 <= value <= 3600:
            raise ValueError("watch poll interval is unsafe")
        return value

    @model_validator(mode="after")
    def coherent_runtime(self) -> "HostedProductionConfig":
        profile = HOSTED_CHAIN_PROFILES_BY_ID[self.chain_id]
        if self.confirmation_depth < profile.min_confirmation_depth:
            raise ValueError("confirmation depth is below the configured chain finality minimum")
        if self.max_priority_fee_per_gas_wei > self.max_fee_per_gas_wei:
            raise ValueError("priority fee limit exceeds fee limit")
        if self.environment == "production" and self.submission_rpc_url == self.watcher_rpc_url:
            raise ValueError("production RPC endpoints must be distinct")
        if self.environment == "production" and not _is_loopback_host(self.bind_host):
            if not self.trusted_tls_terminator:
                raise ValueError("a trusted TLS terminator is required for public binds")
        return self

    @property
    def execution_rpc_url(self) -> str:
        return self.submission_rpc_url

    @property
    def gas_relayer_address(self) -> str:
        return self.relayer_address

    @property
    def pilot_gate_policy(self) -> PilotGatePolicy:
        return PilotGatePolicy(
            max_in_flight_per_node=self.max_in_flight_per_node,
            max_accepted_per_node_utc_day=self.max_accepted_per_node_utc_day,
            max_accepted_per_node_lifetime=self.max_accepted_per_node_lifetime,
            max_gas_usd_micros_per_node_utc_day=(
                self.max_gas_usd_micros_per_node_utc_day
            ),
            max_gas_usd_micros_platform_utc_day=(
                self.max_gas_usd_micros_platform_utc_day
            ),
            native_asset_usd_price_ceiling_micros=(
                self.native_asset_usd_price_ceiling_micros
            ),
        )

    @classmethod
    def from_env(cls) -> "HostedProductionConfig":
        response_key_ref = os.environ.get("CLINK_HOSTED_RESPONSE_KEY_REF", "")
        legacy_response_key_ref = os.environ.get("CLINK_HOSTED_RESPONSE_KMS_KEY_ID", "")
        if response_key_ref and legacy_response_key_ref and response_key_ref != legacy_response_key_ref:
            raise ValueError("response key references conflict")
        chain_id = _env_int("CLINK_HOSTED_CHAIN_ID")
        profile = (
            HOSTED_CHAIN_PROFILES_BY_ID.get(chain_id)
            if type(chain_id) is int
            else None
        )
        default_confirmation_depth = (
            str(profile.min_confirmation_depth) if profile is not None else "2"
        )
        values = {
            "environment": os.environ.get("CLINK_FACILITATOR_ENV", "production"),
            "public_origin": os.environ.get("CLINK_HOSTED_PUBLIC_ORIGIN", ""),
            "postgres_url": os.environ.get("CLINK_HOSTED_POSTGRES_URL", ""),
            "redis_url": os.environ.get("CLINK_HOSTED_REDIS_URL", ""),
            "response_key_ref": response_key_ref or legacy_response_key_ref,
            "core_authority_origin": os.environ.get("CLINK_CORE_AUTHORITY_ORIGIN", ""),
            "core_internal_token": os.environ.get("CLINK_CORE_INTERNAL_API_TOKEN", ""),
            "chain_id": chain_id,
            "asset_contract": os.environ.get(
                "CLINK_HOSTED_ASSET_CONTRACT",
                profile.token if profile is not None else "",
            ),
            "enrollment_ttl_seconds": _env_int("CLINK_HOSTED_ENROLLMENT_TTL_SECONDS", "300"),
            "dpop_ttl_seconds": _env_int("CLINK_HOSTED_DPOP_TTL_SECONDS", "60"),
            "max_request_body_bytes": _env_int(
                "CLINK_HOSTED_MAX_REQUEST_BODY_BYTES", str(128 * 1024)
            ),
            "submission_rpc_url": os.environ.get(
                "CLINK_HOSTED_SUBMISSION_RPC_URL",
                os.environ.get("CLINK_HOSTED_EXECUTION_RPC_URL", ""),
            ),
            "watcher_rpc_url": os.environ.get("CLINK_HOSTED_WATCHER_RPC_URL", ""),
            "executor_address": os.environ.get("CLINK_HOSTED_EXECUTOR_ADDRESS", ""),
            "executor_admin_address": os.environ.get(
                "CLINK_HOSTED_EXECUTOR_ADMIN_ADDRESS", ""
            ),
            "executor_code_hash": os.environ.get("CLINK_HOSTED_EXECUTOR_CODE_HASH", ""),
            "execution_kms_key_id": os.environ.get("CLINK_HOSTED_EXECUTION_KMS_KEY_ID", ""),
            "execution_signer_address": os.environ.get(
                "CLINK_HOSTED_EXECUTION_SIGNER_ADDRESS", ""
            ),
            "gas_kms_key_id": os.environ.get("CLINK_HOSTED_GAS_KMS_KEY_ID", ""),
            "relayer_address": os.environ.get("CLINK_HOSTED_RELAYER_ADDRESS", ""),
            "signer_epoch": _env_int("CLINK_HOSTED_SIGNER_EPOCH", "1"),
            "rpc_timeout_seconds": _env_int("CLINK_HOSTED_RPC_TIMEOUT_SECONDS", "20"),
            "max_gas_limit": _env_int("CLINK_HOSTED_MAX_GAS_LIMIT"),
            "max_fee_per_gas_wei": _env_int("CLINK_HOSTED_MAX_FEE_PER_GAS_WEI"),
            "max_priority_fee_per_gas_wei": _env_int(
                "CLINK_HOSTED_MAX_PRIORITY_FEE_PER_GAS_WEI"
            ),
            "max_total_fee_wei": (
                _env_int("CLINK_HOSTED_MAX_TOTAL_FEE_WEI")
                if "CLINK_HOSTED_MAX_TOTAL_FEE_WEI" in os.environ
                else None
            ),
            "native_asset_usd_price_ceiling_micros": _env_int(
                "CLINK_HOSTED_NATIVE_ASSET_USD_PRICE_CEILING_MICROS"
            ),
            "max_in_flight_per_node": _env_int(
                "CLINK_HOSTED_MAX_IN_FLIGHT_PER_NODE", "10"
            ),
            "max_accepted_per_node_utc_day": _env_int(
                "CLINK_HOSTED_MAX_ACCEPTED_PER_NODE_UTC_DAY", "50"
            ),
            "max_accepted_per_node_lifetime": _env_int(
                "CLINK_HOSTED_MAX_ACCEPTED_PER_NODE_LIFETIME", "250"
            ),
            "max_gas_usd_micros_per_node_utc_day": _env_int(
                "CLINK_HOSTED_MAX_GAS_USD_MICROS_PER_NODE_UTC_DAY", "1000000"
            ),
            "max_gas_usd_micros_platform_utc_day": _env_int(
                "CLINK_HOSTED_MAX_GAS_USD_MICROS_PLATFORM_UTC_DAY", "100000000"
            ),
            "confirmation_depth": _env_int(
                "CLINK_HOSTED_CONFIRMATION_DEPTH", default_confirmation_depth
            ),
            "max_rpc_head_skew": _env_int("CLINK_HOSTED_MAX_RPC_HEAD_SKEW", "2"),
            "bind_host": os.environ.get("CLINK_HOSTED_BIND_HOST", "127.0.0.1"),
            "bind_port": _env_int("CLINK_HOSTED_BIND_PORT", "8081"),
            "trusted_tls_terminator": _env_bool(
                "CLINK_HOSTED_TRUSTED_TLS_TERMINATOR", False
            ),
            "watch_batch_size": _env_int("CLINK_HOSTED_WATCH_BATCH_SIZE", "100"),
            "watch_poll_seconds": _env_int("CLINK_HOSTED_WATCH_POLL_SECONDS", "5"),
        }
        return cls(**values)
