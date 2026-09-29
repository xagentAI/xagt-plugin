from typing import Literal
import re
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.account_service.schemas import canonicalize_evm_address


_UINT256_MAX = 2**256 - 1


class FundingReceipt(BaseModel):
    receipt_id: str
    spending_authorization_id: str
    resource: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    wallet_address: str | None = None
    amount_usdc: str
    venue: str
    destination: str
    chain: str
    token: str
    token_address: str | None = None
    status: str
    tx_hash: str | None = None
    next_action: str
    created_at: str
    metadata: dict = Field(default_factory=dict)
    event_log: list[dict] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()


class CreateSpendingAuthorizationRequest(BaseModel):
    user_id: str
    agent_id: str
    wallet_address: str
    max_amount_usdc: str
    per_order_limit_usdc: str
    venue: str = "polymarket"
    chain: str = "eip155:137"
    token: str = "USDC"
    spender_address: str | None = None
    allowance_tx_hash: str | None = None
    expires_in_minutes: int = 60
    purpose: str = "prediction_market_spending_cap"
    metadata: dict = Field(default_factory=dict)


class SpendingAuthorization(BaseModel):
    model_config = ConfigDict(frozen=True)

    legacy: bool = True
    spending_authorization_id: str
    user_id: str
    agent_id: str
    wallet_address: str
    max_amount_usdc: str
    per_order_limit_usdc: str
    used_amount_usdc: str
    remaining_amount_usdc: str
    venue: str
    chain: str
    token: str
    spender_address: str
    allowance_tx_hash: str | None = None
    purpose: str
    status: str
    expires_at: str
    created_at: str
    updated_at: str | None = None
    metadata: dict = Field(default_factory=dict)
    event_log: list[dict] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()


class SpendFromSpendingAuthorizationRequest(BaseModel):
    spending_authorization_id: str
    amount_usdc: str
    destination: str
    resource: str | None = None
    metadata: dict = Field(default_factory=dict)


class SpendingAuthorizationSpendResult(BaseModel):
    spend_id: str
    spending_authorization_id: str
    user_id: str | None = None
    agent_id: str | None = None
    wallet_address: str | None = None
    amount_usdc: str
    venue: str | None = None
    destination: str
    chain: str | None = None
    token: str | None = None
    status: str
    submitted: bool
    receipt_id: str | None = None
    tx_hash: str | None = None
    reason: str | None = None
    next_action: str
    created_at: str
    metadata: dict = Field(default_factory=dict)
    event_log: list[dict] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()


class FundingStatus(BaseModel):
    user_id: str | None = None
    venue: str | None = None
    spending_authorizations: list[SpendingAuthorization] = Field(default_factory=list)
    receipts: list[FundingReceipt] = Field(default_factory=list)
    available_budget_usdc_by_venue: dict[str, str] = Field(default_factory=dict)
    settled_amount_usdc_by_venue: dict[str, str] = Field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.model_dump()


class CreateSpendingReservationRequest(BaseModel):
    purchase_id: str
    idempotency_key: str
    spending_authorization_id: str | None = None
    authorization_rail: Literal[
        "native_allowance", "clink_payer_proxy", "external_x402"
    ] = (
        "native_allowance"
    )
    wallet_identity_id: str | None = None
    spending_grant_id: str | None = None
    asset_allowance_id: str | None = None
    opc_installation_id: str | None = Field(default=None, min_length=1, max_length=96)
    product: str | None = None
    action_id: str
    policy_decision_id: str
    merchant_id: str
    merchant_trust_tier: Literal["clink_verified", "registry_verified"] | None = None
    quote_hash: str
    amount_usdc: str
    amount_atomic: str
    network: str
    asset: str
    token_address: str | None = None
    destination: str
    resource: str
    venue: str = "clink_marketplace"

    _canonical_token = field_validator("token_address")(
        lambda value: canonicalize_evm_address(value) if value is not None else None
    )

    @model_validator(mode="after")
    def complete_unified_reference_hints(self) -> "CreateSpendingReservationRequest":
        common = (
            self.wallet_identity_id,
            self.spending_grant_id,
            self.product,
        )
        if any(value is not None for value in common) and any(
            value is None for value in common
        ):
            raise ValueError("unified authorization reference hints must be complete")
        if self.authorization_rail in {"native_allowance", "clink_payer_proxy"}:
            if any(value is not None for value in common) and self.asset_allowance_id is None:
                if self.authorization_rail == "clink_payer_proxy":
                    raise ValueError("proxy allowance reference hint is required")
                raise ValueError("native allowance reference hint is required")
        else:
            if self.asset_allowance_id is not None:
                raise ValueError("external x402 must not use an asset allowance")
            if self.token_address is None:
                raise ValueError("external x402 token_address is required")
        return self


class IssuePaymentCapabilityRequest(BaseModel):
    """Hosted enrollment facts supplied to Core for one reserved payment.

    Core derives every payment, authorization, policy, risk, and lifetime field
    from its own durable records.  These five values are the only facts owned
    by the Hosted enrollment/execution boundary.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str
    node_id: str
    wallet_binding_id: str
    executor_contract: str
    payment_challenge_hash: str

    @field_validator("tenant_id", "node_id", "wallet_binding_id")
    @classmethod
    def bounded_identifier(cls, value: str, info) -> str:
        if not value or len(value) > 256:
            raise ValueError(f"{info.field_name} must be a non-empty bounded string")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError(f"{info.field_name} must not contain control characters")
        return value

    _canonical_executor = field_validator("executor_contract")(
        canonicalize_evm_address
    )

    @field_validator("payment_challenge_hash")
    @classmethod
    def canonical_challenge_hash(cls, value: str) -> str:
        if len(value) != 66 or not value.startswith("0x"):
            raise ValueError("payment_challenge_hash must be a lower-case bytes32")
        if any(character not in "0123456789abcdef" for character in value[2:]):
            raise ValueError("payment_challenge_hash must be a lower-case bytes32")
        return value


class HostedExecutionAuthorityRequest(BaseModel):
    """Immutable Hosted execution facts checked against Core-owned state.

    The Facilitator may present these facts, but it cannot choose their value:
    Core compares every field with the durable reservation and payment
    capability before returning an authority projection.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str
    node_id: str
    wallet_binding_id: str
    capability_id: str
    capability_hash: str
    reservation_id: str
    reservation_hash: str
    purchase_id: str
    request_id: str
    request_hash: str
    request_nonce: str
    idempotency_key: str
    chain_id: Literal["eip155:137", "eip155:8453", "eip155:80002"]
    owner: str
    payee: str
    token: str
    amount_atomic: str
    executor: str
    signer_epoch: int
    deadline: int
    execution_scope_hash: str
    execution_digest: str
    relayer_address: str
    payment_challenge_hash: str | None = None

    @field_validator(
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "capability_id",
        "reservation_id",
        "purchase_id",
        "request_id",
        "idempotency_key",
    )
    @classmethod
    def bounded_identifier(cls, value: str, info) -> str:
        if not isinstance(value, str) or not value or len(value) > 256:
            raise ValueError(f"{info.field_name} must be a non-empty bounded string")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError(f"{info.field_name} must not contain control characters")
        return value

    _canonical_addresses = field_validator(
        "owner", "payee", "token", "executor", "relayer_address"
    )(canonicalize_evm_address)

    @field_validator(
        "capability_hash",
        "reservation_hash",
        "request_hash",
        "request_nonce",
        "execution_scope_hash",
        "execution_digest",
        "payment_challenge_hash",
    )
    @classmethod
    def canonical_bytes32(cls, value: str | None, info) -> str | None:
        if value is None and info.field_name == "payment_challenge_hash":
            return None
        if (
            not isinstance(value, str)
            or len(value) != 66
            or not value.startswith("0x")
            or any(character not in "0123456789abcdef" for character in value[2:])
        ):
            raise ValueError(f"{info.field_name} must be a lower-case bytes32")
        return value

    @field_validator("amount_atomic")
    @classmethod
    def canonical_amount(cls, value: str) -> str:
        if (
            not isinstance(value, str)
            or not re.fullmatch(r"[1-9][0-9]*", value)
        ):
            raise ValueError("amount_atomic must be a positive canonical integer")
        if int(value) > _UINT256_MAX:
            raise ValueError("amount_atomic exceeds uint256")
        return value

    @field_validator("signer_epoch", "deadline")
    @classmethod
    def positive_integer(cls, value: int, info) -> int:
        if type(value) is not int or value <= 0 or value > _UINT256_MAX:
            raise ValueError(f"{info.field_name} must be positive")
        return value


class HostedPreflightAuthorityRequest(BaseModel):
    """Immutable Hosted preflight facts checked against Core-owned state.

    Request identifiers and the preflight route belong to the signed envelope,
    while capability and reservation fields are re-read from Core's durable
    records.  In particular, this model intentionally has no execution-only
    digest, signer, relayer, or ``hosted_request_*`` binding.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    protocol_version: Literal["clink-hosted-v1"]
    audience: Literal["hosted-facilitator"]
    http_method: Literal["POST"]
    http_path: Literal["/v1/preflight"]
    request_id: str
    request_hash: str
    idempotency_key: str
    tenant_id: str
    node_id: str
    wallet_binding_id: str
    payment_capability_version: Literal["clink-payment-capability-v1"]
    payment_capability_id: str
    payment_capability_hash: str
    wallet_identity_id: str
    wallet_address: str
    spending_grant_id: str
    spending_grant_hash: str
    asset_allowance_id: str
    reservation_id: str
    reservation_hash: str
    action_id: str
    policy_decision_id: str
    policy_snapshot_hash: str
    risk_evidence_hash: str
    purchase_id: str
    merchant_id: str
    quote_hash: str
    payment_challenge_hash: str
    chain_id: Literal["eip155:137", "eip155:8453", "eip155:80002"]
    asset_contract: str
    amount_atomic: str
    pay_to: str
    executor_contract: str
    execution_scope_hash: str
    request_nonce: str
    issued_at: int
    expires_at: int

    @field_validator(
        "request_id",
        "idempotency_key",
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "payment_capability_id",
        "wallet_identity_id",
        "spending_grant_id",
        "asset_allowance_id",
        "reservation_id",
        "action_id",
        "policy_decision_id",
        "purchase_id",
        "merchant_id",
    )
    @classmethod
    def bounded_identifier(cls, value: str, info) -> str:
        if not isinstance(value, str) or not value or len(value) > 256:
            raise ValueError(f"{info.field_name} must be a non-empty bounded string")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError(f"{info.field_name} must not contain control characters")
        return value

    _canonical_addresses = field_validator(
        "wallet_address", "asset_contract", "pay_to", "executor_contract"
    )(canonicalize_evm_address)

    @field_validator(
        "request_hash",
        "payment_capability_hash",
        "spending_grant_hash",
        "reservation_hash",
        "policy_snapshot_hash",
        "risk_evidence_hash",
        "quote_hash",
        "payment_challenge_hash",
        "execution_scope_hash",
        "request_nonce",
    )
    @classmethod
    def canonical_bytes32(cls, value: str, info) -> str:
        if (
            not isinstance(value, str)
            or len(value) != 66
            or not value.startswith("0x")
            or any(character not in "0123456789abcdef" for character in value[2:])
        ):
            raise ValueError(f"{info.field_name} must be a lower-case bytes32")
        return value

    @field_validator("amount_atomic")
    @classmethod
    def canonical_amount(cls, value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
            raise ValueError("amount_atomic must be a positive canonical integer")
        if int(value) > _UINT256_MAX:
            raise ValueError("amount_atomic exceeds uint256")
        return value

    @field_validator("issued_at", "expires_at")
    @classmethod
    def positive_integer(cls, value: int, info) -> int:
        if type(value) is not int or value <= 0 or value > _UINT256_MAX:
            raise ValueError(f"{info.field_name} must be positive")
        return value

    @model_validator(mode="after")
    def valid_window(self) -> "HostedPreflightAuthorityRequest":
        if self.expires_at <= self.issued_at:
            raise ValueError("preflight validity window is invalid")
        return self


class HostedExecutionAuthorization(BaseModel):
    """Enrollment facts accepted by Core for a Hosted execution request."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["hosted_execution"] = "hosted_execution"
    tenant_id: str
    node_id: str
    wallet_binding_id: str
    executor_contract: str
    payment_challenge_hash: str

    @field_validator("tenant_id", "node_id", "wallet_binding_id")
    @classmethod
    def bounded_identifier(cls, value: str, info) -> str:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 256
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise ValueError(f"{info.field_name} is invalid")
        return value

    _canonical_executor = field_validator("executor_contract")(
        canonicalize_evm_address
    )

    @field_validator("payment_challenge_hash")
    @classmethod
    def canonical_challenge_hash(cls, value: str) -> str:
        if (
            not isinstance(value, str)
            or len(value) != 66
            or not value.startswith("0x")
            or any(character not in "0123456789abcdef" for character in value[2:])
        ):
            raise ValueError("payment_challenge_hash is invalid")
        return value


class SettleSpendingReservationRequest(BaseModel):
    payment_authorization: dict = Field(default_factory=dict)


class ProxyPaymentRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheme: Literal["exact"]
    network: str
    asset: str
    amount_atomic: str
    pay_to: str
    resource: str
    token_name: str = "USD Coin"
    token_version: str = "2"

    _canonical_asset = field_validator("asset")(canonicalize_evm_address)
    _canonical_pay_to = field_validator("pay_to")(canonicalize_evm_address)

    @field_validator("network", "resource", "token_name", "token_version")
    @classmethod
    def nonempty_safe_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(ord(character) < 32 for character in normalized):
            raise ValueError("proxy payment requirement contains invalid text")
        return normalized

    @field_validator("amount_atomic")
    @classmethod
    def canonical_atomic_amount(cls, value: str) -> str:
        if not isinstance(value, str) or not value.isdigit():
            raise ValueError("proxy payment amount_atomic must be a decimal integer")
        return str(int(value, 10))


class PrepareProxyPaymentRequest(BaseModel):
    payment_requirement: ProxyPaymentRequirement


class ReconcileSpendingReservationRequest(BaseModel):
    operator_reconcile: bool = False


class FinalizeSpendingReservationRequest(BaseModel):
    delivery_status: str
    output_hash: str | None = None


class ReleaseSpendingReservationRequest(BaseModel):
    reason: str


class ExternalPaymentVerification(BaseModel):
    model_config = ConfigDict(extra="ignore")

    network: str
    asset: str
    amount_atomic: str
    pay_to: str
    nonce: str
    valid_after: str
    valid_before: str

    @field_validator("network", "asset")
    @classmethod
    def canonical_scope_identifier(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized or any(ord(character) < 32 for character in normalized):
            raise ValueError("external payment scope is invalid")
        return normalized

    @field_validator("amount_atomic")
    @classmethod
    def canonical_atomic_amount(cls, value: str) -> str:
        if not isinstance(value, str) or not value.isdigit():
            raise ValueError("external payment amount_atomic must be a decimal integer")
        return str(int(value, 10))

    _canonical_pay_to = field_validator("pay_to")(canonicalize_evm_address)

    @field_validator("nonce")
    @classmethod
    def canonical_nonce(cls, value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"0[xX][0-9a-fA-F]{64}", value) is None:
            raise ValueError("external payment nonce must be a bytes32 hex value")
        return "0x" + value[2:].lower()

    @field_validator("valid_after", "valid_before")
    @classmethod
    def canonical_validity_bound(cls, value: str) -> str:
        if not isinstance(value, str) or not value.isdigit():
            raise ValueError("external payment validity bounds must be decimal integers")
        parsed = int(value, 10)
        if parsed >= 2**256:
            raise ValueError("external payment validity bounds exceed uint256")
        return str(parsed)

    @model_validator(mode="after")
    def valid_time_window(self) -> "ExternalPaymentVerification":
        if int(self.valid_after) >= int(self.valid_before):
            raise ValueError("external payment validity window is invalid")
        return self


class FinalizeExternalPaymentRequest(BaseModel):
    transaction_hash: str
    payment_response: ExternalPaymentVerification


class FinalizeProxyPaymentRequest(BaseModel):
    transaction_hash: str
    payment_response: ExternalPaymentVerification


_HOSTED_INTENT_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,95}$")
_HOSTED_INTENT_NETWORK = re.compile(r"^[a-z][a-z0-9+.-]{0,15}:[A-Za-z0-9:_-]{1,47}$")
_HOSTED_INTENT_AMOUNT = re.compile(r"^[1-9][0-9]*$")
_ZERO_EVM_ADDRESS = "0x" + "0" * 40


def _hosted_intent_identifier(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _HOSTED_INTENT_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value


def _hosted_intent_network(value: object) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or _HOSTED_INTENT_NETWORK.fullmatch(value) is None
    ):
        raise ValueError("network is invalid")
    return value


def _hosted_intent_address(value: object, *, field_name: str) -> str:
    normalized = canonicalize_evm_address(value)
    if normalized == _ZERO_EVM_ADDRESS:
        raise ValueError(f"{field_name} must not be the zero address")
    return normalized


def _hosted_intent_amount(value: object) -> str:
    if not isinstance(value, str) or _HOSTED_INTENT_AMOUNT.fullmatch(value) is None:
        raise ValueError("amount_atomic is invalid")
    if int(value) > _UINT256_MAX:
        raise ValueError("amount_atomic exceeds uint256")
    return value


class X402ExactIntent(BaseModel):
    """The exact payment shape emitted by Marketplace before Core routing."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    # ``kind`` is a Core-owned normalized discriminator.  Marketplace's
    # existing payload does not send it; ``normalize_hosted_business_intent``
    # adds it through this default.
    kind: Literal["x402_exact"] = "x402_exact"
    scheme: Literal["exact"]
    network: str
    token: str = Field(validation_alias="asset")
    amount_atomic: str
    destination: str = Field(validation_alias="pay_to")

    _canonical_network = field_validator("network")(_hosted_intent_network)
    _canonical_token = field_validator("token")(
        lambda value: _hosted_intent_address(value, field_name="asset")
    )
    _canonical_destination = field_validator("destination")(
        lambda value: _hosted_intent_address(value, field_name="pay_to")
    )
    _canonical_amount = field_validator("amount_atomic")(_hosted_intent_amount)


class PredictionMarketBridgeTransferIntent(BaseModel):
    """The existing Polymarket bridge-transfer payment shape."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    kind: Literal["prediction_market_bridge_transfer"]
    operation_id: str
    reservation_id: str
    binding_id: str
    destination: str = Field(validation_alias="bridge_address")
    token: str = Field(validation_alias="source_token")
    amount_atomic: str

    _canonical_operation_id = field_validator("operation_id")(
        lambda value: _hosted_intent_identifier(value, field_name="operation_id")
    )
    _canonical_reservation_id = field_validator("reservation_id")(
        lambda value: _hosted_intent_identifier(value, field_name="reservation_id")
    )

    @field_validator("binding_id")
    @classmethod
    def canonical_binding_id(cls, value: str) -> str:
        # PM historically trims this opaque binding identifier at its adapter
        # boundary.  Keep that normalization in the Core challenge input so
        # equivalent payloads produce the same challenge.
        normalized = value.strip()
        if normalized != value and not normalized:
            raise ValueError("binding_id is invalid")
        return _hosted_intent_identifier(normalized, field_name="binding_id")

    _canonical_token = field_validator("token")(
        lambda value: _hosted_intent_address(value, field_name="source_token")
    )
    _canonical_destination = field_validator("destination")(
        lambda value: _hosted_intent_address(value, field_name="bridge_address")
    )
    _canonical_amount = field_validator("amount_atomic")(_hosted_intent_amount)


class CreateDirectTransferRequest(BaseModel):
    """Internal Node-to-Core command; actor fields are never agent tool arguments."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    user_id: str
    agent_id: str
    opc_installation_id: str | None = None
    request_id: str
    to_address: str
    network: str
    amount_usdc: str

    @field_validator("user_id", "agent_id", "request_id")
    @classmethod
    def identifier(cls, value: str) -> str:
        return _hosted_intent_identifier(value, field_name="transfer identifier")

    @field_validator("opc_installation_id")
    @classmethod
    def installation(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(r"opc_[0-9a-f]{40}", value) is None:
            raise ValueError("invalid OPC installation")
        return value

    _network = field_validator("network")(_hosted_intent_network)
    _address = field_validator("to_address")(
        lambda value: _hosted_intent_address(value, field_name="to_address")
    )

    @field_validator("amount_usdc")
    @classmethod
    def amount(cls, value: str) -> str:
        # Bounded decimal input, below the ledger's Numeric(38, 6) capacity.
        if re.fullmatch(r"(?:0|[1-9][0-9]{0,13})(?:\.[0-9]{1,6})?", value) is None:
            raise ValueError("amount_usdc must be a decimal string with at most six places")
        amount = Decimal(value)
        if amount <= 0:
            raise ValueError("amount_usdc must be positive")
        return format(amount, "f").rstrip("0").rstrip(".") if "." in value else value


class DirectTransferIntent(BaseModel):
    """Core-owned direct transfer, not a merchant x402 payment or venue deposit."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    kind: Literal["direct_transfer"]
    operation_id: str
    reservation_id: str
    network: str
    destination: str
    token: str
    amount_atomic: str

    @field_validator("operation_id", "reservation_id")
    @classmethod
    def identifier(cls, value: str) -> str:
        return _hosted_intent_identifier(value, field_name="transfer identifier")

    _network = field_validator("network")(_hosted_intent_network)
    _token = field_validator("token")(
        lambda value: _hosted_intent_address(value, field_name="token")
    )
    _destination = field_validator("destination")(
        lambda value: _hosted_intent_address(value, field_name="destination")
    )
    _amount = field_validator("amount_atomic")(_hosted_intent_amount)
