import hmac
import json
import math
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from shared.canonical_assets import AMOY_NETWORK, AMOY_USDC_ADDRESS
from shared.hosted_facilitator_protocol import HOSTED_CHAIN_PROFILES


DEFAULT_ACCOUNT_ALLOWED_PRODUCTS = ("prediction_markets", "marketplace", "transfers")
CANONICAL_EVM_NETWORKS = {
    "eip155:137": "CLINK_POLYGON_RPC_URL",
    "eip155:8453": "CLINK_BASE_RPC_URL",
    AMOY_NETWORK: "CLINK_HOSTED_REHEARSAL_RPC_URL",
}
MISTTRACK_OFFICIAL_BASE_URL = "https://openapi.misttrack.io"
MISTTRACK_POLICY_V1_HOLD_SCORE = 31
MISTTRACK_POLICY_V1_DENY_SCORE = 71
MISTTRACK_MAX_TIMEOUT_SECONDS = 30.0
MISTTRACK_MAX_ATTEMPTS = 5
MISTTRACK_MAX_CACHE_TTL_SECONDS = 86_400
MISTTRACK_MAX_RATE_LIMIT_REQUESTS_PER_WINDOW = 1_000
MISTTRACK_MAX_RATE_LIMIT_WINDOW_SECONDS = 3_600
MAX_REDIS_OPERATION_TIMEOUT_SECONDS = 5.0
PLACEHOLDER_INTERNAL_API_TOKENS = {
    "",
    "change-me",
    "changeme",
    "replace-me",
    "replace-with-a-long-random-secret",
}
MIN_RECEIPT_SIGNING_KEY_BYTES = 32
PLACEHOLDER_RECEIPT_SIGNING_KEYS = {
    "change-me",
    "changeme",
    "replace-me",
    "replace-with-a-different-long-random-secret",
    "replace-with-a-long-random-secret",
}


def receipt_signing_key_error(
    receipt_signing_key: str, internal_api_token: str
) -> str | None:
    if not isinstance(receipt_signing_key, str) or not receipt_signing_key.strip():
        return "CLINK_RECEIPT_SIGNING_KEY is required"
    key = receipt_signing_key.strip()
    if key.lower() in PLACEHOLDER_RECEIPT_SIGNING_KEYS:
        return "CLINK_RECEIPT_SIGNING_KEY must be a non-placeholder secret"
    if len(key.encode("utf-8")) < MIN_RECEIPT_SIGNING_KEY_BYTES:
        return "CLINK_RECEIPT_SIGNING_KEY must contain at least 32 bytes"
    token = internal_api_token.strip() if isinstance(internal_api_token, str) else ""
    if token and hmac.compare_digest(key.encode("utf-8"), token.encode("utf-8")):
        return (
            "CLINK_RECEIPT_SIGNING_KEY must be independent from "
            "CLINK_CORE_INTERNAL_API_TOKEN"
        )
    return None


def _is_loopback_url(value: str) -> bool:
    hostname = (urlsplit(value).hostname or "").rstrip(".").lower()
    if hostname == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _base_url(
    value: str, *, field_name: str, require_https_outside_loopback: bool = False
) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{field_name} must not contain a query or fragment")
    if (
        require_https_outside_loopback
        and parsed.scheme != "https"
        and not _is_loopback_url(value)
    ):
        raise ValueError(f"{field_name} must use HTTPS outside loopback development")
    return value


def _facilitator_origin(value: str) -> str:
    """Normalize a Hosted origin without allowing path or credential injection."""
    if not isinstance(value, str):
        raise ValueError("CLINK_HOSTED_FACILITATOR_URL must be an origin")
    normalized = value.strip().rstrip("/")
    if not normalized:
        return ""
    try:
        parsed = urlsplit(normalized)
        parsed.port
    except (TypeError, ValueError):
        raise ValueError("CLINK_HOSTED_FACILITATOR_URL must be an origin") from None
    hostname = parsed.hostname
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("CLINK_HOSTED_FACILITATOR_URL must be an origin")
    if parsed.scheme != "https" and hostname.lower() not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError(
            "CLINK_HOSTED_FACILITATOR_URL must use HTTPS outside loopback development"
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def _optional_bounded_identifier(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if len(normalized) > 256 or any(
        unicodedata.category(character).startswith("C")
        or unicodedata.category(character) in {"Zl", "Zp"}
        for character in normalized
    ):
        raise ValueError(f"{field_name} must be bounded and control-free")
    return normalized


def _evm_address(value: str, *, field_name: str) -> str:
    normalized = value.strip().lower()
    if normalized and re.fullmatch(r"0x[0-9a-f]{40}", normalized) is None:
        raise ValueError(f"{field_name} must be a canonical EVM address")
    return normalized


def _evm_address_list(value: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    normalized = []
    for item in value:
        address = _evm_address(item, field_name=field_name)
        if not address:
            raise ValueError(f"{field_name} must not contain empty addresses")
        normalized.append(address)
    return tuple(sorted(set(normalized)))


def _positive_integer(
    value: int, *, field_name: str, maximum: int | None = None
) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")
    return value


def _optional_integer_from_env(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a positive integer") from None


def _official_misttrack_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except (TypeError, ValueError):
        raise ValueError(
            "MISTTRACK_BASE_URL must use the official HTTPS host"
        ) from None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "openapi.misttrack.io"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("MISTTRACK_BASE_URL must use the official HTTPS host")
    return MISTTRACK_OFFICIAL_BASE_URL


def _redis_url(value: str, *, required: bool) -> str:
    if not isinstance(value, str):
        raise ValueError("CLINK_REDIS_URL must be a valid Redis URL")
    normalized = value.strip()
    if not normalized:
        if required:
            raise ValueError("CLINK_REDIS_URL is required for Server Profile")
        return ""
    try:
        parsed = urlsplit(normalized)
        parsed.port
    except (TypeError, ValueError):
        raise ValueError("CLINK_REDIS_URL must be a valid Redis URL") from None
    if (
        parsed.scheme not in {"redis", "rediss"}
        or not parsed.hostname
        or parsed.fragment
    ):
        raise ValueError("CLINK_REDIS_URL must be a valid Redis URL")
    return normalized


_MISSING = object()


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Hosted facilitator chain targets contain duplicate keys")
        result[key] = value
    return result


def _hosted_chain_targets(value: object) -> dict[str, dict[str, object]]:
    """Validate the explicit chain-to-origin/response-key mapping.

    Access and device credentials stay at enrollment scope.  A target only
    selects the Hosted origin, response key, and executor trusted for that
    chain.
    """

    if value is None or value == "":
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value, object_pairs_hook=_unique_json_object)
        except (TypeError, ValueError, RecursionError):
            raise ValueError(
                "CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS must be a JSON object"
            ) from None
    if not isinstance(value, Mapping):
        raise ValueError(
            "CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS must be a mapping"
        )

    normalized: dict[str, dict[str, object]] = {}
    for chain, raw_target in value.items():
        if chain not in HOSTED_CHAIN_PROFILES:
            raise ValueError(
                "CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS contains an unsupported chain"
            )
        if not isinstance(raw_target, Mapping):
            raise ValueError(
                "CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS entries must be mappings"
            )
        target_keys = set(raw_target)
        if not target_keys <= {
            "origin",
            "server_public_jwk",
            "trusted_response_jwk",
            "executor_contract",
        }:
            raise ValueError(
                "CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS entries contain unknown fields"
            )
        origin = raw_target.get("origin", _MISSING)
        response_jwk = raw_target.get("server_public_jwk", _MISSING)
        if response_jwk is _MISSING:
            response_jwk = raw_target.get("trusted_response_jwk", _MISSING)
        if (
            "server_public_jwk" in raw_target
            and "trusted_response_jwk" in raw_target
        ):
            raise ValueError(
                "Hosted chain target response JWK has duplicate field names"
            )
        if origin is _MISSING or response_jwk is _MISSING:
            raise ValueError(
                "each Hosted chain target requires origin and trusted response JWK"
            )
        executor = raw_target.get("executor_contract", _MISSING)
        if executor is _MISSING:
            raise ValueError(
                "each Hosted chain target requires executor_contract"
            )
        if not isinstance(origin, str):
            raise ValueError("Hosted chain target origin is invalid")
        if not isinstance(response_jwk, (str, Mapping)):
            raise ValueError("Hosted chain target response JWK is invalid")
        if not isinstance(executor, str):
            raise ValueError("Hosted chain target executor contract is invalid")
        normalized_origin = _facilitator_origin(origin)
        if not normalized_origin:
            raise ValueError("Hosted chain target origin is required")
        if isinstance(response_jwk, str):
            response_jwk = response_jwk.strip()
            if not response_jwk:
                raise ValueError("Hosted chain target response JWK is required")
        normalized_executor = _evm_address(
            executor,
            field_name="Hosted chain target executor contract",
        )
        if not normalized_executor or normalized_executor == "0x" + "0" * 40:
            raise ValueError("Hosted chain target executor contract is invalid")
        normalized[chain] = {
            "origin": normalized_origin,
            "server_public_jwk": (
                dict(response_jwk)
                if isinstance(response_jwk, Mapping)
                else response_jwk
            ),
            "executor_contract": normalized_executor,
        }
    return normalized


def _unique_hosted_wallet_credentials_files(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(
                "CLINK_HOSTED_WALLET_CREDENTIALS_FILES contains duplicate keys"
            )
        result[key] = value
    return result


def _hosted_wallet_credentials_files(value: object) -> dict[str, str]:
    """Validate the explicit network-to-owner-only-registry path mapping."""

    if value is None:
        return {}
    if isinstance(value, str):
        if not value.strip():
            raise ValueError("CLINK_HOSTED_WALLET_CREDENTIALS_FILES must not be empty")
        try:
            value = json.loads(
                value,
                object_pairs_hook=_unique_hosted_wallet_credentials_files,
            )
        except (TypeError, ValueError, RecursionError):
            raise ValueError(
                "CLINK_HOSTED_WALLET_CREDENTIALS_FILES must be a JSON object"
            ) from None
        if not value:
            raise ValueError("CLINK_HOSTED_WALLET_CREDENTIALS_FILES must not be empty")
    if not isinstance(value, Mapping):
        raise ValueError(
            "CLINK_HOSTED_WALLET_CREDENTIALS_FILES must be a mapping"
        )

    normalized: dict[str, str] = {}
    normalized_paths: set[str] = set()
    for network, raw_path in value.items():
        if not isinstance(network, str) or network not in HOSTED_CHAIN_PROFILES:
            raise ValueError(
                "CLINK_HOSTED_WALLET_CREDENTIALS_FILES contains an unsupported network"
            )
        if not isinstance(raw_path, str):
            raise ValueError(
                "CLINK_HOSTED_WALLET_CREDENTIALS_FILES paths must be strings"
            )
        if (
            not raw_path
            or raw_path != raw_path.strip()
            or not Path(raw_path).is_absolute()
            or any(
                ord(character) < 32
                or ord(character) == 127
                or unicodedata.category(character).startswith("C")
                or unicodedata.category(character) in {"Zl", "Zp"}
                for character in raw_path
            )
        ):
            raise ValueError(
                "CLINK_HOSTED_WALLET_CREDENTIALS_FILES paths must be absolute and control-free"
            )
        path = os.path.normcase(os.path.normpath(raw_path))
        if path in normalized_paths:
            raise ValueError(
                "CLINK_HOSTED_WALLET_CREDENTIALS_FILES paths must be unique"
            )
        normalized_paths.add(path)
        normalized[network] = path
    return normalized


@dataclass
class AppConfig:
    authorization_service_host: str = "127.0.0.1"
    authorization_service_port: int = 8013
    policy_service_host: str = "127.0.0.1"
    policy_service_port: int = 8015
    action_service_host: str = "127.0.0.1"
    action_service_port: int = 8016
    audit_service_host: str = "127.0.0.1"
    audit_service_port: int = 8017
    funding_service_host: str = "127.0.0.1"
    funding_service_port: int = 8018
    account_service_host: str = "127.0.0.1"
    account_service_port: int = 8019
    account_public_base_url: str = ""
    account_session_ttl_seconds: int = 900
    account_allowed_products: tuple[str, ...] = DEFAULT_ACCOUNT_ALLOWED_PRODUCTS
    audit_service_base_url: str = ""
    authorization_mcp_host: str = "127.0.0.1"
    authorization_mcp_port: int = 9013
    policy_mcp_host: str = "127.0.0.1"
    policy_mcp_port: int = 9015
    action_mcp_host: str = "127.0.0.1"
    action_mcp_port: int = 9016
    audit_mcp_host: str = "127.0.0.1"
    audit_mcp_port: int = 9017
    funding_mcp_host: str = "127.0.0.1"
    funding_mcp_port: int = 9018
    authorization_session_file: str = "services/authorization_service/authorizations.jsonl"
    policy_decision_file: str = "services/policy_service/policy_decisions.jsonl"
    action_intent_file: str = "services/action_service/action_intents.jsonl"
    action_approval_file: str = "services/action_service/action_approvals.jsonl"
    audit_event_file: str = "services/audit_service/audit_events.jsonl"
    funding_session_file: str = "services/funding_service/funding_records.jsonl"
    clink_live_funding: bool = False
    clink_direct_transfers_enabled: bool = False
    clink_facilitator_mode: str | None = None
    clink_native_facilitator_enabled: bool = False
    clink_hosted_facilitator_url: str = ""
    clink_hosted_facilitator_node_id: str = ""
    clink_hosted_facilitator_tenant_id: str = ""
    clink_hosted_facilitator_wallet_binding_id: str = ""
    clink_hosted_facilitator_server_public_jwk: str = ""
    clink_hosted_facilitator_chain_targets: dict[str, dict[str, object]] = field(
        default_factory=dict,
        repr=False,
    )
    clink_hosted_rehearsal_network: str = ""
    clink_hosted_rehearsal_rpc_url: str = ""
    clink_hosted_facilitator_access_token: str = field(default="", repr=False)
    clink_hosted_facilitator_device_private_key: str = field(default="", repr=False)
    clink_hosted_wallet_credentials_file: str = field(default="", repr=False)
    clink_hosted_wallet_credentials_files: dict[str, str] = field(
        default_factory=dict,
        repr=False,
    )
    polygon_rpc_url: str = ""
    base_rpc_url: str = ""
    clink_native_facilitator_relayer_private_key: str = ""
    clink_native_facilitator_gas_limit: int = 140000
    clink_funding_spender_address: str = ""
    clink_polygon_usdc_address: str = ""
    clink_polygon_spender_address: str = ""
    clink_base_usdc_address: str = ""
    clink_base_spender_address: str = ""
    x402_payment_network: str = "eip155:137"
    x402_payment_token: str = "USDC"
    x402_payment_token_address: str = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
    x402_payment_token_name: str = "USD Coin"
    x402_payment_token_version: str = "2"
    x402_payment_token_decimals: int = 6
    clink_internal_api_token: str = ""
    clink_receipt_signing_key: str = ""
    clink_profile: str = "personal"
    clink_redis_url: str = ""
    clink_redis_operation_timeout_seconds: float = 1.0
    funding_database_url: str = "sqlite+pysqlite:///services/funding_service/funding_ledger.sqlite3"
    native_min_confirmations: int = 1
    payment_reconciliation_max_attempts: int = 12
    payment_reconciliation_max_age_seconds: int = 3600
    risk_provider: str = "misttrack"
    risk_mode: str = "shadow"
    misttrack_api_key: str = ""
    misttrack_base_url: str = MISTTRACK_OFFICIAL_BASE_URL
    misttrack_timeout_seconds: float = 5.0
    misttrack_max_attempts: int = 2
    misttrack_rate_limit_requests_per_window: int | None = None
    misttrack_rate_limit_window_seconds: int | None = None
    risk_hold_score: int = MISTTRACK_POLICY_V1_HOLD_SCORE
    risk_deny_score: int = MISTTRACK_POLICY_V1_DENY_SCORE
    risk_max_age_seconds: int = 300
    risk_cache_ttl_seconds: int = 300
    funding_destination_denylist: tuple[str, ...] = ()
    funding_destination_allowlist: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        credentials_file = self.clink_hosted_wallet_credentials_file
        if not isinstance(credentials_file, str) or (
            credentials_file and (
                not Path(credentials_file).is_absolute()
                or credentials_file != credentials_file.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in credentials_file)
            )
        ):
            raise ValueError("CLINK_HOSTED_WALLET_CREDENTIALS_FILE must be an absolute path")
        credentials_files = _hosted_wallet_credentials_files(
            self.clink_hosted_wallet_credentials_files
        )
        if credentials_file and credentials_files:
            raise ValueError(
                "CLINK_HOSTED_WALLET_CREDENTIALS_FILE and "
                "CLINK_HOSTED_WALLET_CREDENTIALS_FILES are mutually exclusive"
            )
        self.clink_hosted_wallet_credentials_files = credentials_files
        explicit_facilitator_mode = self.clink_facilitator_mode is not None
        if self.clink_facilitator_mode is None:
            self.clink_facilitator_mode = (
                "native" if self.clink_native_facilitator_enabled else "disabled"
            )
        elif not isinstance(self.clink_facilitator_mode, str):
            raise ValueError(
                "CLINK_FACILITATOR_MODE must be disabled, hosted, or native"
            )
        self.clink_facilitator_mode = self.clink_facilitator_mode.strip().lower()
        if self.clink_facilitator_mode not in {"disabled", "hosted", "native"}:
            raise ValueError(
                "CLINK_FACILITATOR_MODE must be disabled, hosted, or native"
            )
        if (
            explicit_facilitator_mode
            and self.clink_native_facilitator_enabled
            and self.clink_facilitator_mode != "native"
        ):
            raise ValueError(
                "CLINK_FACILITATOR_MODE conflicts with "
                "CLINK_NATIVE_FACILITATOR_ENABLED"
            )
        self.clink_native_facilitator_enabled = (
            self.clink_facilitator_mode == "native"
        )
        self.clink_hosted_facilitator_url = _facilitator_origin(
            self.clink_hosted_facilitator_url
        )
        for field_name in (
            "clink_hosted_facilitator_node_id",
            "clink_hosted_facilitator_tenant_id",
            "clink_hosted_facilitator_wallet_binding_id",
            "clink_hosted_facilitator_server_public_jwk",
            "clink_hosted_facilitator_access_token",
            "clink_hosted_facilitator_device_private_key",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise ValueError(f"{field_name.upper()} must be a string")
            setattr(self, field_name, value.strip())
            if field_name in {
                "clink_hosted_facilitator_node_id",
                "clink_hosted_facilitator_tenant_id",
                "clink_hosted_facilitator_wallet_binding_id",
            }:
                setattr(
                    self,
                    field_name,
                    _optional_bounded_identifier(
                        value,
                        field_name=field_name.upper(),
                    ),
                )
        self.clink_hosted_facilitator_chain_targets = _hosted_chain_targets(
            self.clink_hosted_facilitator_chain_targets
        )
        # The old scalar Base origin/JWK pair is a migration bridge only.  It
        # is materialized into an explicit target and is never a runtime
        # fallback for another chain.
        if (
            self.clink_hosted_facilitator_url
            and self.clink_hosted_facilitator_server_public_jwk
            and "eip155:8453" not in self.clink_hosted_facilitator_chain_targets
        ):
            self.clink_hosted_facilitator_chain_targets[
                "eip155:8453"
            ] = {
                "origin": self.clink_hosted_facilitator_url,
                "server_public_jwk": self.clink_hosted_facilitator_server_public_jwk,
            }
        if credentials_files and set(credentials_files) != set(
            self.clink_hosted_facilitator_chain_targets
        ):
            raise ValueError(
                "CLINK_HOSTED_WALLET_CREDENTIALS_FILES keys must match "
                "Hosted facilitator target keys"
            )
        if not isinstance(self.clink_hosted_rehearsal_network, str):
            raise ValueError("CLINK_HOSTED_REHEARSAL_NETWORK must be a string")
        self.clink_hosted_rehearsal_network = (
            self.clink_hosted_rehearsal_network.strip()
        )
        if self.clink_hosted_rehearsal_network not in {"", AMOY_NETWORK}:
            raise ValueError(
                "CLINK_HOSTED_REHEARSAL_NETWORK must be empty or eip155:80002"
            )
        self.clink_hosted_rehearsal_rpc_url = _base_url(
            self.clink_hosted_rehearsal_rpc_url,
            field_name="CLINK_HOSTED_REHEARSAL_RPC_URL",
            require_https_outside_loopback=True,
        )
        rehearsal_network_set = bool(self.clink_hosted_rehearsal_network)
        rehearsal_rpc_set = bool(self.clink_hosted_rehearsal_rpc_url)
        if rehearsal_network_set != rehearsal_rpc_set:
            raise ValueError(
                "CLINK_HOSTED_REHEARSAL_NETWORK and "
                "CLINK_HOSTED_REHEARSAL_RPC_URL must be configured together"
            )
        if rehearsal_network_set:
            if self.clink_facilitator_mode != "hosted":
                raise ValueError(
                    "CLINK_HOSTED_REHEARSAL_NETWORK requires Hosted facilitator mode"
                )
            target_networks = set(self.clink_hosted_facilitator_chain_targets)
            if target_networks != {AMOY_NETWORK}:
                raise ValueError(
                    "Hosted rehearsal requires exactly the eip155:80002 chain target"
                )
            target = self.clink_hosted_facilitator_chain_targets[AMOY_NETWORK]
            executor = target.get("executor_contract") if isinstance(target, Mapping) else None
            if not isinstance(executor, str) or not _evm_address(
                executor, field_name="Hosted rehearsal executor contract"
            ):
                raise ValueError(
                    "Hosted rehearsal requires an exact Amoy executor contract"
                )
            # Bind rehearsal economic scope to the canonical Amoy USDC pair;
            # production asset settings cannot widen this Core instance.
            self.x402_payment_network = AMOY_NETWORK
            self.x402_payment_token = "USDC"
            self.x402_payment_token_address = AMOY_USDC_ADDRESS
        if not isinstance(self.clink_profile, str):
            raise ValueError("CLINK_PROFILE must be personal or server")
        self.clink_profile = self.clink_profile.strip().lower()
        if self.clink_profile not in {"personal", "server"}:
            raise ValueError("CLINK_PROFILE must be personal or server")
        self.clink_redis_url = _redis_url(
            self.clink_redis_url,
            required=self.clink_profile == "server",
        )
        if (
            isinstance(self.clink_redis_operation_timeout_seconds, bool)
            or not isinstance(
                self.clink_redis_operation_timeout_seconds, (int, float)
            )
            or not math.isfinite(self.clink_redis_operation_timeout_seconds)
            or self.clink_redis_operation_timeout_seconds <= 0
        ):
            raise ValueError(
                "CLINK_REDIS_OPERATION_TIMEOUT_SECONDS must be finite and positive"
            )
        if (
            self.clink_redis_operation_timeout_seconds
            > MAX_REDIS_OPERATION_TIMEOUT_SECONDS
        ):
            raise ValueError(
                "CLINK_REDIS_OPERATION_TIMEOUT_SECONDS must be at most "
                f"{MAX_REDIS_OPERATION_TIMEOUT_SECONDS}"
            )
        self.clink_redis_operation_timeout_seconds = float(
            self.clink_redis_operation_timeout_seconds
        )
        if self.account_session_ttl_seconds <= 0:
            raise ValueError("account session TTL must be positive")
        products = tuple(
            dict.fromkeys(
                product.strip().lower()
                for product in self.account_allowed_products
                if product.strip()
            )
        )
        if not products:
            raise ValueError("account allowed products must not be empty")
        self.account_allowed_products = products
        self.account_public_base_url = _base_url(
            self.account_public_base_url,
            field_name="CLINK_ACCOUNT_PUBLIC_BASE_URL",
            require_https_outside_loopback=True,
        )
        if (
            self.account_public_base_url
            and not _is_loopback_url(self.account_public_base_url)
            and self.clink_internal_api_token.strip().lower()
            in PLACEHOLDER_INTERNAL_API_TOKENS
        ):
            raise ValueError(
                "CLINK_CORE_INTERNAL_API_TOKEN must be a non-placeholder secret "
                "for a public account deployment"
            )
        self.audit_service_base_url = _base_url(
            self.audit_service_base_url,
            field_name="CLINK_AUDIT_SERVICE_URL",
        )
        self.polygon_rpc_url = _base_url(
            self.polygon_rpc_url,
            field_name="CLINK_POLYGON_RPC_URL",
            require_https_outside_loopback=True,
        )
        self.base_rpc_url = _base_url(
            self.base_rpc_url,
            field_name="CLINK_BASE_RPC_URL",
            require_https_outside_loopback=True,
        )
        self.clink_polygon_usdc_address = _evm_address(
            self.clink_polygon_usdc_address,
            field_name="CLINK_POLYGON_USDC_ADDRESS",
        )
        self.clink_polygon_spender_address = _evm_address(
            self.clink_polygon_spender_address,
            field_name="CLINK_POLYGON_SPENDER_ADDRESS",
        )
        self.clink_base_usdc_address = _evm_address(
            self.clink_base_usdc_address,
            field_name="CLINK_BASE_USDC_ADDRESS",
        )
        self.clink_base_spender_address = _evm_address(
            self.clink_base_spender_address,
            field_name="CLINK_BASE_SPENDER_ADDRESS",
        )
        self.funding_destination_denylist = _evm_address_list(
            self.funding_destination_denylist,
            field_name="CLINK_FUNDING_DESTINATION_DENYLIST",
        )
        self.funding_destination_allowlist = _evm_address_list(
            self.funding_destination_allowlist,
            field_name="CLINK_FUNDING_DESTINATION_ALLOWLIST",
        )
        if not isinstance(self.risk_provider, str):
            raise ValueError("CLINK_RISK_PROVIDER must be a string")
        if not isinstance(self.risk_mode, str):
            raise ValueError("CLINK_RISK_MODE must be a string")
        if not isinstance(self.misttrack_api_key, str):
            raise ValueError("MISTTRACK_API_KEY must be a string")
        if not isinstance(self.misttrack_base_url, str):
            raise ValueError("MISTTRACK_BASE_URL must use the official HTTPS host")
        self.risk_provider = self.risk_provider.strip().lower()
        self.risk_mode = self.risk_mode.strip().lower()
        self.misttrack_api_key = self.misttrack_api_key.strip()
        if self.risk_provider != "misttrack":
            raise ValueError("CLINK_RISK_PROVIDER=misttrack is required")
        if self.risk_mode not in {"shadow", "enforce"}:
            raise ValueError("CLINK_RISK_MODE must be shadow or enforce")
        self.misttrack_base_url = _official_misttrack_base_url(
            self.misttrack_base_url
        )
        if (
            isinstance(self.misttrack_timeout_seconds, bool)
            or not isinstance(self.misttrack_timeout_seconds, (int, float))
            or not math.isfinite(self.misttrack_timeout_seconds)
            or self.misttrack_timeout_seconds <= 0
        ):
            raise ValueError("MISTTRACK_TIMEOUT_SECONDS must be finite and positive")
        if self.misttrack_timeout_seconds > MISTTRACK_MAX_TIMEOUT_SECONDS:
            raise ValueError(
                "MISTTRACK_TIMEOUT_SECONDS must be at most "
                f"{MISTTRACK_MAX_TIMEOUT_SECONDS}"
            )
        self.misttrack_timeout_seconds = float(self.misttrack_timeout_seconds)
        self.misttrack_max_attempts = _positive_integer(
            self.misttrack_max_attempts,
            field_name="MISTTRACK_MAX_ATTEMPTS",
            maximum=MISTTRACK_MAX_ATTEMPTS,
        )
        rate_limit_values = (
            self.misttrack_rate_limit_requests_per_window,
            self.misttrack_rate_limit_window_seconds,
        )
        if any(value is not None for value in rate_limit_values):
            if any(value is None for value in rate_limit_values):
                raise ValueError(
                    "MISTTRACK_RATE_LIMIT_REQUESTS_PER_WINDOW and "
                    "MISTTRACK_RATE_LIMIT_WINDOW_SECONDS must be configured together"
                )
            self.misttrack_rate_limit_requests_per_window = _positive_integer(
                self.misttrack_rate_limit_requests_per_window,
                field_name="MISTTRACK_RATE_LIMIT_REQUESTS_PER_WINDOW",
                maximum=MISTTRACK_MAX_RATE_LIMIT_REQUESTS_PER_WINDOW,
            )
            self.misttrack_rate_limit_window_seconds = _positive_integer(
                self.misttrack_rate_limit_window_seconds,
                field_name="MISTTRACK_RATE_LIMIT_WINDOW_SECONDS",
                maximum=MISTTRACK_MAX_RATE_LIMIT_WINDOW_SECONDS,
            )
        if (
            self.clink_profile == "server"
            and self.misttrack_api_key
            and self.misttrack_rate_limit_requests_per_window is None
        ):
            raise ValueError(
                "MISTTRACK_RATE_LIMIT_REQUESTS_PER_WINDOW and "
                "MISTTRACK_RATE_LIMIT_WINDOW_SECONDS are required for Server Profile "
                "when MISTTRACK_API_KEY is configured"
            )
        self.risk_max_age_seconds = _positive_integer(
            self.risk_max_age_seconds,
            field_name="CLINK_RISK_MAX_AGE_SECONDS",
        )
        self.risk_cache_ttl_seconds = _positive_integer(
            self.risk_cache_ttl_seconds,
            field_name="CLINK_RISK_CACHE_TTL_SECONDS",
            maximum=MISTTRACK_MAX_CACHE_TTL_SECONDS,
        )
        if type(self.risk_hold_score) is not int or not 1 <= self.risk_hold_score <= 100:
            raise ValueError(
                "CLINK_RISK_HOLD_SCORE must be an integer between 1 and 100"
            )
        if type(self.risk_deny_score) is not int or not 1 <= self.risk_deny_score <= 100:
            raise ValueError(
                "CLINK_RISK_DENY_SCORE must be an integer between 1 and 100"
            )
        if self.risk_hold_score >= self.risk_deny_score:
            raise ValueError(
                "CLINK_RISK_HOLD_SCORE must be below CLINK_RISK_DENY_SCORE"
            )
        if self.risk_mode == "enforce" and (
            self.risk_hold_score > MISTTRACK_POLICY_V1_HOLD_SCORE
            or self.risk_deny_score > MISTTRACK_POLICY_V1_DENY_SCORE
        ):
            raise ValueError(
                "enforce risk thresholds must not weaken misttrack-policy-v1"
            )
        if self.clink_live_funding and self.risk_mode != "enforce":
            raise ValueError(
                "CLINK_RISK_MODE=enforce is required when CLINK_LIVE_FUNDING is enabled"
            )
        if self.clink_live_funding and self.risk_provider != "misttrack":
            raise ValueError(
                "CLINK_RISK_PROVIDER=misttrack is required when CLINK_LIVE_FUNDING is enabled"
            )
        if self.clink_live_funding and not self.misttrack_api_key:
            raise ValueError(
                "MISTTRACK_API_KEY is required when CLINK_LIVE_FUNDING is enabled"
            )

    @classmethod
    def from_env(cls) -> "AppConfig":
        live_funding_value = os.getenv("CLINK_LIVE_FUNDING", "false").strip().lower()
        native_facilitator_value = os.getenv("CLINK_NATIVE_FACILITATOR_ENABLED", "false").strip().lower()
        facilitator_mode_value = os.getenv("CLINK_FACILITATOR_MODE")
        return cls(
            authorization_service_host=os.getenv("AUTHORIZATION_SERVICE_HOST", "127.0.0.1"),
            authorization_service_port=int(os.getenv("AUTHORIZATION_SERVICE_PORT", "8013")),
            policy_service_host=os.getenv("POLICY_SERVICE_HOST", "127.0.0.1"),
            policy_service_port=int(os.getenv("POLICY_SERVICE_PORT", "8015")),
            action_service_host=os.getenv("ACTION_SERVICE_HOST", "127.0.0.1"),
            action_service_port=int(os.getenv("ACTION_SERVICE_PORT", "8016")),
            audit_service_host=os.getenv("AUDIT_SERVICE_HOST", "127.0.0.1"),
            audit_service_port=int(os.getenv("AUDIT_SERVICE_PORT", "8017")),
            funding_service_host=os.getenv("FUNDING_SERVICE_HOST", "127.0.0.1"),
            funding_service_port=int(os.getenv("FUNDING_SERVICE_PORT", "8018")),
            account_service_host=os.getenv("ACCOUNT_SERVICE_HOST", "127.0.0.1"),
            account_service_port=int(os.getenv("ACCOUNT_SERVICE_PORT", "8019")),
            account_public_base_url=os.getenv(
                "CLINK_ACCOUNT_PUBLIC_BASE_URL", ""
            ),
            account_session_ttl_seconds=int(
                os.getenv("CLINK_ACCOUNT_SESSION_TTL_SECONDS", "900")
            ),
            account_allowed_products=tuple(
                os.getenv(
                    "CLINK_ACCOUNT_ALLOWED_PRODUCTS",
                    ",".join(DEFAULT_ACCOUNT_ALLOWED_PRODUCTS),
                ).split(",")
            ),
            audit_service_base_url=os.getenv("CLINK_AUDIT_SERVICE_URL", ""),
            authorization_mcp_host=os.getenv("AUTHORIZATION_MCP_HOST", "127.0.0.1"),
            authorization_mcp_port=int(os.getenv("AUTHORIZATION_MCP_PORT", "9013")),
            policy_mcp_host=os.getenv("POLICY_MCP_HOST", "127.0.0.1"),
            policy_mcp_port=int(os.getenv("POLICY_MCP_PORT", "9015")),
            action_mcp_host=os.getenv("ACTION_MCP_HOST", "127.0.0.1"),
            action_mcp_port=int(os.getenv("ACTION_MCP_PORT", "9016")),
            audit_mcp_host=os.getenv("AUDIT_MCP_HOST", "127.0.0.1"),
            audit_mcp_port=int(os.getenv("AUDIT_MCP_PORT", "9017")),
            funding_mcp_host=os.getenv("FUNDING_MCP_HOST", "127.0.0.1"),
            funding_mcp_port=int(os.getenv("FUNDING_MCP_PORT", "9018")),
            authorization_session_file=os.getenv(
                "AUTHORIZATION_SESSION_FILE",
                "services/authorization_service/authorizations.jsonl",
            ),
            policy_decision_file=os.getenv("POLICY_DECISION_FILE", "services/policy_service/policy_decisions.jsonl"),
            action_intent_file=os.getenv("ACTION_INTENT_FILE", "services/action_service/action_intents.jsonl"),
            action_approval_file=os.getenv("ACTION_APPROVAL_FILE", "services/action_service/action_approvals.jsonl"),
            audit_event_file=os.getenv("AUDIT_EVENT_FILE", "services/audit_service/audit_events.jsonl"),
            funding_session_file=os.getenv("FUNDING_SESSION_FILE", "services/funding_service/funding_records.jsonl"),
            clink_live_funding=live_funding_value in {"1", "true", "yes", "on"},
            clink_direct_transfers_enabled=os.getenv(
                "CLINK_DIRECT_TRANSFERS_ENABLED", "false"
            ).strip().lower() in {"1", "true", "yes", "on"},
            clink_facilitator_mode=facilitator_mode_value,
            clink_native_facilitator_enabled=native_facilitator_value in {"1", "true", "yes", "on"},
            clink_hosted_facilitator_url=os.getenv(
                "CLINK_HOSTED_FACILITATOR_URL", ""
            ),
            clink_hosted_facilitator_node_id=os.getenv(
                "CLINK_HOSTED_FACILITATOR_NODE_ID", ""
            ),
            clink_hosted_facilitator_tenant_id=os.getenv(
                "CLINK_HOSTED_FACILITATOR_TENANT_ID", ""
            ),
            clink_hosted_facilitator_wallet_binding_id=os.getenv(
                "CLINK_HOSTED_FACILITATOR_WALLET_BINDING_ID", ""
            ),
            clink_hosted_facilitator_server_public_jwk=os.getenv(
                "CLINK_HOSTED_FACILITATOR_SERVER_PUBLIC_JWK", ""
            ),
            clink_hosted_facilitator_chain_targets=os.getenv(
                "CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS",
                os.getenv("CLINK_HOSTED_FACILITATOR_TARGETS", ""),
            ),
            clink_hosted_rehearsal_network=os.getenv(
                "CLINK_HOSTED_REHEARSAL_NETWORK", ""
            ),
            clink_hosted_rehearsal_rpc_url=os.getenv(
                "CLINK_HOSTED_REHEARSAL_RPC_URL", ""
            ),
            clink_hosted_facilitator_access_token=os.getenv(
                "CLINK_HOSTED_FACILITATOR_ACCESS_TOKEN", ""
            ),
            clink_hosted_facilitator_device_private_key=os.getenv(
                "CLINK_HOSTED_FACILITATOR_DEVICE_PRIVATE_KEY", ""
            ),
            clink_hosted_wallet_credentials_file=os.getenv(
                "CLINK_HOSTED_WALLET_CREDENTIALS_FILE", ""
            ),
            clink_hosted_wallet_credentials_files=os.getenv(
                "CLINK_HOSTED_WALLET_CREDENTIALS_FILES"
            ),
            polygon_rpc_url=os.getenv("CLINK_POLYGON_RPC_URL", ""),
            base_rpc_url=os.getenv("CLINK_BASE_RPC_URL", ""),
            clink_native_facilitator_relayer_private_key=os.getenv("CLINK_NATIVE_FACILITATOR_RELAYER_PRIVATE_KEY", ""),
            clink_native_facilitator_gas_limit=int(os.getenv("CLINK_NATIVE_FACILITATOR_GAS_LIMIT", "140000")),
            clink_funding_spender_address=os.getenv("CLINK_FUNDING_SPENDER_ADDRESS", ""),
            clink_polygon_usdc_address=os.getenv("CLINK_POLYGON_USDC_ADDRESS", ""),
            clink_polygon_spender_address=os.getenv(
                "CLINK_POLYGON_SPENDER_ADDRESS", ""
            ),
            clink_base_usdc_address=os.getenv("CLINK_BASE_USDC_ADDRESS", ""),
            clink_base_spender_address=os.getenv("CLINK_BASE_SPENDER_ADDRESS", ""),
            x402_payment_network=os.getenv("X402_PAYMENT_NETWORK", "eip155:137"),
            x402_payment_token=os.getenv("X402_PAYMENT_TOKEN", "USDC"),
            x402_payment_token_address=os.getenv("X402_PAYMENT_TOKEN_ADDRESS", "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"),
            x402_payment_token_name=os.getenv("X402_PAYMENT_TOKEN_NAME", "USD Coin"),
            x402_payment_token_version=os.getenv("X402_PAYMENT_TOKEN_VERSION", "2"),
            x402_payment_token_decimals=int(os.getenv("X402_PAYMENT_TOKEN_DECIMALS", "6")),
            clink_internal_api_token=os.getenv("CLINK_CORE_INTERNAL_API_TOKEN", ""),
            clink_receipt_signing_key=os.getenv("CLINK_RECEIPT_SIGNING_KEY", ""),
            clink_profile=os.getenv("CLINK_PROFILE", "personal"),
            clink_redis_url=os.getenv("CLINK_REDIS_URL", ""),
            clink_redis_operation_timeout_seconds=float(
                os.getenv("CLINK_REDIS_OPERATION_TIMEOUT_SECONDS", "1")
            ),
            funding_database_url=os.getenv("CLINK_FUNDING_DATABASE_URL", "sqlite+pysqlite:///services/funding_service/funding_ledger.sqlite3"),
            native_min_confirmations=int(os.getenv("CLINK_NATIVE_MIN_CONFIRMATIONS", "1")),
            payment_reconciliation_max_attempts=int(
                os.getenv("CLINK_PAYMENT_RECONCILIATION_MAX_ATTEMPTS", "12")
            ),
            payment_reconciliation_max_age_seconds=int(
                os.getenv("CLINK_PAYMENT_RECONCILIATION_MAX_AGE_SECONDS", "3600")
            ),
            risk_provider=os.getenv("CLINK_RISK_PROVIDER", "misttrack").strip().lower(),
            risk_mode=os.getenv("CLINK_RISK_MODE", "shadow").strip().lower(),
            misttrack_api_key=os.getenv("MISTTRACK_API_KEY", "").strip(),
            misttrack_base_url=os.getenv(
                "MISTTRACK_BASE_URL", MISTTRACK_OFFICIAL_BASE_URL
            ).strip(),
            misttrack_timeout_seconds=float(
                os.getenv("MISTTRACK_TIMEOUT_SECONDS", "5")
            ),
            misttrack_max_attempts=int(os.getenv("MISTTRACK_MAX_ATTEMPTS", "2")),
            misttrack_rate_limit_requests_per_window=_optional_integer_from_env(
                "MISTTRACK_RATE_LIMIT_REQUESTS_PER_WINDOW"
            ),
            misttrack_rate_limit_window_seconds=_optional_integer_from_env(
                "MISTTRACK_RATE_LIMIT_WINDOW_SECONDS"
            ),
            risk_hold_score=int(os.getenv("CLINK_RISK_HOLD_SCORE", "31")),
            risk_deny_score=int(os.getenv("CLINK_RISK_DENY_SCORE", "71")),
            risk_max_age_seconds=int(
                os.getenv("CLINK_RISK_MAX_AGE_SECONDS", "300")
            ),
            risk_cache_ttl_seconds=int(
                os.getenv("CLINK_RISK_CACHE_TTL_SECONDS", "300")
            ),
            funding_destination_denylist=tuple(
                value.strip()
                for value in os.getenv("CLINK_FUNDING_DESTINATION_DENYLIST", "").split(",")
                if value.strip()
            ),
            funding_destination_allowlist=tuple(
                value.strip()
                for value in os.getenv("CLINK_FUNDING_DESTINATION_ALLOWLIST", "").split(",")
                if value.strip()
            ),
        )

    def describe(self) -> dict:
        description = asdict(self)
        for key in (
            "misttrack_api_key",
            "clink_hosted_facilitator_access_token",
            "clink_hosted_facilitator_device_private_key",
            "clink_native_facilitator_relayer_private_key",
            "clink_hosted_wallet_credentials_file",
            "clink_hosted_wallet_credentials_files",
            "polygon_rpc_url",
            "base_rpc_url",
            "clink_hosted_rehearsal_rpc_url",
            "clink_internal_api_token",
            "clink_receipt_signing_key",
            "clink_redis_url",
            "funding_database_url",
        ):
            if description.get(key):
                description[key] = "<redacted>"
        if description.get("clink_hosted_facilitator_server_public_jwk"):
            description["clink_hosted_facilitator_server_public_jwk"] = "<configured>"
        targets = description.get("clink_hosted_facilitator_chain_targets")
        if isinstance(targets, dict):
            description["clink_hosted_facilitator_chain_targets"] = {
                chain: {
                    "origin": target.get("origin"),
                    "server_public_jwk": "<configured>",
                    "executor_contract": target.get("executor_contract"),
                }
                for chain, target in targets.items()
            }
        return description

    @property
    def clink_hosted_facilitator_targets(self) -> dict[str, dict[str, object]]:
        """Compatibility alias for the explicit Hosted target mapping."""

        return self.clink_hosted_facilitator_chain_targets

    def hosted_facilitator_target_for(
        self, network: str
    ) -> dict[str, object] | None:
        target = self.clink_hosted_facilitator_chain_targets.get(network)
        return dict(target) if target is not None else None

    def rpc_url_for(self, network: str) -> str:
        if network not in self.allowed_evm_networks:
            if network not in CANONICAL_EVM_NETWORKS:
                raise ValueError(f"unsupported canonical EVM network: {network}")
            raise ValueError(f"unsupported configured EVM network: {network}")
        try:
            field_name = CANONICAL_EVM_NETWORKS[network]
        except KeyError as exc:
            raise ValueError(
                f"unsupported canonical EVM network: {network}"
            ) from exc
        if network == AMOY_NETWORK:
            value = self.clink_hosted_rehearsal_rpc_url
        else:
            value = (
                self.polygon_rpc_url
                if network == "eip155:137"
                else self.base_rpc_url
            )
        if not value:
            raise RuntimeError(f"{field_name} is not configured")
        return value

    @property
    def requires_complete_account_approval_targets(self) -> bool:
        return self.clink_live_funding and bool(
            self.account_public_base_url
            and not _is_loopback_url(self.account_public_base_url)
        )

    @property
    def configured_rpc_urls(self) -> dict[str, str]:
        if self.hosted_rehearsal_enabled:
            return {AMOY_NETWORK: self.clink_hosted_rehearsal_rpc_url}
        return {
            network: value
            for network, value in (
                ("eip155:137", self.polygon_rpc_url),
                ("eip155:8453", self.base_rpc_url),
            )
            if value
        }

    @property
    def hosted_rehearsal_enabled(self) -> bool:
        return bool(self.clink_hosted_rehearsal_network)

    @property
    def allowed_evm_networks(self) -> tuple[str, ...]:
        if self.hosted_rehearsal_enabled:
            return (AMOY_NETWORK,)
        return ("eip155:137", "eip155:8453")

    @property
    def authorization_service_url(self) -> str:
        return f"http://{self.authorization_service_host}:{self.authorization_service_port}"

    @property
    def policy_service_url(self) -> str:
        return f"http://{self.policy_service_host}:{self.policy_service_port}"

    @property
    def action_service_url(self) -> str:
        return f"http://{self.action_service_host}:{self.action_service_port}"

    @property
    def audit_service_url(self) -> str:
        return self.audit_service_base_url or (
            f"http://{self.audit_service_host}:{self.audit_service_port}"
        )

    @property
    def funding_service_url(self) -> str:
        return f"http://{self.funding_service_host}:{self.funding_service_port}"

    @property
    def account_service_url(self) -> str:
        return f"http://{self.account_service_host}:{self.account_service_port}"

    @property
    def authorization_mcp_url(self) -> str:
        return f"http://{self.authorization_mcp_host}:{self.authorization_mcp_port}/mcp/"

    @property
    def policy_mcp_url(self) -> str:
        return f"http://{self.policy_mcp_host}:{self.policy_mcp_port}/mcp/"

    @property
    def action_mcp_url(self) -> str:
        return f"http://{self.action_mcp_host}:{self.action_mcp_port}/mcp/"

    @property
    def audit_mcp_url(self) -> str:
        return f"http://{self.audit_mcp_host}:{self.audit_mcp_port}/mcp/"

    @property
    def funding_mcp_url(self) -> str:
        return f"http://{self.funding_mcp_host}:{self.funding_mcp_port}/mcp/"
