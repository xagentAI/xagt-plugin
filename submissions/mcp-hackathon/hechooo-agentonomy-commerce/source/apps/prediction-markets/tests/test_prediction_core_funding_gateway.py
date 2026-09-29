from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from services.funding_adapter_service.core_gateway import (
    HttpPredictionCoreFundingGateway,
    PredictionCoreGatewayError,
    PredictionFundingContext,
)
from shared.config import AppConfig


USER_ID = "telegram_user_1"
AGENT_ID = "hermes"
OPERATION_ID = "pm_funding_1"
IDEMPOTENCY_KEY = "pm_funding_request_1"
RESOURCE = "polymarket:binding:pm_binding_1"
WALLET_IDENTITY_ID = "wallet_identity_1"
SPENDING_GRANT_ID = "spending_grant_1"
ASSET_ALLOWANCE_ID = "asset_allowance_1"
TOKEN = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
SPENDER = "0x" + "5" * 40
DESTINATION = "0x" + "6" * 40
QUOTE_HASH = "0x" + "7" * 64
ACTION_ID = "action_pm_funding_1"
POLICY_DECISION_ID = "policy_pm_funding_1"
RESERVATION_ID = "reserve_pm_funding_1"
TX_HASH = "0x" + "8" * 64
OUTPUT_HASH = "0x" + "9" * 64
NOW = "2026-08-19T12:00:00Z"
MERCHANT_TRUST = "clink_verified"
OPC_INSTALLATION_ID = "opc_" + "a" * 40


def core_policy_decision_type() -> type[Any]:
    module_path = (
        Path(__file__).resolve().parents[3]
        / "apps"
        / "core"
        / "services"
        / "policy_service"
        / "schemas.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_clink_test_core_policy_schemas",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Core policy schema is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    policy_decision = getattr(module, "PolicyDecision", None)
    if not isinstance(policy_decision, type):
        raise RuntimeError("Core PolicyDecision is unavailable")
    return policy_decision


def test_core_internal_token_is_not_exposed_by_config_repr() -> None:
    config = AppConfig(clink_core_internal_api_token="core-token-marker")

    assert "core-token-marker" not in repr(config)
    assert config.describe()["clink_core_internal_api_token"] is True


def context(**updates: Any) -> PredictionFundingContext:
    values: dict[str, Any] = {
        "user_id": USER_ID,
        "agent_id": AGENT_ID,
        "operation_id": OPERATION_ID,
        "idempotency_key": IDEMPOTENCY_KEY,
        "resource": RESOURCE,
        "wallet_identity_id": WALLET_IDENTITY_ID,
        "spending_grant_id": SPENDING_GRANT_ID,
        "asset_allowance_id": ASSET_ALLOWANCE_ID,
        "amount_usdc": "1",
        "amount_atomic": "1000000",
        "token_address": TOKEN,
        "destination": DESTINATION,
        "quote_hash": QUOTE_HASH,
    }
    values.update(updates)
    return PredictionFundingContext(**values)


def test_funding_context_preserves_integer_usdc_amounts() -> None:
    operation = context(amount_usdc="10", amount_atomic="10000000")

    assert operation.amount_usdc == "10"


def test_funding_context_binds_verified_merchant_trust_into_provenance() -> None:
    assert context().provenance["merchant_trust_tier"] == MERCHANT_TRUST


def test_opc_funding_context_is_bound_to_authorization_action_and_reserve() -> None:
    requests: list[httpx.Request] = []
    opc_context = context(opc_installation_id=OPC_INSTALLATION_ID)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/internal/authorization-resolution":
            return json_response(
                {
                    **authorization_payload(),
                    "opc_installation_id": OPC_INSTALLATION_ID,
                }
            )
        if request.url.path == "/actions":
            return json_response(
                {
                    **action_payload(),
                    "metadata": opc_context.provenance,
                }
            )
        if request.url.path == "/funding/spending-reservations":
            return json_response(reservation_payload())
        raise AssertionError(request.url.path)

    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(handler),
    )
    gateway.resolve_authorization(
        user_id=USER_ID,
        agent_id=AGENT_ID,
        amount_usdc="1",
        amount_atomic="1000000",
        token_address=TOKEN,
        spender_address=SPENDER,
        destination=DESTINATION,
        resource=RESOURCE,
        opc_installation_id=OPC_INSTALLATION_ID,
    )
    gateway.create_action(opc_context)
    gateway.reserve(
        opc_context,
        action_id=ACTION_ID,
        policy_decision_id=POLICY_DECISION_ID,
    )

    posted = {
        request.url.path: json.loads(request.content)
        for request in requests
    }
    assert posted["/internal/authorization-resolution"][
        "opc_installation_id"
    ] == OPC_INSTALLATION_ID
    assert posted["/actions"]["metadata"][
        "opc_installation_id"
    ] == OPC_INSTALLATION_ID
    assert posted["/funding/spending-reservations"][
        "opc_installation_id"
    ] == OPC_INSTALLATION_ID


def test_c_funding_context_does_not_emit_an_opc_installation_constraint() -> None:
    assert "opc_installation_id" not in context().provenance


def funding_readiness_payload() -> dict[str, Any]:
    return {
        "service": "funding_service",
        "status": "ready",
        "settlement_rail": "clink_native_facilitator",
        "live_funding_enabled": True,
        "native_facilitator_enabled": True,
        "native_facilitator_ready": True,
        "relayer_address": SPENDER,
        "universal_payer_ready": True,
        "payer_address": SPENDER,
        "automatic_payment_rail": "clink_payer_proxy",
        "supported_assets": {"eip155:137": TOKEN},
        "mandate_limits_enforced": [
            "per_transaction",
            "rolling_hour",
            "daily",
            "total",
        ],
        "spending_authorization_supported": True,
        "spender_address": SPENDER,
        "spending_mode": "relayer_transfer_from",
        "network": "eip155:137",
        "token": "USDC",
        "token_address": TOKEN,
        "missing": [],
        "warnings": [],
        "next_action": "authorize_spending_cap_or_spend",
    }


def hosted_funding_readiness_payload() -> dict[str, Any]:
    payload = funding_readiness_payload()
    payload.update(
        {
            "settlement_rail": "clink_hosted_executor",
            "native_facilitator_enabled": False,
            "native_facilitator_ready": False,
            "hosted_facilitator_enabled": True,
            "hosted_facilitator_ready": True,
            "relayer_address": None,
            "payer_address": None,
            "automatic_payment_rail": "clink_hosted_executor",
            "spender_address": None,
            "spender_addresses": {"eip155:137": SPENDER},
        }
    )
    return payload


def account_readiness_payload() -> dict[str, Any]:
    return {
        "user_id": USER_ID,
        "wallet_bound": True,
        "wallet_address": "0x" + "1" * 40,
        "wallet_identity_id": WALLET_IDENTITY_ID,
        "spending_grant_active": True,
        "active_spending_mandate": {
            "spending_grant_id": SPENDING_GRANT_ID,
            "agent_id": AGENT_ID,
            "limits_usdc": {
                "per_transaction": "5",
                "rolling_hour": "10",
                "daily": "10",
                "total": "25",
            },
            "remaining_usdc": {
                "rolling_hour": "10",
                "daily": "10",
                "total": "25",
            },
            "product_scopes": ["prediction_markets"],
            "venue_scopes": ["polymarket"],
            "merchant_scopes": [],
            "merchant_trust_scopes": ["clink_verified"],
            "network_scopes": ["eip155:137"],
            "asset_scopes": [TOKEN],
            "notification_mode": "silent_under_limits",
            "expires_at": "2026-09-19T12:00:00Z",
        },
        "chain_allowances": {"eip155:137": True, "eip155:8453": False},
        "ready": False,
    }


def authorization_payload() -> dict[str, Any]:
    return {
        "ready": True,
        "authorization_rail": "native_allowance",
        "reason_code": None,
        "wallet_identity_id": WALLET_IDENTITY_ID,
        "spending_grant_id": SPENDING_GRANT_ID,
        "asset_allowance_id": ASSET_ALLOWANCE_ID,
        "remaining_amount_usdc": "25",
        "remaining_daily_amount_usdc": "10",
        "remaining_hourly_amount_usdc": "10",
        "notification_mode": "silent_under_limits",
        "user_interaction_required": False,
        "interaction_reason_code": None,
        "required_amount_atomic": 1_000_000,
        "observed_allowance_atomic": 25_000_000,
        "next_action": "create_action_and_evaluate_policy",
    }


def action_payload(*, state: str = "created") -> dict[str, Any]:
    return {
        "action_id": ACTION_ID,
        "user_id": USER_ID,
        "agent_id": AGENT_ID,
        "action_type": "funding_transfer",
        "amount_usdc": "1",
        "target": DESTINATION,
        "merchant_id": "polymarket",
        "authorization_id": SPENDING_GRANT_ID,
        "policy_decision_id": (
            POLICY_DECISION_ID if state == "policy_approved" else None
        ),
        "payment_id": None,
        "order_id": None,
        "receipt_id": None,
        "tx_hash": None,
        "approval_id": None,
        "approval_state": None,
        "description": "Fund Polymarket Bridge deposit",
        "state": state,
        "error": None,
        "metadata": context().provenance,
        "created_at": NOW,
        "updated_at": NOW,
        "event_log": [],
    }


def risk_assessment_payload(**updates: Any) -> dict[str, Any]:
    assessment: dict[str, Any] = {
        "provider": "misttrack",
        "provider_endpoint": "v2/risk_score",
        "subject": DESTINATION,
        "network": "eip155:137",
        "asset": "USDC",
        "coin": "USDC-Polygon",
        "score": 7,
        "risk_level": "low",
        "indicators": [],
        "risk_details": [],
        "hacking_event": None,
        "decision": "allow",
        "decision_reasons": ["score:7"],
        "mode": "enforce",
        "enforced": True,
        "mapping_version": "misttrack-policy-v1",
        "hold_score": 31,
        "deny_score": 71,
        "assessed_at": "2026-08-19T11:59:30Z",
        "expires_at": "2026-08-19T12:04:30Z",
        "cache_hit": False,
        "response_sha256": "a" * 64,
    }
    assessment.update(updates)
    return assessment


def unavailable_risk_assessment_payload(**updates: Any) -> dict[str, Any]:
    assessment: dict[str, Any] = {
        "provider": "misttrack",
        "provider_endpoint": "v2/risk_score",
        "subject": DESTINATION,
        "network": "eip155:137",
        "asset": "USDC",
        "decision": "unavailable",
        "mode": "enforce",
        "enforced": True,
        "mapping_version": "misttrack-policy-v1",
        "hold_score": 31,
        "deny_score": 71,
        "error_category": "provider_error",
    }
    assessment.update(updates)
    return assessment


def policy_payload() -> dict[str, Any]:
    return {
        "policy_decision_id": POLICY_DECISION_ID,
        "action_id": ACTION_ID,
        "approved": True,
        "decision": "approved",
        "reason_code": "ALLOW",
        "reasons": [],
        "required_action": None,
        "user_id": USER_ID,
        "agent_id": AGENT_ID,
        "action_type": "funding_transfer",
        "amount_usdc": "1",
        "authorization_id": None,
        "merchant_id": "polymarket",
        "target_address": DESTINATION,
        "chain": "eip155:137",
        "authorization_approved": None,
        "remaining_amount_usdc": None,
        "risk_level": "low",
        "risk_score": 7,
        "risk_action": "approve",
        "risk_assessment": risk_assessment_payload(),
        "evaluated_at": NOW,
        "event_log": [],
        "metadata": context().provenance,
    }


def audit_payload() -> dict[str, Any]:
    return {
        "event_id": "audit_pm_funding_1",
        "event_type": "prediction_market_funding_policy_evaluated",
        "source_service": "clink_prediction_markets",
        "action_id": ACTION_ID,
        "user_id": USER_ID,
        "agent_id": AGENT_ID,
        "policy_decision_id": POLICY_DECISION_ID,
        "payment_id": None,
        "order_id": None,
        "receipt_id": None,
        "tx_hash": None,
        "payload": {
            **context().provenance,
            "merchant_id": "polymarket",
            "venue": "polymarket",
        },
        "created_at": NOW,
    }


def reservation_payload(*, state: str = "spending_reserved") -> dict[str, Any]:
    result = {
        "reservation_id": RESERVATION_ID,
        "purchase_id": OPERATION_ID,
        "idempotency_key": IDEMPOTENCY_KEY,
        "spending_authorization_id": None,
        "authorization_rail": "native_allowance",
        "wallet_identity_id": WALLET_IDENTITY_ID,
        "spending_grant_id": SPENDING_GRANT_ID,
        "asset_allowance_id": ASSET_ALLOWANCE_ID,
        "product": "prediction_markets",
        "user_id": USER_ID,
        "agent_id": AGENT_ID,
        "action_id": ACTION_ID,
        "policy_decision_id": POLICY_DECISION_ID,
        "merchant_id": "polymarket",
        "merchant_trust_tier": MERCHANT_TRUST,
        "quote_hash": QUOTE_HASH,
        "amount_usdc": "1",
        "amount_atomic": "1000000",
        "network": "eip155:137",
        "asset": TOKEN,
        "token_address": TOKEN,
        "token_decimals": 6,
        "token_symbol": "USDC",
        "destination": DESTINATION,
        "resource": RESOURCE,
        "venue": "polymarket",
        "spender_address": SPENDER,
        "authorization_path": "unified_grant",
        "budget_accounting_state": "reserved",
        "usage_date": "2026-08-19",
        "single_submission": True,
        "replacement_forbidden": False,
        "failed_submission_evidence": [],
        "state": state,
        "receipt_id": None,
        "tx_hash": None,
        "created_at": NOW,
    }
    if state == "payment_submitted":
        result.update(
            {
                "payment_authorization_hash": "0x" + "a" * 64,
                "settlement_rail": "clink_allowance",
                "settlement_sender": SPENDER,
                "settlement_nonce": 7,
                "settlement_transaction": {
                    "from": SPENDER,
                    "to": TOKEN,
                    "input": "0xdeadbeef",
                },
                "tx_hash": TX_HASH,
                "receipt_id": "fund_receipt_1",
                "reconciliation_status": "pending",
                "next_action": "reconcile_payment",
                "reconciliation_attempts": 0,
                "reconciliation_started_at": NOW,
                "last_reconciliation_at": None,
                "manual_review_reason": None,
                "manual_review_required_at": None,
                "risk_prebroadcast_state": "ready",
                "risk_prebroadcast_blocked": False,
                "risk_prebroadcast_blocked_at": None,
            }
        )
    return result


def prebroadcast_reservation_payload(
    risk_state: str,
) -> dict[str, Any]:
    result = reservation_payload(state="payment_submitted")
    result.update(
        {
            "settlement_rail": "clink_allowance",
            "risk_prebroadcast_state": risk_state,
            "risk_prebroadcast_blocked": risk_state == "blocked",
            "risk_prebroadcast_blocked_at": NOW if risk_state == "blocked" else None,
        }
    )
    if risk_state == "blocked":
        result.update(
            {
                "reconciliation_status": "manual_review_required",
                "next_action": "operator_reconcile",
                "manual_review_reason": (
                    "live funding risk assessment failed immediately before "
                    "submission"
                ),
                "manual_review_required_at": NOW,
            }
        )
    return result


def failed_reservation_payload(*, state: str = "spending_reserved") -> dict[str, Any]:
    result = reservation_payload(state="payment_submitted")
    result.update(
        {
            "state": state,
            "reconciliation_status": "failed",
            "next_action": "release_reservation",
            "replacement_forbidden": True,
            "last_reconciliation_error": (
                "native transaction submission was definitely rejected: "
                "insufficient_funds"
            ),
            "failed_submission_evidence": [
                {
                    "kind": "definite_rpc_rejection",
                    "reason_code": "insufficient_funds",
                    "tx_hash": TX_HASH,
                    "relayer": SPENDER,
                    "nonce": 7,
                    "recorded_at": NOW,
                }
            ],
        }
    )
    if state == "released":
        result["release_reason"] = "definite_rejection"
    return result


def json_response(payload: Any, *, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers={"Content-Type": "application/json"},
        content=json.dumps(payload, separators=(",", ":")).encode(),
    )


@pytest.mark.parametrize(
    ("assessment", "policy_updates", "expected_approved"),
    [
        (risk_assessment_payload(), {}, True),
        (
            unavailable_risk_assessment_payload(),
            {
                "approved": False,
                "decision": "blocked",
                "reason_code": "RISK_PROVIDER_UNAVAILABLE",
                "required_action": "resolve_risk_assessment",
            },
            False,
        ),
    ],
    ids=("complete", "unavailable"),
)
def test_gateway_accepts_actual_core_policy_decision_serialization(
    assessment: dict[str, Any],
    policy_updates: dict[str, Any],
    expected_approved: bool,
) -> None:
    core_payload = policy_payload()
    core_payload["risk_assessment"] = assessment
    core_payload.update(policy_updates)
    serialized = core_policy_decision_type().model_validate(core_payload).to_dict()

    assert "credit_model_assessment" not in serialized
    assert serialized["risk_assessment"] == assessment

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return json_response(serialized)

    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(handler),
    )

    result = gateway.evaluate_policy(
        context(),
        action_id=ACTION_ID,
        risk_level="low",
        risk_score=7,
        risk_action="approve",
        user_confirmed=True,
        live_mode=True,
    )

    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/policies/evaluate")
    ]
    assert result["approved"] is expected_approved
    assert result["risk_assessment"] == assessment


def test_gateway_uses_unified_spending_grant_without_legacy_authorization_id() -> None:
    requests: list[httpx.Request] = []
    core_policy_response = policy_payload()
    core_policy_response["authorization_id"] = None

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return json_response(core_policy_response)

    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(handler),
    )

    result = gateway.evaluate_policy(
        context(),
        action_id=ACTION_ID,
        risk_level="low",
        risk_score=7,
        risk_action="approve",
        user_confirmed=True,
        live_mode=True,
    )

    assert len(requests) == 1
    posted = json.loads(requests[0].content)
    assert "authorization_id" not in posted
    assert result["policy_decision_id"] == POLICY_DECISION_ID


def test_defaults_are_loopback_and_http_client_disables_redirects_and_proxy_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class RecordingClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "services.funding_adapter_service.core_gateway.httpx.Client",
        RecordingClient,
    )

    gateway = HttpPredictionCoreFundingGateway(token="internal-token")

    assert gateway.action_base_url == "http://127.0.0.1:8016"
    assert gateway.policy_base_url == "http://127.0.0.1:8015"
    assert gateway.audit_base_url == "http://127.0.0.1:8017"
    assert gateway.funding_base_url == "http://127.0.0.1:8018"
    assert gateway.account_base_url == "http://127.0.0.1:8019"
    assert captured["follow_redirects"] is False
    assert captured["trust_env"] is False
    assert captured["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer internal-token",
    }


@pytest.mark.parametrize("token", ["", "   ", "token\nforged", "x" * 513])
def test_internal_bearer_must_be_present_bounded_and_header_safe(token: str) -> None:
    with pytest.raises(ValueError, match="Core internal bearer token is invalid"):
        HttpPredictionCoreFundingGateway(token=token)


@pytest.mark.parametrize(
    "field,value",
    [
        ("action_base_url", "http://user:password@127.0.0.1:8016"),
        ("policy_base_url", "http://127.0.0.1:8015/private"),
        ("audit_base_url", "http://127.0.0.1:8017?token=secret"),
        ("funding_base_url", "file:///tmp/core"),
        ("account_base_url", "http://127.0.0.1:8019/#fragment"),
        ("action_base_url", "http://0.0.0.0:8016"),
        ("policy_base_url", "http://10.0.0.8:8015"),
        ("audit_base_url", "http://core.internal:8017"),
        ("funding_base_url", "https://127.0.0.1:8018"),
    ],
)
def test_core_service_urls_must_be_clean_origins(field: str, value: str) -> None:
    with pytest.raises(ValueError, match="Core service URL is invalid"):
        HttpPredictionCoreFundingGateway(token="internal-token", **{field: value})


def test_explicit_localhost_core_origins_are_allowed() -> None:
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        action_base_url="http://localhost:8016",
        policy_base_url="http://localhost:8015",
        audit_base_url="http://localhost:8017",
        funding_base_url="http://localhost:8018",
        account_base_url="http://localhost:8019",
        transport=httpx.MockTransport(
            lambda _request: json_response(funding_readiness_payload())
        ),
    )

    assert gateway.funding_readiness()["status"] == "ready"


def test_gateway_accepts_hosted_readiness_with_a_polygon_executor() -> None:
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(
            lambda _request: json_response(hosted_funding_readiness_payload())
        ),
    )

    assert gateway.funding_readiness() == {
        "status": "ready",
        "live_funding_enabled": True,
        "native_facilitator_ready": False,
        "hosted_facilitator_ready": True,
        "settlement_rail": "clink_hosted_executor",
        "hosted_facilitator_enabled": True,
        "automatic_payment_rail": "clink_hosted_executor",
        "spender_address": None,
        "spender_addresses": {"eip155:137": SPENDER},
        "supported_assets": {"eip155:137": TOKEN},
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("hosted_facilitator_ready", False),
        ("hosted_facilitator_enabled", False),
        ("automatic_payment_rail", "clink_payer_proxy"),
        ("spender_addresses", {"eip155:8453": SPENDER}),
    ],
)
def test_gateway_rejects_unready_hosted_funding_targets(field, value) -> None:
    payload = hosted_funding_readiness_payload()
    payload[field] = value
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(payload)),
    )

    with pytest.raises(PredictionCoreGatewayError, match="response was invalid"):
        gateway.funding_readiness()


def test_gateway_uses_exact_current_core_contracts_and_sanitizes_responses() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        route = (request.method, request.url.path)
        payloads = {
            ("GET", "/funding/readiness"): funding_readiness_payload(),
            ("GET", "/internal/account-readiness"): account_readiness_payload(),
            ("POST", "/internal/authorization-resolution"): authorization_payload(),
            ("POST", "/actions"): action_payload(),
            ("POST", "/policies/evaluate"): policy_payload(),
            ("POST", f"/actions/{ACTION_ID}/update"): action_payload(
                state="policy_approved"
            ),
            ("POST", "/audit/events"): audit_payload(),
            ("POST", "/funding/spending-reservations"): reservation_payload(),
            (
                "POST",
                f"/funding/spending-reservations/{RESERVATION_ID}/settle",
            ): reservation_payload(state="payment_submitted"),
            (
                "GET",
                f"/funding/spending-reservations/{RESERVATION_ID}",
            ): reservation_payload(state="payment_submitted"),
            (
                "POST",
                f"/funding/spending-reservations/{RESERVATION_ID}/reconcile",
            ): reservation_payload(state="payment_submitted"),
            (
                "POST",
                f"/funding/spending-reservations/{RESERVATION_ID}/finalize",
            ): {
                **reservation_payload(state="payment_submitted"),
                "state": "finalized",
                "delivery_status": "venue_credited",
                "output_hash": OUTPUT_HASH,
                "finalized_at": NOW,
            },
            (
                "POST",
                f"/funding/spending-reservations/{RESERVATION_ID}/release",
            ): {
                **reservation_payload(),
                "state": "released",
                "release_reason": "cancelled_before_broadcast",
            },
        }
        assert route in payloads
        return json_response(payloads[route])

    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(handler),
    )
    operation = context()

    readiness = gateway.funding_readiness()
    account = gateway.account_readiness(USER_ID)
    authorization = gateway.resolve_authorization(
        user_id=USER_ID,
        agent_id=AGENT_ID,
        amount_usdc="1",
        amount_atomic="1000000",
        token_address=TOKEN,
        spender_address=SPENDER,
        destination=DESTINATION,
        resource=RESOURCE,
    )
    action = gateway.create_action(operation)
    policy = gateway.evaluate_policy(
        operation,
        action_id=ACTION_ID,
        risk_level="low",
        risk_score=7,
        risk_action="approve",
        user_confirmed=True,
        live_mode=True,
    )
    updated = gateway.update_action_policy_approved(
        operation,
        action_id=ACTION_ID,
        policy_decision_id=policy["policy_decision_id"],
    )
    audit = gateway.audit_policy_evaluated(
        operation,
        action_id=ACTION_ID,
        policy_decision_id=policy["policy_decision_id"],
    )
    reserved = gateway.reserve(
        operation,
        action_id=ACTION_ID,
        policy_decision_id=policy["policy_decision_id"],
    )
    payment_authorization = {
        "kind": "prediction_market_bridge_transfer",
        "operation_id": OPERATION_ID,
        "reservation_id": RESERVATION_ID,
        "binding_id": "pm_binding_1",
        "bridge_address": DESTINATION,
        "source_token": TOKEN,
        "amount_atomic": "1000000",
    }
    submitted = gateway.settle(
        RESERVATION_ID,
        payment_authorization=payment_authorization,
    )
    read = gateway.reservation(RESERVATION_ID)
    reconciled = gateway.reconcile(RESERVATION_ID)
    finalized = gateway.finalize(
        RESERVATION_ID,
        delivery_status="venue_credited",
        output_hash=OUTPUT_HASH,
    )
    released = gateway.release(
        RESERVATION_ID,
        reason="cancelled_before_broadcast",
    )

    assert readiness == {
        "status": "ready",
        "live_funding_enabled": True,
        "native_facilitator_ready": True,
        "settlement_rail": "clink_native_facilitator",
        "spender_address": SPENDER,
        "supported_assets": {"eip155:137": TOKEN},
    }
    assert account["wallet_identity_id"] == WALLET_IDENTITY_ID
    assert authorization["asset_allowance_id"] == ASSET_ALLOWANCE_ID
    assert action["action_id"] == updated["action_id"] == ACTION_ID
    assert policy["policy_decision_id"] == POLICY_DECISION_ID
    assert policy["risk_assessment"] == risk_assessment_payload()
    assert "credit_model_assessment" not in policy
    assert audit["source_service"] == "clink_prediction_markets"
    assert reserved["reservation_id"] == RESERVATION_ID
    assert submitted["tx_hash"] == read["tx_hash"] == TX_HASH
    assert reconciled["state"] == "payment_submitted"
    assert finalized["state"] == "finalized"
    assert released["state"] == "released"
    assert "settlement_transaction" not in submitted
    assert "payment_authorization_hash" not in submitted

    assert all(
        request.headers["Authorization"] == "Bearer internal-token"
        for request in requests
    )
    assert dict(requests[1].url.params) == {"user_id": USER_ID}

    posted = {
        request.url.path: json.loads(request.content)
        for request in requests
        if request.method == "POST"
    }
    assert posted["/internal/authorization-resolution"] == {
        "user_id": USER_ID,
        "agent_id": AGENT_ID,
        "authorization_rail": "native_allowance",
        "product": "prediction_markets",
        "venue": "polymarket",
        "merchant": "polymarket",
        "merchant_trust_tier": "clink_verified",
        "network": "eip155:137",
        "token_address": TOKEN,
        "spender_address": SPENDER,
        "amount_usdc": "1",
        "destination": DESTINATION,
        "resource": RESOURCE,
    }
    assert posted["/actions"] == {
        "user_id": USER_ID,
        "agent_id": AGENT_ID,
        "action_type": "funding_transfer",
        "amount_usdc": "1",
        "target": DESTINATION,
        "merchant_id": "polymarket",
        "authorization_id": SPENDING_GRANT_ID,
        "description": "Fund Polymarket Bridge deposit",
        "metadata": operation.provenance,
    }
    assert posted["/policies/evaluate"] == {
        "action_id": ACTION_ID,
        "user_id": USER_ID,
        "agent_id": AGENT_ID,
        "action_type": "funding_transfer",
        "amount_usdc": "1",
        "merchant_id": "polymarket",
        "target_address": DESTINATION,
        "chain": "eip155:137",
        "risk_level": "low",
        "risk_score": 7,
        "risk_action": "approve",
        "user_confirmed": True,
        "requires_confirmation": True,
        "live_mode": True,
        "metadata": operation.provenance,
    }
    assert posted[f"/actions/{ACTION_ID}/update"] == {
        "state": "policy_approved",
        "policy_decision_id": POLICY_DECISION_ID,
    }
    assert posted["/audit/events"] == {
        "idempotency_key": f"{IDEMPOTENCY_KEY}:policy-evaluated",
        "event_type": "prediction_market_funding_policy_evaluated",
        "source_service": "clink_prediction_markets",
        "action_id": ACTION_ID,
        "user_id": USER_ID,
        "agent_id": AGENT_ID,
        "policy_decision_id": POLICY_DECISION_ID,
        "payload": {
            **operation.provenance,
            "merchant_id": "polymarket",
            "venue": "polymarket",
        },
    }
    assert posted["/funding/spending-reservations"] == {
        "purchase_id": OPERATION_ID,
        "idempotency_key": IDEMPOTENCY_KEY,
        "authorization_rail": "native_allowance",
        "wallet_identity_id": WALLET_IDENTITY_ID,
        "spending_grant_id": SPENDING_GRANT_ID,
        "asset_allowance_id": ASSET_ALLOWANCE_ID,
        "product": "prediction_markets",
        "action_id": ACTION_ID,
        "policy_decision_id": POLICY_DECISION_ID,
        "merchant_id": "polymarket",
        "merchant_trust_tier": MERCHANT_TRUST,
        "quote_hash": QUOTE_HASH,
        "amount_usdc": "1",
        "amount_atomic": "1000000",
        "network": "eip155:137",
        "asset": TOKEN,
        "destination": DESTINATION,
        "resource": RESOURCE,
        "venue": "polymarket",
    }
    assert posted[
        f"/funding/spending-reservations/{RESERVATION_ID}/settle"
    ] == {"payment_authorization": payment_authorization}
    assert posted[
        f"/funding/spending-reservations/{RESERVATION_ID}/reconcile"
    ] == {}
    assert posted[
        f"/funding/spending-reservations/{RESERVATION_ID}/finalize"
    ] == {"delivery_status": "venue_credited", "output_hash": OUTPUT_HASH}
    assert posted[
        f"/funding/spending-reservations/{RESERVATION_ID}/release"
    ] == {"reason": "cancelled_before_broadcast"}


@pytest.mark.parametrize("risk_state", ["pending", "ready", "blocked"])
def test_gateway_accepts_core_prebroadcast_settlement_contract(
    risk_state: str,
) -> None:
    payload = prebroadcast_reservation_payload(risk_state)
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(payload)),
    )

    result = gateway.settle(
        RESERVATION_ID,
        payment_authorization={
            "kind": "prediction_market_bridge_transfer",
            "operation_id": OPERATION_ID,
            "reservation_id": RESERVATION_ID,
            "binding_id": "pm_binding_1",
            "bridge_address": DESTINATION,
            "source_token": TOKEN,
            "amount_atomic": "1000000",
        },
    )

    assert result["risk_prebroadcast_state"] == risk_state
    assert result["risk_prebroadcast_blocked"] is (risk_state == "blocked")
    assert result["risk_prebroadcast_blocked_at"] == (
        NOW if risk_state == "blocked" else None
    )


def test_gateway_accepts_reserved_stage_without_prebroadcast_fields() -> None:
    payload = reservation_payload()
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(payload)),
    )

    result = gateway.reserve(
        context(),
        action_id=ACTION_ID,
        policy_decision_id=POLICY_DECISION_ID,
    )

    assert result["state"] == "spending_reserved"
    assert not any(key.startswith("risk_prebroadcast_") for key in result)


def test_gateway_rejects_native_submitted_stage_without_prebroadcast_fields() -> None:
    payload = reservation_payload(state="payment_submitted")
    payload["settlement_rail"] = "clink_allowance"
    for field in (
        "risk_prebroadcast_state",
        "risk_prebroadcast_blocked",
        "risk_prebroadcast_blocked_at",
    ):
        payload.pop(field)
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(payload)),
    )

    with pytest.raises(
        PredictionCoreGatewayError,
        match="^Core response was invalid$",
    ):
        gateway.reservation(RESERVATION_ID)


@pytest.mark.parametrize(
    "tamper",
    [
        "partial-state",
        "partial-blocked",
        "partial-blocked-at",
        "unknown-state",
        "blocked-not-bool",
        "pending-marked-blocked",
        "ready-with-blocked-at",
        "ready-with-manual-metadata",
        "ready-retryable",
        "blocked-without-time",
        "blocked-noncanonical-time",
        "blocked-wrong-state",
        "blocked-retryable",
        "blocked-retry-action",
        "blocked-manual-time-after-block",
    ],
)
def test_gateway_rejects_incoherent_prebroadcast_settlement_contract(
    tamper: str,
) -> None:
    payload = prebroadcast_reservation_payload("blocked")
    if tamper == "partial-state":
        payload.pop("risk_prebroadcast_state")
    elif tamper == "partial-blocked":
        payload.pop("risk_prebroadcast_blocked")
    elif tamper == "partial-blocked-at":
        payload.pop("risk_prebroadcast_blocked_at")
    elif tamper == "unknown-state":
        payload["risk_prebroadcast_state"] = "approved"
    elif tamper == "blocked-not-bool":
        payload["risk_prebroadcast_blocked"] = 1
    elif tamper == "pending-marked-blocked":
        payload.update(
            {
                "risk_prebroadcast_state": "pending",
                "risk_prebroadcast_blocked": True,
            }
        )
    elif tamper == "ready-with-blocked-at":
        payload.update(
            {
                "risk_prebroadcast_state": "ready",
                "risk_prebroadcast_blocked": False,
            }
        )
    elif tamper == "ready-with-manual-metadata":
        payload.update(
            {
                "risk_prebroadcast_state": "ready",
                "risk_prebroadcast_blocked": False,
                "risk_prebroadcast_blocked_at": None,
                "reconciliation_status": "pending",
                "next_action": "reconcile_payment",
            }
        )
    elif tamper == "ready-retryable":
        payload.update(
            {
                "risk_prebroadcast_state": "ready",
                "risk_prebroadcast_blocked": False,
                "risk_prebroadcast_blocked_at": None,
                "reconciliation_status": "retryable",
                "next_action": "retry_settlement",
                "manual_review_reason": None,
                "manual_review_required_at": None,
            }
        )
    elif tamper == "blocked-without-time":
        payload["risk_prebroadcast_blocked_at"] = None
    elif tamper == "blocked-noncanonical-time":
        payload["risk_prebroadcast_blocked_at"] = "2026-08-19T12:00:00+00:00"
    elif tamper == "blocked-wrong-state":
        payload["state"] = "settled"
    elif tamper == "blocked-retryable":
        payload["reconciliation_status"] = "retryable"
    elif tamper == "blocked-retry-action":
        payload["next_action"] = "retry_settlement"
    else:
        payload["manual_review_required_at"] = "2026-08-19T12:00:01Z"
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(payload)),
    )

    with pytest.raises(
        PredictionCoreGatewayError,
        match="^Core response was invalid$",
    ):
        gateway.reservation(RESERVATION_ID)


@pytest.mark.parametrize("state", ["spending_reserved", "released"])
def test_gateway_accepts_safe_single_submission_failure_evidence(state: str) -> None:
    payload = failed_reservation_payload(state=state)
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(payload)),
    )

    result = gateway.reservation(RESERVATION_ID)

    assert result["state"] == state
    assert result["replacement_forbidden"] is True
    assert result["failed_submission_evidence"] == payload[
        "failed_submission_evidence"
    ]
    assert "settlement_transaction" not in result
    assert "payment_authorization_hash" not in result


@pytest.mark.parametrize(
    "tamper",
    [
        "mapping",
        "string",
        "integer",
        "none",
        "empty",
        "second_evidence",
        "kind",
        "reason_code",
        "recorded_at",
        "state",
        "reconciliation_status",
        "next_action",
        "replacement_forbidden",
        "tx_hash",
        "relayer",
        "nonce",
    ],
)
def test_gateway_rejects_unbound_single_submission_failure_evidence(
    tamper: str,
) -> None:
    payload = failed_reservation_payload()
    evidence = dict(payload["failed_submission_evidence"][0])
    if tamper == "mapping":
        payload["failed_submission_evidence"] = {}
    elif tamper == "string":
        payload["failed_submission_evidence"] = ""
    elif tamper == "integer":
        payload["failed_submission_evidence"] = 0
    elif tamper == "none":
        payload["failed_submission_evidence"] = None
    elif tamper == "empty":
        payload["failed_submission_evidence"] = []
    elif tamper == "second_evidence":
        payload["failed_submission_evidence"] = [evidence, dict(evidence)]
    elif tamper == "kind":
        payload["failed_submission_evidence"] = [
            {**evidence, "kind": "operator_note"}
        ]
    elif tamper == "reason_code":
        payload["failed_submission_evidence"] = [
            {**evidence, "reason_code": "unknown_reason"}
        ]
    elif tamper == "recorded_at":
        payload["failed_submission_evidence"] = [
            {**evidence, "recorded_at": "2026-08-19T12:00:00+00:00"}
        ]
    elif tamper == "state":
        payload["state"] = "payment_submitted"
    elif tamper == "reconciliation_status":
        payload["reconciliation_status"] = "pending"
    elif tamper == "next_action":
        payload["next_action"] = "retry_settlement"
    elif tamper == "replacement_forbidden":
        payload["replacement_forbidden"] = False
    elif tamper == "tx_hash":
        payload["failed_submission_evidence"] = [
            {**evidence, "tx_hash": "0x" + "4" * 64}
        ]
    elif tamper == "relayer":
        payload["failed_submission_evidence"] = [
            {**evidence, "relayer": "0x" + "4" * 40}
        ]
    else:
        payload["failed_submission_evidence"] = [{**evidence, "nonce": 99}]
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(payload)),
    )

    with pytest.raises(
        PredictionCoreGatewayError,
        match="^Core response was invalid$",
    ):
        gateway.reservation(RESERVATION_ID)


@pytest.mark.parametrize(
    "tamper",
    [
        "partial_hash",
        "partial_sender",
        "partial_nonce",
        "partial_projection",
        "reserved_complete_without_failure",
        "released_complete_without_failure",
        "payment_without_canonical",
        "settled_without_canonical",
        "finalized_without_canonical",
    ],
)
def test_gateway_rejects_invalid_single_submission_state_matrix(tamper: str) -> None:
    payload = reservation_payload(state="payment_submitted")
    if tamper == "partial_hash":
        payload["tx_hash"] = None
    elif tamper == "partial_sender":
        payload["settlement_sender"] = None
    elif tamper == "partial_nonce":
        payload["settlement_nonce"] = None
    elif tamper == "partial_projection":
        payload["settlement_transaction"] = None
    elif tamper == "reserved_complete_without_failure":
        payload["state"] = "spending_reserved"
    elif tamper == "released_complete_without_failure":
        payload["state"] = "released"
        payload["release_reason"] = "forged_release"
    else:
        payload["state"] = {
            "payment_without_canonical": "payment_submitted",
            "settled_without_canonical": "settled",
            "finalized_without_canonical": "finalized",
        }[tamper]
        payload.update(
            {
                "tx_hash": None,
                "settlement_sender": None,
                "settlement_nonce": None,
                "settlement_transaction": None,
            }
        )
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(payload)),
    )

    with pytest.raises(
        PredictionCoreGatewayError,
        match="^Core response was invalid$",
    ):
        gateway.reservation(RESERVATION_ID)


def test_authorization_failure_preserves_only_a_safe_reason_code() -> None:
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(
            lambda _request: json_response(
                {
                    "ready": False,
                    "reason_code": "ASSET_ALLOWANCE_REQUIRED",
                    "next_action": "configure_wallet_authorization",
                }
            )
        ),
    )

    result = gateway.resolve_authorization(
        user_id=USER_ID,
        agent_id=AGENT_ID,
        amount_usdc="1",
        amount_atomic="1000000",
        token_address=TOKEN,
        spender_address=SPENDER,
        destination=DESTINATION,
        resource=RESOURCE,
    )

    assert result == {
        "ready": False,
        "reason_code": "ASSET_ALLOWANCE_REQUIRED",
        "next_action": "configure_wallet_authorization",
    }


def test_http_failure_is_redacted_but_preserves_structured_reason_code() -> None:
    secret_markers = (
        "internal-token",
        "https://polygon-rpc.example/secret",
        "0x" + "f" * 64,
    )

    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(
            lambda _request: json_response(
                {
                    "detail": {
                        "code": "TRANSACTION_STATUS_UNKNOWN",
                        "message": " ".join(secret_markers),
                    }
                },
                status_code=409,
            )
        ),
    )

    with pytest.raises(PredictionCoreGatewayError) as exc_info:
        gateway.settle(
            RESERVATION_ID,
            payment_authorization={
                "kind": "prediction_market_bridge_transfer",
                "operation_id": OPERATION_ID,
                "reservation_id": RESERVATION_ID,
                "binding_id": "pm_binding_1",
                "bridge_address": DESTINATION,
                "source_token": TOKEN,
                "amount_atomic": "1000000",
            },
        )

    error = exc_info.value
    assert str(error) == "Core request failed"
    assert error.status_code == 409
    assert error.reason_code == "TRANSACTION_STATUS_UNKNOWN"
    rendered = repr(error)
    assert all(marker not in rendered for marker in secret_markers)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            200,
            headers={"Content-Type": "text/plain"},
            content=b"not json",
        ),
        httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b'{"user_id":"telegram_user_1","user_id":"forged"}',
        ),
        json_response({**account_readiness_payload(), "rpc_url": "https://secret"}),
        httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b"{" + b'\"padding\":\"' + b"x" * 70_000 + b'\"}',
        ),
    ],
)
def test_response_format_size_and_allowlist_fail_closed(
    response: httpx.Response,
) -> None:
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: response),
    )

    with pytest.raises(
        PredictionCoreGatewayError,
        match="^Core response was invalid$",
    ):
        gateway.account_readiness(USER_ID)


def test_redirect_is_not_followed_and_mutation_is_sent_once() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            307,
            headers={"Location": "https://attacker.example/collect?token=secret"},
        )

    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PredictionCoreGatewayError, match="^Core request failed$"):
        gateway.create_action(context())

    assert calls == 1


def test_transport_failure_never_retries_a_mutation() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("upstream marker", request=request)

    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PredictionCoreGatewayError) as exc_info:
        gateway.reserve(
            context(),
            action_id=ACTION_ID,
            policy_decision_id=POLICY_DECISION_ID,
        )

    assert calls == 1
    assert str(exc_info.value) == "Core request failed"
    assert "upstream marker" not in repr(exc_info.value)


@pytest.mark.parametrize(
    "updates",
    [
        {"amount_usdc": 1.0},
        {"amount_usdc": "1.000001", "amount_atomic": "1000000"},
        {"amount_atomic": str(2**256)},
        {"destination": "https://wallet.example/secret"},
        {"resource": "polymarket:binding:pm_binding_1\nforged"},
        {"quote_hash": "0x1234"},
    ],
)
def test_funding_context_rejects_ambiguous_or_drifting_values(
    updates: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        context(**updates)


def test_path_identifier_is_validated_before_any_request() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response({})

    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError, match="Core resource identifier is invalid"):
        gateway.reservation("../../other-user")

    assert calls == 0


def test_resolution_rejects_core_reference_or_amount_drift() -> None:
    payload = authorization_payload()
    payload["required_amount_atomic"] = 999_999
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(payload)),
    )

    with pytest.raises(
        PredictionCoreGatewayError,
        match="^Core response was invalid$",
    ):
        gateway.resolve_authorization(
            user_id=USER_ID,
            agent_id=AGENT_ID,
            amount_usdc="1",
            amount_atomic="1000000",
            token_address=TOKEN,
            spender_address=SPENDER,
            destination=DESTINATION,
            resource=RESOURCE,
        )


def test_policy_normalizes_current_critical_manual_review_risk_contract() -> None:
    posted: dict[str, Any] = {}
    response = policy_payload()
    response.update(
        {
            "approved": False,
            "decision": "blocked",
            "reason_code": "RISK_BLOCKED",
            "required_action": "choose_lower_risk_target",
            "risk_level": "critical",
            "risk_score": 91,
            "risk_action": "manual_review",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        posted.update(json.loads(request.content))
        return json_response(response)

    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(handler),
    )

    result = gateway.evaluate_policy(
        context(),
        action_id=ACTION_ID,
        risk_level=" CRITICAL ",
        risk_score=91,
        risk_action=" MANUAL_REVIEW ",
        user_confirmed=True,
        live_mode=True,
    )

    assert posted["risk_level"] == "critical"
    assert posted["risk_action"] == "manual_review"
    assert result["decision"] == "blocked"
    assert result["required_action"] == "choose_lower_risk_target"
    assert result["risk_level"] == "critical"
    assert result["risk_score"] == 91
    assert result["risk_action"] == "manual_review"
    assert result["risk_assessment"] == risk_assessment_payload()


def test_policy_response_rejects_legacy_assessment_without_canonical_risk() -> None:
    response = policy_payload()
    response.pop("risk_assessment")
    response["credit_model_assessment"] = {
        "decision": "allow",
        "mode": "enforce",
        "enforced": True,
    }
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(response)),
    )

    with pytest.raises(
        PredictionCoreGatewayError,
        match="^Core response was invalid$",
    ):
        gateway.evaluate_policy(
            context(),
            action_id=ACTION_ID,
            risk_level="low",
            risk_score=7,
            risk_action="approve",
            user_confirmed=True,
            live_mode=True,
        )


def test_policy_response_accepts_canonical_unavailable_risk_assessment() -> None:
    response = policy_payload()
    response.update(
        {
            "approved": False,
            "decision": "blocked",
            "reason_code": "RISK_PROVIDER_UNAVAILABLE",
            "required_action": "resolve_risk_assessment",
            "risk_assessment": unavailable_risk_assessment_payload(),
        }
    )
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(response)),
    )

    result = gateway.evaluate_policy(
        context(),
        action_id=ACTION_ID,
        risk_level="low",
        risk_score=7,
        risk_action="approve",
        user_confirmed=True,
        live_mode=True,
    )

    assert result["approved"] is False
    assert result["risk_assessment"] == unavailable_risk_assessment_payload()


def test_policy_response_accepts_shadow_assessment_without_reauthorizing_it() -> None:
    assessment = risk_assessment_payload(
        mode="shadow",
        enforced=False,
        cache_hit=True,
        indicators=["provider supplied indicator"],
        risk_details=[
            {
                "risk_type": "provider_supplied_type",
                "exposure_type": "indirect",
                "value": "1",
            }
        ],
        hacking_event="provider supplied incident text",
    )
    response = policy_payload()
    response["risk_assessment"] = assessment
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(response)),
    )

    result = gateway.evaluate_policy(
        context(),
        action_id=ACTION_ID,
        risk_level="low",
        risk_score=7,
        risk_action="approve",
        user_confirmed=True,
        live_mode=True,
    )

    assert result["risk_assessment"] == assessment


@pytest.mark.parametrize(
    "changes",
    [
        {"decision": "review"},
        {"decision": ["approved"]},
        {"required_action": "https://attacker.example/action"},
        {"risk_level": "critical"},
        {"risk_score": 8},
        {"risk_score": 101},
        {"risk_action": "manual_review"},
    ],
)
def test_policy_response_rejects_decision_and_risk_contract_drift(
    changes: dict[str, Any],
) -> None:
    response = policy_payload()
    response.update(changes)
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(response)),
    )

    with pytest.raises(
        PredictionCoreGatewayError,
        match="^Core response was invalid$",
    ):
        gateway.evaluate_policy(
            context(),
            action_id=ACTION_ID,
            risk_level="low",
            risk_score=7,
            risk_action="approve",
            user_confirmed=True,
            live_mode=True,
        )


@pytest.mark.parametrize(
    "assessment",
    [
        risk_assessment_payload(provider="mistrack"),
        risk_assessment_payload(provider_endpoint="v1/risk_score"),
        risk_assessment_payload(subject="0x" + "9" * 40),
        risk_assessment_payload(subject="0X" + "6" * 40),
        risk_assessment_payload(network="eip155:8453"),
        risk_assessment_payload(asset="ETH"),
        risk_assessment_payload(coin="USDC-Base"),
        risk_assessment_payload(decision="target_required"),
        risk_assessment_payload(mode="observe"),
        risk_assessment_payload(mode=["enforce"]),
        risk_assessment_payload(enforced=False),
        risk_assessment_payload(mapping_version="misttrack-policy-v0"),
        risk_assessment_payload(hold_score=True),
        risk_assessment_payload(hold_score=0),
        risk_assessment_payload(hold_score=71),
        risk_assessment_payload(score=True),
        risk_assessment_payload(score=101),
        risk_assessment_payload(risk_level="critical"),
        risk_assessment_payload(indicators={}),
        risk_assessment_payload(indicators=[1]),
        risk_assessment_payload(risk_details=[{"risk_type": 1}]),
        risk_assessment_payload(risk_details=[{"API-Key": "secret"}]),
        risk_assessment_payload(hacking_event={"secret": "value"}),
        risk_assessment_payload(decision_reasons="score:7"),
        risk_assessment_payload(decision_reasons=[]),
        risk_assessment_payload(assessed_at="2026-08-19T11:59:30+00:00"),
        risk_assessment_payload(expires_at="2026-08-19T11:59:30Z"),
        risk_assessment_payload(cache_hit=0),
        risk_assessment_payload(response_sha256="g" * 64),
        {
            key: value
            for key, value in risk_assessment_payload().items()
            if key != "coin"
        },
        {**risk_assessment_payload(), "error_category": "provider_error"},
        {**risk_assessment_payload(), "api_key": "must-not-cross-boundary"},
    ],
)
def test_policy_response_rejects_malformed_canonical_risk_assessment(
    assessment: dict[str, Any],
) -> None:
    response = policy_payload()
    response["risk_assessment"] = assessment
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(response)),
    )

    with pytest.raises(
        PredictionCoreGatewayError,
        match="^Core response was invalid$",
    ):
        gateway.evaluate_policy(
            context(),
            action_id=ACTION_ID,
            risk_level="low",
            risk_score=7,
            risk_action="approve",
            user_confirmed=True,
            live_mode=True,
        )


@pytest.mark.parametrize(
    "assessment",
    [
        unavailable_risk_assessment_payload(decision="allow"),
        unavailable_risk_assessment_payload(error_category="upstream secret"),
        {
            key: value
            for key, value in unavailable_risk_assessment_payload().items()
            if key != "error_category"
        },
        {**unavailable_risk_assessment_payload(), "coin": "USDC-Polygon"},
    ],
)
def test_policy_response_rejects_malformed_unavailable_risk_assessment(
    assessment: dict[str, Any],
) -> None:
    response = policy_payload()
    response["risk_assessment"] = assessment
    gateway = HttpPredictionCoreFundingGateway(
        token="internal-token",
        transport=httpx.MockTransport(lambda _request: json_response(response)),
    )

    with pytest.raises(
        PredictionCoreGatewayError,
        match="^Core response was invalid$",
    ):
        gateway.evaluate_policy(
            context(),
            action_id=ACTION_ID,
            risk_level="low",
            risk_score=7,
            risk_action="approve",
            user_confirmed=True,
            live_mode=True,
        )
