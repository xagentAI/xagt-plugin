from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text

from services.action_service.schemas import (
    CreateActionIntentRequest,
    RequestActionApprovalRequest,
    SubmitActionApprovalRequest,
)
from services.action_service.service import ActionService
from services.action_policy_repository import ActionPolicyRepository
from services.policy_service.schemas import EvaluateActionPolicyRequest
from services.policy_service.service import PolicyService
from shared.config import AppConfig


DESTINATION = "0x" + "1" * 40
RAW_SIGNATURE = "0x" + "ab" * 65


def test_actions_are_shared_in_the_authoritative_database_and_redact_signatures(
    tmp_path,
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    config = AppConfig(funding_database_url=database_url)
    actions = ActionService(config=config, storage_file=tmp_path / "legacy-actions.jsonl")
    metadata = {"destination": DESTINATION, "network": "eip155:137"}
    intent = actions.create_intent(
        CreateActionIntentRequest(
            user_id="user_1",
            agent_id="hermes",
            action_type="marketplace_purchase",
            amount_usdc="1",
            metadata=metadata,
        )
    )
    approval = actions.request_approval(
        intent.action_id, RequestActionApprovalRequest(message="Approve payment")
    )

    response = ActionService(config=config).submit_approval(
        approval.approval_id,
        SubmitActionApprovalRequest(
            decision="approved",
            approved_by="user_1",
            signature=RAW_SIGNATURE,
        ),
    )

    stored_intent = ActionService(config=config).get_intent(intent.action_id)
    assert stored_intent.state == "user_approved"
    assert stored_intent.approval_state == "approved"
    assert stored_intent.metadata == metadata
    assert response.proof_hash.startswith("0x")
    assert not hasattr(response, "signature")
    assert not (tmp_path / "legacy-actions.jsonl").exists()

    engine = create_engine(database_url)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT proof_hash, payload FROM action_approvals WHERE approval_id = :id"),
            {"id": approval.approval_id},
        ).one()
    assert row.proof_hash == response.proof_hash
    assert RAW_SIGNATURE not in str(row.payload)
    with pytest.raises(ValueError, match="already submitted"):
        actions.submit_approval(
            approval.approval_id,
            SubmitActionApprovalRequest(
                decision="rejected",
                approved_by="user_1",
                signature=RAW_SIGNATURE,
            ),
        )


def test_action_approval_rejects_raw_signature_material_in_metadata(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    config = AppConfig(funding_database_url=database_url)
    actions = ActionService(config=config)
    intent = actions.create_intent(
        CreateActionIntentRequest(
            user_id="user_1",
            agent_id="hermes",
            action_type="service_purchase",
            amount_usdc="1",
        )
    )
    approval = actions.request_approval(
        intent.action_id, RequestActionApprovalRequest(message="Approve payment")
    )

    with pytest.raises(ValueError, match="sensitive signature material"):
        actions.submit_approval(
            approval.approval_id,
            SubmitActionApprovalRequest(
                decision="approved",
                approved_by="user_1",
                signature=RAW_SIGNATURE,
                metadata={"nested": {"signature": RAW_SIGNATURE}},
            ),
        )

    stored = actions.get_approval(approval.approval_id)
    assert stored.state == "requested"
    assert stored.proof_hash is None
    assert RAW_SIGNATURE not in str(stored.to_dict())


def test_action_approval_request_rejects_signature_shaped_metadata(tmp_path):
    config = AppConfig(
        funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    )
    actions = ActionService(config=config)
    intent = actions.create_intent(
        CreateActionIntentRequest(
            user_id="user_1",
            agent_id="hermes",
            action_type="service_purchase",
            amount_usdc="1",
        )
    )

    with pytest.raises(ValueError, match="sensitive signature material"):
        actions.request_approval(
            intent.action_id,
            RequestActionApprovalRequest(
                message="Approve payment",
                metadata={"evidence": RAW_SIGNATURE},
            ),
        )


def test_legacy_jsonl_is_imported_once_and_raw_signatures_are_removed(tmp_path):
    from scripts.import_legacy_action_policy_jsonl import (
        import_legacy_action_policy_state,
    )

    actions_file = tmp_path / "actions.jsonl"
    approvals_file = tmp_path / "approvals.jsonl"
    policies_file = tmp_path / "policies.jsonl"
    action = {
        "action_id": "act_legacy",
        "user_id": "user_1",
        "agent_id": "hermes",
        "action_type": "service_purchase",
        "amount_usdc": "1",
        "state": "created",
        "created_at": "2026-07-16T00:00:00Z",
        "updated_at": "2026-07-16T00:00:00Z",
        "event_log": [],
    }
    latest_action = {
        **action,
        "state": "policy_approved",
        "policy_decision_id": "policy_legacy",
        "updated_at": "2026-07-16T00:01:00Z",
    }
    approval = {
        "approval_id": "appr_legacy",
        "action_id": "act_legacy",
        "user_id": "user_1",
        "agent_id": "hermes",
        "approval_type": "human_confirmation",
        "state": "approved",
        "approved_by": "user_1",
        "signature": RAW_SIGNATURE,
        "metadata": {"evidence": RAW_SIGNATURE},
        "created_at": "2026-07-16T00:00:00Z",
        "expires_at": "2026-07-16T00:15:00Z",
        "responded_at": "2026-07-16T00:01:00Z",
        "event_log": [],
    }
    policy = {
        "policy_decision_id": "policy_legacy",
        "action_id": "act_legacy",
        "approved": True,
        "decision": "approved",
        "reason_code": "APPROVED",
        "reasons": ["legacy decision"],
        "user_id": "user_1",
        "agent_id": "hermes",
        "action_type": "service_purchase",
        "amount_usdc": "1",
        "chain": "base",
        "evaluated_at": "2026-07-16T00:01:00Z",
        "event_log": [],
    }
    actions_file.write_text(
        "\n".join(json.dumps(record) for record in (action, latest_action)) + "\n"
    )
    approvals_file.write_text(json.dumps(approval) + "\n")
    policies_file.write_text(json.dumps(policy) + "\n")
    config = AppConfig(
        funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
        action_intent_file=str(actions_file),
        action_approval_file=str(approvals_file),
        policy_decision_file=str(policies_file),
    )

    imported = import_legacy_action_policy_state(config)

    assert imported == {"actions": 1, "approvals": 1, "policies": 1}
    assert ActionService(config=config).get_intent("act_legacy").state == "policy_approved"
    stored_approval = ActionService(config=config).get_approval("appr_legacy")
    assert stored_approval.proof_hash is not None
    assert RAW_SIGNATURE not in str(stored_approval.to_dict())
    stored_policy = PolicyService(config=config).get_decision("policy_legacy")
    assert stored_policy is not None
    assert stored_policy.chain == "eip155:8453"
    assert not actions_file.exists()
    assert not approvals_file.exists()
    assert not policies_file.exists()
    assert import_legacy_action_policy_state(config) == {
        "actions": 0,
        "approvals": 0,
        "policies": 0,
    }


def test_legacy_jsonl_conflict_fails_closed_and_preserves_source(tmp_path):
    from scripts.import_legacy_action_policy_jsonl import (
        import_legacy_action_policy_state,
    )

    actions_file = tmp_path / "actions.jsonl"
    existing = {
        "action_id": "act_conflict",
        "user_id": "user_1",
        "agent_id": "hermes",
        "action_type": "service_purchase",
        "amount_usdc": "1",
        "state": "created",
        "created_at": "2026-07-16T00:00:00Z",
        "updated_at": "2026-07-16T00:00:00Z",
        "event_log": [],
    }
    legacy = {**existing, "state": "completed"}
    actions_file.write_text(json.dumps(legacy) + "\n")
    config = AppConfig(
        funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}",
        action_intent_file=str(actions_file),
        action_approval_file=str(tmp_path / "approvals.jsonl"),
        policy_decision_file=str(tmp_path / "policies.jsonl"),
    )
    ActionPolicyRepository(config.funding_database_url).create_action_intent(existing)

    with pytest.raises(RuntimeError, match="conflicts with authoritative database"):
        import_legacy_action_policy_state(config)

    assert actions_file.exists()
    assert (
        ActionService(config=config).get_intent("act_conflict").state == "created"
    )


def test_policies_are_shared_in_the_authoritative_database(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    legacy_file = tmp_path / "legacy-policies.jsonl"
    config = AppConfig(funding_database_url=database_url)

    decision = PolicyService(config=config, storage_file=legacy_file).evaluate(
        EvaluateActionPolicyRequest(
            user_id="user_1",
            agent_id="hermes",
            action_type="service_purchase",
            amount_usdc="1",
        )
    )

    assert PolicyService(config=config).get_decision(decision.policy_decision_id) == decision
    assert not legacy_file.exists()
    engine = create_engine(database_url)
    with engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT policy_decision_id FROM policy_decisions "
                "WHERE policy_decision_id = :id"
            ),
            {"id": decision.policy_decision_id},
        ).scalar_one()
    assert stored == decision.policy_decision_id


def test_policy_timestamps_use_one_canonical_utc_suffix(tmp_path):
    config = AppConfig(funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}")

    decision = PolicyService(config=config).evaluate(
        EvaluateActionPolicyRequest(
            user_id="user_1",
            agent_id="hermes",
            action_type="service_purchase",
            amount_usdc="1",
        )
    )

    timestamps = [
        decision.evaluated_at,
        *(event["created_at"] for event in decision.event_log),
    ]
    assert all(timestamp.endswith("Z") for timestamp in timestamps)
    assert all("+00:00Z" not in timestamp for timestamp in timestamps)


def test_fundable_policy_rejects_defaulted_or_noncanonical_target_and_network(tmp_path):
    config = AppConfig(funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}")

    decision = PolicyService(config=config).evaluate(
        EvaluateActionPolicyRequest(
            action_id="act_payment",
            user_id="user_1",
            agent_id="hermes",
            action_type="marketplace_purchase",
            amount_usdc="1",
            target_address=DESTINATION.upper(),
            chain="base",
            metadata={"destination": DESTINATION, "network": "eip155:137"},
        )
    )

    assert decision.approved is False
    assert decision.reason_code == "PAYMENT_TARGET_BINDING_REQUIRED"


def _fundable_request(config: AppConfig, *, target=DESTINATION, chain="eip155:137"):
    action = ActionService(config=config).create_intent(
        CreateActionIntentRequest(
            user_id="user_1",
            agent_id="hermes",
            action_type="marketplace_purchase",
            amount_usdc="1",
            metadata={"destination": DESTINATION, "network": "eip155:137"},
        )
    )
    return EvaluateActionPolicyRequest(
        action_id=action.action_id,
        user_id="user_1",
        agent_id="hermes",
        action_type="marketplace_purchase",
        amount_usdc="1",
        target_address=target,
        chain=chain,
        user_confirmed=True,
        metadata={"destination": DESTINATION, "network": "eip155:137"},
    )


def test_fundable_policy_binds_the_actual_target_and_network(tmp_path):
    config = AppConfig(funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}")

    target_mismatch = PolicyService(config=config).evaluate(
        _fundable_request(config, target="0x" + "2" * 40)
    )
    network_mismatch = PolicyService(config=config).evaluate(
        _fundable_request(config, chain="eip155:8453")
    )

    assert target_mismatch.reason_code == "PAYMENT_TARGET_BINDING_REQUIRED"
    assert network_mismatch.reason_code == "PAYMENT_TARGET_BINDING_REQUIRED"


def test_destination_denylist_overrides_allowlist_and_allowlist_is_restrictive(tmp_path):
    denied = AppConfig(
        funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'denied.sqlite3'}",
        funding_destination_denylist=(DESTINATION,),
        funding_destination_allowlist=(DESTINATION,),
    )
    denied_decision = PolicyService(config=denied).evaluate(_fundable_request(denied))

    restricted = AppConfig(
        funding_database_url=f"sqlite+pysqlite:///{tmp_path / 'restricted.sqlite3'}",
        funding_destination_allowlist=("0x" + "2" * 40,),
    )
    restricted_decision = PolicyService(config=restricted).evaluate(
        _fundable_request(restricted)
    )

    assert denied_decision.reason_code == "DESTINATION_DENYLISTED"
    assert restricted_decision.reason_code == "DESTINATION_NOT_ALLOWLISTED"
