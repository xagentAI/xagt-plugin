from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Callable

import httpx

from platforms.polymarket.executor import PolymarketExecutor
from services.account_binding_service.credential_store import (
    CredentialStore,
    PolymarketApiCredentials,
)
from services.account_binding_service.service import (
    PolymarketAccountBindingService,
)
from services.funding_adapter_service.coordinator import (
    FundingCoordinatorError,
    PolymarketFundingCoordinator,
    VenueAccount,
)
from services.funding_adapter_service.core_gateway import (
    HttpPredictionCoreFundingGateway,
)
from services.funding_adapter_service.schemas import (
    PolymarketFundingRiskAssessment,
    UINT256_MAX_ATOMIC,
)
from services.funding_adapter_service.service import (
    PolymarketFundingAdapterService,
)
from shared.config import AppConfig


_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,95}$")
_RESOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
_POSITIVE_UINT256 = re.compile(r"^[1-9][0-9]{0,77}$")
_UINT256 = re.compile(r"^(?:0|[1-9][0-9]{0,77})$")


class PersonalVenueAccountGateway:
    """Read one Personal user's exact active POLY_1271 venue scope."""

    def __init__(
        self,
        *,
        binding_service: PolymarketAccountBindingService,
        credential_store: CredentialStore,
        clob_client_factory: Callable[[PolymarketApiCredentials], Any],
    ) -> None:
        self.binding_service = binding_service
        self.credential_store = credential_store
        self.clob_client_factory = clob_client_factory

    def resolve_active_account(self, *, user_id: str) -> VenueAccount:
        binding, _credentials = self._exact_scope(user_id=user_id)
        return VenueAccount(
            user_id=user_id,
            binding_id=binding.binding_id,
            venue_wallet_address=_address(binding.funder_address),
        )

    def get_buying_power_atomic(
        self,
        *,
        user_id: str,
        binding_id: str,
        venue_wallet_address: str,
    ) -> str:
        binding, credentials = self._exact_scope(user_id=user_id)
        if (
            binding.binding_id != binding_id
            or _address(binding.funder_address) != _address(venue_wallet_address)
        ):
            raise FundingCoordinatorError("venue account is unavailable")
        try:
            from py_clob_client_v2.clob_types import (
                AssetType,
                BalanceAllowanceParams,
            )

            client = self.clob_client_factory(credentials)
            response = client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            if type(response) is not dict:
                raise ValueError
            balance = response.get("balance")
            return _uint256(balance)
        except FundingCoordinatorError:
            raise
        except Exception:
            raise FundingCoordinatorError(
                "venue buying power is unavailable"
            ) from None

    def _exact_scope(
        self, *, user_id: str
    ) -> tuple[Any, PolymarketApiCredentials]:
        try:
            if not isinstance(user_id, str) or not _ID.fullmatch(user_id):
                raise ValueError
            binding = self.binding_service.latest_binding(
                user_id, venue="polymarket"
            )
            credentials = self.credential_store.get_polymarket_credentials(
                user_id
            )
            record = self.credential_store.latest_record(user_id)
            if binding is None or credentials is None or record is None:
                raise ValueError

            owner = _address(binding.wallet_address)
            deposit = _address(binding.polymarket_deposit_wallet)
            funder = _address(binding.funder_address)
            credential_owner = _address(credentials.wallet_address)
            credential_funder = _address(credentials.funder_address)
            record_owner = _address(record.wallet_address)
            fingerprint = _fingerprint(credentials.api_key)
            if (
                binding.user_id != user_id
                or binding.venue != "polymarket"
                or binding.status != "active"
                or binding.account_mode != "deposit_wallet"
                or binding.polymarket_signature_type != "3"
                or binding.has_api_credentials is not True
                or credentials.signature_type != "3"
                or record.user_id != user_id
                or record.venue != "polymarket"
                or deposit != funder
                or owner != credential_owner
                or owner != record_owner
                or funder != credential_funder
                or binding.api_key_fingerprint != fingerprint
                or record.api_key_fingerprint != fingerprint
                or not all(
                    isinstance(value, str) and bool(value)
                    for value in (
                        credentials.api_key,
                        credentials.api_secret,
                        credentials.api_passphrase,
                    )
                )
            ):
                raise ValueError
            return binding, credentials
        except FundingCoordinatorError:
            raise
        except Exception:
            raise FundingCoordinatorError("venue account is unavailable") from None


class CoreDelegatedRiskAssessmentGateway:
    """Build a fresh non-authoritative context input for Core policy.

    This is deliberately not an external risk assessment. The low/zero/approve
    input only lets the funding coordinator reach Core; Core Policy and its
    versioned MistTrack mapping remain the sole live funding decision.
    """

    available = True
    health_mode = "delegated_to_core"

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))

    def assess(
        self,
        *,
        operation_id: str,
        user_id: str,
        bridge_address: str,
        amount_atomic: str,
        resource: str,
    ) -> PolymarketFundingRiskAssessment:
        try:
            operation = _identifier(operation_id)
            subject = _identifier(user_id)
            bridge = _address(bridge_address)
            amount = _positive_uint256(amount_atomic)
            selected_resource = _resource(resource)
            now = self.clock()
            if (
                not isinstance(now, datetime)
                or now.tzinfo is None
                or now.utcoffset() is None
            ):
                raise ValueError
            assessed_at = now.astimezone(UTC)
            digest = hashlib.sha256(
                json.dumps(
                    [operation, subject, bridge, amount, selected_resource],
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            return PolymarketFundingRiskAssessment(
                assessment_id=f"pm_core_delegated_{digest[:32]}",
                subject_id=subject,
                bridge_address=bridge,
                amount_atomic=amount,
                resource=selected_resource,
                risk_level="low",
                risk_score=0,
                risk_action="approve",
                assessed_at=assessed_at,
            )
        except Exception:
            raise FundingCoordinatorError(
                "funding risk input is unavailable", status_code=503
            ) from None


def build_production_funding_coordinator(
    config: AppConfig,
    *,
    funding_adapter: PolymarketFundingAdapterService | None = None,
    core_transport: httpx.BaseTransport | None = None,
    binding_service: PolymarketAccountBindingService | None = None,
    credential_store: CredentialStore | None = None,
    clob_client_factory: Callable[[PolymarketApiCredentials], Any] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> PolymarketFundingCoordinator:
    """Assemble the Personal single-process funding coordinator without I/O."""

    if config.profile != "personal":
        raise ValueError("production funding coordinator requires personal profile")
    selected_adapter = funding_adapter or PolymarketFundingAdapterService(config)
    selected_store = credential_store
    if selected_store is None and binding_service is not None:
        selected_store = binding_service.credential_store
    selected_store = selected_store or CredentialStore(config)
    selected_bindings = binding_service or PolymarketAccountBindingService(
        config,
        credential_store=selected_store,
    )
    if clob_client_factory is None:
        executor = PolymarketExecutor(config, credential_store=selected_store)
        clob_client_factory = executor._l2_client

    core_gateway = HttpPredictionCoreFundingGateway(
        token=config.clink_core_internal_api_token,
        action_base_url=config.clink_core_action_service_url,
        policy_base_url=config.clink_core_policy_service_url,
        audit_base_url=config.clink_core_audit_service_url,
        funding_base_url=config.clink_core_funding_service_url,
        account_base_url=config.clink_core_account_service_url,
        transport=core_transport,
    )
    return PolymarketFundingCoordinator(
        config=config,
        funding_adapter=selected_adapter,
        core_gateway=core_gateway,
        venue_accounts=PersonalVenueAccountGateway(
            binding_service=selected_bindings,
            credential_store=selected_store,
            clob_client_factory=clob_client_factory,
        ),
        risk_assessments=CoreDelegatedRiskAssessmentGateway(clock=clock),
        clock=clock,
    )


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError
    return value


def _address(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError
    normalized = value.strip().lower()
    if not _ADDRESS.fullmatch(normalized) or normalized == "0x" + "0" * 40:
        raise ValueError
    return normalized


def _resource(value: Any) -> str:
    if not isinstance(value, str) or not _RESOURCE.fullmatch(value):
        raise ValueError
    return value


def _positive_uint256(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not _POSITIVE_UINT256.fullmatch(value)
        or len(value) == len(UINT256_MAX_ATOMIC)
        and value > UINT256_MAX_ATOMIC
    ):
        raise ValueError
    return value


def _uint256(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not _UINT256.fullmatch(value)
        or len(value) == len(UINT256_MAX_ATOMIC)
        and value > UINT256_MAX_ATOMIC
    ):
        raise ValueError
    return value


def _fingerprint(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}"
