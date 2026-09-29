from __future__ import annotations

from dataclasses import replace

import pytest

from services.funding_service.hosted_wallet_registry import HostedWalletRegistry
from services.funding_service.service import FundingService
from shared.config import AppConfig
from test_hosted_wallet_registry import _record, _write_registry
from test_task_2b_hosted_routing import (
    BASE, POLYGON, NOW, _RecordingHostedClient, _exact_business_authorization,
    _hosted_config, _hosted_settlement_context, _target,
)


def _scoped_context(tmp_path, *, network=BASE, submit_unknown=False):
    client = _RecordingHostedClient(network, submit_unknown=submit_unknown)
    repository, original, reserved, authorization = _hosted_settlement_context(
        tmp_path, network=network, hosted_clients={network: client},
        targets={network: _target("https://hosted.example")},
    )
    record = _record(user_id="user_1", wallet_identity_id="identity_1",
                     tenant_id="tenant_1", node_id="node_1", wallet_binding_id="binding_1")
    path = tmp_path / "hosted-wallets.json"
    _write_registry(path, [record])
    config = replace(original.config, clink_hosted_wallet_credentials_file=str(path))
    selected = []

    def factory(credential, chain, _target):
        selected.append((credential, chain))
        assert credential.user_id == "user_1" and chain == network
        return client

    registry = HostedWalletRegistry(path, chain_targets=config.clink_hosted_facilitator_chain_targets,
                                    client_factory=factory)
    service = FundingService(config=config, policy_service=original.policy_service,
                             hosted_wallet_registry=registry)
    service._utc_now = lambda: NOW.replace(tzinfo=None)
    return repository, service, reserved, client, path, record, selected


def test_registry_configuration_is_optional_strict_and_redacted(monkeypatch, tmp_path):
    assert AppConfig().clink_hosted_wallet_credentials_file == ""
    path = str(tmp_path / "operator-secret-wallets.json")
    monkeypatch.setenv("CLINK_HOSTED_WALLET_CREDENTIALS_FILE", path)
    config = AppConfig.from_env()
    assert config.clink_hosted_wallet_credentials_file == path
    assert path not in repr(config)
    assert config.describe()["clink_hosted_wallet_credentials_file"] == "<redacted>"
    for invalid in ("relative.json", " /absolute.json", "/bad\npath", True):
        with pytest.raises(ValueError, match="CREDENTIALS_FILE"):
            AppConfig(clink_hosted_wallet_credentials_file=invalid)


@pytest.mark.parametrize("network", [BASE, POLYGON])
def test_business_payment_selects_verified_wallet_mapping_not_global_credentials(tmp_path, network):
    _repository, service, row, client, _path, _record_value, selected = _scoped_context(
        tmp_path, network=network)
    # The legacy scalars deliberately disagree. Per-wallet routing must ignore them.
    service.config.clink_hosted_facilitator_tenant_id = "wrong_global_tenant"
    result = service.settle_reservation(row["reservation_id"], _exact_business_authorization(network))
    assert result["state"] == "payment_submitted"
    assert len(client.submit_calls) == 1
    assert selected and all(item[0].tenant_id == "tenant_1" for item in selected)
    assert service.hosted_clients == {}


def test_missing_mapping_never_falls_back_and_does_not_issue_capability(tmp_path):
    _repository, service, row, client, path, _record_value, _selected = _scoped_context(tmp_path)
    _write_registry(path, [])
    with pytest.raises(ValueError, match="hosted wallet"):
        service.settle_reservation(row["reservation_id"], _exact_business_authorization(BASE))
    with service.ledger.transaction() as tx:
        assert tx.payment_capability_for_reservation(row["reservation_id"]) is None
        assert tx.get(row["reservation_id"])["budget_accounting_state"] == "reserved"
    assert client.submit_calls == []


def test_internal_capability_request_cannot_substitute_another_enrollment(tmp_path):
    from services.funding_service.schemas import IssuePaymentCapabilityRequest
    _repository, service, row, client, _path, _record_value, _selected = _scoped_context(tmp_path)
    with pytest.raises(ValueError, match="enrollment identity"):
        service.issue_payment_capability(row["reservation_id"], IssuePaymentCapabilityRequest(
            tenant_id="other_tenant", node_id="other_node", wallet_binding_id="other_binding",
            executor_contract=service.config.clink_hosted_facilitator_chain_targets[BASE]["executor_contract"],
            payment_challenge_hash="0x" + "12" * 32,
        ))
    assert client.submit_calls == []


def test_unknown_payment_recovers_using_sealed_old_mapping_not_new_current_wallet(tmp_path):
    _repository, service, row, client, path, record, selected = _scoped_context(tmp_path, submit_unknown=True)
    request = _exact_business_authorization(BASE)
    first = service.settle_reservation(row["reservation_id"], request)
    assert first["hosted_submission_unknown"] is True
    _write_registry(path, [
        {**record, "state": "recovery_only"},
        _record(user_id="user_1", wallet_identity_id="identity_new", tenant_id="tenant_1",
                node_id="node_new", wallet_binding_id="binding_new"),
    ])
    replay = service.settle_reservation(row["reservation_id"], request)
    assert replay["hosted_submission_unknown"] is True
    assert len(client.submit_calls) == 1 and len(client.lookup_calls) == 1
    assert selected[-1][0].wallet_identity_id == "identity_1"
    assert selected[-1][0].state == "recovery_only"
    with service.ledger.transaction() as tx:
        capability = tx.payment_capability_for_reservation(row["reservation_id"])
    with pytest.raises(ValueError, match="recovery-only"):
        service._require_hosted_client(BASE, capability=capability, for_submission=True)


def test_unreadable_registry_never_uses_cached_client_or_global_fallback(tmp_path):
    _repository, service, row, client, path, _record_value, _selected = _scoped_context(tmp_path)
    path.chmod(0o644)
    with pytest.raises(ValueError, match="hosted wallet"):
        service.settle_reservation(row["reservation_id"], _exact_business_authorization(BASE))
    assert client.submit_calls == []


def test_readiness_is_per_verified_user_and_contains_no_enrollment_secrets(tmp_path):
    repository, service, _row, _client, path, record, _selected = _scoped_context(tmp_path)
    ready = service.get_hosted_wallet_readiness("user_1")
    assert ready["ready"] is True
    assert ready["credential_routing"] == "per_wallet"
    assert service.get_hosted_wallet_readiness("user_2")["reason_code"] == "WALLET_NOT_READY"
    assert record["access_token"] not in str(ready)
    assert "node_1" not in str(ready)
    _write_registry(path, [])
    assert service.get_hosted_wallet_readiness("user_1")["reason_code"] == "HOSTED_ENROLLMENT_REQUIRED"
    _write_registry(path, [record])
    repository.revoke_wallet_identity_and_pause_active_grants("identity_1", NOW)
    assert service.get_hosted_wallet_readiness("user_1")["ready"] is False


def test_scoped_readiness_does_not_require_legacy_global_credentials(tmp_path):
    _repository, service, _row, _client, _path, _record_value, _selected = _scoped_context(tmp_path)
    for field in ("tenant_id", "node_id", "wallet_binding_id", "access_token", "device_private_key"):
        setattr(service.config, "clink_hosted_facilitator_" + field, "")
    result = service.get_funding_readiness()
    assert result["hosted_facilitator_ready"] is True
    assert result["hosted_credential_routing"] == "per_wallet"
    assert result["user_enrollment_required"] is True


def test_scoped_registry_cannot_be_combined_with_injected_global_client(tmp_path):
    config = _hosted_config(tmp_path, clink_hosted_wallet_credentials_file=str(tmp_path / "registry.json"))
    with pytest.raises(ValueError, match="mutually exclusive"):
        FundingService(config=config, hosted_client=_RecordingHostedClient(BASE))


def test_hosted_wallet_readiness_http_requires_internal_auth_and_filters_by_user(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    _repository, service, _row, hosted, _path, record, _selected = _scoped_context(tmp_path)
    config = replace(service.config, clink_internal_api_token="test-internal-readiness-token")
    # The existing app constructs its default service at import. Keep that
    # initialization on the temporary fixture database as well.
    monkeypatch.setenv("CLINK_FUNDING_DATABASE_URL", config.funding_database_url)
    import services.funding_service.app as funding_app

    monkeypatch.setattr(funding_app, "SERVICE", service)
    monkeypatch.setattr(funding_app, "APP_CONFIG", config)
    with TestClient(funding_app.create_app()) as client:
        path = "/funding/hosted-wallet-readiness"
        for headers in ({}, {"Authorization": "Bearer runtime-token"}):
            assert client.get(path, params={"user_id": "user_1"}, headers=headers).status_code == 401
        headers = {"Authorization": "Bearer " + config.clink_internal_api_token}
        ready = client.get(path, params={"user_id": "user_1"}, headers=headers)
        assert ready.status_code == 200 and ready.json()["ready"] is True
        assert record["access_token"] not in ready.text
        assert "wallet_binding_id" not in ready.text
        other = client.get(path, params={"user_id": "user_2"}, headers=headers)
        assert other.status_code == 200 and other.json()["ready"] is False
        invalid = client.get(path, params={"user_id": ""}, headers=headers)
        assert invalid.status_code == 422
    assert hosted.submit_calls == []
