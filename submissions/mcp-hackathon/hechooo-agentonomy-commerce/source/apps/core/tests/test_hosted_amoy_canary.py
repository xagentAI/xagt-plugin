from __future__ import annotations

import fcntl
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.account_service.service import (
    AMOY_NETWORK,
    AMOY_NETWORK_CONFIG,
    configured_network_configs,
)
from services.funding_service.schemas import (
    HostedExecutionAuthorityRequest,
    HostedPreflightAuthorityRequest,
)
from services.funding_service.service import FundingService
from shared.canonical_assets import (
    AMOY_NETWORK as ASSET_AMOY_NETWORK,
    AMOY_USDC_ADDRESS,
    CanonicalAssetRegistry,
)
from shared.config import AppConfig
from shared.evm_rpc import NetworkRpcTransport
from shared.payment_capability import PaymentCapabilityV1
from services.funding_service import hosted_canary
from services.funding_service.hosted_canary import CanaryError, CoreHttpError, run_canary


AMOY = "eip155:80002"
AMOY_USDC = "0x41e94eb019c0762f9bfcf9fb1e58725bfb0e7582"
PAYEE = "0x2222222222222222222222222222222222222222"
EXECUTOR = "0x3333333333333333333333333333333333333333"
ORIGIN = "https://hosted.example.test"


def _target() -> dict[str, object]:
    return {
        "origin": ORIGIN,
        "server_public_jwk": "{\"kty\":\"EC\",\"crv\":\"P-256\",\"x\":\"x\",\"y\":\"y\"}",
        "executor_contract": EXECUTOR,
    }


def _config(**overrides: object) -> AppConfig:
    values: dict[str, object] = {
        "clink_facilitator_mode": "hosted",
        "clink_hosted_rehearsal_network": AMOY,
        "clink_hosted_rehearsal_rpc_url": "https://rpc-amoy.example.test",
        "clink_hosted_facilitator_chain_targets": {AMOY: _target()},
    }
    values.update(overrides)
    return AppConfig(**values)


def _reservation(*, payee: str = PAYEE, amount: str = "10000", executor: str = EXECUTOR) -> dict:
    return {
        "reservation_id": "reservation-amoy-1",
        "idempotency_key": "idempotency-amoy-1",
        "network": AMOY,
        "token_address": AMOY_USDC,
        "amount_atomic": amount,
        "destination": payee,
        "pay_to": payee,
        "spender_address": executor,
        "purchase_id": "purchase-amoy-1",
        "resource": "https://merchant.example/amoy-canary",
        "state": "reserved",
        "budget_accounting_state": "reserved",
    }


def _settled_reservation() -> dict:
    result = _reservation()
    result.update(
        {
            "state": "settled",
            "budget_accounting_state": "settled",
            "tx_hash": "0x" + "a" * 64,
            "receipt_id": "receipt-amoy-1",
            "hosted_execution_id": "hosted-execution-amoy-1",
            "hosted_watcher_evidence_hash": "0x" + "b" * 64,
            "receipt": {
                "receipt_id": "receipt-amoy-1",
                "tx_hash": "0x" + "a" * 64,
                "metadata": {
                    "hosted_execution_id": "hosted-execution-amoy-1",
                },
            },
        }
    )
    return result


def test_rehearsal_gate_is_explicit_all_or_none_and_hosted_only() -> None:
    with pytest.raises(ValueError, match="HOSTED_REHEARSAL_NETWORK"):
        AppConfig(clink_hosted_rehearsal_network=AMOY)
    with pytest.raises(ValueError, match="HOSTED_REHEARSAL_RPC_URL"):
        AppConfig(clink_hosted_rehearsal_rpc_url="https://rpc-amoy.example.test")
    with pytest.raises(ValueError, match="(?i)hosted"):
        AppConfig(
            clink_hosted_rehearsal_network=AMOY,
            clink_hosted_rehearsal_rpc_url="https://rpc-amoy.example.test",
            clink_facilitator_mode="disabled",
            clink_hosted_facilitator_chain_targets={AMOY: _target()},
        )
    with pytest.raises(ValueError, match="80002"):
        AppConfig(
            clink_hosted_rehearsal_network="eip155:137",
            clink_hosted_rehearsal_rpc_url="https://rpc.example.test",
            clink_facilitator_mode="hosted",
            clink_hosted_facilitator_chain_targets={"eip155:137": _target()},
        )


def test_rehearsal_scope_is_amoy_only_and_default_scope_is_unchanged() -> None:
    rehearsal = _config()
    assert rehearsal.hosted_rehearsal_enabled is True
    assert rehearsal.allowed_evm_networks == (AMOY,)
    assert rehearsal.configured_rpc_urls == {AMOY: "https://rpc-amoy.example.test"}
    assert rehearsal.rpc_url_for(AMOY) == "https://rpc-amoy.example.test"
    with pytest.raises(ValueError):
        rehearsal.rpc_url_for("eip155:137")
    assert rehearsal.x402_payment_network == AMOY
    assert rehearsal.x402_payment_token_address.lower() == AMOY_USDC
    registry = CanonicalAssetRegistry.from_config(rehearsal)
    assert registry.token_address(AMOY) == AMOY_USDC
    with pytest.raises(ValueError):
        registry.asset("eip155:137")

    default = AppConfig(
        polygon_rpc_url="https://polygon.example.test",
        base_rpc_url="https://base.example.test",
    )
    assert default.hosted_rehearsal_enabled is False
    assert default.allowed_evm_networks == ("eip155:137", "eip155:8453")
    assert default.configured_rpc_urls == {
        "eip155:137": "https://polygon.example.test",
        "eip155:8453": "https://base.example.test",
    }
    assert set(CanonicalAssetRegistry.from_config(default).assets) == {
        "eip155:137",
        "eip155:8453",
    }


def test_amoy_asset_rpc_account_and_capability_projections_are_exact() -> None:
    config = _config()
    assert ASSET_AMOY_NETWORK == AMOY
    assert AMOY_USDC_ADDRESS == AMOY_USDC
    assert configured_network_configs(config) == {AMOY: AMOY_NETWORK_CONFIG}
    transport = NetworkRpcTransport(config.configured_rpc_urls)
    assert transport.rpc_urls == {AMOY: "https://rpc-amoy.example.test"}
    capability = PaymentCapabilityV1.model_construct(
        network=AMOY,
        asset_contract=AMOY_USDC,
        executor_contract=EXECUTOR,
    )
    assert capability.network == AMOY


def test_amoy_funding_risk_evidence_requires_polygon_provider_provenance(
    tmp_path: Path,
) -> None:
    service = FundingService(
        config=_config(
            funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'funding.sqlite3'}"
        )
    )
    now = datetime.now(UTC)
    assessment = {
        "provider": "misttrack",
        "provider_endpoint": "v2/risk_score",
        "subject": PAYEE,
        "network": AMOY,
        "asset": "USDC",
        "coin": "USDC-Polygon",
        "decision": "allow",
        "mode": "enforce",
        "enforced": True,
        "mapping_version": "misttrack-policy-v1",
        "hold_score": service.config.risk_hold_score,
        "deny_score": service.config.risk_deny_score,
        "assessed_at": (now - timedelta(seconds=1)).isoformat(),
        "expires_at": (now + timedelta(minutes=4)).isoformat(),
    }
    scope = {"network": AMOY, "asset": AMOY_USDC, "destination": PAYEE}

    with pytest.raises(ValueError, match="missing or not bound"):
        service._require_fresh_misttrack_assessment(
            scope,
            SimpleNamespace(risk_assessment=assessment, event_log=[]),
        )

    assessment["provider_network"] = "eip155:137"
    expires_at = service._require_fresh_misttrack_assessment(
        scope,
        SimpleNamespace(risk_assessment=assessment, event_log=[]),
    )
    assert expires_at > now


def test_hosted_schema_accepts_amoy_but_service_rejects_without_runtime_gate(
    tmp_path: Path,
) -> None:
    digest = "0x" + "1" * 64
    authority = {
        "tenant_id": "tenant-amoy",
        "node_id": "node-amoy",
        "wallet_binding_id": "wallet-amoy",
        "capability_id": "capability-amoy",
        "capability_hash": digest,
        "reservation_id": "reservation-amoy-1",
        "reservation_hash": digest,
        "purchase_id": "purchase-amoy",
        "request_id": "request-amoy",
        "request_hash": digest,
        "request_nonce": digest,
        "idempotency_key": "idempotency-amoy-1",
        "chain_id": AMOY,
        "owner": "0x1111111111111111111111111111111111111111",
        "payee": PAYEE,
        "token": AMOY_USDC,
        "amount_atomic": "10000",
        "executor": EXECUTOR,
        "signer_epoch": 1,
        "deadline": 2,
        "execution_scope_hash": digest,
        "execution_digest": digest,
        "relayer_address": "0x4444444444444444444444444444444444444444",
    }
    assert HostedExecutionAuthorityRequest(**authority).chain_id == AMOY
    preflight = {
        "protocol_version": "clink-hosted-v1",
        "audience": "hosted-facilitator",
        "http_method": "POST",
        "http_path": "/v1/preflight",
        "request_id": "request-amoy",
        "request_hash": digest,
        "idempotency_key": "idempotency-amoy-1",
        "tenant_id": "tenant-amoy",
        "node_id": "node-amoy",
        "wallet_binding_id": "wallet-amoy",
        "payment_capability_version": "clink-payment-capability-v1",
        "payment_capability_id": "capability-amoy",
        "payment_capability_hash": digest,
        "wallet_identity_id": "identity-amoy",
        "wallet_address": "0x1111111111111111111111111111111111111111",
        "spending_grant_id": "grant-amoy",
        "spending_grant_hash": digest,
        "asset_allowance_id": "allowance-amoy",
        "reservation_id": "reservation-amoy-1",
        "reservation_hash": digest,
        "action_id": "action-amoy",
        "policy_decision_id": "policy-amoy",
        "policy_snapshot_hash": digest,
        "risk_evidence_hash": digest,
        "purchase_id": "purchase-amoy",
        "merchant_id": "merchant-amoy",
        "quote_hash": digest,
        "payment_challenge_hash": digest,
        "chain_id": AMOY,
        "asset_contract": AMOY_USDC,
        "amount_atomic": "10000",
        "pay_to": PAYEE,
        "executor_contract": EXECUTOR,
        "execution_scope_hash": digest,
        "request_nonce": digest,
        "issued_at": 1,
        "expires_at": 2,
    }
    assert HostedPreflightAuthorityRequest(**preflight).chain_id == AMOY

    config = AppConfig(
        clink_facilitator_mode="hosted",
        clink_hosted_facilitator_chain_targets={AMOY: _target()},
        funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'funding.sqlite3'}",
    )
    service = FundingService(config=config, hosted_clients={AMOY: object()})
    with pytest.raises(ValueError, match="configured Hosted"):
        service._require_hosted_client(AMOY)


def test_canary_submits_once_then_reconciles_to_strict_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str, dict | None]] = []

    def request(method: str, path: str, payload: dict | None, headers: dict[str, str]) -> dict:
        del headers
        calls.append((method, path, payload))
        if method == "GET":
            return _reservation()
        if path.endswith("/settle"):
            return _reservation()
        assert path.endswith("/reconcile")
        return _settled_reservation()

    journal = tmp_path / "canary.json"
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", "test-token-must-not-be-persisted")
    rc = run_canary(
        core_origin="http://127.0.0.1:8018",
        reservation_id="reservation-amoy-1",
        expected_payee=PAYEE,
        expected_amount_atomic="10000",
        expected_executor=EXECUTOR,
        journal_path=journal,
        submit_once=True,
        request_json=request,
        timeout_seconds=1,
        poll_seconds=0,
        emit=lambda _: None,
    )
    assert rc == 0
    assert [item[0] for item in calls] == ["GET", "POST", "POST"]
    assert calls[1][1].endswith("/settle")
    assert calls[1][2] == {
        "payment_authorization": {
            "scheme": "exact",
            "network": AMOY,
            "asset": AMOY_USDC,
            "amount_atomic": "10000",
            "pay_to": PAYEE,
        }
    }
    assert calls[2][1].endswith("/reconcile")
    assert stat.S_IMODE(journal.stat().st_mode) == 0o600
    journal_text = journal.read_text()
    assert "test-token-must-not-be-persisted" not in journal_text


def test_canary_unknown_outcome_restart_never_posts_settle_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = tmp_path / "canary.json"
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", "secret")
    settle_calls = 0

    def first_request(method: str, path: str, payload: dict | None, headers: dict[str, str]) -> dict:
        nonlocal settle_calls
        del payload, headers
        if method == "GET":
            return _reservation()
        if path.endswith("/settle"):
            settle_calls += 1
            raise TimeoutError("unknown")
        return _reservation()

    clock = iter([0.0, 0.0, 2.0])
    first_rc = run_canary(
        core_origin="http://127.0.0.1:8018",
        reservation_id="reservation-amoy-1",
        expected_payee=PAYEE,
        expected_amount_atomic="10000",
        expected_executor=EXECUTOR,
        journal_path=journal,
        submit_once=True,
        request_json=first_request,
        timeout_seconds=1,
        poll_seconds=0,
        monotonic=lambda: next(clock),
        emit=lambda _: None,
    )
    assert first_rc != 0
    assert settle_calls == 1

    calls: list[tuple[str, str]] = []

    def restart_request(method: str, path: str, payload: dict | None, headers: dict[str, str]) -> dict:
        del payload, headers
        calls.append((method, path))
        if method == "GET":
            return _settled_reservation()
        assert path.endswith("/reconcile")
        return _settled_reservation()

    second_rc = run_canary(
        core_origin="http://127.0.0.1:8018",
        reservation_id="reservation-amoy-1",
        expected_payee=PAYEE,
        expected_amount_atomic="10000",
        expected_executor=EXECUTOR,
        journal_path=journal,
        submit_once=True,
        request_json=restart_request,
        timeout_seconds=1,
        poll_seconds=0,
        emit=lambda _: None,
    )
    assert second_rc == 0
    assert all(not path.endswith("/settle") for _, path in calls)


def test_canary_reconcile_result_must_keep_reservation_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", "secret")
    calls: list[tuple[str, str]] = []

    def request(
        method: str, path: str, payload: dict | None, headers: dict[str, str]
    ) -> dict:
        del payload, headers
        calls.append((method, path))
        if method == "GET":
            return _reservation()
        if path.endswith("/settle"):
            return _reservation()
        mismatched = _settled_reservation()
        mismatched["reservation_id"] = "another-reservation"
        mismatched["idempotency_key"] = "another-idempotency-key"
        return mismatched

    clock = iter([0.0, 0.0, 2.0])
    rc = run_canary(
        core_origin="http://127.0.0.1:8018",
        reservation_id="reservation-amoy-1",
        expected_payee=PAYEE,
        expected_amount_atomic="10000",
        expected_executor=EXECUTOR,
        journal_path=tmp_path / "canary.json",
        submit_once=True,
        request_json=request,
        timeout_seconds=1,
        poll_seconds=0,
        monotonic=lambda: next(clock),
        emit=lambda _: None,
    )

    assert rc != 0
    assert [method for method, _ in calls] == ["GET", "POST", "POST"]
    assert calls[1][1].endswith("/settle")
    assert calls[2][1].endswith("/reconcile")


def test_canary_exact_scope_mismatch_stops_before_settle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []

    def request(method: str, path: str, payload: dict | None, headers: dict[str, str]) -> dict:
        del payload, headers
        calls.append((method, path))
        return _reservation(payee="0x4444444444444444444444444444444444444444")

    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", "secret")
    rc = run_canary(
        core_origin="http://127.0.0.1:8018",
        reservation_id="reservation-amoy-1",
        expected_payee=PAYEE,
        expected_amount_atomic="10000",
        expected_executor=EXECUTOR,
        journal_path=tmp_path / "canary.json",
        submit_once=True,
        request_json=request,
        timeout_seconds=1,
        poll_seconds=0,
        emit=lambda _: None,
    )
    assert rc != 0
    assert all(not path.endswith("/settle") for _, path in calls)


def test_canary_redacts_token_and_requires_all_success_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output: list[str] = []
    token = "super-secret-token"
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", token)

    def request(method: str, path: str, payload: dict | None, headers: dict[str, str]) -> dict:
        del method, path, payload
        assert headers["Authorization"] == f"Bearer {token}"
        result = _settled_reservation()
        result.pop("hosted_watcher_evidence_hash")
        return result

    rc = run_canary(
        core_origin="http://core.example.test",
        reservation_id="reservation-amoy-1",
        expected_payee=PAYEE,
        expected_amount_atomic="10000",
        expected_executor=EXECUTOR,
        journal_path=tmp_path / "canary.json",
        submit_once=False,
        request_json=request,
        timeout_seconds=1,
        poll_seconds=0,
        emit=output.append,
    )
    assert rc != 0
    assert all(token not in line for line in output)


def test_canary_requires_immutable_watcher_evidence_hash_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", "secret")

    def request(
        method: str, path: str, payload: dict | None, headers: dict[str, str]
    ) -> dict:
        del method, path, payload, headers
        result = _settled_reservation()
        result["hosted_watcher_evidence_hash"] = "not-a-content-hash"
        return result

    rc = run_canary(
        core_origin="http://127.0.0.1:8018",
        reservation_id="reservation-amoy-1",
        expected_payee=PAYEE,
        expected_amount_atomic="10000",
        expected_executor=EXECUTOR,
        journal_path=tmp_path / "canary.json",
        request_json=request,
        emit=lambda _: None,
    )

    assert rc != 0


def test_canary_holds_owner_only_exclusive_lock_during_core_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", "secret")
    journal = tmp_path / "canary.json"
    observed_lock = False

    def request(
        method: str, path: str, payload: dict | None, headers: dict[str, str]
    ) -> dict:
        nonlocal observed_lock
        del method, path, payload, headers
        lock_path = journal.with_name(f"{journal.name}.lock")
        assert not lock_path.is_symlink()
        assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
        descriptor = os.open(lock_path, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        observed_lock = True
        return _settled_reservation()

    rc = run_canary(
        core_origin="http://127.0.0.1:8018",
        reservation_id="reservation-amoy-1",
        expected_payee=PAYEE,
        expected_amount_atomic="10000",
        expected_executor=EXECUTOR,
        journal_path=journal,
        request_json=request,
        emit=lambda _: None,
    )

    assert rc == 0
    assert observed_lock is True


def test_canary_fsyncs_journal_parent_directory_before_returning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", "secret")
    fsynced_modes: list[int] = []
    original_fsync = hosted_canary.os.fsync

    def recording_fsync(descriptor: int) -> None:
        fsynced_modes.append(os.fstat(descriptor).st_mode)
        original_fsync(descriptor)

    monkeypatch.setattr(hosted_canary.os, "fsync", recording_fsync)

    rc = run_canary(
        core_origin="http://127.0.0.1:8018",
        reservation_id="reservation-amoy-1",
        expected_payee=PAYEE,
        expected_amount_atomic="10000",
        expected_executor=EXECUTOR,
        journal_path=tmp_path / "canary.json",
        request_json=lambda *_args: _settled_reservation(),
        emit=lambda _: None,
    )

    assert rc == 0
    assert any(stat.S_ISREG(mode) for mode in fsynced_modes)
    assert any(stat.S_ISDIR(mode) for mode in fsynced_modes)


@pytest.mark.parametrize(
    "conflict",
    (
        "receipt_tx_hash",
        "receipt_id",
        "receipt_execution_id",
        "blank_receipt_id",
        "malformed_execution_id",
    ),
)
def test_canary_rejects_conflicting_or_malformed_success_evidence(
    conflict: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", "secret")
    result = _settled_reservation()
    if conflict == "receipt_tx_hash":
        result["receipt"]["tx_hash"] = "0x" + "c" * 64
    elif conflict == "receipt_id":
        result["receipt"]["receipt_id"] = "receipt-amoy-other"
    elif conflict == "receipt_execution_id":
        result["receipt"]["metadata"]["hosted_execution_id"] = (
            "hosted-execution-amoy-other"
        )
    elif conflict == "blank_receipt_id":
        result["receipt_id"] = "   "
    else:
        result["hosted_execution_id"] = "../not-an-opaque-id"

    rc = run_canary(
        core_origin="http://127.0.0.1:8018",
        reservation_id="reservation-amoy-1",
        expected_payee=PAYEE,
        expected_amount_atomic="10000",
        expected_executor=EXECUTOR,
        journal_path=tmp_path / "canary.json",
        request_json=lambda *_args: result,
        emit=lambda _: None,
    )

    assert rc != 0


def test_core_http_client_disables_redirect_capable_urlopen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener_used = False

    class RedirectingResponse:
        def __enter__(self) -> "RedirectingResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _size: int) -> bytes:
            return b"{}"

    class RefusingOpener:
        def open(self, request: object, *, timeout: float) -> object:
            del timeout
            raise hosted_canary.HTTPError(
                getattr(request, "full_url", "https://core.example.test"),
                302,
                "redirect refused",
                {},
                None,
            )

    def build_refusing_opener(*handlers: object) -> RefusingOpener:
        nonlocal opener_used
        assert handlers
        opener_used = True
        return RefusingOpener()

    monkeypatch.setattr(
        hosted_canary,
        "urlopen",
        lambda *_args, **_kwargs: RedirectingResponse(),
        raising=False,
    )
    monkeypatch.setattr(
        hosted_canary,
        "build_opener",
        build_refusing_opener,
        raising=False,
    )

    with pytest.raises(CoreHttpError, match="302"):
        hosted_canary._request_json(
            "GET",
            "https://core.example.test/reservation",
            None,
            {"Authorization": "Bearer must-not-leak"},
            timeout_seconds=1,
        )

    assert opener_used is True
