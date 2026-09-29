from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from services.account_binding_service.credential_store import (
    CredentialRecord,
    PolymarketApiCredentials,
)
from services.account_binding_service.schemas import PolymarketAccountBinding
from services.funding_adapter_service.coordinator import FundingCoordinatorError
from shared.config import AppConfig


USER_ID = "telegram_user_1"
BINDING_ID = "pm_binding_1"
OWNER = "0x1111111111111111111111111111111111111111"
FUNDER = "0x2222222222222222222222222222222222222222"
BRIDGE = "0x3333333333333333333333333333333333333333"
NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
API_KEY = "api-key-secret-marker"
API_KEY_FINGERPRINT = (
    f"sha256:{hashlib.sha256(API_KEY.encode('utf-8')).hexdigest()[:12]}"
)


def _config(tmp_path, **updates) -> AppConfig:
    values = {
        "profile": "personal",
        "polymarket_bridge_database_path": str(tmp_path / "bridge.sqlite3"),
        "account_binding_file": str(tmp_path / "bindings.jsonl"),
        "credential_store_file": str(tmp_path / "credentials.jsonl"),
        "credential_store_dev_secret": "production-assembly-test-secret",
        "prediction_markets_internal_api_token": "prediction-token",
        "clink_core_internal_api_token": "core-token",
    }
    values.update(updates)
    return AppConfig(**values)


def _binding(**updates) -> PolymarketAccountBinding:
    values = {
        "binding_id": BINDING_ID,
        "session_id": "pm_bind_sess_1",
        "user_id": USER_ID,
        "agent_id": "hermes",
        "venue": "polymarket",
        "wallet_address": OWNER,
        "polymarket_deposit_wallet": FUNDER,
        "funder_address": FUNDER,
        "account_mode": "deposit_wallet",
        "polymarket_signature_type": "3",
        "has_api_credentials": True,
        "api_key_fingerprint": API_KEY_FINGERPRINT,
        "status": "active",
        "next_action": "account_binding_active",
        "created_at": NOW.isoformat(),
    }
    values.update(updates)
    return PolymarketAccountBinding.model_validate(values)


def _credentials(**updates) -> PolymarketApiCredentials:
    values = {
        "api_key": API_KEY,
        "api_secret": "api-secret-marker",
        "api_passphrase": "api-passphrase-marker",
        "signature_type": "3",
        "funder_address": FUNDER,
        "wallet_address": OWNER,
    }
    values.update(updates)
    return PolymarketApiCredentials(**values)


def _record(**updates) -> CredentialRecord:
    values = {
        "user_id": USER_ID,
        "venue": "polymarket",
        "wallet_address": OWNER,
        "api_key_fingerprint": API_KEY_FINGERPRINT,
        "credential_source": "polymarket_l1_derive",
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }
    values.update(updates)
    return CredentialRecord(**values)


class _BindingServiceStub:
    def __init__(self, binding: PolymarketAccountBinding | None) -> None:
        self.binding = binding
        self.calls: list[tuple[str, str]] = []

    def latest_binding(
        self, user_id: str, venue: str = "polymarket"
    ) -> PolymarketAccountBinding | None:
        self.calls.append((user_id, venue))
        return self.binding


class _CredentialStoreStub:
    def __init__(
        self,
        credentials: PolymarketApiCredentials | None,
        record: CredentialRecord | None,
    ) -> None:
        self.credentials = credentials
        self.record = record

    def get_polymarket_credentials(
        self, user_id: str
    ) -> PolymarketApiCredentials | None:
        assert user_id == USER_ID
        return self.credentials

    def latest_record(self, user_id: str) -> CredentialRecord | None:
        assert user_id == USER_ID
        return self.record


class _BalanceClient:
    def __init__(self, response) -> None:
        self.response = response
        self.calls = []

    def get_balance_allowance(self, params):
        self.calls.append(params)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _gateway(
    *,
    binding: PolymarketAccountBinding | None = None,
    credentials: PolymarketApiCredentials | None = None,
    record: CredentialRecord | None = None,
    balance_response=None,
):
    from services.funding_adapter_service.production_gateways import (
        PersonalVenueAccountGateway,
    )

    binding_service = _BindingServiceStub(binding or _binding())
    credential_store = _CredentialStoreStub(
        credentials or _credentials(), record or _record()
    )
    client = _BalanceClient(
        {"balance": "1234567", "allowances": {}}
        if balance_response is None
        else balance_response
    )
    gateway = PersonalVenueAccountGateway(
        binding_service=binding_service,
        credential_store=credential_store,
        clob_client_factory=lambda _credentials: client,
    )
    return gateway, binding_service, client


def test_default_personal_app_assembles_funding_coordinator_without_injection(
    tmp_path,
) -> None:
    from services.funding_adapter_service.app import create_app

    app = create_app(config=_config(tmp_path))
    with TestClient(app) as client:
        health = client.get("/healthz")
        downstream_failure = client.post(
            "/polymarket/funding-operations",
            json={
                "user_id": USER_ID,
                "amount_usdc": "1.000000",
                "idempotency_key": "pm_funding_demo_1",
                "resource": "polymarket:funding:demo",
            },
            headers={"Authorization": "Bearer prediction-token"},
        )

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["funding_coordinator"] == "assembled"
    assert health.json()["risk_assessment"] == "delegated_to_core"
    assert health.json()["risk_authority"] == "core_policy"
    assert downstream_failure.status_code == 409
    assert downstream_failure.json() == {"detail": "venue account is unavailable"}


def test_default_personal_app_starts_fail_closed_when_core_token_is_missing(
    tmp_path,
) -> None:
    from services.funding_adapter_service.app import create_app

    app = create_app(config=_config(tmp_path, clink_core_internal_api_token=""))
    with TestClient(app) as client:
        health = client.get("/healthz")
        unavailable = client.post(
            "/polymarket/funding-operations",
            json={
                "user_id": USER_ID,
                "amount_usdc": "1.000000",
                "idempotency_key": "pm_funding_demo_2",
                "resource": "polymarket:funding:demo",
            },
            headers={"Authorization": "Bearer prediction-token"},
        )

    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert health.json()["funding_coordinator"] == "unavailable"
    assert health.json()["risk_assessment"] == "unavailable"
    assert health.json()["risk_authority"] == "unavailable"
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "funding operations are unavailable"}


def test_production_builder_accepts_no_network_core_and_clob_dependencies(
    tmp_path,
) -> None:
    from services.funding_adapter_service.core_gateway import (
        PredictionCoreGatewayError,
    )
    from services.funding_adapter_service.production_gateways import (
        CoreDelegatedRiskAssessmentGateway,
        PersonalVenueAccountGateway,
        build_production_funding_coordinator,
    )

    requests = []

    def core_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, json={"detail": "test core unavailable"})

    binding_service = _BindingServiceStub(_binding())
    credential_store = _CredentialStoreStub(_credentials(), _record())
    clob_factory = lambda _credentials: _BalanceClient({"balance": "0"})
    coordinator = build_production_funding_coordinator(
        _config(tmp_path),
        core_transport=httpx.MockTransport(core_handler),
        binding_service=binding_service,
        credential_store=credential_store,
        clob_client_factory=clob_factory,
        clock=lambda: NOW,
    )

    assert isinstance(coordinator.venue_accounts, PersonalVenueAccountGateway)
    assert coordinator.venue_accounts.clob_client_factory is clob_factory
    assert isinstance(
        coordinator.risk_assessments, CoreDelegatedRiskAssessmentGateway
    )
    with pytest.raises(PredictionCoreGatewayError):
        coordinator.core_gateway.funding_readiness()
    assert len(requests) == 1
    assert requests[0].url == "http://127.0.0.1:8018/funding/readiness"


def test_lifespan_closes_only_the_app_assembled_core_gateway(
    tmp_path, monkeypatch
) -> None:
    import services.funding_adapter_service.app as funding_app

    class ClosingCoreGateway:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    class DelegatedRiskInput:
        available = True
        health_mode = "delegated_to_core"

    class CoordinatorStub:
        def __init__(self) -> None:
            self.core_gateway = ClosingCoreGateway()
            self.risk_assessments = DelegatedRiskInput()

        @property
        def risk_assessment_available(self) -> bool:
            return True

    assembled = CoordinatorStub()
    monkeypatch.setattr(
        funding_app,
        "build_production_funding_coordinator",
        lambda _config, **_kwargs: assembled,
    )
    app = funding_app.create_app(config=_config(tmp_path / "assembled"))

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert assembled.core_gateway.close_calls == 0

    assert assembled.core_gateway.close_calls == 1

    injected = CoordinatorStub()
    injected_app = funding_app.create_app(
        config=_config(tmp_path / "injected"),
        coordinator=injected,
    )
    with TestClient(injected_app) as client:
        assert client.get("/healthz").status_code == 200

    assert injected.core_gateway.close_calls == 0


def test_personal_venue_gateway_resolves_only_exact_latest_type3_scope() -> None:
    gateway, binding_service, _client = _gateway()

    account = gateway.resolve_active_account(user_id=USER_ID)

    assert account.user_id == USER_ID
    assert account.binding_id == BINDING_ID
    assert account.venue_wallet_address == FUNDER
    assert binding_service.calls == [(USER_ID, "polymarket")]


@pytest.mark.parametrize(
    ("binding", "credentials", "record"),
    (
        (_binding(user_id="telegram_user_2"), _credentials(), _record()),
        (_binding(status="revoked"), _credentials(), _record()),
        (_binding(polymarket_signature_type="2"), _credentials(), _record()),
        (
            _binding(polymarket_deposit_wallet=BRIDGE),
            _credentials(),
            _record(),
        ),
        (_binding(), _credentials(signature_type="0"), _record()),
        (_binding(), _credentials(wallet_address=BRIDGE), _record()),
        (_binding(), _credentials(funder_address=BRIDGE), _record()),
        (_binding(), _credentials(), _record(wallet_address=BRIDGE)),
        (
            _binding(),
            _credentials(),
            _record(api_key_fingerprint="sha256:000000000000"),
        ),
    ),
)
def test_personal_venue_gateway_rejects_binding_or_credential_scope_drift(
    binding,
    credentials,
    record,
) -> None:
    gateway, _binding_service, client = _gateway(
        binding=binding,
        credentials=credentials,
        record=record,
    )

    with pytest.raises(FundingCoordinatorError) as captured:
        gateway.resolve_active_account(user_id=USER_ID)

    assert str(captured.value) == "venue account is unavailable"
    assert "marker" not in str(captured.value)
    assert client.calls == []


def test_buying_power_uses_pinned_collateral_balance_allowance_contract() -> None:
    from py_clob_client_v2.clob_types import AssetType

    gateway, _binding_service, client = _gateway(
        balance_response={"balance": "1234567", "allowances": {"x": "0"}}
    )

    balance = gateway.get_buying_power_atomic(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=FUNDER,
    )

    assert balance == "1234567"
    assert len(client.calls) == 1
    assert client.calls[0].asset_type == AssetType.COLLATERAL
    assert client.calls[0].token_id is None


def test_account_balance_endpoint_returns_user_scoped_polymarket_cash(tmp_path) -> None:
    from services.funding_adapter_service.app import create_app

    gateway, _binding_service, balance_client = _gateway(
        balance_response={"balance": "1234567", "allowances": {}}
    )
    coordinator = SimpleNamespace(venue_accounts=gateway)
    app = create_app(config=_config(tmp_path), coordinator=coordinator)

    with TestClient(app) as client:
        response = client.get(
            f"/polymarket/account-balance?user_id={USER_ID}",
            headers={"Authorization": "Bearer prediction-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "user_id": USER_ID,
        "venue": "polymarket",
        "venue_wallet_address": FUNDER,
        "asset": "USDC",
        "available_amount_atomic": "1234567",
        "available_amount_usdc": "1.234567",
    }
    assert len(balance_client.calls) == 1


@pytest.mark.parametrize(
    "response",
    (
        {},
        {"balance": 1},
        {"balance": 1.0},
        {"balance": "-1"},
        {"balance": "01"},
        {"balance": str(2**256)},
        RuntimeError("api-secret-marker"),
    ),
)
def test_buying_power_fails_closed_for_invalid_or_failed_clob_response(
    response,
) -> None:
    gateway, _binding_service, _client = _gateway(balance_response=response)

    with pytest.raises(FundingCoordinatorError) as captured:
        gateway.get_buying_power_atomic(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            venue_wallet_address=FUNDER,
        )

    assert str(captured.value) == "venue buying power is unavailable"
    assert "marker" not in str(captured.value)


def test_buying_power_rechecks_exact_binding_scope_before_clob_call() -> None:
    gateway, _binding_service, client = _gateway()

    with pytest.raises(FundingCoordinatorError, match="venue account is unavailable"):
        gateway.get_buying_power_atomic(
            user_id=USER_ID,
            binding_id="pm_binding_drifted",
            venue_wallet_address=FUNDER,
        )
    with pytest.raises(FundingCoordinatorError, match="venue account is unavailable"):
        gateway.get_buying_power_atomic(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            venue_wallet_address=BRIDGE,
        )

    assert client.calls == []


def test_core_delegated_risk_input_is_fresh_and_stably_bound_to_exact_context() -> None:
    from services.funding_adapter_service.production_gateways import (
        CoreDelegatedRiskAssessmentGateway,
    )

    observed = [NOW]
    gateway = CoreDelegatedRiskAssessmentGateway(clock=lambda: observed[0])
    context = {
        "operation_id": "pm_funding_operation_1",
        "user_id": USER_ID,
        "bridge_address": BRIDGE,
        "amount_atomic": "1000000",
        "resource": "polymarket:funding:demo",
    }

    first = gateway.assess(**context)
    observed[0] = NOW + timedelta(seconds=1)
    second = gateway.assess(**context)

    assert gateway.available is True
    assert first.assessment_id == second.assessment_id
    assert first.assessed_at == NOW
    assert second.assessed_at == NOW + timedelta(seconds=1)
    assert first.subject_id == USER_ID
    assert first.bridge_address == BRIDGE
    assert first.amount_atomic == "1000000"
    assert first.resource == "polymarket:funding:demo"
    assert (first.risk_level, first.risk_score, first.risk_action) == (
        "low",
        0,
        "approve",
    )

    for changed in (
        {**context, "operation_id": "pm_funding_operation_2"},
        {**context, "user_id": "telegram_user_2"},
        {**context, "bridge_address": FUNDER},
        {**context, "amount_atomic": "1000001"},
        {**context, "resource": "polymarket:funding:other"},
    ):
        assert gateway.assess(**changed).assessment_id != first.assessment_id


def test_core_delegated_risk_input_rejects_invalid_clock_without_leaking() -> None:
    from services.funding_adapter_service.production_gateways import (
        CoreDelegatedRiskAssessmentGateway,
    )

    gateway = CoreDelegatedRiskAssessmentGateway(
        clock=lambda: datetime(2026, 8, 20, 12, 0)
    )
    with pytest.raises(FundingCoordinatorError) as captured:
        gateway.assess(
            operation_id="pm_funding_operation_1",
            user_id=USER_ID,
            bridge_address=BRIDGE,
            amount_atomic="1000000",
            resource="polymarket:funding:demo",
        )

    assert str(captured.value) == "funding risk input is unavailable"
