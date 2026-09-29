from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from services.account_service.repository import AccountRepository
from services.account_service.schemas import (
    SpendingGrantRequest,
    WalletIdentity,
    reject_control_characters,
)
from services.account_service.service import AccountService
from services.audit_service.service import AuditService


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
DOMAIN = "account.clink.example"
TOKEN = "0x" + "22" * 20


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def grant_context(tmp_path):
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'grants.db'}")
    account = Account.create()
    identity = WalletIdentity(
        wallet_identity_id="wallet_identity_1",
        user_id="user_1",
        wallet_address=account.address,
        status="active",
        proof_hash="0xproof",
        verified_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    repository.save_wallet_identity(identity)
    clock = Clock()
    service = AccountService(repository, domain=DOMAIN, clock=clock)
    return service, repository, account, identity, clock


def grant_request(identity: WalletIdentity, **updates) -> SpendingGrantRequest:
    values = {
        "user_id": identity.user_id,
        "wallet_identity_id": identity.wallet_identity_id,
        "agent_id": "hermes",
        "max_amount_usdc": Decimal("25"),
        "per_transaction_limit_usdc": Decimal("5"),
        "hourly_limit_usdc": Decimal("7"),
        "daily_limit_usdc": Decimal("10"),
        "product_scopes": ["marketplace", "prediction_markets", "marketplace"],
        "venue_scopes": ["clink_marketplace", "polymarket", "polymarket"],
        "merchant_scopes": ["merchant-b", "merchant-a", "merchant-a"],
        "merchant_trust_scopes": [
            "registry_verified",
            "clink_verified",
            "registry_verified",
        ],
        "notification_mode": "silent_under_limits",
        "network_scopes": ["eip155:8453", "eip155:137", "eip155:137"],
        "asset_scopes": [TOKEN.upper().replace("0X", "0x"), TOKEN],
        "starts_at": NOW,
        "expires_at": NOW + timedelta(days=7),
    }
    values.update(updates)
    return SpendingGrantRequest(**values)


def signed_request(service, account, request: SpendingGrantRequest):
    challenge = service.create_spending_grant_challenge(request)
    signature = Account.sign_message(
        encode_defunct(text=challenge.message_to_sign), account.key
    ).signature.hex()
    return request.model_copy(
        update={
            "session_id": challenge.session_id,
            "signed_message": challenge.message_to_sign,
            "signature": signature,
        }
    ), challenge


def test_signed_grant_binds_all_terms_and_normalizes_scopes(grant_context):
    service, _repository, account, identity, _clock = grant_context
    request, challenge = signed_request(service, account, grant_request(identity))

    assert "Purpose: clink_spending_grant" in challenge.message_to_sign
    assert f"Wallet Identity ID: {identity.wallet_identity_id}" in challenge.message_to_sign
    assert f"Wallet Address: {identity.wallet_address}" in challenge.message_to_sign

    grant = service.create_spending_grant(request)

    assert grant.status == "active"
    assert grant.product_scopes == ["marketplace", "prediction_markets"]
    assert grant.venue_scopes == ["clink_marketplace", "polymarket"]
    assert grant.merchant_scopes == ["merchant-a", "merchant-b"]
    assert grant.merchant_trust_scopes == ["clink_verified", "registry_verified"]
    assert grant.notification_mode == "silent_under_limits"
    assert grant.hourly_limit_usdc == Decimal("7")
    assert grant.network_scopes == ["eip155:137", "eip155:8453"]
    assert grant.asset_scopes == [TOKEN]


def test_new_signed_mandate_atomically_supersedes_overlapping_active_grant(
    grant_context,
):
    service, repository, account, identity, _clock = grant_context
    first_signed, _challenge = signed_request(
        service, account, grant_request(identity)
    )
    first = service.create_spending_grant(first_signed)
    second_signed, _challenge = signed_request(
        service,
        account,
        grant_request(
            identity,
            max_amount_usdc=Decimal("30"),
            per_transaction_limit_usdc=Decimal("6"),
            hourly_limit_usdc=Decimal("8"),
            daily_limit_usdc=Decimal("12"),
        ),
    )

    second = service.create_spending_grant(second_signed)

    stored_first = repository.spending_grant(first.spending_grant_id)
    assert stored_first.status == "revoked"
    assert stored_first.status_reason == "superseded_by_signed_mandate"
    assert [
        item.spending_grant_id
        for item in repository.active_spending_grants("user_1", NOW)
    ] == [second.spending_grant_id]


def test_signed_amendment_changes_same_grant_and_preserves_committed_budget(
    grant_context,
):
    service, repository, account, identity, _clock = grant_context
    first_signed, _challenge = signed_request(
        service, account, grant_request(identity)
    )
    first = service.create_spending_grant(first_signed)
    repository.save_spending_grant(
        first.model_copy(
            update={
                "used_amount_usdc": Decimal("12"),
                "reserved_amount_usdc": Decimal("2"),
            }
        )
    )
    amendment = grant_request(
        identity,
        amends_spending_grant_id=first.spending_grant_id,
        max_amount_usdc=Decimal("30"),
        per_transaction_limit_usdc=Decimal("30"),
        hourly_limit_usdc=Decimal("30"),
        daily_limit_usdc=Decimal("30"),
    )
    amended_signed, _challenge = signed_request(service, account, amendment)

    amended = service.create_spending_grant(amended_signed)

    assert amended.spending_grant_id == first.spending_grant_id
    assert amended.status == first.status
    assert amended.created_at == first.created_at
    assert amended.max_amount_usdc == Decimal("30")
    assert amended.per_transaction_limit_usdc == Decimal("30")
    assert amended.hourly_limit_usdc == Decimal("30")
    assert amended.daily_limit_usdc == Decimal("30")
    assert amended.used_amount_usdc == Decimal("12")
    assert amended.reserved_amount_usdc == Decimal("2")
    assert [
        item.spending_grant_id
        for item in repository.active_spending_grants(identity.user_id, NOW)
    ] == [first.spending_grant_id]
    events = AuditService(database_url=str(repository.engine.url)).get_trail(
        user_id=identity.user_id
    ).events
    assert [event.event_type for event in events] == [
        "grant_created",
        "grant_amended",
    ]


def test_signed_amendment_rejects_scope_change_and_limit_below_committed(
    grant_context,
):
    service, repository, account, identity, _clock = grant_context
    first_signed, _challenge = signed_request(
        service, account, grant_request(identity)
    )
    first = service.create_spending_grant(first_signed)
    repository.save_spending_grant(
        first.model_copy(
            update={
                "used_amount_usdc": Decimal("12"),
                "reserved_amount_usdc": Decimal("2"),
            }
        )
    )

    with pytest.raises(ValueError, match="cannot change grant scope"):
        service.create_spending_grant_challenge(
            grant_request(
                identity,
                amends_spending_grant_id=first.spending_grant_id,
                venue_scopes=["polymarket"],
            )
        )

    too_low = grant_request(
        identity,
        amends_spending_grant_id=first.spending_grant_id,
        max_amount_usdc=Decimal("13"),
        per_transaction_limit_usdc=Decimal("13"),
        hourly_limit_usdc=Decimal("13"),
        daily_limit_usdc=Decimal("13"),
    )
    too_low_signed, _challenge = signed_request(service, account, too_low)
    with pytest.raises(ValueError, match="below spent and pending amount"):
        service.create_spending_grant(too_low_signed)


def test_future_mandate_keeps_current_grant_active_until_handover(grant_context):
    service, repository, account, identity, clock = grant_context
    first_signed, _challenge = signed_request(
        service, account, grant_request(identity)
    )
    first = service.create_spending_grant(first_signed)
    handover_at = NOW + timedelta(hours=2)
    second_signed, _challenge = signed_request(
        service,
        account,
        grant_request(
            identity,
            starts_at=handover_at,
            expires_at=NOW + timedelta(days=8),
        ),
    )

    second = service.create_spending_grant(second_signed)

    stored_first = repository.spending_grant(first.spending_grant_id)
    assert stored_first.status == "active"
    assert stored_first.expires_at == handover_at
    assert [item.spending_grant_id for item in repository.active_spending_grants("user_1", NOW)] == [
        first.spending_grant_id
    ]

    clock.now = handover_at
    assert [
        item.spending_grant_id
        for item in repository.active_spending_grants("user_1", handover_at)
    ] == [second.spending_grant_id]


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("agent_id", "other-agent"),
        ("max_amount_usdc", Decimal("26")),
        ("per_transaction_limit_usdc", Decimal("4")),
        ("hourly_limit_usdc", Decimal("6")),
        ("daily_limit_usdc", Decimal("9")),
        ("product_scopes", ["marketplace"]),
        ("venue_scopes", ["other-venue"]),
        ("merchant_scopes", ["other-merchant"]),
        ("merchant_trust_scopes", ["clink_verified"]),
        ("notification_mode", "notify_all"),
        ("network_scopes", ["eip155:8453"]),
        ("asset_scopes", ["0x" + "33" * 20]),
        ("starts_at", NOW + timedelta(minutes=1)),
        ("expires_at", NOW + timedelta(days=8)),
    ],
)
def test_signed_grant_rejects_any_terms_tampering(grant_context, field, replacement):
    service, _repository, account, identity, _clock = grant_context
    signed, _challenge = signed_request(service, account, grant_request(identity))
    tampered = signed.model_copy(update={field: replacement})

    with pytest.raises(ValueError, match="grant terms do not match challenge"):
        service.create_spending_grant(tampered)


def test_signed_grant_rejects_wrong_wallet_and_session_replay(grant_context):
    service, _repository, account, identity, _clock = grant_context
    request = grant_request(identity)
    challenge = service.create_spending_grant_challenge(request)
    wrong_signature = Account.sign_message(
        encode_defunct(text=challenge.message_to_sign), Account.create().key
    ).signature.hex()

    with pytest.raises(ValueError, match="signature does not match wallet"):
        service.create_spending_grant(
            request.model_copy(
                update={
                    "session_id": challenge.session_id,
                    "signed_message": challenge.message_to_sign,
                    "signature": wrong_signature,
                }
            )
        )

    signed, _challenge = signed_request(service, account, request)
    service.create_spending_grant(signed)
    with pytest.raises(ValueError, match="already consumed"):
        service.create_spending_grant(signed)


def test_concurrent_grant_creation_has_one_winner(grant_context):
    service, _repository, account, identity, _clock = grant_context
    signed, _challenge = signed_request(service, account, grant_request(identity))
    barrier = Barrier(2)

    def create():
        barrier.wait()
        try:
            return "success", service.create_spending_grant(signed)
        except ValueError as exc:
            return "error", str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [future.result() for future in [executor.submit(create), executor.submit(create)]]

    assert [status for status, _ in outcomes].count("success") == 1
    assert [status for status, _ in outcomes].count("error") == 1


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"product_scopes": []}, "at least one product scope"),
        ({"product_scopes": ["all"]}, "unsupported product scope"),
        ({"product_scopes": ["unknown"]}, "unsupported product scope"),
        ({"max_amount_usdc": Decimal("0")}, "amounts must be positive"),
        ({"per_transaction_limit_usdc": Decimal("26")}, "per-transaction limit exceeds total grant"),
        ({"hourly_limit_usdc": Decimal("4")}, "per-transaction limit exceeds hourly limit"),
        ({"hourly_limit_usdc": Decimal("11")}, "hourly limit exceeds daily limit"),
        ({"daily_limit_usdc": Decimal("26")}, "daily limit exceeds total grant"),
        ({"starts_at": NOW + timedelta(days=1), "expires_at": NOW}, "starts_at must be before expires_at"),
        (
            {"starts_at": NOW - timedelta(minutes=1), "expires_at": NOW},
            "grant expiry must be in the future",
        ),
        ({"network_scopes": []}, "at least one network scope"),
        ({"asset_scopes": []}, "at least one asset scope"),
    ],
)
def test_grant_challenge_rejects_invalid_policy(grant_context, updates, message):
    service, _repository, _account, identity, _clock = grant_context

    with pytest.raises(ValueError, match=message):
        service.create_spending_grant_challenge(grant_request(identity, **updates))


def test_grant_lifecycle_is_idempotent_and_reduce_only(grant_context):
    service, repository, account, identity, _clock = grant_context
    signed, _challenge = signed_request(service, account, grant_request(identity))
    grant = service.create_spending_grant(signed)

    paused = service.pause_spending_grant(grant.spending_grant_id)
    assert paused.status == "paused"
    assert paused.status_reason == "user_paused"
    assert service.pause_spending_grant(grant.spending_grant_id) == paused

    resumed = service.resume_spending_grant(grant.spending_grant_id)
    assert resumed.status == "active"
    assert resumed.status_reason is None
    assert service.resume_spending_grant(grant.spending_grant_id) == resumed

    reduced = service.reduce_spending_grant(
        grant.spending_grant_id,
        max_amount_usdc=Decimal("20"),
        per_transaction_limit_usdc=Decimal("4"),
        daily_limit_usdc=Decimal("8"),
        hourly_limit_usdc=Decimal("6"),
    )
    assert reduced.max_amount_usdc == Decimal("20")
    assert reduced.hourly_limit_usdc == Decimal("6")
    with pytest.raises(ValueError, match="cannot increase"):
        service.reduce_spending_grant(grant.spending_grant_id, max_amount_usdc=Decimal("21"))

    revoked = service.revoke_spending_grant(grant.spending_grant_id)
    assert revoked.status == "revoked"
    assert service.revoke_spending_grant(grant.spending_grant_id) == revoked
    with pytest.raises(ValueError, match="revoked grant cannot be resumed"):
        service.resume_spending_grant(grant.spending_grant_id)
    events = AuditService(database_url=str(repository.engine.url)).get_trail(
        user_id=identity.user_id
    ).events
    assert [event.event_type for event in events] == [
        "grant_created",
        "grant_paused",
        "grant_resumed",
        "grant_reduced",
        "grant_revoked",
    ]


def test_identity_security_pause_cannot_be_resumed(grant_context):
    service, _repository, account, identity, _clock = grant_context
    signed, _challenge = signed_request(service, account, grant_request(identity))
    grant = service.create_spending_grant(signed)

    service.revoke_wallet_identity(identity.wallet_identity_id)

    with pytest.raises(ValueError, match="security-paused grant cannot be resumed"):
        service.resume_spending_grant(grant.spending_grant_id)


def test_future_grant_is_pending_and_active_query_honors_boundaries(grant_context):
    service, repository, account, identity, _clock = grant_context
    starts_at = NOW + timedelta(hours=1)
    expires_at = NOW + timedelta(hours=2)
    signed, _challenge = signed_request(
        service,
        account,
        grant_request(identity, starts_at=starts_at, expires_at=expires_at),
    )

    grant = service.create_spending_grant(signed)

    assert grant.status == "pending"
    assert repository.active_spending_grants(
        identity.user_id, at=starts_at - timedelta(microseconds=1)
    ) == []
    active = repository.active_spending_grants(identity.user_id, at=starts_at)
    assert [item.spending_grant_id for item in active] == [grant.spending_grant_id]
    assert active[0].status == "active"
    assert repository.active_spending_grants(identity.user_id, at=expires_at) == []
    assert repository._spending_grant_by_id(grant.spending_grant_id).status == "expired"


def test_resume_user_paused_future_grant_returns_pending_until_start(grant_context):
    service, repository, account, identity, _clock = grant_context
    starts_at = NOW + timedelta(hours=1)
    signed, _challenge = signed_request(
        service,
        account,
        grant_request(identity, starts_at=starts_at, expires_at=starts_at + timedelta(hours=1)),
    )
    grant = service.create_spending_grant(signed)

    assert service.pause_spending_grant(grant.spending_grant_id).status == "paused"
    resumed = service.resume_spending_grant(grant.spending_grant_id)

    assert resumed.status == "pending"
    assert resumed.status_reason is None
    assert repository.active_spending_grants(identity.user_id, at=starts_at) == [
        resumed.model_copy(update={"status": "active", "updated_at": starts_at})
    ]


def test_resume_expired_user_paused_grant_marks_expired(grant_context):
    service, _repository, account, identity, clock = grant_context
    expires_at = NOW + timedelta(hours=1)
    signed, _challenge = signed_request(
        service,
        account,
        grant_request(identity, expires_at=expires_at),
    )
    grant = service.create_spending_grant(signed)
    service.pause_spending_grant(grant.spending_grant_id)
    clock.now = expires_at

    resumed = service.resume_spending_grant(grant.spending_grant_id)

    assert resumed.status == "expired"
    assert resumed.status_reason == "grant_expired"


def test_revoked_identity_prevents_future_pending_grant_activation(grant_context):
    service, repository, account, identity, _clock = grant_context
    starts_at = NOW + timedelta(hours=1)
    signed, _challenge = signed_request(
        service,
        account,
        grant_request(identity, starts_at=starts_at, expires_at=starts_at + timedelta(hours=1)),
    )
    grant = service.create_spending_grant(signed)

    service.revoke_wallet_identity(identity.wallet_identity_id)

    assert repository.active_spending_grants(identity.user_id, at=starts_at) == []
    persisted = repository._spending_grant_by_id(grant.spending_grant_id)
    assert persisted.status == "paused"
    assert persisted.status_reason == "wallet_identity_revoked"


@pytest.mark.parametrize(
    "value",
    [
        "bad\x00value",
        "bad\rvalue",
        "bad\nvalue",
        "bad\u202evalue",
        "bad\u2028value",
        "bad\u2029value",
        "bad\ud800value",
        "bad\ue000value",
        "bad\u0378value",
    ],
)
def test_message_fields_reject_unicode_display_controls(value):
    with pytest.raises(ValueError, match="control characters"):
        reject_control_characters(value)


def test_message_fields_preserve_printable_unicode():
    value = "商家-cafe-🙂"

    assert reject_control_characters(value) == value


def test_explicit_empty_allowed_products_fails_closed(grant_context):
    _service, repository, _account, identity, clock = grant_context
    service = AccountService(
        repository,
        domain=DOMAIN,
        clock=clock,
        allowed_products=set(),
    )

    with pytest.raises(ValueError, match="unsupported product scope"):
        service.create_spending_grant_challenge(grant_request(identity))


def test_explicit_empty_network_configs_fails_grant_creation_closed(grant_context):
    _service, repository, _account, identity, clock = grant_context
    service = AccountService(
        repository,
        domain=DOMAIN,
        clock=clock,
        network_configs={},
    )

    with pytest.raises(ValueError, match="unsupported network scope"):
        service.create_spending_grant_challenge(grant_request(identity))
