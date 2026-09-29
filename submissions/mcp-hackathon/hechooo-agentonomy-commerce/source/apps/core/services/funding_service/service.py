import base64
import binascii
import json
import hashlib
import hmac
import os
import re
import secrets
import time
from contextlib import contextmanager
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Any
from uuid import uuid4

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_checksum_address
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from services.funding_service.schemas import (
    CreateSpendingReservationRequest,
    IssuePaymentCapabilityRequest,
    HostedExecutionAuthorityRequest,
    HostedPreflightAuthorityRequest,
    FinalizeSpendingReservationRequest,
    FinalizeExternalPaymentRequest,
    FinalizeProxyPaymentRequest,
    PrepareProxyPaymentRequest,
    ReleaseSpendingReservationRequest,
    SettleSpendingReservationRequest,
    HostedExecutionAuthorization,
    CreateSpendingAuthorizationRequest,
    FundingReceipt,
    FundingStatus,
    SpendFromSpendingAuthorizationRequest,
    SpendingAuthorization,
    SpendingAuthorizationSpendResult,
)
from services.funding_service.hosted_routing import (
    build_hosted_payment_challenge,
)
from services.funding_service.hosted_wallet_registry import (
    HostedWalletRegistry,
    HostedWalletRegistryError,
)
from services.funding_service.hosted_wallet_router import HostedWalletRouter
from services.account_service.repository import WalletIdentityRow
from services.funding_service.ledger import (
    FundingLedger,
    canonicalize_transaction_hash,
    require_matching_reservation_immutable_fields,
    require_unified_reservation,
)
from services.action_service.service import ActionService
from services.account_service.schemas import (
    MAX_UINT256,
    SpendingGrant,
    canonicalize_evm_address,
)
from services.policy_service.misttrack import MISTTRACK_ENDPOINT
from services.policy_service.risk_policy import RISK_MAPPING_VERSION
from services.policy_service.schemas import PolicyDecision
from services.policy_service.service import PolicyService
from services.audit_service.service import AuditService
from shared.canonical_assets import (
    AMOY_NETWORK,
    POLYGON_NETWORK,
    CanonicalAssetRegistry,
)
from shared.config import (
    AppConfig,
    CANONICAL_EVM_NETWORKS,
    receipt_signing_key_error,
)
from shared.evm_rpc import NetworkRpcTransport, RpcSubmissionRejected
from shared.payment_capability import (
    MAX_PAYMENT_CAPABILITY_LIFETIME_SECONDS,
    PAYMENT_CAPABILITY_VERSION,
    PaymentCapabilityV1,
    execution_scope_hash,
    policy_decision_snapshot_hash,
    revocation_projection_id,
    risk_evidence_hash,
    reservation_scope_hash,
    spending_grant_terms_hash,
)
from services.funding_service.hosted_client import (
    HostedExecutionRequest,
    HostedExecutionUnknown,
    HostedFacilitatorClient,
    HostedFacilitatorError,
)
from shared.hosted_facilitator_protocol import (
    DeviceSigningKey,
    HostedExecutionResponse,
    HostedProtocolError,
    HOSTED_CHAIN_PROFILES,
    HOSTED_PRODUCTION_CHAIN_IDS,
    hosted_chain_profile,
)


_TRANSFER_WITH_AUTHORIZATION_SELECTOR = bytes.fromhex("e3ee160e")
_TRANSFER_WITH_AUTHORIZATION_CALLDATA_BYTES = 4 + (9 * 32)
_CDP_FACILITATOR_ATTRIBUTION = bytes.fromhex(
    "a161776a6364705f666163696c31"
    "000e0280218021802180218021802180218021"
)
_EXTERNAL_AUTHORIZATION_CLOCK_SKEW_SECONDS = 60
_EXTERNAL_AUTHORIZATION_LIFETIME_SECONDS = 900
_MISTTRACK_COIN_BY_NETWORK = {
    "eip155:8453": "USDC-Base",
    "eip155:137": "USDC-Polygon",
}
_HOSTED_PRODUCTION_NETWORKS = tuple(
    sorted(
        profile.chain
        for profile in HOSTED_CHAIN_PROFILES.values()
        if profile.chain_id in HOSTED_PRODUCTION_CHAIN_IDS
    )
)


def _configured_hosted_client(config: AppConfig) -> HostedFacilitatorClient | None:
    """Build the legacy scalar Base bridge, if one is configured."""

    return _configured_hosted_clients(config).get("eip155:8453")


def _configured_hosted_clients(
    config: AppConfig,
) -> dict[str, HostedFacilitatorClient]:
    """Build one immutable-chain client per complete configured target."""

    if (
        config.clink_facilitator_mode != "hosted"
        or config.clink_hosted_wallet_credentials_file
        or getattr(config, "clink_hosted_wallet_credentials_files", {})
    ):
        return {}
    values = (
        config.clink_hosted_facilitator_tenant_id,
        config.clink_hosted_facilitator_node_id,
        config.clink_hosted_facilitator_wallet_binding_id,
        config.clink_hosted_facilitator_access_token,
        config.clink_hosted_facilitator_device_private_key,
    )
    if any(not value for value in values):
        return {}
    encoded_key = config.clink_hosted_facilitator_device_private_key
    if encoded_key.startswith("base64:"):
        encoded_key = encoded_key.removeprefix("base64:")
    try:
        if encoded_key.startswith("0x"):
            der = bytes.fromhex(encoded_key[2:])
        else:
            der = base64.b64decode(encoded_key, validate=True)
        device_key = DeviceSigningKey.from_pkcs8_der(der)
        clients: dict[str, HostedFacilitatorClient] = {}
        for chain, target in config.clink_hosted_facilitator_chain_targets.items():
            try:
                origin = target["origin"]
                response_jwk = target["server_public_jwk"]
                clients[chain] = HostedFacilitatorClient(
                    chain_id=chain,
                    origin=origin,
                    tenant_id=config.clink_hosted_facilitator_tenant_id,
                    node_id=config.clink_hosted_facilitator_node_id,
                    wallet_binding_id=config.clink_hosted_facilitator_wallet_binding_id,
                    access_token=config.clink_hosted_facilitator_access_token,
                    device_key=device_key,
                    server_public_jwk=response_jwk,
                )
            except (
                HostedProtocolError,
                ValueError,
                TypeError,
                KeyError,
                binascii.Error,
                UnicodeError,
            ):
                # Readiness reports the missing target without exposing the
                # invalid key or any enrollment secret.
                continue
        return clients
    except (
        HostedProtocolError,
        ValueError,
        TypeError,
        binascii.Error,
        UnicodeError,
    ):
        return {}


@dataclass(frozen=True)
class ReservationProvenance:
    action: Any
    authorization_path: str
    product: str | None
    unified_references: dict[str, str] | None
    authorization_rail: str = "native_allowance"


class _PrebroadcastRiskBlocked(ValueError):
    pass


class FundingService:
    """Owns user spending caps and Clink-native funding receipts."""

    def __init__(
        self,
        config: AppConfig | None = None,
        storage_file: Path | str | None = None,
        rpc_transport: Callable[[str, str, list], Any] | None = None,
        policy_service: PolicyService | None = None,
        hosted_client: HostedFacilitatorClient | None = None,
        hosted_clients: Mapping[str, HostedFacilitatorClient] | None = None,
        hosted_wallet_registry: HostedWalletRegistry | HostedWalletRouter | None = None,
    ) -> None:
        self.config = config or AppConfig.from_env()
        self._hosted_allowed_networks = (
            (self.config.clink_hosted_rehearsal_network,)
            if self.config.hosted_rehearsal_enabled
            else _HOSTED_PRODUCTION_NETWORKS
        )
        self.asset_registry = CanonicalAssetRegistry.from_config(self.config)
        if self.config.native_min_confirmations < 1:
            raise ValueError("native_min_confirmations must be positive")
        if self.config.payment_reconciliation_max_attempts < 1:
            raise ValueError("payment reconciliation max attempts must be positive")
        if self.config.payment_reconciliation_max_age_seconds < 1:
            raise ValueError("payment reconciliation max age must be positive")
        default_file = Path(__file__).resolve().parent / "funding_records.jsonl"
        self.storage_file = Path(storage_file or os.getenv("FUNDING_SESSION_FILE", str(default_file)))
        self.rpc_transport = rpc_transport or NetworkRpcTransport(
            self.config.configured_rpc_urls
        )
        self.policy_service = policy_service or PolicyService(config=self.config)
        self.ledger = FundingLedger(self.config.funding_database_url)
        configured_wallet_files = getattr(
            self.config, "clink_hosted_wallet_credentials_files", {}
        )
        scoped_hosted = hosted_wallet_registry is not None or bool(
            self.config.clink_hosted_wallet_credentials_file
        ) or bool(configured_wallet_files)
        if scoped_hosted and (hosted_client is not None or hosted_clients is not None):
            raise ValueError("wallet registry and global Hosted clients are mutually exclusive")
        self.hosted_wallet_registry = hosted_wallet_registry
        if self.hosted_wallet_registry is None and configured_wallet_files:
            self.hosted_wallet_registry = HostedWalletRouter(
                configured_wallet_files,
                chain_targets=self.config.clink_hosted_facilitator_chain_targets,
            )
        if (
            self.hosted_wallet_registry is None
            and self.config.clink_hosted_wallet_credentials_file
        ):
            self.hosted_wallet_registry = HostedWalletRegistry(
                self.config.clink_hosted_wallet_credentials_file,
                chain_targets=self.config.clink_hosted_facilitator_chain_targets,
            )
        if hosted_client is not None and hosted_clients is not None:
            raise ValueError("hosted_client and hosted_clients are mutually exclusive")
        if hosted_clients is None:
            configured_clients = _configured_hosted_clients(self.config)
        else:
            if not isinstance(hosted_clients, Mapping):
                raise ValueError("hosted_clients must be a mapping")
            configured_clients = dict(hosted_clients)
        if hosted_client is not None:
            # Existing tests and migration callers may inject the old scalar
            # client. Store it as an explicit Base mapping entry.
            configured_clients.setdefault("eip155:8453", hosted_client)
        self.hosted_clients = MappingProxyType(configured_clients)
        self.hosted_client = hosted_client or self.hosted_clients.get("eip155:8453")

    def reserve_spending(self, request: CreateSpendingReservationRequest) -> dict:
        provenance = self._verify_marketplace_provenance(request)
        if provenance.authorization_path != "unified_grant":
            raise ValueError("legacy spending authorizations are read-only")
        amount = self._parse_amount(request.amount_usdc)
        if amount <= 0:
            raise ValueError("reservation amount must be positive")
        return self._reserve_unified_spending(request, amount, provenance)

    def _reserve_unified_spending(self, request, amount, provenance):
        action = provenance.action
        now = self._utc_now()
        trusted_request = request.model_copy(
            update={
                **provenance.unified_references,
                "authorization_rail": provenance.authorization_rail,
                "spending_authorization_id": None,
            }
        )
        trusted_payload = trusted_request.model_dump()
        if trusted_request.opc_installation_id is None:
            trusted_payload.pop("opc_installation_id")
        with self.ledger.transaction() as tx:
            existing = tx.by_purchase(request.purchase_id)
            if existing:
                self._verify_reservation_replay(existing, trusted_request)
                return existing
            reservation_id = f"reserve_{uuid4().hex[:12]}"
            selection = tx.reserve_unified_budget(
                trusted_request,
                actor_user_id=action.user_id,
                actor_agent_id=action.agent_id,
                amount=amount,
                now=now,
                reservation_id=reservation_id,
                expected_selection={
                    "wallet_identity_id": provenance.unified_references[
                        "wallet_identity_id"
                    ],
                    "spending_grant_id": provenance.unified_references[
                        "spending_grant_id"
                    ],
                    "asset_allowance_id": (
                        provenance.unified_references["asset_allowance_id"]
                        if provenance.authorization_rail
                        in {"native_allowance", "clink_payer_proxy"}
                        else None
                    ),
                },
                external_token_decimals=self.config.x402_payment_token_decimals,
                external_token_symbol=self.config.x402_payment_token,
                canonical_token_address=self.asset_registry.token_address(
                    trusted_request.network
                ),
            )
            external_challenge = {}
            if provenance.authorization_rail == "external_x402":
                now_utc = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
                now_epoch = int(now_utc.timestamp())
                external_challenge = {
                    "nonce": "0x" + secrets.token_hex(32),
                    "valid_after": str(
                        now_epoch - _EXTERNAL_AUTHORIZATION_CLOCK_SKEW_SECONDS
                    ),
                    "valid_before": str(
                        now_epoch + _EXTERNAL_AUTHORIZATION_LIFETIME_SECONDS
                    ),
                }
            payload = {
                "reservation_id": reservation_id,
                **trusted_payload,
                **external_challenge,
                "user_id": action.user_id,
                "agent_id": action.agent_id,
                "product": provenance.product,
                "single_submission": provenance.product == "prediction_markets",
                "replacement_forbidden": False,
                "authorization_rail": provenance.authorization_rail,
                "token_address": selection["token_address"],
                "token_decimals": selection["token_decimals"],
                "token_symbol": selection["token_symbol"],
                "spender_address": selection["spender_address"],
                "authorization_path": "unified_grant",
                "budget_accounting_state": "reserved",
                "usage_date": selection["usage_date"].isoformat(),
                "state": "spending_reserved",
                "receipt_id": None,
                "tx_hash": None,
                "created_at": self._format_time(now),
            }
            tx.put(
                "reservation",
                reservation_id,
                payload,
                purchase_id=request.purchase_id,
                idempotency_key=request.idempotency_key,
                action_id=request.action_id,
                policy_decision_id=request.policy_decision_id,
                reservation_id=reservation_id,
            )
            return payload

    @staticmethod
    def _verify_reservation_replay(existing, request):
        if any(
            existing.get(key) != value
            for key, value in request.model_dump().items()
            if value is not None
        ):
            raise ValueError("purchase replay changed immutable scope")

    def _verify_marketplace_provenance(self, request: CreateSpendingReservationRequest) -> ReservationProvenance:
        action=ActionService(config=self.config).get_intent(request.action_id)
        policy=self.policy_service.get_decision(request.policy_decision_id)
        if not action:
            raise ValueError("funding action is missing or not approved")
        base_reference_keys = (
            "product",
            "wallet_identity_id",
            "spending_grant_id",
        )
        unified_markers = (*base_reference_keys, "asset_allowance_id", "authorization_rail")
        has_unified_provenance = any(key in action.metadata for key in unified_markers)
        unified_references = None
        authorization_rail = "native_allowance"
        if has_unified_provenance:
            if not all(key in action.metadata for key in base_reference_keys):
                raise ValueError("unified action provenance is incomplete")
            authorization_rail = action.metadata.get("authorization_rail")
            if authorization_rail not in {
                "native_allowance",
                "clink_payer_proxy",
                "external_x402",
            }:
                raise ValueError("unified action provenance is incomplete")
            has_allowance = "asset_allowance_id" in action.metadata
            if (
                authorization_rail in {"native_allowance", "clink_payer_proxy"}
                and not has_allowance
            ):
                raise ValueError("allowance-backed action requires asset allowance")
            if authorization_rail == "external_x402" and has_allowance:
                raise ValueError("external action provenance cannot include asset allowance")
            if authorization_rail == "external_x402" and "token_address" not in action.metadata:
                raise ValueError("external action provenance requires token address")
            unified_references = {
                key: action.metadata[key] for key in base_reference_keys
            }
            if has_allowance:
                unified_references["asset_allowance_id"] = action.metadata[
                    "asset_allowance_id"
                ]
            opc_installation_id = action.metadata.get("opc_installation_id")
            if opc_installation_id is not None:
                if not isinstance(opc_installation_id, str) or not opc_installation_id:
                    raise ValueError("unified OPC installation provenance is invalid")
                unified_references["opc_installation_id"] = opc_installation_id
        if unified_references is not None:
            if request.spending_authorization_id is not None:
                raise ValueError("unified action cannot use legacy spending authorization")
            if request.authorization_rail != authorization_rail:
                raise ValueError("unified authorization rail hint mismatch")
            for key, trusted_value in unified_references.items():
                if key == "opc_installation_id":
                    continue
                hinted_value = getattr(request, key)
                if hinted_value is not None and hinted_value != trusted_value:
                    raise ValueError("unified authorization reference hint mismatch")
            if request.opc_installation_id != unified_references.get(
                "opc_installation_id"
            ):
                raise ValueError("unified OPC installation reference hint mismatch")
        else:
            if request.spending_authorization_id is None:
                raise ValueError("legacy action requires spending authorization")
            if any(getattr(request, key) is not None for key in base_reference_keys):
                raise ValueError("legacy action cannot use unified authorization references")
            if request.opc_installation_id is not None:
                raise ValueError("legacy action cannot use an OPC installation")

        product = unified_references["product"] if unified_references else None
        if product == "transfers":
            if (
                request.venue != "clink_transfers"
                or request.merchant_id != request.destination
                or request.merchant_trust_tier is not None
                or authorization_rail != "native_allowance"
            ):
                raise ValueError("direct transfer provenance is invalid")
            action_type="funding_transfer"
            audit_source="clink_core_transfer"
            audit_event="direct_transfer_policy_evaluated"
        elif product == "prediction_markets":
            action_type="funding_transfer"
            audit_source="clink_prediction_markets"
            audit_event="prediction_market_funding_policy_evaluated"
        else:
            action_type="marketplace_purchase"
            audit_source="clink_marketplace"
            audit_event="marketplace_purchase_policy_evaluated"
        if action.action_type!=action_type or action.state not in {"policy_approved","user_approved"}:
            raise ValueError("funding action is missing or not approved")
        expected={"purchase_id":request.purchase_id,"quote_hash":request.quote_hash,"network":request.network,"asset":request.asset,"amount_atomic":request.amount_atomic,"destination":request.destination,"resource":request.resource}
        if unified_references is not None:
            expected["authorization_rail"] = authorization_rail
            expected.update(unified_references)
            if request.merchant_trust_tier is not None:
                expected["merchant_trust_tier"] = request.merchant_trust_tier
            if authorization_rail == "external_x402":
                expected["token_address"] = request.token_address
        if (
            action.merchant_id != request.merchant_id
            or self._parse_amount(action.amount_usdc) != self._parse_amount(request.amount_usdc)
            or action.policy_decision_id != request.policy_decision_id
            or action.metadata != expected
        ):
            raise ValueError("marketplace action scope mismatch")
        self._require_current_policy_controls(
            request,
            policy,
            action_type=action_type,
            user_id=action.user_id,
            agent_id=action.agent_id,
            expected_metadata=expected,
        )
        events = AuditService(
            database_url=self.config.funding_database_url
        ).get_trail(action_id=request.action_id).events
        matched=any(event.source_service==audit_source and event.event_type==audit_event and event.policy_decision_id==request.policy_decision_id and event.user_id==action.user_id and event.agent_id==action.agent_id and event.payload=={**expected,"merchant_id":request.merchant_id,"venue":request.venue} for event in events)
        if not matched: raise ValueError("exact marketplace policy audit event required")
        return ReservationProvenance(
            action=action,
            authorization_path="unified_grant" if unified_references else "legacy",
            product=product,
            unified_references=unified_references,
            authorization_rail=authorization_rail,
        )

    def _require_current_policy_controls(
        self,
        scope: CreateSpendingReservationRequest | dict,
        policy: Any,
        *,
        action_type: str,
        user_id: str,
        agent_id: str,
        expected_metadata: dict,
    ) -> datetime | None:
        destination = self._funding_scope_value(scope, "destination")
        try:
            policy_scope_matches = (
                policy is not None
                and getattr(policy, "approved", None) is True
                and getattr(policy, "policy_decision_id", None)
                == self._funding_scope_value(scope, "policy_decision_id")
                and getattr(policy, "action_id", None)
                == self._funding_scope_value(scope, "action_id")
                and getattr(policy, "action_type", None) == action_type
                and self._parse_amount(getattr(policy, "amount_usdc", ""))
                == self._parse_amount(
                    self._funding_scope_value(scope, "amount_usdc")
                )
                and getattr(policy, "merchant_id", None)
                == self._funding_scope_value(scope, "merchant_id")
                and getattr(policy, "user_id", None) == user_id
                and getattr(policy, "agent_id", None) == agent_id
                and getattr(policy, "target_address", None) == destination
                and getattr(policy, "chain", None)
                == self._funding_scope_value(scope, "network")
                and getattr(policy, "metadata", None) == expected_metadata
            )
        except (TypeError, ValueError):
            policy_scope_matches = False
        if not policy_scope_matches:
            raise ValueError("marketplace policy scope mismatch")
        if destination in self.config.funding_destination_denylist:
            raise ValueError("destination is denied by current funding policy")
        if (
            self.config.funding_destination_allowlist
            and destination not in self.config.funding_destination_allowlist
        ):
            raise ValueError("destination is not allowed by current funding policy")
        if not self.config.clink_live_funding:
            return None
        return self._require_fresh_misttrack_assessment(scope, policy)

    def _require_fresh_misttrack_assessment(
        self, scope: CreateSpendingReservationRequest | dict, policy: Any
    ) -> datetime:
        assessment = getattr(policy, "risk_assessment", None)
        network = self._funding_scope_value(scope, "network")
        asset = self._funding_scope_value(scope, "asset")
        destination = self._funding_scope_value(scope, "destination")
        if self.config.hosted_rehearsal_enabled and network == AMOY_NETWORK:
            expected_coin = "USDC-Polygon"
            expected_provider_network = POLYGON_NETWORK
        else:
            expected_coin = _MISTTRACK_COIN_BY_NETWORK.get(network)
            expected_provider_network = network
        provider_network = (
            assessment.get("provider_network", network)
            if isinstance(assessment, dict)
            else None
        )
        try:
            canonical_destination = self._canonical_evm_address(destination)
        except ValueError:
            canonical_destination = None
        try:
            canonical_asset = self.asset_registry.require_pair(network, asset)
        except (TypeError, ValueError):
            canonical_asset = None
        invalid = (
            not isinstance(assessment, dict)
            or assessment.get("provider") != "misttrack"
            or assessment.get("provider_endpoint") != MISTTRACK_ENDPOINT
            or assessment.get("mode") != "enforce"
            or assessment.get("enforced") is not True
            or assessment.get("mapping_version") != RISK_MAPPING_VERSION
            or type(assessment.get("hold_score")) is not int
            or assessment.get("hold_score") != self.config.risk_hold_score
            or type(assessment.get("deny_score")) is not int
            or assessment.get("deny_score") != self.config.risk_deny_score
            or destination != canonical_destination
            or assessment.get("subject") != canonical_destination
            or assessment.get("network") != network
            or provider_network != expected_provider_network
            or (
                network == AMOY_NETWORK
                and assessment.get("provider_network") != POLYGON_NETWORK
            )
            or canonical_asset is None
            or asset != canonical_asset.token_address
            or canonical_asset.token_symbol != "USDC"
            or assessment.get("asset") != "USDC"
            or expected_coin is None
            or assessment.get("coin") != expected_coin
        )
        if invalid:
            raise ValueError("live funding risk assessment is missing or not bound")

        try:
            assessed_at = self._parse_risk_timestamp(assessment.get("assessed_at"))
            expires_at = self._parse_risk_timestamp(assessment.get("expires_at"))
        except ValueError:
            raise ValueError("live funding risk assessment timestamps are invalid") from None
        now = self._risk_now()
        if (
            assessed_at > now
            or expires_at <= assessed_at
            or now >= expires_at
            or (now - assessed_at).total_seconds()
            > self.config.risk_max_age_seconds
        ):
            raise ValueError("live funding risk assessment is stale")

        decision = assessment.get("decision")
        hold_was_confirmed = decision == "hold" and any(
            self._valid_risk_hold_confirmation(
                event,
                assessed_at=assessed_at,
                now=now,
            )
            for event in (getattr(policy, "event_log", None) or [])
        )
        if decision != "allow" and not hold_was_confirmed:
            raise ValueError("live funding risk assessment is not approved")
        return expires_at

    def _valid_risk_hold_confirmation(
        self,
        event: Any,
        *,
        assessed_at: datetime,
        now: datetime,
    ) -> bool:
        if not isinstance(event, dict) or set(event) != {"event", "created_at"}:
            return False
        if event.get("event") != "risk_hold_confirmed":
            return False
        try:
            confirmed_at = self._parse_risk_timestamp(event.get("created_at"))
        except ValueError:
            return False
        return assessed_at <= confirmed_at <= now

    @staticmethod
    def _funding_scope_value(
        scope: CreateSpendingReservationRequest | dict, field: str
    ) -> Any:
        return scope.get(field) if isinstance(scope, dict) else getattr(scope, field)

    @staticmethod
    def _parse_risk_timestamp(value: Any) -> datetime:
        if not isinstance(value, str) or not value:
            raise ValueError("risk timestamp must be a timezone-aware string")
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
            offset = parsed.utcoffset()
        except (OverflowError, TypeError, ValueError):
            raise ValueError("risk timestamp is invalid") from None
        if parsed.tzinfo is None or offset is None:
            raise ValueError("risk timestamp must include a timezone")
        return parsed.astimezone(UTC)

    def _risk_now(self) -> datetime:
        now = self._utc_now()
        if not isinstance(now, datetime):
            raise ValueError("funding clock is invalid")
        if now.tzinfo is None:
            return now.replace(tzinfo=UTC)
        return now.astimezone(UTC)

    @staticmethod
    def _policy_metadata_from_reservation(row: dict) -> dict:
        expected = {
            key: row[key]
            for key in (
                "purchase_id",
                "quote_hash",
                "network",
                "asset",
                "amount_atomic",
                "destination",
                "resource",
            )
        }
        expected.update(
            {
                "authorization_rail": row["authorization_rail"],
                "product": row["product"],
                "wallet_identity_id": row["wallet_identity_id"],
                "spending_grant_id": row["spending_grant_id"],
            }
        )
        if row.get("asset_allowance_id") is not None:
            expected["asset_allowance_id"] = row["asset_allowance_id"]
        if row.get("opc_installation_id") is not None:
            expected["opc_installation_id"] = row["opc_installation_id"]
        if row.get("merchant_trust_tier") is not None:
            expected["merchant_trust_tier"] = row["merchant_trust_tier"]
        if row["authorization_rail"] == "external_x402":
            expected["token_address"] = row["token_address"]
        return expected

    @staticmethod
    def _policy_action_type(product: str | None) -> str:
        return (
            "funding_transfer"
            if product in {"prediction_markets", "transfers"}
            else "marketplace_purchase"
        )

    def _require_reservation_policy_controls(self, row: dict) -> datetime:
        policy = self.policy_service.get_decision(row["policy_decision_id"])
        risk_expires_at = self._require_current_policy_controls(
            row,
            policy,
            action_type=self._policy_action_type(row.get("product")),
            user_id=row["user_id"],
            agent_id=row["agent_id"],
            expected_metadata=self._policy_metadata_from_reservation(row),
        )
        if risk_expires_at is None:
            raise ValueError("live funding risk assessment is missing or not bound")
        return risk_expires_at

    def get_reservation(self, reservation_id: str) -> dict | None:
        with self.ledger.transaction() as tx: return tx.get(reservation_id)

    def issue_payment_capability(
        self,
        reservation_id: str,
        request: IssuePaymentCapabilityRequest,
    ) -> PaymentCapabilityV1:
        """Seal one active Core reservation for Hosted execution.

        Hosted may contribute only its enrollment and challenge facts.  The
        reservation, wallet authorization, policy/risk decision and all
        execution scope are re-read under the funding transaction lock.
        """

        if not isinstance(request, IssuePaymentCapabilityRequest):
            try:
                request = IssuePaymentCapabilityRequest.model_validate(
                    request, strict=True
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("payment capability request is invalid") from exc

        now = self._as_utc_datetime(self._utc_now())
        issued_at = int(now.timestamp())
        if issued_at <= 0:
            raise ValueError("funding clock is invalid")

        with self.ledger.transaction() as tx:
            row = tx.get(reservation_id)
            if row is None:
                raise ValueError("reservation not found")
            if row.get("state") != "spending_reserved":
                raise ValueError("payment capability requires a spending_reserved reservation")
            if row.get("budget_accounting_state") != "reserved":
                raise ValueError("payment capability requires a reserved budget")
            require_unified_reservation(row)
            if row.get("authorization_rail") not in {
                "native_allowance",
                "clink_payer_proxy",
            }:
                raise ValueError("payment capability requires an allowance-backed reservation")
            if any(
                row.get(field) is not None
                for field in (
                    "receipt_id",
                    "tx_hash",
                    "settlement_transaction",
                    "settlement_sender",
                    "settlement_nonce",
                    "payment_authorization",
                )
            ):
                raise ValueError("payment capability cannot bind a submitted reservation")

            amount_atomic = row.get("amount_atomic")
            if (
                not isinstance(amount_atomic, str)
                or re.fullmatch(r"[1-9][0-9]*", amount_atomic) is None
            ):
                raise ValueError("reservation amount_atomic must be a positive integer")
            amount = int(amount_atomic, 10)
            if amount > MAX_UINT256:
                raise ValueError("reservation amount_atomic exceeds uint256")

            existing = tx.payment_capability_for_reservation(reservation_id)
            if existing is not None and existing.expires_at <= issued_at:
                raise ValueError("payment capability is expired and terminal")

            identity, grant, allowance = tx.validate_unified_lifecycle(
                row, now=now
            )
            registry = getattr(self, "hosted_wallet_registry", None)
            if registry is not None:
                # Selection follows the Core identity locked above, never an
                # enrollment supplied by the caller or the sandbox runtime.
                credential = (
                    registry.for_capability(existing, for_submission=True)
                    if existing is not None
                    else registry.current(
                        user_id=identity.user_id,
                        wallet_identity_id=identity.wallet_identity_id,
                        network=row["network"],
                    )
                )
                if any(getattr(request, field) != getattr(credential, field) for field in (
                    "tenant_id", "node_id", "wallet_binding_id"
                )):
                    raise ValueError("Hosted enrollment identity does not match verified wallet")
            if allowance is None:
                raise ValueError("active asset allowance is required")
            executor_contract = request.executor_contract
            if self.config.clink_facilitator_mode == "hosted":
                configured_executor = self._hosted_executor_address(
                    self.config.clink_hosted_facilitator_chain_targets.get(
                        row["network"]
                    )
                )
                if configured_executor is None:
                    raise ValueError(
                        "Hosted target executor contract is not configured"
                    )
                if configured_executor != executor_contract:
                    raise ValueError(
                        "requested executor does not match Hosted target"
                    )
            if allowance.spender_address.lower() != executor_contract:
                raise ValueError("requested executor does not match allowance spender")
            try:
                observed_allowance = int(allowance.observed_allowance_atomic)
            except (TypeError, ValueError, InvalidOperation):
                raise ValueError("observed allowance is invalid") from None
            if observed_allowance < amount:
                raise ValueError("asset allowance is insufficient for reservation amount")

            action, policy = tx.locked_payment_authorities(
                row["action_id"], row["policy_decision_id"]
            )
            if action is None or policy is None:
                raise ValueError("funding action or policy decision is missing")
            risk_expires_at = self._require_current_policy_controls(
                row,
                policy,
                action_type=self._policy_action_type(row.get("product")),
                user_id=row["user_id"],
                agent_id=row["agent_id"],
                expected_metadata=self._policy_metadata_from_reservation(row),
            )
            if risk_expires_at is None:
                raise ValueError("live funding risk assessment is missing or not bound")
            policy = self._payment_capability_policy(policy)
            if action.state not in {"policy_approved", "user_approved"}:
                raise ValueError("funding action is not approved")
            if action.user_id != row["user_id"] or action.agent_id != row["agent_id"]:
                raise ValueError("funding action identity mismatch")
            if action.action_type != self._policy_action_type(row.get("product")):
                raise ValueError("funding action type mismatch")
            if action.merchant_id != row.get("merchant_id"):
                raise ValueError("funding action merchant mismatch")
            if self._parse_amount(action.amount_usdc) != self._parse_amount(
                row["amount_usdc"]
            ):
                raise ValueError("funding action amount mismatch")
            if action.metadata != self._policy_metadata_from_reservation(row):
                raise ValueError("funding action scope mismatch")
            if action.policy_decision_id != row["policy_decision_id"]:
                raise ValueError("funding action policy mismatch")

            grant_model = self._payment_capability_grant(grant)
            grant_hash = spending_grant_terms_hash(grant_model)
            policy_hash = policy_decision_snapshot_hash(policy)
            risk_hash = risk_evidence_hash(policy.risk_assessment)
            scope_hash = execution_scope_hash(
                network=row["network"],
                asset_contract=row["token_address"],
                wallet_address=identity.wallet_address,
                executor_contract=executor_contract,
                pay_to=row["destination"],
                amount_atomic=amount_atomic,
                purchase_id=row["purchase_id"],
                reservation_id=row["reservation_id"],
                quote_hash=row["quote_hash"],
            )
            reservation_hash = reservation_scope_hash(
                reservation_id=row["reservation_id"],
                purchase_id=row["purchase_id"],
                user_id=row["user_id"],
                agent_id=row["agent_id"],
                wallet_identity_id=row["wallet_identity_id"],
                spending_grant_id=row["spending_grant_id"],
                asset_allowance_id=row["asset_allowance_id"],
                action_id=row["action_id"],
                policy_decision_id=row["policy_decision_id"],
                merchant_id=row["merchant_id"],
                product=row["product"],
                venue=row["venue"],
                quote_hash=row["quote_hash"],
                network=row["network"],
                asset_contract=row["token_address"],
                amount_atomic=amount_atomic,
                pay_to=row["destination"],
                authorization_rail=row["authorization_rail"],
            )
            revocation_id = revocation_projection_id(
                wallet_identity_id=identity.wallet_identity_id,
                spending_grant_id=grant.spending_grant_id,
                asset_allowance_id=allowance.asset_allowance_id,
                wallet_binding_id=request.wallet_binding_id,
            )
            grant_expires_at = self._as_utc_datetime(grant.expires_at)
            risk_expires_at = self._as_utc_datetime(risk_expires_at)
            expires_at = min(
                issued_at + MAX_PAYMENT_CAPABILITY_LIFETIME_SECONDS,
                int(grant_expires_at.timestamp()),
                int(risk_expires_at.timestamp()),
            )
            if existing is None and expires_at <= issued_at:
                raise ValueError("payment capability authority is expired")

            if existing is not None:
                replay_authority_expires_at = min(
                    existing.issued_at + MAX_PAYMENT_CAPABILITY_LIFETIME_SECONDS,
                    int(grant_expires_at.timestamp()),
                    int(risk_expires_at.timestamp()),
                )
                if replay_authority_expires_at < existing.expires_at:
                    raise ValueError("payment capability authority changed or expired")
                capability_issued_at = existing.issued_at
                capability_expires_at = existing.expires_at
            else:
                capability_issued_at = issued_at
                capability_expires_at = expires_at

            capability = PaymentCapabilityV1(
                capability_version=PAYMENT_CAPABILITY_VERSION,
                capability_id=self._payment_capability_id(reservation_id),
                user_id=identity.user_id,
                agent_id=grant.agent_id,
                tenant_id=request.tenant_id,
                node_id=request.node_id,
                wallet_binding_id=request.wallet_binding_id,
                wallet_identity_id=identity.wallet_identity_id,
                wallet_address=identity.wallet_address,
                spending_grant_id=grant.spending_grant_id,
                spending_grant_hash=grant_hash,
                asset_allowance_id=allowance.asset_allowance_id,
                action_id=row["action_id"],
                policy_decision_id=row["policy_decision_id"],
                policy_snapshot_hash=policy_hash,
                risk_evidence_hash=risk_hash,
                reservation_id=row["reservation_id"],
                reservation_hash=reservation_hash,
                purchase_id=row["purchase_id"],
                merchant_id=row["merchant_id"],
                product=row["product"],
                venue=row["venue"],
                quote_hash=row["quote_hash"],
                payment_challenge_hash=request.payment_challenge_hash,
                network=row["network"],
                asset_contract=row["token_address"],
                amount_atomic=amount_atomic,
                pay_to=row["destination"],
                executor_contract=executor_contract,
                execution_scope_hash=scope_hash,
                confirmation_mode=(
                    "policy_approved"
                    if action.state == "policy_approved"
                    and policy.authorization_approved is True
                    else "user_approved"
                ),
                revocation_id=revocation_id,
                issued_at=capability_issued_at,
                expires_at=capability_expires_at,
            )
            if existing is not None:
                if capability != existing:
                    raise ValueError("payment capability authority or replay scope changed")
                return existing
            return tx.put_payment_capability(
                capability,
                idempotency_key=row["idempotency_key"],
            )

    @staticmethod
    def _validate_hosted_reservation_capability(
        row: dict, capability: PaymentCapabilityV1
    ) -> None:
        expected = {
            "reservation_id": capability.reservation_id,
            "purchase_id": capability.purchase_id,
            "action_id": capability.action_id,
            "policy_decision_id": capability.policy_decision_id,
            "quote_hash": capability.quote_hash,
            "merchant_id": capability.merchant_id,
            "wallet_identity_id": capability.wallet_identity_id,
            "spending_grant_id": capability.spending_grant_id,
            "asset_allowance_id": capability.asset_allowance_id,
            "network": capability.network,
            "token_address": capability.asset_contract,
            "amount_atomic": capability.amount_atomic,
            "destination": capability.pay_to,
            "spender_address": capability.executor_contract,
        }
        if any(row.get(field) != value for field, value in expected.items()):
            raise ValueError("hosted reservation scope changed")

    @contextmanager
    def _hosted_authority_scope(
        self,
        reservation_id: str,
        *,
        require_spending_reserved: bool,
        require_live: bool,
    ):
        now = self._as_utc_datetime(self._utc_now())
        now_timestamp = int(now.timestamp())
        if now_timestamp <= 0:
            raise ValueError("funding clock is invalid")

        with self.ledger.transaction() as tx:
            row = tx.get(reservation_id)
            if row is None:
                raise ValueError("reservation not found")
            if require_spending_reserved:
                if row.get("state") != "spending_reserved":
                    raise ValueError("hosted preflight requires an active reservation")
            elif row.get("state") not in {"spending_reserved", "payment_submitted"}:
                raise ValueError("hosted authority requires an active reservation")
            if row.get("budget_accounting_state") != "reserved":
                raise ValueError("hosted authority requires a reserved budget")
            require_unified_reservation(row)
            if require_live or row.get("state") == "spending_reserved":
                tx.validate_unified_lifecycle(row, now=now)

            capability = tx.payment_capability_for_reservation(reservation_id)
            if capability is None:
                raise ValueError("Hosted payment capability is unavailable")
            if capability.network not in self._hosted_allowed_networks_projection():
                raise ValueError(
                    "Hosted economic rail only supports configured Hosted chains"
                )
            if capability.expires_at <= now_timestamp:
                raise ValueError("Hosted payment capability is expired")
            self._validate_hosted_reservation_capability(row, capability)
            yield tx, row, capability, now_timestamp

    def authorize_hosted_preflight(
        self,
        reservation_id: str,
        request: HostedPreflightAuthorityRequest,
    ) -> HostedPreflightAuthorityRequest:
        """Return the Core-owned scope for a dry-run Hosted preflight.

        This is a read-only check.  It deliberately binds only the signed
        preflight envelope and the durable capability/reservation scope; the
        execution-only ``hosted_request_*`` fields are not consulted.
        """

        if not isinstance(request, HostedPreflightAuthorityRequest):
            try:
                request = HostedPreflightAuthorityRequest.model_validate(
                    request, strict=True
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("hosted preflight authority request is invalid") from exc
        if request.reservation_id != reservation_id:
            raise ValueError("hosted preflight reservation is invalid")
        if request.chain_id not in self._hosted_allowed_networks_projection():
            raise ValueError(
                "Hosted economic rail only supports configured Hosted chains"
            )

        with self._hosted_authority_scope(
            reservation_id,
            require_spending_reserved=True,
            require_live=True,
        ) as (_tx, row, capability, _now_timestamp):
            expected = {
                "payment_capability_version": capability.capability_version,
                "payment_capability_id": capability.capability_id,
                "payment_capability_hash": capability.capability_hash,
                "tenant_id": capability.tenant_id,
                "node_id": capability.node_id,
                "wallet_binding_id": capability.wallet_binding_id,
                "wallet_identity_id": capability.wallet_identity_id,
                "wallet_address": capability.wallet_address,
                "spending_grant_id": capability.spending_grant_id,
                "spending_grant_hash": capability.spending_grant_hash,
                "asset_allowance_id": capability.asset_allowance_id,
                "reservation_id": capability.reservation_id,
                "reservation_hash": capability.reservation_hash,
                "action_id": capability.action_id,
                "policy_decision_id": capability.policy_decision_id,
                "policy_snapshot_hash": capability.policy_snapshot_hash,
                "risk_evidence_hash": capability.risk_evidence_hash,
                "purchase_id": capability.purchase_id,
                "merchant_id": capability.merchant_id,
                "quote_hash": capability.quote_hash,
                "payment_challenge_hash": capability.payment_challenge_hash,
                "chain_id": capability.network,
                "asset_contract": capability.asset_contract,
                "amount_atomic": capability.amount_atomic,
                "pay_to": capability.pay_to,
                "executor_contract": capability.executor_contract,
                "execution_scope_hash": capability.execution_scope_hash,
                "issued_at": capability.issued_at,
                "expires_at": capability.expires_at,
            }
            if any(getattr(request, field) != value for field, value in expected.items()):
                raise ValueError("hosted preflight scope changed")
            if request.idempotency_key != row.get("idempotency_key"):
                raise ValueError("hosted preflight idempotency binding changed")
            return request

    def authorize_hosted_execution(
        self,
        reservation_id: str,
        request: HostedExecutionAuthorityRequest,
    ) -> HostedExecutionAuthorityRequest:
        """Return the exact Core-bound execution scope for the Facilitator.

        This endpoint is deliberately read-only.  It never creates a
        capability or changes a reservation; it only re-reads the durable
        reservation and capability under the funding lock and echoes the
        validated immutable scope.  Callers must therefore issue the
        capability through ``issue_payment_capability`` first.
        """

        if not isinstance(request, HostedExecutionAuthorityRequest):
            try:
                request = HostedExecutionAuthorityRequest.model_validate(
                    request, strict=True
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("hosted authority request is invalid") from exc
        if request.reservation_id != reservation_id:
            raise ValueError("hosted authority reservation is invalid")
        if request.chain_id not in self._hosted_allowed_networks_projection():
            raise ValueError(
                "Hosted economic rail only supports configured Hosted chains"
            )
        try:
            profile = hosted_chain_profile(request.chain_id)
        except ValueError:
            raise ValueError("Hosted execution chain is unsupported") from None

        with self._hosted_authority_scope(
            reservation_id,
            require_spending_reserved=False,
            require_live=False,
        ) as (_tx, row, capability, _now_timestamp):
            if capability.network != request.chain_id or (
                capability.asset_contract.lower() != profile.token
            ):
                raise ValueError("Hosted authority asset scope is invalid")

            expected_request = {
                "request_id": row.get("hosted_request_id"),
                "request_hash": row.get("hosted_request_hash"),
                "request_nonce": row.get("hosted_request_nonce"),
                "idempotency_key": row.get("idempotency_key"),
            }
            if any(
                expected_request[field] is None
                or getattr(request, field) != expected_request[field]
                for field in expected_request
            ):
                raise ValueError("hosted request binding changed")

            expected = {
                "tenant_id": capability.tenant_id,
                "node_id": capability.node_id,
                "wallet_binding_id": capability.wallet_binding_id,
                "capability_id": capability.capability_id,
                "capability_hash": capability.capability_hash,
                "reservation_id": capability.reservation_id,
                "reservation_hash": capability.reservation_hash,
                "purchase_id": capability.purchase_id,
                "owner": capability.wallet_address,
                "payee": capability.pay_to,
                "token": capability.asset_contract,
                "amount_atomic": capability.amount_atomic,
                "executor": capability.executor_contract,
                "deadline": capability.expires_at,
                "execution_scope_hash": capability.execution_scope_hash,
            }
            if any(getattr(request, field) != value for field, value in expected.items()):
                raise ValueError("hosted authority scope changed")
            if request.payment_challenge_hash is not None and (
                request.payment_challenge_hash != capability.payment_challenge_hash
            ):
                raise ValueError("hosted payment challenge changed")
            if not request.relayer_address or request.relayer_address == capability.wallet_address:
                raise ValueError("hosted relayer scope is invalid")

            # Core does not sign an EVM digest here.  It does bind the
            # supplied digest, epoch and relayer to the exact request that
            # was checked; the Facilitator independently recomputes the
            # digest before allowing the relayer to sign or broadcast.
            return request.model_copy(
                update={"payment_challenge_hash": capability.payment_challenge_hash}
            )

    @staticmethod
    def _payment_capability_policy(policy: Any) -> PolicyDecision:
        if isinstance(policy, PolicyDecision):
            if policy.approved is not True:
                raise ValueError("current policy decision is not approved")
            return policy
        try:
            if isinstance(policy, dict):
                projection = dict(policy)
            elif hasattr(policy, "model_dump"):
                projection = policy.model_dump(mode="json")
            elif hasattr(policy, "__dict__"):
                projection = dict(vars(policy))
            else:
                raise TypeError("policy projection is not a mapping")
            projection.setdefault("reasons", [])
            projection.setdefault("required_action", None)
            projection.setdefault("authorization_id", None)
            projection.setdefault("authorization_approved", None)
            projection.setdefault("remaining_amount_usdc", None)
            projection.setdefault("risk_level", None)
            projection.setdefault("risk_score", None)
            projection.setdefault("risk_action", None)
            projection.setdefault("risk_assessment", None)
            projection.setdefault("credit_model_assessment", None)
            projection.setdefault("evaluated_at", "1970-01-01T00:00:00Z")
            projection.setdefault("event_log", [])
            projection.setdefault("metadata", {})
            normalized = PolicyDecision.model_validate(projection, strict=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("current policy decision is invalid") from exc
        if normalized.approved is not True:
            raise ValueError("current policy decision is not approved")
        return normalized

    @staticmethod
    def _payment_capability_grant(grant: Any) -> SpendingGrant:
        try:
            def utc_timestamp(value: datetime) -> datetime:
                if value.tzinfo is None or value.utcoffset() is None:
                    return value.replace(tzinfo=UTC)
                return value.astimezone(UTC)

            normalized = SpendingGrant.model_validate(
                {
                    "spending_grant_id": grant.spending_grant_id,
                    "wallet_identity_id": grant.wallet_identity_id,
                    "user_id": grant.user_id,
                    "agent_id": grant.agent_id,
                    "status": grant.status,
                    "status_reason": grant.status_reason,
                    "max_amount_usdc": grant.max_amount_usdc,
                    "per_transaction_limit_usdc": grant.per_transaction_limit_usdc,
                    "hourly_limit_usdc": grant.hourly_limit_usdc,
                    "daily_limit_usdc": grant.daily_limit_usdc,
                    "used_amount_usdc": grant.used_amount_usdc,
                    "reserved_amount_usdc": grant.reserved_amount_usdc,
                    "product_scopes": grant.product_scopes,
                    "venue_scopes": grant.venue_scopes,
                    "merchant_scopes": grant.merchant_scopes,
                    "merchant_trust_scopes": grant.merchant_trust_scopes,
                    "notification_mode": grant.notification_mode,
                    "network_scopes": grant.network_scopes,
                    "asset_scopes": grant.asset_scopes,
                    "starts_at": utc_timestamp(grant.starts_at),
                    "expires_at": utc_timestamp(grant.expires_at),
                    "created_at": utc_timestamp(grant.created_at),
                    "updated_at": utc_timestamp(grant.updated_at),
                },
                strict=True,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("active spending grant is invalid") from exc
        return normalized

    @staticmethod
    def _payment_capability_id(reservation_id: str) -> str:
        if not isinstance(reservation_id, str) or not reservation_id:
            raise ValueError("reservation_id is required")
        return "capability_" + hashlib.sha256(reservation_id.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _hosted_requested(request: SettleSpendingReservationRequest) -> bool:
        authorization = request.payment_authorization
        return isinstance(authorization, dict) and authorization.get("kind") == "hosted_execution"

    def _hosted_selected_for_business(
        self,
        row: Mapping[str, Any],
        *,
        has_hosted_capability: bool,
    ) -> bool:
        if row.get("settlement_rail") == "hosted" or has_hosted_capability:
            return True
        return (
            self.config.clink_facilitator_mode == "hosted"
            and row.get("authorization_rail") == "native_allowance"
        )

    def _hosted_authorization(
        self, request: SettleSpendingReservationRequest
    ) -> HostedExecutionAuthorization:
        try:
            return HostedExecutionAuthorization.model_validate(
                request.payment_authorization, strict=True
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("hosted execution authorization is invalid") from exc

    def _hosted_business_authorization(
        self,
        row: Mapping[str, Any],
        request: SettleSpendingReservationRequest,
    ) -> tuple[HostedExecutionAuthorization, str]:
        challenge = build_hosted_payment_challenge(
            request.payment_authorization,
            row,
        )
        executor = self._hosted_executor_address(
            self.config.clink_hosted_facilitator_chain_targets.get(row.get("network"))
        )
        if executor is None:
            raise ValueError("Hosted target executor contract is not configured")
        registry = getattr(self, "hosted_wallet_registry", None)
        if registry is not None:
            with self.ledger.transaction() as tx:
                sealed = tx.payment_capability_for_reservation(row["reservation_id"])
            # Recovery remains pinned to the original enrollment, even after a
            # user changes wallets or an operator retires it to recovery-only.
            credential = (
                registry.for_capability(sealed)
                if sealed is not None
                else registry.current(
                    user_id=row["user_id"],
                    wallet_identity_id=row["wallet_identity_id"],
                    network=row["network"],
                )
            )
            tenant_id, node_id, wallet_binding_id = (
                credential.tenant_id, credential.node_id, credential.wallet_binding_id
            )
        else:
            tenant_id, node_id, wallet_binding_id = (
                self.config.clink_hosted_facilitator_tenant_id,
                self.config.clink_hosted_facilitator_node_id,
                self.config.clink_hosted_facilitator_wallet_binding_id,
            )
        try:
            authorization = HostedExecutionAuthorization(
                tenant_id=tenant_id,
                node_id=node_id,
                wallet_binding_id=wallet_binding_id,
                executor_contract=executor,
                payment_challenge_hash=challenge,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Hosted enrollment is not ready") from exc
        return authorization, challenge

    def _configured_hosted_production_networks(self) -> tuple[str, ...]:
        targets = self.config.clink_hosted_facilitator_chain_targets
        return tuple(
            network
            for network in self._hosted_allowed_networks_projection()
            if network in targets
        )

    def _hosted_allowed_networks_projection(self) -> tuple[str, ...]:
        """Return the instance's narrow Hosted network scope.

        A few migration callers construct a service with ``__new__`` and
        inject only the methods they exercise.  Keep those callers on the
        historical production projection while normal construction uses the
        explicit rehearsal gate calculated in ``__init__``.
        """

        configured = getattr(self, "_hosted_allowed_networks", None)
        if configured is not None:
            return configured
        config = getattr(self, "config", None)
        if config is not None and getattr(config, "hosted_rehearsal_enabled", False):
            return (config.clink_hosted_rehearsal_network,)
        return _HOSTED_PRODUCTION_NETWORKS

    @staticmethod
    def _hosted_executor_address(target: object) -> str | None:
        if not isinstance(target, Mapping):
            return None
        try:
            executor = canonicalize_evm_address(target.get("executor_contract"))
        except (TypeError, ValueError):
            return None
        if executor == "0x" + "0" * 40:
            return None
        return executor

    def _hosted_spender_addresses(
        self, networks: tuple[str, ...]
    ) -> dict[str, str]:
        return {
            network: executor
            for network in networks
            if (executor := self._hosted_executor_address(
                self.config.clink_hosted_facilitator_chain_targets.get(network)
            ))
        }

    def _hosted_configuration_missing(self) -> list[str]:
        required = {
            "CLINK_HOSTED_FACILITATOR_TENANT_ID": self.config.clink_hosted_facilitator_tenant_id,
            "CLINK_HOSTED_FACILITATOR_NODE_ID": self.config.clink_hosted_facilitator_node_id,
            "CLINK_HOSTED_FACILITATOR_WALLET_BINDING_ID": self.config.clink_hosted_facilitator_wallet_binding_id,
            "CLINK_HOSTED_FACILITATOR_ACCESS_TOKEN": self.config.clink_hosted_facilitator_access_token,
            "CLINK_HOSTED_FACILITATOR_DEVICE_PRIVATE_KEY": self.config.clink_hosted_facilitator_device_private_key,
        }
        scoped_wallets = (
            getattr(self, "hosted_wallet_registry", None) is not None
            or bool(getattr(self.config, "clink_hosted_wallet_credentials_files", {}))
        )
        missing = (
            []
            if scoped_wallets
            else [field_name for field_name, value in required.items() if not value]
        )
        targets = self.config.clink_hosted_facilitator_chain_targets
        if not targets:
            missing.append("CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS")
        allowed_networks = self._configured_hosted_production_networks()
        if targets and not allowed_networks:
            missing.append(
                "CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS must include an allowed target"
            )
        for network in allowed_networks:
            target = targets.get(network)
            if not isinstance(target, Mapping):
                missing.append(
                    f"CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS[{network}]"
                )
                continue
            if not target.get("origin"):
                missing.append(
                    f"CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS[{network}].origin"
                )
            if not target.get("server_public_jwk"):
                missing.append(
                    f"CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS[{network}].server_public_jwk"
                )
            if self._hosted_executor_address(target) is None:
                missing.append(
                    f"CLINK_HOSTED_FACILITATOR_CHAIN_TARGETS[{network}].executor_contract"
                )
        return missing

    @staticmethod
    def _validate_hosted_client_identity(
        client: HostedFacilitatorClient,
        capability: PaymentCapabilityV1,
    ) -> None:
        expected = {
            "tenant_id": capability.tenant_id,
            "node_id": capability.node_id,
            "wallet_binding_id": capability.wallet_binding_id,
        }
        for field_name, value in expected.items():
            actual = getattr(client, field_name, None)
            if actual != value:
                raise ValueError(
                    "Hosted enrollment identity does not match capability"
                )

    def _require_hosted_client(
        self,
        network: str,
        *,
        capability: PaymentCapabilityV1 | None = None,
        for_submission: bool = False,
    ) -> HostedFacilitatorClient:
        if self.config.clink_facilitator_mode != "hosted":
            raise ValueError("Hosted execution is not enabled")
        if network not in self._hosted_allowed_networks_projection():
            raise ValueError(
                "Hosted economic rail only supports configured Hosted chains"
            )
        try:
            hosted_chain_profile(network)
        except ValueError:
            raise ValueError("Hosted execution chain is unsupported") from None
        configured_executor = self._hosted_executor_address(
            self.config.clink_hosted_facilitator_chain_targets.get(network)
        )
        if configured_executor is None:
            raise ValueError(
                f"Hosted target executor contract for {network} is not configured"
            )
        registry = getattr(self, "hosted_wallet_registry", None)
        if registry is not None:
            if capability is None:
                raise ValueError("Hosted wallet capability is required")
            credential = registry.for_capability(
                capability,
                for_submission=for_submission,
            )
            client = registry.client(credential, network)
        else:
            client = self.hosted_clients.get(network)
        if client is None:
            raise ValueError(f"Hosted target for {network} is not configured")
        client_chain = getattr(client, "chain_id", None)
        if client_chain != network:
            raise ValueError("Hosted client chain does not match durable network")
        if not all(
            callable(getattr(client, method, None))
            for method in (
                "prepare_execution",
                "submit",
                "recover",
                "recover_by_idempotency",
            )
        ):
            raise ValueError("Hosted execution configuration is incomplete")
        if capability is not None:
            if capability.executor_contract.lower() != configured_executor:
                raise ValueError(
                    "Hosted capability executor does not match configured target"
                )
            self._validate_hosted_client_identity(client, capability)
        return client

    def _hosted_capability(
        self,
        reservation_id: str,
        authorization: HostedExecutionAuthorization,
        *,
        require_reserved: bool,
    ) -> PaymentCapabilityV1:
        if require_reserved:
            capability = self.issue_payment_capability(
                reservation_id,
                IssuePaymentCapabilityRequest(
                    tenant_id=authorization.tenant_id,
                    node_id=authorization.node_id,
                    wallet_binding_id=authorization.wallet_binding_id,
                    executor_contract=authorization.executor_contract,
                    payment_challenge_hash=authorization.payment_challenge_hash,
                ),
            )
            self._require_hosted_client(capability.network, capability=capability)
            return capability
        with self.ledger.transaction() as tx:
            capability = tx.payment_capability_for_reservation(reservation_id)
        if capability is None:
            raise ValueError("Hosted payment capability is unavailable")
        if (
            capability.tenant_id != authorization.tenant_id
            or capability.node_id != authorization.node_id
            or capability.wallet_binding_id != authorization.wallet_binding_id
            or capability.executor_contract != authorization.executor_contract
            or capability.payment_challenge_hash != authorization.payment_challenge_hash
        ):
            raise ValueError("Hosted execution authorization scope changed")
        self._require_hosted_client(capability.network, capability=capability)
        return capability

    def _prepare_hosted_request(
        self,
        row: dict,
        capability: PaymentCapabilityV1,
        client: HostedFacilitatorClient,
    ) -> HostedExecutionRequest:
        return client.prepare_execution(
            capability,
            request_id=row.get("hosted_request_id") or row["reservation_id"],
            idempotency_key=row["idempotency_key"],
            request_nonce=row.get("hosted_request_nonce"),
            now=(
                int(row["hosted_request_issued_at"])
                if row.get("hosted_request_issued_at") is not None
                else None
            ),
        )

    def _settle_hosted_reservation(
        self,
        reservation_id: str,
        request: SettleSpendingReservationRequest,
        *,
        authorization: HostedExecutionAuthorization | None = None,
        authorization_hash: str | None = None,
    ) -> dict:
        if authorization is None:
            authorization = self._hosted_authorization(request)
        if authorization_hash is None:
            authorization_hash = "0x" + keccak(
                json.dumps(
                    request.payment_authorization,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hex()
        with self.ledger.transaction() as tx:
            row = tx.get(reservation_id)
            if row is None:
                raise ValueError("reservation not found")
            self._require_unified_reservation(row)
            self._require_canonical_asset_pair(row)
            if row.get("state") in {"settled", "finalized", "released"}:
                return row
            stored_authorization_hash = row.get("payment_authorization_hash")
            if (
                stored_authorization_hash is not None
                and stored_authorization_hash != authorization_hash
            ):
                raise ValueError("a different payment authorization is pending")
            if row.get("settlement_rail") == "hosted" and (
                row.get("hosted_submission_unknown") is True
                or row.get("hosted_execution_id")
                or row.get("state") == "payment_submitted"
            ):
                recover = True
            else:
                recover = False

        if recover:
            return self._reconcile_hosted_reservation(
                reservation_id, authorization=authorization
            )

        capability = self._hosted_capability(
            reservation_id, authorization, require_reserved=True
        )
        client = self._require_hosted_client(
            capability.network, capability=capability, for_submission=True
        )
        with self.ledger.transaction() as tx:
            current = tx.get(reservation_id)
            if current is None:
                raise ValueError("reservation not found")
            if current.get("state") != "spending_reserved":
                return current
            # A previous worker may have dispatched after our initial read.
            # For direct transfers the durable request marker is a one-way
            # dispatch claim: a late worker must only recover that request.
            recover = current.get("product") == "transfers" and bool(current.get("hosted_request_id"))
            if recover:
                if not current.get("hosted_execution_id") and current.get("hosted_submission_unknown") is not True:
                    tx.require_no_durable_transaction_evidence(reservation_id)
                    self._put_reservation(tx, {**current, "hosted_submission_unknown": True})
            else:
                prepared = self._prepare_hosted_request(current, capability, client)
                submitted = {
                    **current,
                    "settlement_rail": "hosted",
                    "payment_authorization_hash": authorization_hash,
                    "hosted_request_id": prepared.envelope.request_id,
                    "hosted_request_nonce": prepared.envelope.request_nonce,
                    "hosted_request_hash": prepared.request_hash,
                    "hosted_request_issued_at": prepared.envelope.issued_at,
                    "hosted_execution_id": None,
                    "hosted_status": "requested",
                    "hosted_submission_unknown": False,
                    "reconciliation_status": "pending",
                    "next_action": "submit_hosted_execution",
                    "last_reconciliation_error": None,
                }
                self._put_reservation(tx, submitted)

        if recover:
            return self._reconcile_hosted_reservation(reservation_id, authorization=authorization)

        try:
            response = client.submit(prepared)
        except HostedExecutionUnknown:
            with self.ledger.transaction() as tx:
                current = tx.get(reservation_id)
                if current is None:
                    raise ValueError("reservation not found")
                unknown = {
                    **current,
                    "hosted_status": "submission_unknown",
                    "hosted_submission_unknown": True,
                    "reconciliation_status": "pending",
                    "next_action": "reconcile_hosted_execution",
                    "last_reconciliation_error": "hosted execution submission outcome is unknown",
                }
                self._put_reservation(tx, unknown)
                return unknown
        except HostedFacilitatorError as exc:
            with self.ledger.transaction() as tx:
                current = tx.get(reservation_id)
                if current is None:
                    raise ValueError("reservation not found")
                retryable = {
                    **current,
                    "state": "spending_reserved",
                    "settlement_rail": "hosted",
                    "hosted_status": "unavailable",
                    "hosted_submission_unknown": False,
                    "reconciliation_status": "retryable",
                    "next_action": "retry_settlement",
                    "last_reconciliation_error": "hosted execution is unavailable",
                }
                self._put_reservation(tx, retryable)
                return retryable
        return self._apply_hosted_response(reservation_id, response)

    def _reconcile_hosted_reservation(
        self,
        reservation_id: str,
        *,
        authorization: HostedExecutionAuthorization | None = None,
        operator_reconcile: bool = False,
    ) -> dict:
        with self.ledger.transaction() as tx:
            row = tx.get(reservation_id)
            if row is None:
                raise ValueError("reservation not found")
            if row.get("settlement_rail") != "hosted":
                raise ValueError("reservation is not a Hosted execution")
            if row.get("state") in {"released", "reorg_review"}:
                return row
            execution_id = row.get("hosted_execution_id")
            if not execution_id and row.get("hosted_submission_unknown") is not True:
                return row
            capability = tx.payment_capability_for_reservation(reservation_id)
        if capability is None:
            raise ValueError("Hosted payment capability is unavailable")
        if authorization is None:
            authorization = HostedExecutionAuthorization(
                tenant_id=capability.tenant_id,
                node_id=capability.node_id,
                wallet_binding_id=capability.wallet_binding_id,
                executor_contract=capability.executor_contract,
                payment_challenge_hash=capability.payment_challenge_hash,
            )
        else:
            self._hosted_capability(
                reservation_id,
                authorization,
                require_reserved=False,
            )
        client = self._require_hosted_client(capability.network, capability=capability)
        request = self._prepare_hosted_request(row, capability, client)
        try:
            if execution_id:
                response = client.recover(request, execution_id)
            else:
                response = client.recover_by_idempotency(request)
        except HostedFacilitatorError:
            with self.ledger.transaction() as tx:
                current = tx.get(reservation_id)
                if current is None:
                    raise ValueError("reservation not found")
                return {
                    **current,
                    "reconciliation_status": "pending",
                    "next_action": "reconcile_hosted_execution",
                    "last_reconciliation_error": "hosted execution status is unavailable",
                }
        return self._apply_hosted_response(reservation_id, response)

    def _validate_hosted_response_binding(
        self,
        row: dict,
        capability: PaymentCapabilityV1,
        response: Any,
    ) -> None:
        if not isinstance(response, HostedExecutionResponse):
            raise ValueError("Hosted execution response is invalid")
        try:
            profile = hosted_chain_profile(capability.network)
        except ValueError:
            raise ValueError("Hosted execution response chain is unsupported") from None
        expected = {
            "request_id": row.get("hosted_request_id"),
            "request_hash": row.get("hosted_request_hash"),
            "idempotency_key": row.get("idempotency_key"),
            "capability_id": capability.capability_id,
            "capability_hash": capability.capability_hash,
            "reservation_id": capability.reservation_id,
            "reservation_hash": capability.reservation_hash,
            "purchase_id": capability.purchase_id,
            "execution_scope_hash": capability.execution_scope_hash,
            "owner": capability.wallet_address,
            "payee": capability.pay_to,
            "token": capability.asset_contract,
            "amount_atomic": capability.amount_atomic,
            "executor": capability.executor_contract,
            "owner_nonce": row.get("hosted_request_nonce"),
            "deadline": capability.expires_at,
            "chain_id": capability.network,
        }
        if any(getattr(response, field, None) != value for field, value in expected.items()):
            raise ValueError("Hosted execution response scope does not match Core authority")
        if response.token != profile.token:
            raise ValueError("Hosted execution response token does not match chain")
        if response.finality_boundary != profile.finality_boundary and response.state in {
            "confirmed",
            "finalized",
            "reverted",
            "released",
            "reorg_review",
        }:
            raise ValueError("Hosted execution response finality boundary does not match chain")
        if response.state in {"finalized", "reverted", "released"} and (
            response.confirmations < profile.min_confirmation_depth
        ):
            raise ValueError("Hosted execution response confirmations are insufficient")
        if response.state == "released" and (
            response.release_evidence is None
            or response.release_evidence.finality_boundary_timestamp < response.deadline
        ):
            raise ValueError(
                "Hosted execution response release evidence is not past the authorization deadline"
            )
        if response.state == "released" and (
            response.release_evidence.finality_boundary_timestamp
            > int(self._as_utc_datetime(self._utc_now()).timestamp())
        ):
            raise ValueError(
                "Hosted execution response release evidence is from the future"
            )

    @staticmethod
    def _require_release_matches_reverted_evidence(
        row: Mapping[str, Any], release_projection: Mapping[str, Any]
    ) -> None:
        reverted_projection = row.get("hosted_watcher_evidence")
        if reverted_projection is None:
            return
        if not isinstance(reverted_projection, Mapping):
            raise ValueError("Hosted reverted evidence is invalid")
        immutable_fields = (
            "execution_id",
            "transaction_hash",
            "receipt_block_hash",
            "receipt_block_number",
            "reverted_at",
            "finality_boundary",
        )
        if any(
            reverted_projection.get(field) != release_projection.get(field)
            for field in immutable_fields
        ):
            raise ValueError(
                "Hosted release evidence does not match reverted receipt"
            )

    def _hosted_capability_for_response(
        self, tx, row: dict, response: Any
    ) -> PaymentCapabilityV1:
        capability = tx.payment_capability_for_reservation(row["reservation_id"])
        if capability is None:
            raise ValueError("Hosted payment capability is unavailable")
        self._validate_hosted_response_binding(row, capability, response)
        return capability

    def _apply_hosted_response(
        self, reservation_id: str, response: Any
    ) -> dict:
        state = getattr(response, "state", None)
        evidence = response.model_dump(mode="json")
        transaction_hash = response.transaction_hash
        if transaction_hash is not None:
            transaction_hash = canonicalize_transaction_hash(transaction_hash)
        with self.ledger.transaction() as tx:
            current = tx.get(reservation_id)
            if current is None:
                raise ValueError("reservation not found")
            self._require_unified_reservation(current)
            if current.get("settlement_rail") != "hosted":
                raise ValueError("reservation is not a Hosted execution")
            capability = self._hosted_capability_for_response(tx, current, response)
            prior_state = current.get("state")
            prior_execution_id = current.get("hosted_execution_id")
            prior_submission_unknown = current.get("hosted_submission_unknown") is True
            if (
                prior_execution_id
                and prior_execution_id != response.execution_id
            ):
                raise ValueError("Hosted execution identity changed")
            if state == "expired" and response.failure_reason_code == "UNSIGNED_EXECUTION_EXPIRED":
                return self._release_unsigned_hosted_expiry(tx, current, response)
            if prior_state in {"settled", "finalized"}:
                if state == "finalized":
                    if (
                        prior_execution_id is not None
                        and prior_execution_id == response.execution_id
                        and current.get("hosted_watcher_evidence") == evidence
                        and current.get("tx_hash") == transaction_hash
                        and current.get("budget_accounting_state") == "settled"
                        and bool(current.get("receipt"))
                        and current.get("receipt_id")
                    ):
                        return current
                    raise ValueError(
                        "Hosted finalized response conflicts with settled reservation"
                    )
                if state != "reorg_review":
                    raise ValueError("Hosted response would regress settled reservation")
            if prior_state == "released" and state != "released":
                # RELEASED is terminal.  A delayed, already-signed watcher
                # projection must never recreate a budget reservation.
                return current
            current = {
                **current,
                "hosted_execution_id": response.execution_id,
                "hosted_status": state,
                "hosted_submission_unknown": state == "submission_unknown",
                "hosted_response": evidence,
            }
            if transaction_hash is not None and state not in {
                "submission_rejected",
                "expired",
                "rejected",
            }:
                current["tx_hash"] = transaction_hash
                current["receipt_id"] = current.get("receipt_id") or (
                    f"fund_receipt_{reservation_id}"
                )
            if state in {"preparing", "submitted", "submission_unknown", "confirmed"}:
                if transaction_hash is None:
                    pending = {
                        **current,
                        "state": "spending_reserved",
                        "reconciliation_status": "pending",
                        "next_action": "reconcile_hosted_execution",
                    }
                    self._put_reservation(tx, pending)
                    return pending
                submitted = {
                    **current,
                    "state": "payment_submitted",
                    "reconciliation_status": "pending",
                    "next_action": "reconcile_hosted_execution",
                    "last_reconciliation_error": None,
                }
                self._put_reservation(tx, submitted, tx_hash=transaction_hash)
                return submitted
            if state == "finalized":
                if transaction_hash is None:
                    raise ValueError("Hosted finalized response lacks transaction hash")
                if prior_execution_id is None and not prior_submission_unknown:
                    raise ValueError(
                        "Hosted finalized response lacks original execution identity"
                    )
                if prior_execution_id is not None and prior_execution_id != response.execution_id:
                    raise ValueError(
                        "Hosted finalized response lacks original execution identity"
                    )
                if prior_state not in {"payment_submitted", "spending_reserved"}:
                    raise ValueError("Hosted finalized response lacks submitted state")
                if prior_state == "spending_reserved":
                    # A POST response may be lost after the facilitator has
                    # submitted and finalized the transaction.  Seal the
                    # original transaction binding before recording watcher
                    # evidence so receipt creation sees the same immutable
                    # payment_submitted provenance as the normal path.
                    current = {
                        **current,
                        "state": "payment_submitted",
                        "reconciliation_status": "pending",
                        "next_action": "reconcile_hosted_execution",
                    }
                    self._put_reservation(tx, current, tx_hash=transaction_hash)
                current = tx.record_hosted_watcher_evidence(
                    current, evidence, now=self._utc_now()
                )
                authorization = self._reservation_authorization(current, tx=tx)
                if authorization is None:
                    raise ValueError("spending authorization not found")
                request = SpendFromSpendingAuthorizationRequest(
                    spending_authorization_id=authorization.spending_authorization_id,
                    amount_usdc=current["amount_usdc"],
                    destination=current["destination"],
                    resource=current["resource"],
                    metadata={
                        "purchase_id": current["purchase_id"],
                        "merchant_id": current["merchant_id"],
                        "quote_hash": current["quote_hash"],
                    },
                )
                receipt = self._record_spending_receipt(
                    authorization=authorization,
                    request=request,
                    tx_hash=transaction_hash,
                    receipt_id=current.get("receipt_id"),
                    metadata={
                        "purchase_id": current["purchase_id"],
                        "merchant_id": current["merchant_id"],
                        "quote_hash": current["quote_hash"],
                        "action_id": current["action_id"],
                        "policy_decision_id": current["policy_decision_id"],
                        "hosted_execution_id": response.execution_id,
                        "hosted_watcher_evidence_hash": current.get(
                            "hosted_watcher_evidence_hash"
                        ),
                    },
                    tx=tx,
                )
                settled = tx.settle_unified_budget(current, now=self._utc_now())
                settled = {
                    **settled,
                    "state": "settled",
                    "receipt": receipt.to_dict(),
                    "reconciliation_status": "settled",
                    "next_action": "deliver_service",
                    "settled_at": self._format_time(self._utc_now()),
                }
                self._put_reservation(tx, settled, tx_hash=transaction_hash)
                return settled
            if state == "reverted":
                if current.get("budget_accounting_state") != "reserved":
                    raise ValueError(
                        "Hosted reverted response cannot recreate reserved budget"
                    )
                current = tx.record_hosted_watcher_evidence(
                    current, evidence, now=self._utc_now()
                )
                held = {
                    **current,
                    "state": "payment_submitted",
                    "budget_accounting_state": "reserved",
                    "reconciliation_status": "pending",
                    "next_action": "status_only",
                    "last_reconciliation_error": (
                        "Hosted execution reverted; awaiting safe release proof"
                    ),
                    "release_reason": response.failure_reason_code,
                }
                self._put_reservation(tx, held, tx_hash=transaction_hash)
                return held
            if state == "reorg_review":
                current = tx.record_hosted_watcher_reorg_evidence(
                    current, evidence, now=self._utc_now()
                )
                reviewed = {
                    **current,
                    "state": "reorg_review",
                    "reconciliation_status": "manual_review_required",
                    "next_action": "manual_review",
                    "last_reconciliation_error": "Hosted execution requires reorg review",
                    "reorg_reviewed_at": self._format_time(self._utc_now()),
                }
                self._put_reservation(tx, reviewed, tx_hash=transaction_hash)
                return reviewed
            if state in {"submission_rejected", "expired", "rejected"}:
                held = {
                    **current,
                    "state": "spending_reserved",
                    "budget_accounting_state": current.get(
                        "budget_accounting_state", "reserved"
                    ),
                    "reconciliation_status": "manual_review_required",
                    "next_action": "status_only",
                    "last_reconciliation_error": (
                        "Hosted execution was "
                        + state
                        + "; status-only reconciliation is required"
                    ),
                    "release_reason": response.failure_reason_code,
                }
                self._put_reservation(tx, held)
                return held
            if state == "released":
                if transaction_hash is None:
                    raise ValueError("Hosted released response lacks transaction hash")
                if prior_execution_id is None and not prior_submission_unknown:
                    raise ValueError(
                        "Hosted released response lacks original execution identity"
                    )
                if prior_state not in {
                    "payment_submitted",
                    "spending_reserved",
                    "released",
                }:
                    raise ValueError("Hosted released response lacks submitted state")
                release_evidence = response.release_evidence
                if release_evidence is None:
                    raise ValueError(
                        "Hosted released response lacks release evidence"
                    )
                self._require_release_matches_reverted_evidence(current, evidence)
                if prior_state == "spending_reserved":
                    # A POST response may be lost after the on-chain revert.
                    # Bind the recovered execution and transaction before the
                    # release proof updates aggregate budget accounting.
                    current = {
                        **current,
                        "state": "payment_submitted",
                        "reconciliation_status": "pending",
                        "next_action": "status_only",
                    }
                    self._put_reservation(tx, current, tx_hash=transaction_hash)
                current = tx.record_hosted_watcher_release_evidence(
                    current,
                    evidence,
                    now=self._utc_now(),
                )
                released = tx.release_unified_budget(current, now=self._utc_now())
                released = {
                    **released,
                    "state": "released",
                    "hosted_status": state,
                    "reconciliation_status": "failed",
                    "next_action": "terminal",
                    "last_reconciliation_error": (
                        "Hosted execution was "
                        + state
                    ),
                    "release_reason": response.failure_reason_code,
                    "released_at": current.get("released_at")
                    or self._format_time(self._utc_now()),
                }
                self._put_reservation(tx, released, tx_hash=transaction_hash)
                return released
            raise ValueError("Hosted execution response state is invalid")

    def _release_unsigned_hosted_expiry(self, tx, row: dict, response: HostedExecutionResponse) -> dict:
        """Close only a signed attestation of fenced, never-signed execution.

        Called under the reservation lock, after full capability/response binding.
        A generic expiry, missing hash, or timeout is never release authority.
        """
        response = HostedExecutionResponse.model_validate(response.model_dump(mode="json"), strict=True)
        now = self._utc_now()
        if not response.deadline <= (response.expired_at or 0) <= int(self._as_utc_datetime(now).timestamp()):
            raise ValueError("Hosted unsigned expiry time is invalid")
        if not row.get("hosted_execution_id") and row.get("hosted_submission_unknown") is not True:
            raise ValueError("Hosted unsigned expiry lacks original execution identity")
        replay = row.get("state") == "released"
        if (row.get("state"), row.get("budget_accounting_state")) != (
            ("released", "released") if replay else ("spending_reserved", "reserved")
        ):
            raise ValueError("Hosted unsigned expiry cannot release this reservation state")
        if replay and row.get("hosted_unsigned_expiry_evidence") is None:
            raise ValueError("Hosted unsigned expiry conflicts with prior release")
        # Check original Core provenance before replacing hosted_response.
        if any(row.get(field) is not None for field in (
            "tx_hash", "receipt_id", "receipt", "settlement_raw_transaction",
            "settlement_transaction", "settlement_sender",
            "hosted_watcher_evidence", "hosted_watcher_release_evidence",
            "hosted_watcher_reorg_evidence",
        )) or row.get("failed_submission_evidence") not in (None, []):
            raise ValueError("Hosted unsigned expiry conflicts with existing transaction evidence")
        previous = row.get("hosted_response")
        if previous is not None:
            if not isinstance(previous, Mapping) or previous.get("state") not in {
                "preparing", "expired", "rejected",
            } or any(previous.get(field) is not None for field in (
                "transaction_hash", "submitted_at", "receipt_block_hash", "receipt_block_number",
                "safe_block_hash", "safe_block_number", "confirmed_at", "finalized_at",
                "reverted_at", "reorg_reviewed_at", "release_evidence",
            )) or previous.get("confirmations", 0) != 0:
                raise ValueError("Hosted unsigned expiry conflicts with prior Hosted evidence")
        bound = {**row, "hosted_execution_id": response.execution_id}
        proven = tx.record_hosted_unsigned_expiry_evidence(
            bound, response.model_dump(mode="json"), now=now,
        )
        if replay:
            return row
        released = tx.release_unified_budget(proven, now=now)
        released = {
            **released,
            "state": "released", "hosted_status": "expired",
            "hosted_submission_unknown": False,
            "hosted_response": response.model_dump(mode="json"),
            "reconciliation_status": "failed", "next_action": "terminal",
            "release_reason": "UNSIGNED_EXECUTION_EXPIRED",
            "last_reconciliation_error": "Hosted execution expired before signing; no transaction was broadcast",
            "released_at": self._format_time(now),
        }
        self._put_reservation(tx, released)
        return released

    def settle_reservation(self, reservation_id: str, request: SettleSpendingReservationRequest) -> dict:
        if self._hosted_requested(request):
            return self._settle_hosted_reservation(reservation_id, request)
        with self.ledger.transaction() as tx:
            routing_row = tx.get(reservation_id)
            if routing_row is None:
                raise ValueError("reservation not found")
            has_hosted_capability = (
                tx.payment_capability_for_reservation(reservation_id) is not None
            )
        hosted_selected = self._hosted_selected_for_business(
            routing_row,
            has_hosted_capability=has_hosted_capability,
        )
        if hosted_selected:
            if routing_row.get("authorization_rail") not in {
                "native_allowance",
                "clink_payer_proxy",
            }:
                raise ValueError(
                    "Hosted execution requires an allowance-backed reservation"
                )
            authorization, authorization_hash = (
                self._hosted_business_authorization(routing_row, request)
            )
            return self._settle_hosted_reservation(
                reservation_id,
                request,
                authorization=authorization,
                authorization_hash=authorization_hash,
            )
        authorization_hash="0x"+keccak(json.dumps(request.payment_authorization,sort_keys=True).encode()).hex()
        reconcile_existing=False
        with self.ledger.transaction() as tx:
            row=tx.get(reservation_id)
            if not row: raise ValueError("reservation not found")
            self._require_unified_reservation(row)
            self._require_canonical_asset_pair(row)
            if row["authorization_rail"] not in {
                "native_allowance",
                "clink_payer_proxy",
            }:
                raise ValueError("external x402 reservation requires external finalize")
            if row["state"] in {"settled","finalized"}: return row
            if row.get("single_submission") is True and row.get(
                "replacement_forbidden"
            ) is True:
                raise ValueError(
                    "single-submission reservation forbids a replacement transaction"
                )
            if row["state"] == "payment_submitted":
                if row.get("payment_authorization_hash") != authorization_hash:
                    raise ValueError("a different payment authorization is pending")
                reconcile_existing=True
            else:
                expected_state = (
                    "proxy_authorization_ready"
                    if row["authorization_rail"] == "clink_payer_proxy"
                    else "spending_reserved"
                )
                if row["state"] != expected_state:
                    raise ValueError(f"reservation is {row['state']}")
        if reconcile_existing: return self.reconcile_reservation(reservation_id)
        self._receipt_signing_key()
        self._require_native_funding_enabled()
        allowance_error = None
        prepared = None
        with self.ledger.transaction() as tx:
            current=tx.get(reservation_id)
            self._require_unified_reservation(current)
            self._require_canonical_asset_pair(current)
            expected_state = (
                "proxy_authorization_ready"
                if current["authorization_rail"] == "clink_payer_proxy"
                else "spending_reserved"
            )
            if current["state"] != expected_state: return current
            if current.get("single_submission") is True and current.get(
                "replacement_forbidden"
            ) is True:
                raise ValueError(
                    "single-submission reservation forbids a replacement transaction"
                )
            tx.validate_unified_lifecycle(current, now=self._utc_now())
            authorization=self._reservation_authorization(current,tx=tx)
            if not authorization: raise ValueError("spending authorization not found")
            try:
                observed = self._read_reservation_allowance(
                    current, authorization.wallet_address
                )
            except Exception:
                tx.observe_allowance_before_submission(
                    current, stale=True, now=self._utc_now()
                )
                allowance_error = "asset allowance refresh failed closed"
            else:
                allowance_status = tx.observe_allowance_before_submission(
                    current,
                    observed_allowance_atomic=observed,
                    now=self._utc_now(),
                )
                if allowance_status != "active":
                    allowance_error = (
                        f"asset allowance is {allowance_status} before submission"
                    )
                elif observed < int(current["amount_atomic"]):
                    allowance_error = (
                        "asset allowance is insufficient before submission"
                    )
            if allowance_error is None:
                # PolicyDecision rows are append-only. Re-read the same decision only
                # after locking the reservation, then re-read it again after every
                # nonce/gas/signing operation before persisting a sendable transaction.
                self._require_reservation_policy_controls(current)
                relayer_key, relayer = self._native_relayer_credentials()
                chain_pending_nonce = self._rpc_int(
                    current["network"],
                    "eth_getTransactionCount",
                    [relayer.address, "pending"],
                )
                nonce = tx.allocate_relayer_nonce(
                    current,
                    network=current["network"],
                    relayer_address=relayer.address,
                    chain_pending_nonce=chain_pending_nonce,
                    now=self._utc_now(),
                )
                prepared=self._build_native_transaction(
                    authorization,
                    current,
                    nonce=nonce,
                    relayer_key=relayer_key,
                    relayer=relayer,
                )
                self._require_reservation_policy_controls(current)
                reconciliation_started_at=self._format_time(self._utc_now())
                settlement_rail = (
                    "clink_payer_reimbursement"
                    if current["authorization_rail"] == "clink_payer_proxy"
                    else "clink_allowance"
                )
                row={**current,"state":"payment_submitted","payment_authorization_hash":authorization_hash,"settlement_rail":settlement_rail,"tx_hash":prepared["tx_hash"],"settlement_sender":prepared["relayer"],"settlement_nonce":prepared["nonce"],"settlement_transaction":prepared["transaction"],"receipt_id":None if current["authorization_rail"] == "clink_payer_proxy" else f"fund_receipt_{reservation_id}","reconciliation_status":"pending","next_action":"reconcile_payment","reconciliation_attempts":0,"reconciliation_started_at":reconciliation_started_at,"last_reconciliation_at":None,"manual_review_reason":None,"manual_review_required_at":None,"risk_prebroadcast_state":"pending","risk_prebroadcast_blocked":False,"risk_prebroadcast_blocked_at":None}
                self._put_reservation(tx,row,tx_hash=prepared["tx_hash"])
        if allowance_error is not None:
            raise ValueError(allowance_error)
        assert prepared is not None
        try:
            self._require_native_funding_enabled()
            raw_transaction = (
                self._reconstruct_native_transaction(row)
                if row.get("single_submission") is True
                else prepared["raw_transaction"]
            )
            row = self._authorize_native_broadcast(row)
            submitted = self._send_native_raw_transaction(row, raw_transaction)
            if submitted!=prepared["tx_hash"]:
                raise RuntimeError("native facilitator returned a mismatched transaction hash")
        except _PrebroadcastRiskBlocked:
            raise
        except RpcSubmissionRejected as exc:
            rejection_code = exc.reason_code
            saved_error = (
                "native transaction submission was definitely rejected: "
                + rejection_code
            )
            self._save_reconciliation_error(
                reservation_id, prepared["tx_hash"], saved_error
            )
            return self._retryable_reservation(
                row,
                saved_error,
                preserve_nonce=True,
                failure_kind="definite_rpc_rejection",
                reason_code=rejection_code,
            )
        except Exception as exc:
            saved_error = (
                "native transaction submission status is ambiguous"
                if row.get("single_submission") is True
                else str(exc)
            )
            self._save_reconciliation_error(
                reservation_id, prepared["tx_hash"], saved_error
            )
        return self.reconcile_reservation(reservation_id)

    def prepare_proxy_payment(
        self,
        reservation_id: str,
        request: PrepareProxyPaymentRequest,
    ) -> dict:
        requirement = request.payment_requirement
        requirement_scope = requirement.model_dump(mode="json")
        requirement_hash = "0x" + keccak(
            json.dumps(
                requirement_scope,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hex()

        with self.ledger.transaction() as tx:
            row = tx.get(reservation_id)
            if not row:
                raise ValueError("reservation not found")
            self._require_unified_reservation(row)
            self._require_canonical_asset_pair(row)
            if row["authorization_rail"] != "clink_payer_proxy":
                raise ValueError("reservation is not a Clink payer proxy payment")
            if not self._proxy_requirement_matches_reservation(row, requirement_scope):
                raise ValueError("merchant challenge drift")
            self._require_proxy_token_domain(requirement_scope)
            if row["state"] in {
                "proxy_authorization_ready",
                "proxy_payment_ready",
            }:
                if row.get("proxy_challenge_hash") != requirement_hash:
                    raise ValueError("merchant challenge drift")
                if not self._proxy_authorization_expired(row):
                    return row
                if row["state"] == "proxy_payment_ready":
                    self._require_proxy_authorization_rotation_safe(row)
            if row["state"] not in {
                "spending_reserved",
                "proxy_authorization_ready",
                "payer_funded",
                "proxy_payment_ready",
            }:
                raise ValueError(f"reservation is {row['state']}")

            risk_expires_at = self._require_reservation_policy_controls(row)
            payer_key, payer = self._native_relayer_credentials()
            payer_address = self._canonical_evm_address(payer.address)
            now = self._risk_now()
            now_epoch = int(now.timestamp())
            valid_after = now_epoch - _EXTERNAL_AUTHORIZATION_CLOCK_SKEW_SECONDS
            valid_before = min(
                now_epoch + _EXTERNAL_AUTHORIZATION_LIFETIME_SECONDS,
                int(risk_expires_at.timestamp()),
            )
            if valid_before <= now_epoch:
                raise ValueError(
                    "live funding risk assessment has insufficient validity"
                )
            nonce = "0x" + secrets.token_hex(32)
            authorization = {
                "from": payer_address,
                "to": requirement.pay_to,
                "value": requirement.amount_atomic,
                "validAfter": str(valid_after),
                "validBefore": str(valid_before),
                "nonce": nonce,
            }
            typed_data = self._proxy_payment_typed_data(
                requirement_scope,
                authorization,
            )
            signature = self._ensure_0x(
                Account.sign_message(
                    encode_typed_data(full_message=typed_data),
                    payer_key,
                ).signature.hex()
            )
            payment_payload = {
                "x402Version": 2,
                "resource": {"url": requirement.resource},
                "accepted": {
                    "scheme": requirement.scheme,
                    "network": requirement.network,
                    "amount": requirement.amount_atomic,
                    "asset": requirement.asset,
                    "payTo": requirement.pay_to,
                    "extra": {
                        "name": requirement.token_name,
                        "version": requirement.token_version,
                    },
                },
                "payload": {
                    "signature": signature,
                    "authorization": authorization,
                },
                "typed_data": typed_data,
            }
            payer_is_funded = row["state"] in {"payer_funded", "proxy_payment_ready"}
            prepared = {
                **row,
                "state": (
                    "proxy_payment_ready"
                    if payer_is_funded
                    else "proxy_authorization_ready"
                ),
                "payer_address": payer_address,
                "proxy_nonce": nonce,
                "proxy_valid_after": str(valid_after),
                "proxy_valid_before": str(valid_before),
                "proxy_challenge_hash": requirement_hash,
                "payment_payload": payment_payload,
                "next_action": (
                    "submit_proxy_payment"
                    if payer_is_funded
                    else "fund_clink_payer"
                ),
                "proxy_payment_prepared_at": self._format_time(self._utc_now()),
            }
            self._put_reservation(tx, prepared, tx_hash=row.get("tx_hash"))
            return prepared

    def finalize_reservation(self,reservation_id:str,request:FinalizeSpendingReservationRequest)->dict:
        with self.ledger.transaction() as tx:
            row=tx.get(reservation_id)
            if not row: raise ValueError("settled reservation required")
            self._require_unified_reservation(row)
            if row["state"] not in {"settled","finalized"}: raise ValueError("settled reservation required")
            if row["state"]=="finalized": return row
            row={**row,"state":"finalized","delivery_status":request.delivery_status,"output_hash":request.output_hash,"finalized_at":self._format_time(self._utc_now())}
            self._put_reservation(tx,row,tx_hash=row.get("tx_hash"));return row

    def release_reservation(self,reservation_id:str,request:ReleaseSpendingReservationRequest)->dict:
        with self.ledger.transaction() as tx:
            row=tx.get(reservation_id)
            if not row: raise ValueError("reservation not found")
            self._require_unified_reservation(row)
            tx.validate_single_submission_state(row)
            if row["state"] in {
                "payment_submitted",
                "payer_funded",
                "proxy_payment_ready",
                "settled",
                "finalized",
            }:
                raise ValueError("submitted or settled reservation cannot be released")
            if row["state"] == "released": return row
            row=tx.release_unified_budget(row,now=self._utc_now())
            row={**row,"state":"released","release_reason":request.reason}
            self._put_reservation(tx,row);return row

    def finalize_external_payment(self,reservation_id:str,request:FinalizeExternalPaymentRequest)->dict:
        transaction_hash=canonicalize_transaction_hash(request.transaction_hash)
        proof=request.payment_response.model_dump()
        reconcile_existing=False
        with self.ledger.transaction() as tx:
            row=tx.get(reservation_id)
            if not row: raise ValueError("reservation not found")
            self._require_unified_reservation(row)
            self._require_canonical_asset_pair(row)
            if row["authorization_rail"] != "external_x402":
                raise ValueError("native allowance reservation cannot accept external payment")
            self._require_external_payment_challenge(row)
            if row["state"] in {"settled","finalized"}: return row
            if row["state"] not in {"spending_reserved","payment_submitted"}: raise ValueError("reservation cannot accept external payment")
            bound=tx.by_tx_hash(transaction_hash)
            if bound and bound.get("reservation_id")!=reservation_id:
                raise ValueError("transaction is already bound to another reservation")
            if row["state"] == "payment_submitted":
                if row.get("settlement_rail") != "external_x402_signature": raise ValueError("native payment is pending")
                if canonicalize_transaction_hash(row.get("tx_hash"))!=transaction_hash:
                    raise ValueError("a different transaction is pending")
                reconcile_existing=True
        if reconcile_existing: return self.reconcile_reservation(reservation_id)
        expected_scope=self._canonical_external_payment_scope({"network":row["network"],"asset":row["asset"],"amount_atomic":row["amount_atomic"],"pay_to":row["destination"],"nonce":row["nonce"],"valid_after":row["valid_after"],"valid_before":row["valid_before"]})
        proof_scope=self._canonical_external_payment_scope(proof)
        if proof_scope!=expected_scope: raise ValueError("external payment scope mismatch")
        proof_identity={"transaction_hash":transaction_hash,**proof_scope}
        proof_hash="0x"+keccak(json.dumps(proof_identity,sort_keys=True,separators=(",",":")).encode()).hex()
        self._require_observed_external_payment_matches(row, transaction_hash)
        payment_executed = self._external_payment_has_executed(row, transaction_hash)
        try:
            with self.ledger.transaction() as tx:
                bound=tx.by_tx_hash(transaction_hash)
                if bound and bound.get("reservation_id")!=reservation_id: raise ValueError("transaction is already bound to another reservation")
                current=tx.get(reservation_id)
                self._require_unified_reservation(current)
                self._require_canonical_asset_pair(current)
                if current["state"] != "spending_reserved": return current
                identity, grant, _allowance = tx.unified_authorization_scope(current)
                revoked = identity.status == "revoked" or grant.status == "revoked" or (
                    grant.status == "paused"
                    and grant.status_reason == "wallet_identity_revoked"
                )
                if revoked:
                    if not payment_executed:
                        tx.validate_unified_lifecycle(current, now=self._utc_now())
                else:
                    tx.validate_unified_lifecycle(
                        current,
                        now=self._utc_now(),
                        payment_already_executed=payment_executed,
                    )
                reconciliation_started_at=self._format_time(self._utc_now())
                row={**current,"state":"payment_submitted","settlement_rail":"external_x402_signature","tx_hash":transaction_hash,"receipt_id":f"fund_receipt_{reservation_id}","payment_proof_hash":proof_hash,"reconciliation_status":"pending","next_action":"reconcile_payment","reconciliation_attempts":0,"reconciliation_started_at":reconciliation_started_at,"last_reconciliation_at":None,"manual_review_reason":None,"manual_review_required_at":None}
                self._put_reservation(tx,row,tx_hash=transaction_hash)
        except IntegrityError as exc:
            raise ValueError("transaction is already bound to another reservation") from exc
        return self.reconcile_reservation(reservation_id)

    def finalize_proxy_payment(
        self,
        reservation_id: str,
        request: FinalizeProxyPaymentRequest,
    ) -> dict:
        transaction_hash = canonicalize_transaction_hash(request.transaction_hash)
        proof = request.payment_response.model_dump()
        reconcile_existing = False
        with self.ledger.transaction() as tx:
            row = tx.get(reservation_id)
            if not row:
                raise ValueError("reservation not found")
            self._require_unified_reservation(row)
            self._require_canonical_asset_pair(row)
            if row["authorization_rail"] != "clink_payer_proxy":
                raise ValueError("reservation is not a Clink payer proxy payment")
            self._require_proxy_payment_challenge(row)
            if row["state"] in {"settled", "finalized"}:
                return row
            if row["state"] not in {"proxy_payment_ready", "payment_submitted"}:
                raise ValueError("reservation cannot accept proxy payment")
            bound = tx.by_tx_hash(transaction_hash)
            if bound and bound.get("reservation_id") != reservation_id:
                raise ValueError("transaction is already bound to another reservation")
            if row["state"] == "payment_submitted":
                if row.get("settlement_rail") != "clink_payer_proxy":
                    raise ValueError("a different payment rail is pending")
                if canonicalize_transaction_hash(row.get("tx_hash")) != transaction_hash:
                    raise ValueError("a different transaction is pending")
                reconcile_existing = True
        if reconcile_existing:
            return self.reconcile_reservation(reservation_id)

        expected_scope = self._canonical_external_payment_scope(
            {
                "network": row["network"],
                "asset": row["token_address"],
                "amount_atomic": row["amount_atomic"],
                "pay_to": row["destination"],
                "nonce": row["proxy_nonce"],
                "valid_after": row["proxy_valid_after"],
                "valid_before": row["proxy_valid_before"],
            }
        )
        proof_scope = self._canonical_external_payment_scope(proof)
        if proof_scope != expected_scope:
            raise ValueError("proxy payment scope mismatch")
        proof_identity = {"transaction_hash": transaction_hash, **proof_scope}
        proof_hash = "0x" + keccak(
            json.dumps(
                proof_identity,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hex()
        self._require_observed_external_payment_matches(row, transaction_hash)
        try:
            with self.ledger.transaction() as tx:
                bound = tx.by_tx_hash(transaction_hash)
                if bound and bound.get("reservation_id") != reservation_id:
                    raise ValueError("transaction is already bound to another reservation")
                current = tx.get(reservation_id)
                self._require_unified_reservation(current)
                self._require_canonical_asset_pair(current)
                if current["state"] != "proxy_payment_ready":
                    return current
                reconciliation_started_at = self._format_time(self._utc_now())
                submitted = {
                    **current,
                    "state": "payment_submitted",
                    "settlement_rail": "clink_payer_proxy",
                    "merchant_tx_hash": transaction_hash,
                    "tx_hash": transaction_hash,
                    "receipt_id": f"fund_receipt_{reservation_id}",
                    "payment_proof_hash": proof_hash,
                    "reconciliation_status": "pending",
                    "next_action": "reconcile_payment",
                    "reconciliation_attempts": 0,
                    "reconciliation_started_at": reconciliation_started_at,
                    "last_reconciliation_at": None,
                    "manual_review_reason": None,
                    "manual_review_required_at": None,
                }
                self._put_reservation(tx, submitted, tx_hash=transaction_hash)
        except IntegrityError as exc:
            raise ValueError("transaction is already bound to another reservation") from exc
        return self.reconcile_reservation(reservation_id)

    def reconcile_reservation(
        self, reservation_id: str, *, operator_reconcile: bool = False
    ) -> dict:
        hosted = False
        with self.ledger.transaction() as hosted_tx:
            hosted_row = hosted_tx.get(reservation_id)
            hosted = hosted_row is not None and hosted_row.get("settlement_rail") == "hosted"
        if hosted:
            return self._reconcile_hosted_reservation(
                reservation_id, operator_reconcile=operator_reconcile
            )
        with self.ledger.transaction() as tx:
            row=tx.get(reservation_id)
            if not row: raise ValueError("reservation not found")
            self._require_unified_reservation(row)
            self._require_canonical_asset_pair(row)
            if row.get("risk_prebroadcast_blocked") is True or row.get(
                "risk_prebroadcast_state"
            ) in {"pending", "blocked"}:
                return row
            if row["state"] in {"settled","finalized","payer_funded","proxy_payment_ready"}:
                if row.get("reconciliation_status") == "settled": return row
                row={**row,"reconciliation_status":"settled","next_action":"deliver_service"}
                self._put_reservation(tx,row,tx_hash=row.get("tx_hash"));return row
            if row["state"] == "proxy_authorization_ready":
                return row
            if row["state"] == "spending_reserved":
                if row.get("single_submission") is True and row.get(
                    "replacement_forbidden"
                ) is True:
                    return row
                row={**row,"reconciliation_status":"retryable","next_action":"retry_settlement"}
                self._put_reservation(tx,row);return row
            if row["state"] != "payment_submitted": raise ValueError(f"reservation is {row['state']}")
            if (
                row.get("reconciliation_status") == "manual_review_required"
                and not operator_reconcile
            ):
                return row
            now=self._utc_now()
            if not operator_reconcile:
                limit_reason=self._reconciliation_limit_reason(row,now)
                if limit_reason:
                    row=self._manual_review_reservation(row,limit_reason,now=now)
                    self._put_reservation(tx,row,tx_hash=row.get("tx_hash"));return row
                row={**row,"reconciliation_attempts":int(row.get("reconciliation_attempts") or 0)+1,"reconciliation_started_at":row.get("reconciliation_started_at") or self._format_time(now),"last_reconciliation_at":self._format_time(now)}
            else:
                row={**row,"operator_reconciliation_attempts":int(row.get("operator_reconciliation_attempts") or 0)+1,"last_operator_reconciliation_at":self._format_time(now)}
            self._put_reservation(tx,row,tx_hash=row.get("tx_hash"))
        if row.get("settlement_rail") in {"clink_allowance", "clink_payer_reimbursement"}: return self._reconcile_native_reservation(row,operator_reconcile=operator_reconcile)
        if row.get("settlement_rail") in {
            "external_x402_signature",
            "clink_payer_proxy",
        }:
            return self._reconcile_external_reservation(
                row, operator_reconcile=operator_reconcile
            )
        return self._pending_reservation(row,"settlement rail is missing",manual_review=operator_reconcile)

    def _reconcile_native_reservation(
        self, row: dict, *, operator_reconcile: bool = False
    ) -> dict:
        row = self._authoritative_reservation(row)
        self._require_canonical_asset_pair(row)
        tx_hash=row["tx_hash"]
        try:
            receipt=self._rpc_call(row["network"],"eth_getTransactionReceipt",[tx_hash])
            if isinstance(receipt,dict):
                chain_tx=self._rpc_call(row["network"],"eth_getTransactionByHash",[tx_hash])
                evidence_error=self._validate_native_settlement_evidence(
                    row, receipt, chain_tx
                )
                if evidence_error:
                    return self._pending_reservation(
                        row,
                        evidence_error,
                        manual_review=True,
                    )
                try:
                    confirmed=self._receipt_has_confirmations(receipt,row["network"])
                except Exception as exc:
                    error = (
                        "native confirmation lookup failed"
                        if row.get("single_submission") is True
                        else str(exc)
                    )
                    return self._pending_reservation(
                        row, error, manual_review=operator_reconcile
                    )
                if not confirmed: return self._pending_reservation(row,"native transaction lacks required confirmations",manual_review=operator_reconcile)
                status=str(receipt.get("status","")).lower()
                if status in {"0x0","0"}: return self._retryable_reservation(
                    row,
                    "native transaction failed onchain",
                    failure_kind="failed_receipt",
                    reason_code="onchain_revert",
                )
                if status not in {"0x1","1"}: return self._pending_reservation(row,"native receipt status is not final",manual_review=operator_reconcile)
                return self._complete_native_reservation(row)
            chain_tx=self._rpc_call(row["network"],"eth_getTransactionByHash",[tx_hash])
            if isinstance(chain_tx,dict): return self._pending_reservation(row,None,manual_review=operator_reconcile)
            if not self.config.clink_live_funding or not self.config.clink_native_facilitator_enabled:
                return self._pending_reservation(
                    row,
                    "native transaction cannot be found; replacement is forbidden",
                    manual_review=True,
                )
            try:
                raw_transaction = self._reconstruct_native_transaction(row)
            except ValueError as exc:
                return self._pending_reservation(row, str(exc), manual_review=True)
            try:
                submitted = self._send_native_raw_transaction(row, raw_transaction)
            except _PrebroadcastRiskBlocked:
                return self.get_reservation(row["reservation_id"])
            except Exception as exc:
                error = (
                    "exact native transaction rebroadcast status is ambiguous"
                    if row.get("single_submission") is True
                    else f"exact native transaction rebroadcast failed: {exc}"
                )
                return self._pending_reservation(
                    row,
                    error,
                    manual_review=True,
                )
            if submitted != tx_hash:
                return self._pending_reservation(
                    row,
                    "exact native transaction rebroadcast returned a mismatched hash",
                    manual_review=True,
                )
            return self._pending_reservation(
                row, "exact native transaction rebroadcast for reconciliation"
            )
        except Exception as exc:
            error = (
                "native settlement reconciliation lookup failed"
                if row.get("single_submission") is True
                else str(exc)
            )
            return self._pending_reservation(
                row, error, manual_review=operator_reconcile
            )

    def _reconcile_external_reservation(
        self, row: dict, *, operator_reconcile: bool = False
    ) -> dict:
        row = self._authoritative_reservation(row)
        self._require_canonical_asset_pair(row)
        tx_hash=row["tx_hash"]
        try:
            receipt=self._rpc_call(row["network"],"eth_getTransactionReceipt",[tx_hash])
        except Exception:
            return self._pending_reservation(
                row,
                "external receipt lookup failed",
                manual_review=True,
            )
        if receipt is None:
            return self._pending_reservation(row,None,manual_review=operator_reconcile)
        if not isinstance(receipt,dict):
            return self._pending_reservation(
                row,
                "external receipt response is invalid",
                manual_review=True,
            )
        try:
            chain_tx=self._rpc_call(row["network"],"eth_getTransactionByHash",[tx_hash])
        except Exception:
            return self._pending_reservation(
                row,
                "external transaction lookup failed for a mined receipt",
                manual_review=True,
            )
        if not isinstance(chain_tx,dict):
            return self._pending_reservation(
                row,
                "external transaction details are unavailable for a mined receipt",
                manual_review=True,
            )
        try:
            receipt_hash=canonicalize_transaction_hash(receipt.get("transactionHash"))
            chain_hash=canonicalize_transaction_hash(chain_tx.get("hash"))
        except ValueError:
            return self._pending_reservation(
                row,
                "external mined payment identity is incomplete",
                manual_review=True,
            )
        if receipt_hash!=tx_hash or chain_hash!=tx_hash:
            return self._pending_reservation(
                row,
                "external mined payment hash does not match the reserved transaction",
                manual_review=True,
            )
        try:
            confirmed=self._receipt_has_confirmations(receipt,row["network"])
        except Exception:
            return self._pending_reservation(
                row,
                "external receipt block number is missing or invalid",
                manual_review=True,
            )
        if not confirmed: return self._pending_reservation(row,"external payment lacks required confirmations",manual_review=operator_reconcile)
        status=str(receipt.get("status","")).lower()
        if status in {"0x0", "0"}:
            if row.get("authorization_rail") == "clink_payer_proxy":
                return self._retryable_proxy_payment(
                    row, "proxy payment transaction failed onchain"
                )
            return self._retryable_reservation(
                row,
                "external payment transaction failed onchain",
                failure_kind="failed_receipt",
                reason_code="onchain_revert",
            )
        if status not in {"0x1","1"}: return self._pending_reservation(row,"external receipt status is not final",manual_review=operator_reconcile)
        try:
            token_address=self._reservation_token_address(row)
            transaction_target=self._canonical_evm_address(chain_tx.get("to"))
        except ValueError:
            return self._pending_reservation(
                row,
                "external payment token contract cannot be verified after successful receipt",
                manual_review=True,
            )
        if transaction_target!=token_address:
            return self._pending_reservation(
                row,
                "external payment token contract mismatch after successful receipt",
                manual_review=True,
            )
        calldata_error=self._validate_external_payment_calldata(row,chain_tx.get("input"))
        if calldata_error:
            return self._pending_reservation(
                row,
                f"{calldata_error} after successful receipt",
                manual_review=True,
            )
        with self.ledger.transaction() as tx:
            current=tx.get(row["reservation_id"])
            if not self._same_pending_payment(current,row): return current
            self._require_unified_reservation(current)
            authorization=self._reservation_authorization(current,tx=tx)
            if not authorization: raise ValueError("spending authorization not found")
            request=SpendFromSpendingAuthorizationRequest(spending_authorization_id=authorization.spending_authorization_id,amount_usdc=current["amount_usdc"],destination=current["destination"],resource=current["resource"],metadata={"purchase_id":current["purchase_id"],"merchant_id":current["merchant_id"],"quote_hash":current["quote_hash"]})
            receipt=self._record_spending_receipt(authorization=authorization,request=request,tx_hash=current["tx_hash"],receipt_id=current["receipt_id"],metadata={"purchase_id":current["purchase_id"],"merchant_id":current["merchant_id"],"quote_hash":current["quote_hash"],"action_id":current["action_id"],"policy_decision_id":current["policy_decision_id"],"payer_address":current.get("payer_address"),"reimbursement_tx_hash":current.get("reimbursement_tx_hash"),"merchant_tx_hash":current.get("merchant_tx_hash")},tx=tx)
            revocations=tx.record_external_reconciliation_after_revocation(
                current, now=self._utc_now()
            )
            if current["authorization_rail"] != "clink_payer_proxy":
                current=tx.settle_unified_budget(current,now=self._utc_now())
            settled={**current,"state":"settled","receipt":receipt.to_dict(),"reconciliation_status":"settled","next_action":"deliver_service","settled_at":self._format_time(self._utc_now()),"reconciled_after_authorization_revocation":bool(revocations)}
            self._put_reservation(tx,settled,tx_hash=tx_hash);return settled

    def _external_payment_has_executed(self, row: dict, tx_hash: str) -> bool:
        try:
            receipt = self._rpc_call(
                row["network"], "eth_getTransactionReceipt", [tx_hash]
            )
            chain_tx = self._rpc_call(
                row["network"], "eth_getTransactionByHash", [tx_hash]
            )
            if not isinstance(receipt, dict) or not isinstance(chain_tx, dict):
                return False
            if not self._receipt_has_confirmations(receipt, row["network"]):
                return False
            if str(receipt.get("status", "")).lower() not in {"0x1", "1"}:
                return False
            if canonicalize_transaction_hash(receipt.get("transactionHash")) != tx_hash:
                return False
            if canonicalize_transaction_hash(chain_tx.get("hash")) != tx_hash:
                return False
            token_address = self._reservation_token_address(row)
            if self._canonical_evm_address(chain_tx.get("to")) != token_address:
                return False
            return self._validate_external_payment_calldata(
                row, chain_tx.get("input")
            ) is None
        except Exception:
            return False

    def _require_observed_external_payment_matches(
        self, row: dict, tx_hash: str
    ) -> None:
        try:
            chain_tx = self._rpc_call(
                row["network"], "eth_getTransactionByHash", [tx_hash]
            )
            if not isinstance(chain_tx, dict) or any(
                chain_tx.get(field) is None for field in ("hash", "to", "input")
            ):
                raise ValueError("external payment transaction is incomplete")
            if canonicalize_transaction_hash(chain_tx["hash"]) != tx_hash:
                raise ValueError("external payment transaction hash mismatch")
            target = self._canonical_evm_address(chain_tx["to"])
            token_address = self._reservation_token_address(row)
            calldata_error = self._validate_external_payment_calldata(
                row, chain_tx["input"]
            )
            if target != token_address or calldata_error is not None:
                raise ValueError("external payment transaction scope mismatch")
        except Exception as exc:
            raise ValueError(
                "external payment transaction does not match reservation challenge"
            ) from exc

    def _validate_external_payment_calldata(self,row:dict,calldata:Any)->str|None:
        try:
            if row.get("authorization_rail") == "clink_payer_proxy":
                self._require_proxy_payment_challenge(row)
            else:
                self._require_external_payment_challenge(row)
        except ValueError:
            return "external payment reservation challenge is unavailable"
        if not isinstance(calldata,str) or not calldata.startswith("0x"):
            return "external payment calldata encoding is invalid"
        try:
            raw=bytes.fromhex(calldata[2:])
        except ValueError:
            return "external payment calldata encoding is invalid"
        if len(raw)<_TRANSFER_WITH_AUTHORIZATION_CALLDATA_BYTES:
            return "external payment calldata length mismatch"
        if raw[:4]!=_TRANSFER_WITH_AUTHORIZATION_SELECTOR:
            return "external payment calldata selector is not allowed"
        attribution = raw[_TRANSFER_WITH_AUTHORIZATION_CALLDATA_BYTES:]
        if attribution and attribution != _CDP_FACILITATOR_ATTRIBUTION:
            return "external payment calldata attribution is not allowed"
        words=[
            raw[offset:offset+32]
            for offset in range(4,_TRANSFER_WITH_AUTHORIZATION_CALLDATA_BYTES,32)
        ]
        try:
            payer=self._abi_word_address(words[0])
            recipient=self._abi_word_address(words[1])
            expected_recipient=self._canonical_evm_address(row["destination"])
            amount=int.from_bytes(words[2],"big")
            expected_amount=int(row["amount_atomic"])
            valid_after=int.from_bytes(words[3],"big")
            expected_valid_after=int(
                row[
                    "proxy_valid_after"
                    if row.get("authorization_rail") == "clink_payer_proxy"
                    else "valid_after"
                ]
            )
            valid_before=int.from_bytes(words[4],"big")
            expected_valid_before=int(
                row[
                    "proxy_valid_before"
                    if row.get("authorization_rail") == "clink_payer_proxy"
                    else "valid_before"
                ]
            )
            nonce="0x"+words[5].hex()
            expected_nonce=str(
                row[
                    "proxy_nonce"
                    if row.get("authorization_rail") == "clink_payer_proxy"
                    else "nonce"
                ]
            ).lower()
        except (TypeError,ValueError):
            return "external payment calldata arguments are invalid"
        if int.from_bytes(words[6],"big")>255:
            return "external payment calldata signature arguments are invalid"
        try:
            if row.get("authorization_rail") == "clink_payer_proxy":
                expected_payer = self._canonical_evm_address(row.get("payer_address"))
            else:
                authorization=self._reservation_authorization(row)
                if not authorization:
                    return "external payment calldata authorization scope is unavailable"
                expected_payer=self._canonical_evm_address(authorization.wallet_address)
        except ValueError:
            return "external payment calldata authorization scope is invalid"
        if payer!=expected_payer:
            return "external payment calldata payer mismatch"
        if recipient!=expected_recipient:
            return "external payment calldata recipient mismatch"
        if amount!=expected_amount:
            return "external payment calldata amount mismatch"
        if valid_after!=expected_valid_after:
            return "external payment calldata validAfter mismatch"
        if valid_before!=expected_valid_before:
            return "external payment calldata validBefore mismatch"
        if nonce!=expected_nonce:
            return "external payment calldata nonce mismatch"
        return None

    @staticmethod
    def _canonical_evm_address(value:Any)->str:
        if not isinstance(value,str) or len(value)!=42 or not value.startswith("0x"):
            raise ValueError("invalid EVM address")
        try:
            decoded=bytes.fromhex(value[2:])
        except ValueError as exc:
            raise ValueError("invalid EVM address") from exc
        if len(decoded)!=20:
            raise ValueError("invalid EVM address")
        return "0x"+decoded.hex()

    @classmethod
    def _abi_word_address(cls,word:bytes)->str:
        if len(word)!=32 or word[:12]!=bytes(12):
            raise ValueError("invalid ABI address word")
        return cls._canonical_evm_address("0x"+word[12:].hex())

    def _complete_native_reservation(self,row:dict)->dict:
        with self.ledger.transaction() as tx:
            current=tx.get(row["reservation_id"])
            if not self._same_pending_payment(current,row): return current
            self._require_unified_reservation(current)
            authorization=self._reservation_authorization(current,tx=tx)
            if not authorization: raise ValueError("spending authorization not found")
            if current["authorization_rail"] == "clink_payer_proxy":
                current=tx.settle_unified_budget(current,now=self._utc_now())
                proxy_ready = isinstance(current.get("payment_payload"), dict)
                funded={**current,"state":"proxy_payment_ready" if proxy_ready else "payer_funded","reimbursement_tx_hash":current["tx_hash"],"receipt_id":None,"reconciliation_status":"settled","next_action":"submit_proxy_payment" if proxy_ready else "prepare_proxy_payment","payer_funded_at":self._format_time(self._utc_now())}
                self._put_reservation(tx,funded,tx_hash=current["tx_hash"]);return funded
            request=SpendFromSpendingAuthorizationRequest(spending_authorization_id=authorization.spending_authorization_id,amount_usdc=current["amount_usdc"],destination=current["destination"],resource=current["resource"],metadata={"purchase_id":current["purchase_id"],"merchant_id":current["merchant_id"],"quote_hash":current["quote_hash"]})
            receipt=self._record_spending_receipt(authorization=authorization,request=request,tx_hash=current["tx_hash"],receipt_id=current["receipt_id"],metadata={"purchase_id":current["purchase_id"],"merchant_id":current["merchant_id"],"quote_hash":current["quote_hash"],"action_id":current["action_id"],"policy_decision_id":current["policy_decision_id"]},tx=tx)
            current=tx.settle_unified_budget(current,now=self._utc_now())
            settled={**current,"state":"settled","receipt":receipt.to_dict(),"reconciliation_status":"settled","next_action":"deliver_service","settled_at":self._format_time(self._utc_now())}
            self._put_reservation(tx,settled,tx_hash=current["tx_hash"]);return settled

    def _reservation_authorization(self,row,*,tx=None):
        self._require_unified_reservation(row)
        if tx is None:
            with self.ledger.transaction() as current_tx:
                identity,grant,allowance=current_tx.unified_authorization_scope(row)
                return self._synthetic_authorization(identity,grant,allowance,row)
        identity,grant,allowance=tx.unified_authorization_scope(row)
        return self._synthetic_authorization(identity,grant,allowance,row)

    def _authoritative_reservation(self, row):
        if not isinstance(row, dict) or not row.get("reservation_id"):
            self._require_unified_reservation(row)
        with self.ledger.transaction() as tx:
            current = tx.get(row["reservation_id"])
            if current is None:
                raise ValueError("unified authorization provenance is unavailable")
            require_matching_reservation_immutable_fields(current, row)
            self._require_unified_reservation(row)
            tx.unified_authorization_scope(current)
            return current

    def _resolve_authoritative_unified_spend(self, authorization, request, *, tx=None):
        if authorization.legacy:
            raise ValueError("legacy spending authorizations are read-only")
        metadata = authorization.metadata
        base_provenance_fields = (
            "reservation_id",
            "wallet_identity_id",
            "spending_grant_id",
            "authorization_rail",
            "product",
            "token_address",
            "token_decimals",
            "amount_atomic",
        )
        authorization_rail = (
            metadata.get("authorization_rail") if isinstance(metadata, dict) else None
        )
        if authorization_rail in {"native_allowance", "clink_payer_proxy"}:
            provenance_fields = (*base_provenance_fields, "asset_allowance_id")
        elif authorization_rail == "external_x402":
            provenance_fields = base_provenance_fields
            if metadata.get("asset_allowance_id") is not None:
                raise ValueError("external x402 authorization cannot use an allowance")
        else:
            raise ValueError("unified authorization provenance has invalid rail")
        if not isinstance(metadata, dict) or any(
            metadata.get(field) in {None, ""} for field in provenance_fields
        ):
            raise ValueError("unified authorization provenance is incomplete")

        def resolve(current_tx):
            reservation = current_tx.get(metadata["reservation_id"])
            if reservation is None:
                raise ValueError("unified authorization provenance is unavailable")
            canonical = self._reservation_authorization(reservation, tx=current_tx)
            authorization_fields = (
                "spending_authorization_id",
                "user_id",
                "agent_id",
                "wallet_address",
                "venue",
                "chain",
                "token",
                "spender_address",
                "purpose",
            )
            if any(
                getattr(authorization, field) != getattr(canonical, field)
                for field in authorization_fields
            ) or any(
                metadata.get(field) != canonical.metadata.get(field)
                for field in provenance_fields
            ):
                raise ValueError("unified authorization provenance does not match ledger")
            if (
                request.spending_authorization_id
                != canonical.spending_authorization_id
                or self._parse_amount(request.amount_usdc)
                != self._parse_amount(reservation["amount_usdc"])
                or request.destination != reservation["destination"]
                or (
                    request.resource is not None
                    and request.resource != reservation["resource"]
                )
            ):
                raise ValueError("unified authorization provenance does not match spend")
            return canonical, reservation

        if tx is not None:
            return resolve(tx)
        with self.ledger.transaction() as current_tx:
            return resolve(current_tx)

    @staticmethod
    def _require_unified_reservation(row: dict) -> None:
        require_unified_reservation(row)

    def _synthetic_authorization(self,identity,grant,allowance,row):
        remaining=max(grant.max_amount_usdc-grant.used_amount_usdc-grant.reserved_amount_usdc,Decimal("0"))
        return SpendingAuthorization(
            legacy=False,
            spending_authorization_id=grant.spending_grant_id,
            user_id=grant.user_id,
            agent_id=grant.agent_id,
            wallet_address=identity.wallet_address,
            max_amount_usdc=self._format_amount(grant.max_amount_usdc),
            per_order_limit_usdc=self._format_amount(grant.per_transaction_limit_usdc),
            used_amount_usdc=self._format_amount(grant.used_amount_usdc),
            remaining_amount_usdc=self._format_amount(remaining),
            venue=row["venue"],
            chain=row["network"],
            token=row["token_symbol"],
            spender_address=row.get("spender_address") or row["destination"],
            allowance_tx_hash=allowance.allowance_tx_hash if allowance is not None else None,
            purpose=row["product"],
            status=grant.status,
            expires_at=self._format_time(self.ledger_time(grant.expires_at)),
            created_at=self._format_time(self.ledger_time(grant.created_at)),
            updated_at=self._format_time(self.ledger_time(grant.updated_at)),
            metadata={
                **{
                    key: row[key]
                    for key in (
                        "wallet_identity_id",
                        "spending_grant_id",
                        "asset_allowance_id",
                        "authorization_rail",
                        "product",
                        "reservation_id",
                    )
                },
                "token_address": row["token_address"],
                "token_decimals": row["token_decimals"],
                "amount_atomic": row["amount_atomic"],
            },
        )

    @staticmethod
    def ledger_time(value):
        return value if value.tzinfo is None else value.astimezone(UTC).replace(tzinfo=None)

    def _pending_reservation(
        self, row: dict, error: str | None, *, manual_review: bool = False
    ) -> dict:
        with self.ledger.transaction() as tx:
            current=tx.get(row["reservation_id"])
            if not self._same_pending_payment(current,row): return current
            if manual_review:
                updated=self._manual_review_reservation(
                    current,
                    error or "operator reconciliation remains ambiguous",
                )
            else:
                updated={**current,"reconciliation_status":"pending","next_action":"reconcile_payment"}
            if error: updated["last_reconciliation_error"]=error
            self._put_reservation(tx,updated,tx_hash=current.get("tx_hash"));return updated

    def _authorize_native_broadcast(self, row: dict) -> dict:
        reason = "live funding risk assessment failed immediately before submission"
        try:
            self._require_reservation_policy_controls(row)
        except Exception:
            self._block_unbroadcast_native_reservation(row, reason)
            raise _PrebroadcastRiskBlocked(
                "live funding risk assessment is unavailable before submission"
            ) from None

        with self.ledger.transaction() as tx:
            current = tx.get(row["reservation_id"])
            if not self._same_pending_payment(current, row):
                raise _PrebroadcastRiskBlocked(
                    "native transaction changed before submission"
                )
            if current.get("risk_prebroadcast_blocked") is True or current.get(
                "risk_prebroadcast_state"
            ) == "blocked":
                raise _PrebroadcastRiskBlocked(
                    "native transaction is blocked before submission"
                )
            if current.get("risk_prebroadcast_state") != "pending":
                raise _PrebroadcastRiskBlocked(
                    "native transaction is not pending risk authorization"
                )
            authorized = {
                **current,
                "risk_prebroadcast_state": "ready",
            }
            self._put_reservation(tx, authorized, tx_hash=current["tx_hash"])
            return authorized

    def _send_native_raw_transaction(self, row: dict, raw_transaction: str) -> str:
        reason = "live funding risk assessment failed immediately before submission"
        risk_failed = False
        submitted = None
        with self.ledger.transaction() as tx:
            current = tx.get(row["reservation_id"])
            if not self._same_pending_payment(current, row):
                raise _PrebroadcastRiskBlocked(
                    "native transaction changed before submission"
                )
            if current.get("risk_prebroadcast_blocked") is True or current.get(
                "risk_prebroadcast_state"
            ) in {"pending", "blocked"}:
                raise _PrebroadcastRiskBlocked(
                    "native transaction is blocked before submission"
                )
            try:
                self._require_reservation_policy_controls(current)
            except Exception:
                self._put_blocked_native_reservation(tx, current, reason)
                risk_failed = True
            else:
                submitted = self._rpc_call(
                    current["network"],
                    "eth_sendRawTransaction",
                    [raw_transaction],
                )
        if risk_failed:
            raise _PrebroadcastRiskBlocked(
                "live funding risk assessment is unavailable before submission"
            ) from None
        return canonicalize_transaction_hash(submitted)

    def _put_blocked_native_reservation(
        self,
        tx,
        current: dict,
        reason: str,
    ) -> dict:
        updated = self._manual_review_reservation(current, reason)
        updated = {
            **updated,
            "risk_prebroadcast_state": "blocked",
            "risk_prebroadcast_blocked": True,
            "risk_prebroadcast_blocked_at": current.get(
                "risk_prebroadcast_blocked_at"
            )
            or self._format_time(self._utc_now()),
            "last_reconciliation_error": reason,
        }
        self._put_reservation(tx, updated, tx_hash=current["tx_hash"])
        return updated

    def _block_unbroadcast_native_reservation(self, row: dict, reason: str) -> dict:
        with self.ledger.transaction() as tx:
            current = tx.get(row["reservation_id"])
            if not self._same_pending_payment(current, row):
                return current
            return self._put_blocked_native_reservation(tx, current, reason)

    def _retryable_reservation(
        self,
        row: dict,
        reason: str,
        *,
        preserve_nonce: bool = False,
        failure_kind: str = "definitive_failure",
        reason_code: str = "payment_failed",
    ) -> dict:
        with self.ledger.transaction() as tx:
            current=tx.get(row["reservation_id"])
            if not self._same_pending_payment(current,row): return current
            if current.get("single_submission") is True:
                tx_hash = canonicalize_transaction_hash(current["tx_hash"])
                failed = [*current.get("failed_tx_hashes", [])]
                if tx_hash not in failed:
                    failed.append(tx_hash)
                evidence = [*current.get("failed_submission_evidence", [])]
                evidence.append(
                    {
                        "kind": failure_kind,
                        "reason_code": reason_code,
                        "tx_hash": tx_hash,
                        "relayer": current.get("settlement_sender"),
                        "nonce": current.get("settlement_nonce"),
                        "recorded_at": self._format_time(self._utc_now()),
                    }
                )
                updated = {
                    **current,
                    "state": "spending_reserved",
                    "reconciliation_status": "failed",
                    "next_action": "release_reservation",
                    "last_reconciliation_error": reason,
                    "failed_tx_hashes": failed,
                    "failed_submission_evidence": evidence,
                    "replacement_forbidden": True,
                }
                self._put_reservation(tx, updated, tx_hash=tx_hash)
                return updated
            failed=[*current.get("failed_tx_hashes",[]),canonicalize_transaction_hash(current["tx_hash"])]
            updated={**current,"state":"spending_reserved","reconciliation_status":"retryable","next_action":"prepare_proxy_payment" if current.get("authorization_rail") == "clink_payer_proxy" else "retry_settlement","last_reconciliation_error":reason,"failed_tx_hashes":failed,"tx_hash":None,"settlement_sender":current.get("settlement_sender") if preserve_nonce else None,"settlement_nonce":current.get("settlement_nonce") if preserve_nonce else None,"settlement_transaction":None,"settlement_rail":None,"payment_authorization_hash":None,"payment_proof_hash":None}
            if current.get("authorization_rail") == "clink_payer_proxy":
                updated.update(self._cleared_proxy_authorization())
            self._put_reservation(tx,updated);return updated

    def _retryable_proxy_payment(self, row: dict, reason: str) -> dict:
        with self.ledger.transaction() as tx:
            current = tx.get(row["reservation_id"])
            if not self._same_pending_payment(current, row):
                return current
            failed = [
                *current.get("failed_merchant_tx_hashes", []),
                canonicalize_transaction_hash(current["tx_hash"]),
            ]
            reimbursement_hash = canonicalize_transaction_hash(
                current["reimbursement_tx_hash"]
            )
            updated = {
                **current,
                "state": "payer_funded",
                "reconciliation_status": "retryable",
                "next_action": "prepare_proxy_payment",
                "last_reconciliation_error": reason,
                "failed_merchant_tx_hashes": failed,
                "merchant_tx_hash": None,
                "tx_hash": reimbursement_hash,
                "settlement_rail": "clink_payer_reimbursement",
                "receipt_id": None,
                "payment_proof_hash": None,
            }
            updated.update(self._cleared_proxy_authorization())
            self._put_reservation(tx, updated, tx_hash=reimbursement_hash)
            return updated

    def _save_reconciliation_error(self,reservation_id:str,tx_hash:str,error:str)->None:
        tx_hash=canonicalize_transaction_hash(tx_hash)
        with self.ledger.transaction() as tx:
            current=tx.get(reservation_id)
            if current and current.get("state")=="payment_submitted" and canonicalize_transaction_hash(current.get("tx_hash"))==tx_hash:
                updated={**current,"last_reconciliation_error":error}
                self._put_reservation(tx,updated,tx_hash=tx_hash)

    def _put_reservation(self,tx,row:dict,tx_hash:str|None=None)->dict:
        self._require_unified_reservation(row)
        return tx.put("reservation",row["reservation_id"],row,purchase_id=row["purchase_id"],idempotency_key=row["idempotency_key"],action_id=row["action_id"],policy_decision_id=row["policy_decision_id"],reservation_id=row["reservation_id"],tx_hash=tx_hash)

    @staticmethod
    def _same_pending_payment(current:dict|None,expected:dict)->bool:
        if not current or current.get("state")!="payment_submitted": return False
        try:
            return canonicalize_transaction_hash(current.get("tx_hash"))==canonicalize_transaction_hash(expected.get("tx_hash"))
        except ValueError:
            return False

    def _reconciliation_limit_reason(self,row:dict,now:datetime)->str|None:
        attempts=int(row.get("reconciliation_attempts") or 0)
        if attempts>=self.config.payment_reconciliation_max_attempts:
            return "automatic reconciliation attempt limit reached"
        started_value=row.get("reconciliation_started_at") or row.get("created_at")
        try:
            started=datetime.fromisoformat(str(started_value).removesuffix("Z"))
        except (TypeError,ValueError):
            return "reconciliation timing metadata is invalid"
        if (now-started).total_seconds()>=self.config.payment_reconciliation_max_age_seconds:
            return "automatic reconciliation age limit reached"
        return None

    def _manual_review_reservation(
        self,row:dict,reason:str,*,now:datetime|None=None
    )->dict:
        timestamp=self._format_time(now or self._utc_now())
        return {**row,"reconciliation_status":"manual_review_required","next_action":"operator_reconcile","manual_review_reason":reason,"manual_review_required_at":row.get("manual_review_required_at") or timestamp}

    @staticmethod
    def _canonical_external_payment_scope(payment:dict)->dict:
        try:
            network=str(payment["network"]).strip().lower()
            asset=str(payment["asset"]).strip().lower()
            amount=int(str(payment["amount_atomic"]),10)
            pay_to=str(payment["pay_to"])
            nonce=str(payment["nonce"])
            valid_after=int(str(payment["valid_after"]),10)
            valid_before=int(str(payment["valid_before"]),10)
            if not network or not asset or amount<0:
                raise ValueError
            if len(pay_to)!=42 or not pay_to.startswith(("0x","0X")):
                raise ValueError
            int(pay_to[2:],16)
            if len(nonce)!=66 or not nonce.startswith(("0x","0X")):
                raise ValueError
            int(nonce[2:],16)
            if valid_after < 0 or valid_after >= valid_before or valid_before >= 2**256:
                raise ValueError
        except (KeyError,TypeError,ValueError) as exc:
            raise ValueError("external payment scope mismatch") from exc
        return {"network":network,"asset":asset,"amount_atomic":str(amount),"pay_to":"0x"+pay_to[2:].lower(),"nonce":"0x"+nonce[2:].lower(),"valid_after":str(valid_after),"valid_before":str(valid_before)}

    @staticmethod
    def _require_external_payment_challenge(row: dict) -> None:
        try:
            nonce = row["nonce"]
            valid_after = row["valid_after"]
            valid_before = row["valid_before"]
            if (
                not isinstance(nonce, str)
                or len(nonce) != 66
                or not nonce.startswith("0x")
            ):
                raise ValueError
            int(nonce[2:], 16)
            if int(valid_after) < 0 or int(valid_after) >= int(valid_before):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "external x402 reservation challenge is unavailable; legacy reservation is read-only"
            ) from exc

    @staticmethod
    def _require_proxy_payment_challenge(row: dict) -> None:
        try:
            nonce = row["proxy_nonce"]
            valid_after = row["proxy_valid_after"]
            valid_before = row["proxy_valid_before"]
            payer_address = row["payer_address"]
            if (
                not isinstance(nonce, str)
                or len(nonce) != 66
                or not nonce.startswith("0x")
                or not isinstance(payer_address, str)
            ):
                raise ValueError
            int(nonce[2:], 16)
            int(payer_address.removeprefix("0x"), 16)
            if int(valid_after) < 0 or int(valid_after) >= int(valid_before):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("proxy payment challenge is unavailable") from exc

    @staticmethod
    def _parse_rpc_quantity(value: object, *, field: str) -> int:
        if not isinstance(value, str) or re.fullmatch(
            r"0x(?:0|[1-9a-f][0-9a-f]*)", value
        ) is None:
            raise ValueError(f"{field} is missing or invalid")
        return int(value, 16)

    def _receipt_has_confirmations(self,receipt:dict,network:str)->bool:
        included=self._parse_rpc_quantity(
            receipt.get("blockNumber"), field="receipt block number"
        )
        latest=self._parse_rpc_quantity(
            self._rpc_call(network,"eth_blockNumber",[]),
            field="latest block number",
        )
        return latest-included+1>=self.config.native_min_confirmations

    def create_spending_authorization(self, request: CreateSpendingAuthorizationRequest) -> SpendingAuthorization:
        raise ValueError("legacy spending authorizations are read-only")

    def _verify_allowance_transaction(self,request:CreateSpendingAuthorizationRequest,spender_address:str,max_amount:Decimal)->None:
        if not request.allowance_tx_hash: raise ValueError("allowance_tx_hash is required")
        allowance_tx_hash=canonicalize_transaction_hash(request.allowance_tx_hash)
        receipt=self._rpc_call(request.chain,"eth_getTransactionReceipt",[allowance_tx_hash]);chain_tx=self._rpc_call(request.chain,"eth_getTransactionByHash",[allowance_tx_hash])
        if not isinstance(receipt,dict) or str(receipt.get("status","")).lower() not in {"0x1","1"}: raise ValueError("allowance transaction is not successful")
        if not isinstance(chain_tx,dict) or str(chain_tx.get("from","")).lower()!=request.wallet_address.lower() or str(chain_tx.get("to","")).lower()!=self.config.x402_payment_token_address.lower(): raise ValueError("allowance transaction wallet or token mismatch")
        calldata=str(chain_tx.get("input","")).lower();selector="0x095ea7b3";spender_word=spender_address.lower().removeprefix("0x").rjust(64,"0")
        if not calldata.startswith(selector) or calldata[10:74]!=spender_word: raise ValueError("allowance spender mismatch")
        approved=int(calldata[74:138],16);required=int(max_amount*(10**self.config.x402_payment_token_decimals))
        if approved<required: raise ValueError("onchain allowance is below spending cap")
        latest=self._rpc_int(request.chain,"eth_blockNumber",[]);included=int(str(receipt["blockNumber"]),16)
        if latest-included+1<self.config.native_min_confirmations: raise ValueError("allowance transaction lacks confirmations")

    def get_spending_authorization(self, spending_authorization_id: str) -> SpendingAuthorization | None:
        record = self._load_latest("spending_authorization").get(spending_authorization_id)
        if not record:
            return None
        return self._normalize_spending_authorization(SpendingAuthorization(**record))

    def revoke_spending_authorization(
        self,
        spending_authorization_id: str,
        *,
        reason: str = "user_requested_wallet_unbind",
        metadata: dict | None = None,
    ) -> SpendingAuthorization:
        raise ValueError("legacy spending authorizations are read-only")

    def spend_from_spending_authorization(
        self,
        request: SpendFromSpendingAuthorizationRequest,
    ) -> SpendingAuthorizationSpendResult:
        raise ValueError("legacy spending authorizations are read-only")

    def _spending_result(
        self,
        request: SpendFromSpendingAuthorizationRequest,
        status: str,
        submitted: bool,
        next_action: str,
        created_at: datetime,
        authorization: SpendingAuthorization | None = None,
        receipt_id: str | None = None,
        tx_hash: str | None = None,
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> SpendingAuthorizationSpendResult:
        return SpendingAuthorizationSpendResult(
            spend_id=f"fund_spend_{uuid4().hex[:12]}",
            spending_authorization_id=request.spending_authorization_id,
            user_id=authorization.user_id if authorization else None,
            agent_id=authorization.agent_id if authorization else None,
            wallet_address=authorization.wallet_address if authorization else None,
            amount_usdc=self._format_amount(self._parse_amount(request.amount_usdc)),
            venue=authorization.venue if authorization else None,
            destination=request.destination,
            chain=authorization.chain if authorization else None,
            token=authorization.token if authorization else None,
            status=status,
            submitted=submitted,
            receipt_id=receipt_id,
            tx_hash=tx_hash,
            reason=reason,
            next_action=next_action,
            created_at=self._format_time(created_at),
            metadata=metadata or {},
            event_log=[
                {
                    "event": "spending_authorization_spend_evaluated",
                    "status": status,
                    "submitted": submitted,
                    "reason": reason,
                    "receipt_id": receipt_id,
                    "tx_hash": tx_hash,
                    "created_at": self._format_time(created_at),
                }
            ],
        )

    def _record_spending_receipt(
        self,
        authorization: SpendingAuthorization,
        request: SpendFromSpendingAuthorizationRequest,
        tx_hash: str | None,
        receipt_id: str | None = None,
        metadata: dict | None = None,
        tx=None,
    ) -> FundingReceipt:
        authorization, reservation = self._resolve_authoritative_unified_spend(
            authorization, request, tx=tx
        )
        self._require_canonical_asset_pair(reservation)
        if tx_hash is not None:
            tx_hash=canonicalize_transaction_hash(tx_hash)
        if (
            reservation.get("state") != "payment_submitted"
            or reservation.get("receipt_id") != receipt_id
            or canonicalize_transaction_hash(reservation.get("tx_hash")) != tx_hash
        ):
            raise ValueError("unified authorization provenance does not match pending receipt")
        signing_key = self._receipt_signing_key()
        if receipt_id:
            existing=tx.get(receipt_id) if tx is not None else None
            if existing:
                existing_receipt=FundingReceipt.model_validate(existing)
                if not self.verify_receipt_signature(existing_receipt):
                    raise RuntimeError("stored Funding receipt signature is invalid")
                return existing_receipt
        now = self._utc_now()
        receipt = FundingReceipt(
            receipt_id=receipt_id or f"fund_receipt_{uuid4().hex[:12]}",
            spending_authorization_id=authorization.spending_authorization_id,
            resource=reservation["resource"],
            user_id=authorization.user_id,
            agent_id=authorization.agent_id,
            wallet_address=authorization.wallet_address,
            amount_usdc=self._format_amount(self._parse_amount(reservation["amount_usdc"])),
            venue=authorization.venue,
            destination=reservation["destination"],
            chain=authorization.chain,
            token=authorization.token,
            token_address=reservation["token_address"],
            status="settled",
            tx_hash=tx_hash,
            next_action="sync_venue_balance",
            created_at=self._format_time(now),
            metadata={
                **(metadata or {}),
                **{
                    key: reservation[key]
                    for key in (
                        "reservation_id",
                        "wallet_identity_id",
                        "spending_grant_id",
                        "asset_allowance_id",
                        "authorization_rail",
                        "product",
                        "purchase_id",
                        "merchant_id",
                        "quote_hash",
                        "action_id",
                        "policy_decision_id",
                        "amount_atomic",
                        "token_decimals",
                    )
                },
            },
            event_log=[
                {
                    "event": "spending_authorization_receipt_recorded",
                    "status": "settled",
                    "tx_hash": tx_hash,
                    "created_at": self._format_time(now),
                }
            ],
        )
        scope=self._receipt_scope(receipt)
        signature=hmac.new(signing_key,json.dumps(scope,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest()
        receipt=receipt.model_copy(update={"metadata":{**receipt.metadata,"receipt_scope":scope,"receipt_signature":"sha256="+signature}})
        if tx is None:
            raise RuntimeError("receipt persistence requires a funding transaction")
        tx.put("receipt", receipt.receipt_id, receipt.to_dict())
        return receipt

    def verify_receipt_signature(self, receipt: FundingReceipt) -> bool:
        if not receipt.token_address or receipt_signing_key_error(
            self.config.clink_receipt_signing_key,
            self.config.clink_internal_api_token,
        ):
            return False
        scope = receipt.metadata.get("receipt_scope")
        signature = receipt.metadata.get("receipt_signature")
        expected_scope = self._receipt_scope(receipt)
        if scope != expected_scope or not isinstance(signature, str):
            return False
        expected = "sha256=" + hmac.new(
            self.config.clink_receipt_signing_key.strip().encode("utf-8"),
            json.dumps(expected_scope, sort_keys=True, separators=(",", ":")).encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    def _receipt_signing_key(self) -> bytes:
        error = receipt_signing_key_error(
            self.config.clink_receipt_signing_key,
            self.config.clink_internal_api_token,
        )
        if error:
            raise RuntimeError(error)
        return self.config.clink_receipt_signing_key.strip().encode("utf-8")

    @staticmethod
    def _receipt_scope(receipt: FundingReceipt) -> dict:
        return {
            "receipt_id": receipt.receipt_id,
            "reservation_id": receipt.metadata.get("reservation_id"),
            "spending_authorization_id": receipt.spending_authorization_id,
            "spending_grant_id": receipt.metadata.get("spending_grant_id"),
            "asset_allowance_id": receipt.metadata.get("asset_allowance_id"),
            "wallet_identity_id": receipt.metadata.get("wallet_identity_id"),
            "authorization_rail": receipt.metadata.get("authorization_rail"),
            "user_id": receipt.user_id,
            "agent_id": receipt.agent_id,
            "action_id": receipt.metadata.get("action_id"),
            "policy_decision_id": receipt.metadata.get("policy_decision_id"),
            "purchase_id": receipt.metadata.get("purchase_id"),
            "merchant_id": receipt.metadata.get("merchant_id"),
            "quote_hash": receipt.metadata.get("quote_hash"),
            "payer": receipt.wallet_address,
            "pay_to": receipt.destination,
            "resource": receipt.resource,
            "amount_usdc": receipt.amount_usdc,
            "amount_atomic": receipt.metadata.get("amount_atomic"),
            "venue": receipt.venue,
            "product": receipt.metadata.get("product"),
            "chain": receipt.chain,
            "token": receipt.token,
            "token_address": receipt.token_address,
            "token_decimals": receipt.metadata.get("token_decimals"),
            "tx_hash": receipt.tx_hash,
            "status": receipt.status,
            "next_action": receipt.next_action,
            "created_at": receipt.created_at,
            "event_log": receipt.event_log,
        }

    def _require_canonical_asset_pair(self, row: dict) -> None:
        self.asset_registry.require_pair(row["network"], row["token_address"])

    def _prepare_native_transaction(self,authorization:SpendingAuthorization,request:SpendFromSpendingAuthorizationRequest)->dict:
        authorization, reservation = self._resolve_authoritative_unified_spend(
            authorization, request
        )
        if reservation.get("state") != "spending_reserved":
            raise ValueError("unified authorization provenance is not spendable")
        return self._build_native_transaction(authorization, reservation)

    def _read_reservation_allowance(
        self, reservation: dict, wallet_address: str
    ) -> int:
        self._require_unified_reservation(reservation)
        calldata = (
            "0xdd62ed3e"
            + self._abi_address(wallet_address)
            + self._abi_address(reservation["spender_address"])
        )
        observed = self._rpc_int(
            reservation["network"],
            "eth_call",
            [
                {"to": reservation["token_address"], "data": calldata},
                "latest",
            ],
        )
        if observed < 0 or observed >= 2**256:
            raise RuntimeError("asset allowance result is invalid")
        return observed

    def _build_native_transaction(
        self,
        authorization,
        reservation,
        *,
        nonce: int | None = None,
        relayer_key: str | None = None,
        relayer=None,
    ) -> dict:
        self._require_native_funding_enabled()
        if relayer_key is None or relayer is None:
            relayer_key, relayer = self._native_relayer_credentials()
        if authorization.spender_address.lower() != relayer.address.lower():
            raise RuntimeError(
                "current native spending mode requires spender_address to match the Clink relayer address"
            )

        amount = self._parse_amount(reservation["amount_usdc"])
        token_address, token_decimals = self._authorization_token_scope(authorization)
        atomic_value = amount * (Decimal(10) ** token_decimals)
        if atomic_value != atomic_value.to_integral_value():
            raise RuntimeError("settlement amount cannot be represented by selected token decimals")
        persisted_atomic = authorization.metadata.get("amount_atomic")
        if not isinstance(persisted_atomic, str) or not persisted_atomic.isdigit():
            raise RuntimeError("unified authorization is missing immutable atomic amount")
        atomic_amount = int(persisted_atomic)
        if atomic_amount != int(atomic_value):
            raise RuntimeError(
                "immutable atomic amount does not match reservation amount and decimals"
            )
        calldata = self._transfer_from_calldata(
            from_address=authorization.wallet_address,
            to_address=self._native_transfer_destination(reservation, relayer.address),
            atomic_amount=atomic_amount,
        )
        chain_id = self._chain_id(authorization.chain)
        if nonce is None:
            nonce=self._rpc_int(authorization.chain,"eth_getTransactionCount", [relayer.address, "pending"])
        tx = {
            "chainId": chain_id,
            "from": relayer.address,
            "to": token_address,
            "value": 0,
            "data": calldata,
            "nonce": nonce,
            "gasPrice": self._rpc_int(authorization.chain,"eth_gasPrice", []),
        }
        try:
            tx["gas"] = self._rpc_int(authorization.chain,"eth_estimateGas", [self._json_rpc_tx(tx)])
        except Exception:
            tx["gas"] = self.config.clink_native_facilitator_gas_limit
        signed = Account.sign_transaction(tx, relayer_key)
        raw_transaction = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        raw=self._ensure_0x(raw_transaction.hex())
        transaction = {
            "chainId": chain_id,
            "from": self._canonical_evm_address(relayer.address),
            "to": self._canonical_evm_address(token_address),
            "value": 0,
            "data": calldata,
            "nonce": nonce,
            "gasPrice": tx["gasPrice"],
            "gas": tx["gas"],
        }
        return {"raw_transaction":raw,"tx_hash":"0x"+keccak(bytes.fromhex(raw.removeprefix("0x"))).hex(),"relayer":transaction["from"],"nonce":nonce,"transaction":transaction}

    def _reconstruct_native_transaction(self, row: dict) -> str:
        transaction = row.get("settlement_transaction")
        if not isinstance(transaction, dict):
            raise ValueError("native transaction reconstruction fields are unavailable")
        expected_fields = {
            "chainId",
            "from",
            "to",
            "value",
            "data",
            "nonce",
            "gasPrice",
            "gas",
        }
        if set(transaction) != expected_fields:
            raise ValueError("native transaction reconstruction fields are invalid")
        try:
            sender = self._canonical_evm_address(transaction["from"])
            token = self._canonical_evm_address(transaction["to"])
            nonce = int(transaction["nonce"])
            values = {
                field: int(transaction[field])
                for field in ("chainId", "value", "gasPrice", "gas")
            }
            calldata = str(transaction["data"])
        except (TypeError, ValueError) as exc:
            raise ValueError("native transaction reconstruction fields are invalid") from exc
        if (
            nonce < 0
            or values["chainId"] != self._chain_id(row["network"])
            or values["value"] != 0
            or nonce != int(row["settlement_nonce"])
            or sender != self._canonical_evm_address(row["settlement_sender"])
            or token != self._reservation_token_address(row)
            or not isinstance(calldata, str)
            or not calldata.startswith("0x")
        ):
            raise ValueError("native transaction reconstruction fields are invalid")
        relayer_key, relayer = self._native_relayer_credentials()
        if sender != self._canonical_evm_address(relayer.address):
            raise ValueError("native transaction reconstruction relayer does not match")
        signing_transaction = {
            "chainId": values["chainId"],
            # eth-account verifies this display address against the private key.
            "from": relayer.address,
            "to": to_checksum_address(token),
            "value": values["value"],
            "data": calldata,
            "nonce": nonce,
            "gasPrice": values["gasPrice"],
            "gas": values["gas"],
        }
        signed = Account.sign_transaction(signing_transaction, relayer_key)
        raw_transaction = getattr(signed, "raw_transaction", None) or getattr(
            signed, "rawTransaction"
        )
        raw = self._ensure_0x(raw_transaction.hex())
        reconstructed_hash = "0x" + keccak(
            bytes.fromhex(raw.removeprefix("0x"))
        ).hex()
        if reconstructed_hash != row["tx_hash"]:
            raise ValueError("reconstructed native transaction hash does not match")
        return raw

    def _validate_native_settlement_evidence(
        self, row: dict, receipt: dict, chain_tx: Any
    ) -> str | None:
        if not isinstance(chain_tx, dict):
            return "native transaction details are unavailable for a mined receipt"
        try:
            tx_hash = canonicalize_transaction_hash(row["tx_hash"])
            if canonicalize_transaction_hash(receipt.get("transactionHash")) != tx_hash:
                return "native receipt hash does not match the reserved transaction"
            if canonicalize_transaction_hash(chain_tx.get("hash")) != tx_hash:
                return "native transaction hash does not match the reservation"
            sender = self._canonical_evm_address(chain_tx.get("from"))
            expected_sender = self._canonical_evm_address(row["settlement_sender"])
            nonce = self._parse_rpc_quantity(
                chain_tx.get("nonce"), field="native transaction nonce"
            )
            token = self._canonical_evm_address(chain_tx.get("to"))
            expected_token = self._reservation_token_address(row)
        except (TypeError, ValueError):
            return "native settlement transaction evidence is malformed"
        if sender != expected_sender:
            return "native settlement sender does not match the reservation"
        if nonce != int(row["settlement_nonce"]):
            return "native settlement nonce does not match the reservation"
        if token != expected_token:
            return "native settlement token target does not match the reservation"
        calldata = chain_tx.get("input")
        transaction = row.get("settlement_transaction")
        if not isinstance(transaction, dict) or calldata != transaction.get("data"):
            return "native settlement calldata does not match the signed reservation"
        if not isinstance(calldata, str) or not calldata.startswith("0x"):
            return "native settlement calldata is malformed"
        try:
            raw = bytes.fromhex(calldata[2:])
            if len(raw) != 4 + 3 * 32 or raw[:4] != bytes.fromhex("23b872dd"):
                return "native settlement calldata is malformed"
            owner = self._abi_word_address(raw[4:36])
            destination = self._abi_word_address(raw[36:68])
            amount = int.from_bytes(raw[68:100], "big")
            authorization = self._reservation_authorization(row)
            expected_owner = self._canonical_evm_address(authorization.wallet_address)
            expected_destination = self._native_transfer_destination(
                row, row["settlement_sender"]
            )
        except (TypeError, ValueError, AttributeError):
            return "native settlement calldata is malformed"
        if owner != expected_owner:
            return "native settlement owner does not match the authorization"
        if destination != expected_destination:
            return "native settlement destination does not match the reservation"
        if amount != int(row["amount_atomic"]):
            return "native settlement amount does not match the reservation"
        return None

    def _native_transfer_destination(
        self,
        reservation: dict,
        relayer_address: str,
    ) -> str:
        if reservation.get("authorization_rail") == "clink_payer_proxy":
            payer = self._canonical_evm_address(relayer_address)
            if payer != self._canonical_evm_address(reservation["spender_address"]):
                raise ValueError("Clink payer does not match the approved spender")
            return payer
        return self._canonical_evm_address(reservation["destination"])

    def _proxy_requirement_matches_reservation(
        self,
        reservation: dict,
        requirement: dict,
    ) -> bool:
        try:
            return (
                requirement["scheme"] == "exact"
                and requirement["network"] == reservation["network"]
                and self._canonical_evm_address(requirement["asset"])
                == self._reservation_token_address(reservation)
                and str(requirement["amount_atomic"])
                == str(reservation["amount_atomic"])
                and self._canonical_evm_address(requirement["pay_to"])
                == self._canonical_evm_address(reservation["destination"])
                and requirement["resource"] == reservation["resource"]
            )
        except (KeyError, TypeError, ValueError):
            return False

    def _require_proxy_token_domain(self, requirement: dict) -> None:
        if (
            requirement.get("token_name") != self.config.x402_payment_token_name
            or requirement.get("token_version")
            != self.config.x402_payment_token_version
        ):
            raise ValueError(
                "merchant token domain does not match trusted Core configuration"
            )

    def _proxy_authorization_expired(self, reservation: dict) -> bool:
        try:
            valid_before = int(reservation["proxy_valid_before"])
        except (KeyError, TypeError, ValueError):
            return True
        now = self._utc_now().replace(tzinfo=UTC)
        return valid_before <= int(now.timestamp())

    def _require_proxy_authorization_rotation_safe(self, reservation: dict) -> None:
        try:
            valid_before = int(reservation["proxy_valid_before"])
            nonce = str(reservation["proxy_nonce"]).lower()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "merchant payment authorization state is unavailable"
            ) from exc
        if len(nonce) != 66 or not nonce.startswith("0x"):
            raise ValueError("merchant payment authorization nonce is invalid")
        latest = self._rpc_call(
            reservation["network"], "eth_getBlockByNumber", ["finalized", False]
        )
        if not isinstance(latest, dict):
            raise RuntimeError("finalized block is unavailable")
        try:
            finalized_number = self._parse_rpc_quantity(
                latest.get("number"), field="finalized block number"
            )
            chain_timestamp = self._parse_rpc_quantity(
                latest.get("timestamp"), field="finalized block timestamp"
            )
        except ValueError as exc:
            raise RuntimeError("finalized block metadata is invalid") from exc
        finalized_block = hex(finalized_number)
        if chain_timestamp <= valid_before:
            raise ValueError(
                "merchant payment authorization may still be live; reconciliation required"
            )
        payer = self._canonical_evm_address(reservation.get("payer_address"))
        selector = keccak(text="authorizationState(address,bytes32)")[:4].hex()
        calldata = "0x" + selector + self._abi_address(payer) + nonce[2:]
        encoded_state = self._rpc_call(
            reservation["network"],
            "eth_call",
            [
                {"to": reservation["token_address"], "data": calldata},
                finalized_block,
            ],
        )
        if not isinstance(encoded_state, str) or re.fullmatch(
            r"0x[0-9a-fA-F]{64}", encoded_state
        ) is None:
            raise RuntimeError("authorizationState result is invalid")
        used = int(encoded_state, 16)
        if used not in {0, 1}:
            raise RuntimeError("authorizationState result is invalid")
        if used == 1:
            raise ValueError(
                "merchant payment authorization was already consumed; reconciliation required"
            )

    @staticmethod
    def _cleared_proxy_authorization() -> dict:
        return {
            "proxy_nonce": None,
            "proxy_valid_after": None,
            "proxy_valid_before": None,
            "proxy_challenge_hash": None,
            "payment_payload": None,
            "proxy_payment_prepared_at": None,
        }

    def _proxy_payment_typed_data(
        self,
        requirement: dict,
        authorization: dict,
    ) -> dict:
        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "TransferWithAuthorization": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "validAfter", "type": "uint256"},
                    {"name": "validBefore", "type": "uint256"},
                    {"name": "nonce", "type": "bytes32"},
                ],
            },
            "primaryType": "TransferWithAuthorization",
            "domain": {
                "name": requirement["token_name"],
                "version": requirement["token_version"],
                "chainId": self._chain_id(requirement["network"]),
                "verifyingContract": requirement["asset"],
            },
            "message": authorization,
        }

    def _native_relayer_credentials(self):
        self._require_native_funding_enabled()
        relayer_key = self._normalize_private_key(
            self.config.clink_native_facilitator_relayer_private_key
        )
        if not relayer_key:
            raise RuntimeError(
                "CLINK_NATIVE_FACILITATOR_RELAYER_PRIVATE_KEY is not configured"
            )
        return relayer_key, Account.from_key(relayer_key)

    def _require_native_funding_enabled(self) -> None:
        if not self.config.clink_live_funding:
            raise RuntimeError("CLINK_LIVE_FUNDING is disabled")
        if not self.config.clink_native_facilitator_enabled:
            raise RuntimeError("CLINK_NATIVE_FACILITATOR_ENABLED is disabled")

    def _authorization_token_scope(
        self, authorization: SpendingAuthorization
    ) -> tuple[str, int]:
        try:
            token_address = self._canonical_evm_address(
                authorization.metadata["token_address"]
            )
            token_decimals = int(authorization.metadata["token_decimals"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                "unified authorization is missing selected token scope"
            ) from exc
        if not 0 <= token_decimals <= 255:
            raise RuntimeError("unified authorization token decimals are invalid")
        return to_checksum_address(token_address), token_decimals

    def _reservation_token_address(self, row: dict) -> str:
        self._require_unified_reservation(row)
        if "token_address" not in row:
            raise ValueError("unified reservation is missing selected token scope")
        return self._canonical_evm_address(row["token_address"])

    def _transfer_from_calldata(self, from_address: str, to_address: str, atomic_amount: int) -> str:
        selector = keccak(text="transferFrom(address,address,uint256)")[:4].hex()
        return "0x" + selector + self._abi_address(from_address) + self._abi_address(to_address) + self._abi_uint(atomic_amount)

    def _rpc_call(self, network: str, method: str, params: list) -> object:
        if network not in self.config.allowed_evm_networks:
            raise RuntimeError(f"unsupported configured EVM network: {network}")
        expected_chain_id = self._chain_id(network)
        observed = self._raw_rpc_call(network, "eth_chainId", [])
        try:
            observed_chain_id = int(str(observed), 16)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("RPC chain id is invalid") from exc
        if observed_chain_id != expected_chain_id:
            raise RuntimeError("RPC chain id does not match requested network")
        if method == "eth_chainId":
            return observed
        return self._raw_rpc_call(network, method, params)

    def _raw_rpc_call(self, network: str, method: str, params: list) -> object:
        return self.rpc_transport(network, method, params)

    def _rpc_int(self, network: str, method: str, params: list) -> int:
        result = self._rpc_call(network, method, params)
        if isinstance(result, str) and result.startswith("0x"):
            return int(result, 16)
        return int(result)

    def _wait_for_receipt(self, network: str, tx_hash: str) -> dict | None:
        for _ in range(3):
            receipt = self._rpc_call(network,"eth_getTransactionReceipt", [tx_hash])
            if isinstance(receipt, dict):
                included=int(str(receipt.get("blockNumber","0x0")),16)
                latest=self._rpc_int(network,"eth_blockNumber",[])
                if latest-included+1>=self.config.native_min_confirmations:
                    return receipt
            time.sleep(1)
        raise RuntimeError("native settlement receipt lacks required confirmations")

    def _native_relayer_address(self) -> str:
        relayer_key = self._normalize_private_key(self.config.clink_native_facilitator_relayer_private_key)
        if not relayer_key:
            return ""
        try:
            return Account.from_key(relayer_key).address
        except Exception:
            return ""

    @staticmethod
    def _json_rpc_tx(tx: dict) -> dict:
        return {
            key: (hex(value) if isinstance(value, int) else value)
            for key, value in tx.items()
            if key != "chainId"
        }

    @staticmethod
    def _normalize_private_key(private_key: str) -> str:
        if not private_key:
            return ""
        private_key = private_key.strip().strip('"').strip("'")
        return private_key if private_key.startswith("0x") else f"0x{private_key}"

    @staticmethod
    def _ensure_0x(value: str) -> str:
        return value if value.startswith("0x") else f"0x{value}"

    @staticmethod
    def _abi_address(value: str) -> str:
        return value.removeprefix("0x").lower().rjust(64, "0")

    @staticmethod
    def _abi_uint(value: int) -> str:
        if value < 0:
            raise RuntimeError("ABI uint cannot be negative")
        return hex(value).removeprefix("0x").rjust(64, "0")

    def get_funding_status(self, user_id: str | None = None, venue: str | None = None) -> FundingStatus:
        spending_authorizations = [
            self._normalize_spending_authorization(SpendingAuthorization(**record))
            for record in self._load_latest("spending_authorization").values()
        ]
        receipts = [FundingReceipt(**record) for record in self._load_latest("receipt").values()]
        if user_id:
            spending_authorizations = [item for item in spending_authorizations if item.user_id == user_id]
            receipts = [item for item in receipts if item.user_id == user_id]
        if venue:
            spending_authorizations = [item for item in spending_authorizations if item.venue == venue]
            receipts = [item for item in receipts if item.venue == venue]

        available: dict[str, Decimal] = {}
        for authorization in spending_authorizations:
            if authorization.status != "active":
                continue
            available.setdefault(authorization.venue, Decimal("0"))
            available[authorization.venue] += self._parse_amount(authorization.remaining_amount_usdc)

        settled: dict[str, Decimal] = {}
        for receipt in receipts:
            if receipt.status != "settled":
                continue
            settled.setdefault(receipt.venue, Decimal("0"))
            settled[receipt.venue] += self._parse_amount(receipt.amount_usdc)

        return FundingStatus(
            user_id=user_id,
            venue=venue,
            spending_authorizations=spending_authorizations,
            receipts=receipts,
            available_budget_usdc_by_venue={key: self._format_amount(value) for key, value in sorted(available.items())},
            settled_amount_usdc_by_venue={key: self._format_amount(value) for key, value in sorted(settled.items())},
        )

    def get_hosted_wallet_readiness(self, user_id: str) -> dict:
        """Read-only enrollment status; it is not authority to submit a payment."""
        if not isinstance(user_id, str) or not user_id or len(user_id) > 96:
            raise ValueError("user identity is invalid")
        registry = getattr(self, "hosted_wallet_registry", None)
        result = {
            "user_id": user_id,
            "credential_routing": "per_wallet" if registry is not None else "single_wallet",
            "ready": False,
            "reason_code": "HOSTED_PER_WALLET_ROUTING_REQUIRED",
            "network_status": {},
            "ready_networks": [],
        }
        if registry is None or self.config.clink_facilitator_mode != "hosted":
            return result
        with self.ledger.sessions() as session:
            identities = session.scalars(select(WalletIdentityRow).where(
                WalletIdentityRow.user_id == user_id,
                WalletIdentityRow.status == "active",
            ).limit(2)).all()
            if len(identities) != 1 or not identities[0].verified_at or not identities[0].proof_hash:
                return {**result, "reason_code": "WALLET_NOT_READY"}
            wallet_identity_id = identities[0].wallet_identity_id
        readiness = self.get_funding_readiness()
        configured_networks = self._configured_hosted_production_networks()
        service_ready_networks = set(readiness.get("ready_networks", ()))
        network_status: dict[str, dict[str, object]] = {}
        ready_networks: list[str] = []
        for network in configured_networks:
            try:
                registry.current(
                    user_id=user_id,
                    wallet_identity_id=wallet_identity_id,
                    network=network,
                )
            except HostedWalletRegistryError:
                network_status[network] = {
                    "ready": False,
                    "reason_code": "HOSTED_ENROLLMENT_REQUIRED",
                }
                continue
            if network not in service_ready_networks:
                network_status[network] = {
                    "ready": False,
                    "reason_code": "HOSTED_SERVICE_NOT_READY",
                }
                continue
            network_status[network] = {"ready": True, "reason_code": None}
            ready_networks.append(network)
        ready_networks.sort()
        if ready_networks:
            return {
                **result,
                "ready": True,
                "reason_code": None,
                "network_status": network_status,
                "ready_networks": ready_networks,
            }
        reason_code = (
            "HOSTED_SERVICE_NOT_READY"
            if any(
                item.get("reason_code") == "HOSTED_SERVICE_NOT_READY"
                for item in network_status.values()
            )
            else "HOSTED_ENROLLMENT_REQUIRED"
        )
        return {
            **result,
            "reason_code": reason_code,
            "network_status": network_status,
            "ready_networks": ready_networks,
        }

    def get_funding_readiness(self) -> dict:
        missing: list[str] = []
        warnings: list[str] = []
        hosted_mode = self.config.clink_facilitator_mode == "hosted"
        settlement_rail = "clink_hosted_executor" if hosted_mode else "clink_native_facilitator"
        relayer_address = None
        native_ready = False
        if not hosted_mode:
            if not self.config.clink_native_facilitator_enabled:
                missing.append("CLINK_NATIVE_FACILITATOR_ENABLED=true")
            if not self.config.polygon_rpc_url:
                missing.append("CLINK_POLYGON_RPC_URL")
            if not self.config.base_rpc_url:
                missing.append("CLINK_BASE_RPC_URL")
            if not self.config.clink_polygon_usdc_address:
                missing.append("CLINK_POLYGON_USDC_ADDRESS")
            if not self.config.clink_base_usdc_address:
                missing.append("CLINK_BASE_USDC_ADDRESS")
            receipt_key_error = receipt_signing_key_error(
                self.config.clink_receipt_signing_key,
                self.config.clink_internal_api_token,
            )
            if receipt_key_error:
                missing.append(receipt_key_error)
            relayer_key = self._normalize_private_key(
                self.config.clink_native_facilitator_relayer_private_key
            )
            if not relayer_key:
                missing.append("CLINK_NATIVE_FACILITATOR_RELAYER_PRIVATE_KEY")
            else:
                try:
                    relayer_address = Account.from_key(relayer_key).address
                except Exception:
                    missing.append("CLINK_NATIVE_FACILITATOR_RELAYER_PRIVATE_KEY")
                    warnings.append(
                        "CLINK_NATIVE_FACILITATOR_RELAYER_PRIVATE_KEY is not a valid EVM private key"
                    )
        configured_spenders = {
            "CLINK_FUNDING_SPENDER_ADDRESS": self.config.clink_funding_spender_address,
            "CLINK_POLYGON_SPENDER_ADDRESS": self.config.clink_polygon_spender_address,
            "CLINK_BASE_SPENDER_ADDRESS": self.config.clink_base_spender_address,
        }
        if relayer_address and not hosted_mode:
            for field_name, configured_spender in configured_spenders.items():
                if configured_spender and configured_spender.lower() != relayer_address.lower():
                    message = (
                        f"{field_name} must match the relayer address in current native mode"
                    )
                    missing.append(message)
                    warnings.append(message)
        native_ready = not missing if not hosted_mode else False

        hosted_missing: list[str] = []
        hosted_networks: tuple[str, ...] = ()
        hosted_ready_networks: list[str] = []
        hosted_network_status: dict[str, dict[str, object]] = {}
        if hosted_mode:
            hosted_missing.extend(self._hosted_configuration_missing())
            hosted_networks = self._configured_hosted_production_networks()
            registry = getattr(self, "hosted_wallet_registry", None)
            if isinstance(registry, HostedWalletRouter):
                try:
                    available_networks = set(registry.configured_networks())
                except HostedWalletRegistryError:
                    available_networks = set()
                for network in hosted_networks:
                    credentials_ready = network in available_networks
                    ready = credentials_ready and self.config.clink_live_funding
                    hosted_network_status[network] = {
                        "ready": ready,
                        "reason_code": (
                            None
                            if ready
                            else (
                                "HOSTED_SERVICE_NOT_READY"
                                if credentials_ready
                                else "HOSTED_WALLET_CREDENTIALS_UNAVAILABLE"
                            )
                        ),
                    }
                    if ready:
                        hosted_ready_networks.append(network)
                if hosted_networks and not (set(hosted_networks) & available_networks):
                    hosted_missing.append("HOSTED_WALLET_CREDENTIALS_UNAVAILABLE")
            elif registry is not None:
                try:
                    available_networks = set(registry.configured_networks())
                except HostedWalletRegistryError:
                    available_networks = set()
                    hosted_missing.append("HOSTED_WALLET_CREDENTIALS_UNAVAILABLE")
                for network in hosted_networks:
                    credentials_ready = network in available_networks
                    ready = credentials_ready and self.config.clink_live_funding
                    hosted_network_status[network] = {
                        "ready": ready,
                        "reason_code": (
                            None
                            if ready
                            else (
                                "HOSTED_SERVICE_NOT_READY"
                                if credentials_ready
                                else "HOSTED_WALLET_CREDENTIALS_UNAVAILABLE"
                            )
                        ),
                    }
                    if not credentials_ready:
                        hosted_missing.append(f"HOSTED_WALLET_CREDENTIALS[{network}]")
                    elif ready:
                        hosted_ready_networks.append(network)
            else:
                for network in hosted_networks:
                    client = self.hosted_clients.get(network)
                    credentials_ready = client is not None and all(
                        callable(getattr(client, method, None))
                        for method in (
                            "prepare_execution",
                            "submit",
                            "recover",
                            "recover_by_idempotency",
                        )
                    )
                    ready = credentials_ready and self.config.clink_live_funding
                    hosted_network_status[network] = {
                        "ready": ready,
                        "reason_code": (
                            None
                            if ready
                            else (
                                "HOSTED_SERVICE_NOT_READY"
                                if credentials_ready
                                else "HOSTED_FACILITATOR_UNAVAILABLE"
                            )
                        ),
                    }
                    if ready:
                        hosted_ready_networks.append(network)
                    elif not credentials_ready and client is None:
                        hosted_missing.append(f"HOSTED_FACILITATOR_CLIENT[{network}]")
                    elif not credentials_ready:
                        hosted_missing.append(
                            f"HOSTED_FACILITATOR_CLIENT[{network}] is incomplete"
                        )
            missing.extend(hosted_missing)

        hosted_ready_networks.sort()
        if not self.config.clink_live_funding:
            missing.append("CLINK_LIVE_FUNDING=true")
        live_ready = self.config.clink_live_funding and not missing
        # A local credential file is configuration evidence, not payment
        # readiness. Preserve the legacy configuration-only boolean below,
        # but never advertise a ready network while service gates are closed.
        if not live_ready:
            hosted_ready_networks = []
            for network, state in hosted_network_status.items():
                if state["ready"]:
                    hosted_network_status[network] = {
                        "ready": False,
                        "reason_code": "HOSTED_SERVICE_NOT_READY",
                    }
        if hosted_mode:
            supported_assets = {
                network: HOSTED_CHAIN_PROFILES[network].token
                for network in hosted_networks
            }
            spender_addresses = self._hosted_spender_addresses(hosted_networks)
        else:
            supported_assets = {
                network: token
                for network, token in {
                    "eip155:137": self.config.clink_polygon_usdc_address,
                    "eip155:8453": self.config.clink_base_usdc_address,
                }.items()
                if token
            }
            native_spender = self.config.clink_funding_spender_address or relayer_address
            spender_addresses = {
                network: configured or native_spender
                for network, configured in {
                    "eip155:137": self.config.clink_polygon_spender_address,
                    "eip155:8453": self.config.clink_base_spender_address,
                }.items()
                if configured or native_spender
            }
        spender_values = set(spender_addresses.values())
        spender_address = (
            next(iter(spender_values))
            if len(spender_values) == 1
            else None
        )
        return {
            "service": "funding_service",
            "status": "ready" if live_ready else "not_ready",
            "settlement_rail": settlement_rail,
            "live_funding_enabled": self.config.clink_live_funding,
            "native_facilitator_enabled": self.config.clink_native_facilitator_enabled,
            "native_facilitator_ready": native_ready,
            "hosted_facilitator_enabled": hosted_mode,
            "hosted_facilitator_ready": hosted_mode and not hosted_missing,
            "hosted_credential_routing": (
                "per_wallet" if getattr(self, "hosted_wallet_registry", None) is not None
                else "single_wallet"
            ),
            "user_enrollment_required": getattr(self, "hosted_wallet_registry", None) is not None,
            "configured_networks": list(hosted_networks),
            "ready_networks": hosted_ready_networks,
            "network_status": hosted_network_status,
            "relayer_address": relayer_address,
            "universal_payer_ready": live_ready,
            "payer_address": relayer_address,
            "automatic_payment_rail": (
                "clink_hosted_executor"
                if hosted_mode
                else "clink_payer_proxy"
            )
            if live_ready
            else None,
            "supported_assets": supported_assets,
            "mandate_limits_enforced": [
                "per_transaction",
                "rolling_hour",
                "daily",
                "total",
            ],
            "spending_authorization_supported": True,
            "spender_address": spender_address,
            "spender_addresses": spender_addresses,
            "spending_mode": "relayer_transfer_from",
            "network": self.config.x402_payment_network,
            "token": self.config.x402_payment_token,
            "token_address": self.config.x402_payment_token_address,
            "missing": missing,
            "warnings": warnings,
            "next_action": "authorize_spending_cap_or_spend"
            if live_ready
            else (
                "configure_hosted_facilitator"
                if hosted_mode
                else "configure_native_facilitator"
            ),
        }

    def _normalize_spending_authorization(self, authorization: SpendingAuthorization) -> SpendingAuthorization:
        if authorization.status != "active":
            return authorization
        if datetime.fromisoformat(authorization.expires_at.removesuffix("Z")) > self._utc_now():
            return authorization
        now = self._utc_now()
        return authorization.model_copy(
            update={
                "status": "expired",
                "remaining_amount_usdc": "0",
                "updated_at": self._format_time(now),
                "event_log": [
                    *authorization.event_log,
                    {"event": "spending_authorization_expired", "created_at": self._format_time(now)},
                ],
            }
        )

    def _load_latest(self, record_type: str) -> dict[str, dict]:
        records: dict[str, dict] = {}
        if self.storage_file.exists():
            with self.storage_file.open() as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if record.get("record_type") != record_type:
                        continue
                    records[record["record_id"]] = record["payload"]
        if record_type == "receipt":
            records.update(self.ledger.list_records("receipt"))
        return records

    @staticmethod
    def _looks_like_address(value: str | None) -> bool:
        return bool(value and value.startswith("0x") and len(value) == 42 and int(value, 16) != 0)

    @staticmethod
    def _chain_id(network: str) -> int:
        if network.startswith("eip155:"):
            return int(network.split(":", 1)[1])
        raise ValueError(f"unsupported x402 EVM network: {network}")

    @staticmethod
    def _parse_amount(value: str) -> Decimal:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("amount_usdc must be a valid decimal string") from exc
        if not amount.is_finite():
            raise ValueError("amount_usdc must be finite")
        if amount < 0:
            raise ValueError("amount_usdc must be non-negative")
        return amount

    @staticmethod
    def _format_amount(value: Decimal) -> str:
        rendered = format(value, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return rendered or "0"

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.utcnow()

    @staticmethod
    def _as_utc_datetime(value: datetime) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError("funding timestamp is invalid")
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.isoformat() + "Z"
