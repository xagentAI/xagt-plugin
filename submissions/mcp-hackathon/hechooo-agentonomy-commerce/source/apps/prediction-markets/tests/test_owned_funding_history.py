from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from services.funding_adapter_service.app import create_app
from services.funding_adapter_service.coordinator import (
    FundingCoordinatorError,
    PolymarketFundingCoordinator,
    VenueAccount,
)
from services.funding_adapter_service.repository import (
    BridgeRepositoryError,
    SQLiteBridgeRepository,
)
from services.funding_adapter_service.schemas import (
    PolymarketBridgeDeposit,
    PolymarketFundingOperation,
)
from shared.config import AppConfig


USER_ID = "telegram_user_1"
OTHER_USER_ID = "telegram_user_2"
BINDING_ID = "pm_binding_old"
NEW_BINDING_ID = "pm_binding_new"
VENUE_WALLET = "0x1111111111111111111111111111111111111111"
BRIDGE_ADDRESS = "0x2222222222222222222222222222222222222222"
SOURCE_TOKEN = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
DESTINATION_TOKEN = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"
SPENDER_ADDRESS = "0x4444444444444444444444444444444444444444"
OPERATION_ID = "pm_funding_history_1"
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def _operation(*, user_id: str = USER_ID) -> PolymarketFundingOperation:
    return PolymarketFundingOperation.model_validate(
        {
            "operation_id": OPERATION_ID,
            "user_id": user_id,
            "agent_id": "hermes",
            "idempotency_key": "pm_funding_history_idem_1",
            "binding_id": BINDING_ID,
            "venue_wallet_address": VENUE_WALLET,
            "bridge_address": BRIDGE_ADDRESS,
            "source_network": "eip155:137",
            "source_token_address": SOURCE_TOKEN,
            "destination_network": "eip155:137",
            "destination_token_address": DESTINATION_TOKEN,
            "amount_usdc": "1.000000",
            "amount_atomic": "1000000",
            "resource": "polymarket:funding:history",
            "request_hash": "0x" + "a" * 64,
            "quote_hash": "0x" + "b" * 64,
            "wallet_identity_id": "wallet_identity_1",
            "spending_grant_id": "spending_grant_1",
            "asset_allowance_id": "asset_allowance_1",
            "spender_address": SPENDER_ADDRESS,
            "venue_buying_power_before_atomic": "0",
            "risk_assessment_id": "risk_history_1",
            "risk_level": "low",
            "risk_score": 0,
            "risk_action": "approve",
            "risk_assessed_at": NOW,
            "status": "created",
            "created_at": NOW,
            "updated_at": NOW,
            "revision": 0,
        }
    )


class _MutableVenueAccounts:
    def __init__(self) -> None:
        self.binding_id: str | None = BINDING_ID
        self.calls: list[str] = []

    def resolve_active_account(self, *, user_id: str) -> VenueAccount:
        self.calls.append(user_id)
        if self.binding_id is None:
            raise FundingCoordinatorError("venue account is unavailable")
        return VenueAccount(
            user_id=user_id,
            binding_id=self.binding_id,
            venue_wallet_address=VENUE_WALLET,
        )


class _RecordingRepository(SQLiteBridgeRepository):
    def __init__(self, database_path) -> None:
        super().__init__(database_path)
        self.recovery_calls: list[tuple[str, str]] = []

    def get_funding_operation_for_recovery(
        self, *, user_id: str, operation_id: str
    ):
        self.recovery_calls.append((user_id, operation_id))
        return super().get_funding_operation_for_recovery(
            user_id=user_id,
            operation_id=operation_id,
        )


def _fixture(tmp_path):
    config = AppConfig(
        polymarket_bridge_database_path=str(tmp_path / "bridge.sqlite3"),
        prediction_markets_internal_api_token="prediction-token",
    )
    repository = _RecordingRepository(config.polymarket_bridge_database_path)
    repository.save_deposit_target(
        PolymarketBridgeDeposit(
            deposit_id="pm_deposit_history_1",
            user_id=USER_ID,
            binding_id=BINDING_ID,
            venue_wallet_address=VENUE_WALLET,
            bridge_address=BRIDGE_ADDRESS,
            source_network="eip155:137",
            source_token_address=SOURCE_TOKEN,
            destination_network="eip155:137",
            destination_token_address=DESTINATION_TOKEN,
            status="ready",
            created_at=NOW,
        )
    )
    operation = _operation()
    repository.create_funding_operation(operation)
    venue = _MutableVenueAccounts()
    coordinator = PolymarketFundingCoordinator(
        config=config,
        funding_adapter=SimpleNamespace(repository=repository),
        core_gateway=SimpleNamespace(),
        venue_accounts=venue,
    )
    return config, repository, operation, venue, coordinator


def test_history_reads_old_operation_after_binding_change_and_unbind_without_mutation(
    tmp_path,
) -> None:
    config, repository, operation, venue, coordinator = _fixture(tmp_path)

    venue.binding_id = NEW_BINDING_ID
    with pytest.raises(
        FundingCoordinatorError, match="funding operation is unavailable"
    ):
        coordinator.get(user_id=USER_ID, operation_id=operation.operation_id)

    venue.calls.clear()
    history = coordinator.get_history(
        user_id=USER_ID,
        operation_id=operation.operation_id,
    )
    assert history == operation
    assert venue.calls == []
    assert repository.recovery_calls == [(USER_ID, operation.operation_id)]

    venue.binding_id = None
    assert coordinator.get_history(
        user_id=USER_ID,
        operation_id=operation.operation_id,
    ) == operation
    assert venue.calls == []
    assert repository.recovery_calls == [
        (USER_ID, operation.operation_id),
        (USER_ID, operation.operation_id),
    ]

    app = create_app(
        config=config,
        service=SimpleNamespace(repository=repository),
        coordinator=coordinator,
    )
    with TestClient(app) as client:
        response = client.get(
            f"/polymarket/funding-history/{operation.operation_id}",
            params={"user_id": USER_ID},
            headers={"Authorization": "Bearer prediction-token"},
        )
    assert response.status_code == 200
    expected = coordinator.view(operation).model_dump(mode="json")
    expected.pop("opc_installation_id")
    assert response.json() == expected
    assert "opc_installation_id" not in response.json()


@pytest.mark.parametrize(
    ("user_id", "operation_id"),
    [
        (OTHER_USER_ID, OPERATION_ID),
        (USER_ID, "not valid"),
        ("not valid", OPERATION_ID),
        (USER_ID, "missing_history_operation"),
    ],
)
def test_history_is_not_available_outside_exact_canonical_scope(
    tmp_path, user_id, operation_id
) -> None:
    _config, _repository, _operation_value, _venue, coordinator = _fixture(tmp_path)

    with pytest.raises(
        FundingCoordinatorError, match="funding operation is unavailable"
    ) as captured:
        coordinator.get_history(user_id=user_id, operation_id=operation_id)
    assert captured.value.status_code == 404


def test_history_route_requires_internal_bearer_and_does_not_echo_scope(
    tmp_path,
) -> None:
    config, repository, operation, _venue, coordinator = _fixture(tmp_path)
    app = create_app(
        config=config,
        service=SimpleNamespace(repository=repository),
        coordinator=coordinator,
    )
    marker = "history-private-marker"
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            f"/polymarket/funding-history/{marker}",
            params={"user_id": USER_ID},
        )
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid internal bearer token"}
    assert marker not in response.text
    assert operation.operation_id not in response.text


def test_history_repository_failure_is_safe_503(tmp_path) -> None:
    config, repository, operation, _venue, coordinator = _fixture(tmp_path)

    def fail(*, user_id: str, operation_id: str):
        del user_id, operation_id
        raise BridgeRepositoryError("database secret marker")

    repository.get_funding_operation_for_recovery = fail
    app = create_app(
        config=config,
        service=SimpleNamespace(repository=repository),
        coordinator=coordinator,
    )
    with TestClient(app) as client:
        response = client.get(
            f"/polymarket/funding-history/{operation.operation_id}",
            params={"user_id": USER_ID},
            headers={"Authorization": "Bearer prediction-token"},
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "funding operation history lookup failed"}
    assert "database secret marker" not in response.text
