from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from services.account_service.repository import AccountRepository
from services.account_service.schemas import SpendingGrant, WalletIdentity
from services.policy_service.schemas import PolicyDecision
from shared.hosted_facilitator_protocol import canonical_json_bytes, sha256_identifier
from shared.payment_capability import (
    PAYMENT_CAPABILITY_VERSION,
    VERIFICATION_ONLY_RISK_ABSENCE_MARKER,
    PaymentCapabilityV1,
    execution_scope_hash,
    policy_decision_snapshot_hash,
    reservation_scope_hash,
    revocation_projection_id,
    risk_evidence_hash,
    spending_grant_terms_hash,
)


NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)


def valid_capability(**overrides: object) -> PaymentCapabilityV1:
    values: dict[str, object] = {
        "capability_version": PAYMENT_CAPABILITY_VERSION,
        "capability_id": "capability_1",
        "user_id": "user_1",
        "agent_id": "hermes",
        "tenant_id": "tenant_1",
        "node_id": "node_1",
        "wallet_binding_id": "wallet_binding_1",
        "wallet_identity_id": "wallet_identity_1",
        "wallet_address": "0x" + "11" * 20,
        "spending_grant_id": "grant_1",
        "spending_grant_hash": "0x" + "12" * 32,
        "asset_allowance_id": "allowance_1",
        "action_id": "action_1",
        "policy_decision_id": "decision_1",
        "policy_snapshot_hash": "0x" + "13" * 32,
        "risk_evidence_hash": "0x" + "14" * 32,
        "reservation_id": "reservation_1",
        "reservation_hash": "0x" + "18" * 32,
        "purchase_id": "purchase_1",
        "merchant_id": "merchant_1",
        "product": "marketplace",
        "venue": "clink_marketplace",
        "quote_hash": "0x" + "15" * 32,
        "payment_challenge_hash": "0x" + "15" * 32,
        "network": "eip155:137",
        "asset_contract": "0x" + "22" * 20,
        "amount_atomic": "1000000",
        "pay_to": "0x" + "ab" * 20,
        "executor_contract": "0x" + "44" * 20,
        "execution_scope_hash": "0x" + "16" * 32,
        "confirmation_mode": "policy_approved",
        "revocation_id": "0x" + "17" * 32,
        "issued_at": 2_000_000_000,
        "expires_at": 2_000_000_060,
    }
    values.update(overrides)
    return PaymentCapabilityV1(**values)


def valid_grant(**overrides: object) -> SpendingGrant:
    values: dict[str, object] = {
        "spending_grant_id": "grant_1",
        "wallet_identity_id": "wallet_identity_1",
        "user_id": "user_1",
        "agent_id": "hermes",
        "status": "active",
        "status_reason": None,
        "max_amount_usdc": Decimal("10"),
        "per_transaction_limit_usdc": Decimal("2"),
        "hourly_limit_usdc": Decimal("4"),
        "daily_limit_usdc": Decimal("8"),
        "used_amount_usdc": Decimal("1"),
        "reserved_amount_usdc": Decimal("2"),
        "product_scopes": ["marketplace"],
        "venue_scopes": ["clink_marketplace"],
        "merchant_scopes": ["merchant_1"],
        "merchant_trust_scopes": ["clink_verified"],
        "notification_mode": "silent_under_limits",
        "network_scopes": ["eip155:137"],
        "asset_scopes": ["0x" + "22" * 20],
        "starts_at": NOW,
        "expires_at": datetime(2026, 9, 4, 12, tzinfo=UTC),
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return SpendingGrant(**values)


def valid_policy(**overrides: object) -> PolicyDecision:
    values: dict[str, object] = {
        "policy_decision_id": "decision_1",
        "action_id": "action_1",
        "approved": True,
        "decision": "approved",
        "reason_code": "within_policy",
        "reasons": ["grant active"],
        "required_action": None,
        "user_id": "user_1",
        "agent_id": "hermes",
        "action_type": "marketplace_purchase",
        "amount_usdc": "1",
        "authorization_id": "grant_1",
        "merchant_id": "merchant_1",
        "target_address": "0x" + "33" * 20,
        "chain": "eip155:137",
        "authorization_approved": True,
        "remaining_amount_usdc": "9",
        "risk_level": "low",
        "risk_score": 1,
        "risk_action": "allow",
        "risk_assessment": {"decision": "allow", "provider": "misttrack"},
        "credit_model_assessment": None,
        "evaluated_at": "2026-08-04T12:00:00Z",
        "event_log": [{"event": "evaluated"}],
        "metadata": {"quote_hash": "0x" + "15" * 32},
    }
    values.update(overrides)
    return PolicyDecision(**values)


def test_capability_has_stable_compact_utf8_canonical_serialization() -> None:
    first = valid_capability(merchant_id="mérchant")
    second = PaymentCapabilityV1(
        **dict(reversed(list(first.model_dump(mode="json").items())))
    )

    assert first.canonical_bytes() == second.canonical_bytes()
    assert b'"merchant_id":"m\xc3\xa9rchant"' in first.canonical_bytes()
    assert b": " not in first.canonical_bytes()
    assert first.capability_hash == second.capability_hash
    assert first.capability_hash == sha256_identifier(first.canonical_bytes())


def test_capability_is_frozen_and_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        valid_capability(untrusted_scope="x")
    with pytest.raises(ValueError):
        valid_capability().amount_atomic = "2"


@pytest.mark.parametrize(
    "field",
    ["wallet_address", "asset_contract", "pay_to", "executor_contract"],
)
def test_capability_canonicalizes_evm_addresses(field: str) -> None:
    capability = valid_capability(**{field: "0x" + "AB" * 20})

    assert getattr(capability, field) == "0x" + "ab" * 20


@pytest.mark.parametrize("amount", ["0", "01", "1.0", "+1", "-1", "", 1])
def test_amount_atomic_is_a_positive_canonical_integer_string(amount: object) -> None:
    with pytest.raises(ValueError, match="amount_atomic"):
        valid_capability(amount_atomic=amount)


@pytest.mark.parametrize("network", ["eip155:137", "eip155:8453", "eip155:80002"])
def test_capability_supports_polygon_base_and_amoy(network: str) -> None:
    assert valid_capability(network=network).network == network


@pytest.mark.parametrize("network", ["polygon", "eip155:1"])
def test_capability_rejects_unsupported_networks(network: str) -> None:
    with pytest.raises(ValueError, match="network"):
        valid_capability(network=network)


def test_capability_lifetime_is_positive_ordered_and_at_most_sixty_seconds() -> None:
    with pytest.raises(ValueError, match="lifetime"):
        valid_capability(issued_at=100, expires_at=161)
    with pytest.raises(ValueError, match="timestamps"):
        valid_capability(issued_at=100, expires_at=100)
    with pytest.raises(ValueError, match="timestamps"):
        valid_capability(issued_at=0, expires_at=1)


@pytest.mark.parametrize(
    "field",
    [
        "capability_id",
        "user_id",
        "agent_id",
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "wallet_identity_id",
        "spending_grant_id",
        "asset_allowance_id",
        "action_id",
        "policy_decision_id",
        "reservation_id",
        "purchase_id",
        "merchant_id",
        "product",
        "venue",
    ],
)
@pytest.mark.parametrize("value", ["", "bad\nidentifier", "x" * 257])
def test_capability_rejects_malformed_identifiers(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=field):
        valid_capability(**{field: value})


@pytest.mark.parametrize(
    "field",
    [
        "spending_grant_hash",
        "policy_snapshot_hash",
        "risk_evidence_hash",
        "reservation_hash",
        "quote_hash",
        "payment_challenge_hash",
        "execution_scope_hash",
        "revocation_id",
    ],
)
@pytest.mark.parametrize("value", ["hash", "0x" + "A" * 64, "0x" + "a" * 63])
def test_capability_rejects_malformed_hashes(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=field):
        valid_capability(**{field: value})


def test_payment_challenge_hash_is_an_independent_bound_fact() -> None:
    capability = valid_capability(payment_challenge_hash="0x" + "99" * 32)

    assert capability.payment_challenge_hash != capability.quote_hash
    assert capability.capability_hash != valid_capability().capability_hash


def test_reservation_scope_hash_has_a_fixed_core_owned_vector() -> None:
    assert reservation_scope_hash(
        reservation_id="reservation_1",
        purchase_id="purchase_1",
        user_id="user_1",
        agent_id="hermes",
        wallet_identity_id="wallet_identity_1",
        spending_grant_id="grant_1",
        asset_allowance_id="allowance_1",
        action_id="action_1",
        policy_decision_id="decision_1",
        merchant_id="merchant_1",
        product="marketplace",
        venue="clink_marketplace",
        quote_hash="0x" + "15" * 32,
        network="eip155:8453",
        asset_contract="0x" + "22" * 20,
        amount_atomic="1000000",
        pay_to="0x" + "ab" * 20,
        authorization_rail="native_allowance",
    ) == "0xbfe78c1ddf36428d004e03c43bf753c8896f3546532387932e6aa745092eb197"


@pytest.mark.parametrize(
    "updates",
    [
        {"capability_id": "capability_2"},
        {"user_id": "user_2"},
        {"agent_id": "agent_2"},
        {"tenant_id": "tenant_2"},
        {"node_id": "node_2"},
        {"wallet_binding_id": "wallet_binding_2"},
        {"wallet_identity_id": "wallet_identity_2"},
        {"wallet_address": "0x" + "aa" * 20},
        {"spending_grant_id": "grant_2"},
        {"spending_grant_hash": "0x" + "21" * 32},
        {"asset_allowance_id": "allowance_2"},
        {"action_id": "action_2"},
        {"policy_decision_id": "decision_2"},
        {"policy_snapshot_hash": "0x" + "23" * 32},
        {"risk_evidence_hash": "0x" + "24" * 32},
        {"reservation_id": "reservation_2"},
        {"reservation_hash": "0x" + "28" * 32},
        {"purchase_id": "purchase_2"},
        {"merchant_id": "merchant_2"},
        {"product": "prediction_markets"},
        {"venue": "another_venue"},
        {
            "quote_hash": "0x" + "25" * 32,
            "payment_challenge_hash": "0x" + "25" * 32,
        },
        {"payment_challenge_hash": "0x" + "26" * 32},
        {"network": "eip155:8453"},
        {"asset_contract": "0x" + "bb" * 20},
        {"amount_atomic": "1000001"},
        {"pay_to": "0x" + "cc" * 20},
        {"executor_contract": "0x" + "dd" * 20},
        {"execution_scope_hash": "0x" + "26" * 32},
        {"confirmation_mode": "user_approved"},
        {"revocation_id": "0x" + "27" * 32},
        {"issued_at": 2_000_000_001, "expires_at": 2_000_000_060},
        {"expires_at": 2_000_000_059},
    ],
)
def test_every_authority_and_payment_field_is_bound_into_capability_hash(
    updates: dict[str, object],
) -> None:
    assert valid_capability(**updates).capability_hash != valid_capability().capability_hash


def test_spending_grant_terms_hash_excludes_mutable_lifecycle_and_usage() -> None:
    original = valid_grant()
    mutable_changes = original.model_copy(
        update={
            "status": "paused",
            "status_reason": "operator pause",
            "used_amount_usdc": Decimal("3"),
            "reserved_amount_usdc": Decimal("4"),
            "created_at": datetime(2026, 8, 3, 12, tzinfo=UTC),
            "updated_at": datetime(2026, 8, 5, 12, tzinfo=UTC),
        }
    )

    assert spending_grant_terms_hash(mutable_changes) == spending_grant_terms_hash(
        original
    )


def test_spending_grant_terms_hash_changes_for_signed_limits_and_scopes() -> None:
    original_hash = spending_grant_terms_hash(valid_grant())

    assert (
        spending_grant_terms_hash(
            valid_grant(per_transaction_limit_usdc=Decimal("1"))
        )
        != original_hash
    )
    assert (
        spending_grant_terms_hash(valid_grant(product_scopes=["prediction_markets"]))
        != original_hash
    )


@pytest.mark.parametrize(
    "field_name",
    [
        "max_amount_usdc",
        "per_transaction_limit_usdc",
        "hourly_limit_usdc",
        "daily_limit_usdc",
    ],
)
def test_spending_grant_terms_hash_canonicalizes_equivalent_usdc_scales(
    field_name: str,
) -> None:
    common_limits = {
        "max_amount_usdc": Decimal("10"),
        "per_transaction_limit_usdc": Decimal("10"),
        "hourly_limit_usdc": Decimal("10"),
        "daily_limit_usdc": Decimal("10"),
    }
    hashes = {
        spending_grant_terms_hash(
            valid_grant(**{**common_limits, field_name: value})
        )
        for value in (Decimal("10"), Decimal("10.0"), Decimal("10.000000"))
    }

    assert len(hashes) == 1


def test_spending_grant_terms_hash_matches_numeric_database_projection(tmp_path) -> None:
    repository = AccountRepository(
        f"sqlite+pysqlite:///{tmp_path / 'grant-scale.sqlite3'}"
    )
    repository.save_wallet_identity(
        WalletIdentity(
            wallet_identity_id="wallet_identity_1",
            user_id="user_1",
            wallet_address="0x" + "11" * 20,
            status="active",
            proof_hash="0xproof",
            verified_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    original = valid_grant(max_amount_usdc=Decimal("10"))
    repository.save_spending_grant(original)

    reloaded = repository.spending_grant(original.spending_grant_id)

    assert reloaded is not None
    assert reloaded.max_amount_usdc == Decimal("10.000000")
    assert reloaded.max_amount_usdc.as_tuple().exponent == -6
    assert spending_grant_terms_hash(reloaded) == spending_grant_terms_hash(original)


def test_policy_snapshot_hash_binds_the_complete_policy_decision() -> None:
    original = valid_policy()
    reversed_policy = PolicyDecision(
        **dict(reversed(list(original.model_dump(mode="json").items())))
    )

    assert policy_decision_snapshot_hash(reversed_policy) == policy_decision_snapshot_hash(
        original
    )
    assert policy_decision_snapshot_hash(
        original.model_copy(update={"event_log": [{"event": "changed"}]})
    ) != policy_decision_snapshot_hash(original)


def test_missing_risk_uses_only_the_explicit_verification_only_marker() -> None:
    expected = sha256_identifier(
        canonical_json_bytes(VERIFICATION_ONLY_RISK_ABSENCE_MARKER)
    )

    assert risk_evidence_hash(None) == expected
    assert expected != sha256_identifier(canonical_json_bytes({}))
    assert risk_evidence_hash({"decision": "allow"}) != expected


@pytest.mark.parametrize(
    "risk_assessment",
    [{"score": 1.5}, {"score": Decimal("1.0")}, {1: "non-string key"}],
)
def test_risk_evidence_hash_rejects_non_canonical_values(risk_assessment) -> None:
    with pytest.raises(ValueError, match="canonical JSON"):
        risk_evidence_hash(risk_assessment)


def test_execution_scope_hash_is_canonical_and_payment_bound() -> None:
    scope = {
        "network": "eip155:137",
        "asset_contract": "0x" + "22" * 20,
        "wallet_address": "0x" + "11" * 20,
        "executor_contract": "0x" + "44" * 20,
        "pay_to": "0x" + "ab" * 20,
        "amount_atomic": "1000000",
        "purchase_id": "purchase_1",
        "reservation_id": "reservation_1",
        "quote_hash": "0x" + "15" * 32,
    }

    assert execution_scope_hash(**scope) == execution_scope_hash(
        **{**scope, "pay_to": "0x" + "AB" * 20}
    )
    assert execution_scope_hash(**{**scope, "amount_atomic": "1000001"}) != (
        execution_scope_hash(**scope)
    )


def test_revocation_projection_binds_every_revocable_authority() -> None:
    projection = {
        "wallet_identity_id": "wallet_identity_1",
        "spending_grant_id": "grant_1",
        "asset_allowance_id": "allowance_1",
        "wallet_binding_id": "wallet_binding_1",
    }
    original = revocation_projection_id(**projection)

    for field in projection:
        assert revocation_projection_id(
            **{**projection, field: projection[field] + "_changed"}
        ) != original
