from __future__ import annotations

import hashlib
from datetime import timedelta

from sqlalchemy import inspect

from services.account_service.app import create_app
from services.account_service.opc_service import OpcPairingRow
from services.account_service.repository import PublicAccountSessionRow
from shared.hosted_facilitator_protocol import DeviceSigningKey
from test_opc_account import (
    ASGIClient,
    INTERNAL_TOKEN,
    NOW,
    _context,
    _pair,
    _public_session,
)


def _pairing_session_id(opc, pairing: dict) -> str:
    return opc.pairing(pairing["pairing_id"])["public_account_session_id"]


def _expire_public_session(
    repository, public_account_session_id: str, *, status: str, now=NOW
) -> None:
    with repository._write_session() as session:
        row = session.get(PublicAccountSessionRow, public_account_session_id)
        assert row is not None
        row.status = status
        row.expires_at = now - timedelta(seconds=1)
        row.updated_at = now


def _expire_public_session_by_access(repository, pairing: dict, *, at) -> str:
    public_token = pairing["verification_uri"].rsplit("/", 1)[1]
    session = repository.access_public_account_session(
        hashlib.sha256(public_token.encode()).hexdigest(), at
    )
    assert session is not None
    assert session.status == "expired"
    return session.public_account_session_id


def _set_pairing_status(repository, pairing_id: str, status: str) -> None:
    with repository._write_session() as session:
        row = session.get(OpcPairingRow, pairing_id)
        assert row is not None
        row.status = status
        row.updated_at = NOW


def test_cleanup_retains_expired_public_session_referenced_only_by_opc_pairing(
    tmp_path,
) -> None:
    _clock, repository, _account, opc = _context(tmp_path)
    pairing = _pair(opc, DeviceSigningKey.generate())
    pairing_before = opc.pairing(pairing["pairing_id"])
    public_session_id = _expire_public_session_by_access(
        repository, pairing, at=NOW + timedelta(minutes=11)
    )

    removed = repository.cleanup_expired_public_account_sessions(
        NOW + timedelta(minutes=11)
    )

    assert removed == 0
    retained = repository.public_account_session_by_id(public_session_id)
    assert retained is not None
    assert retained.status == "expired"
    assert opc.pairing(pairing["pairing_id"]) == pairing_before


def test_cleanup_marks_elapsed_active_opc_session_expired_without_deleting(tmp_path) -> None:
    _clock, repository, _account, opc = _context(tmp_path)
    pairing = _pair(opc, DeviceSigningKey.generate())
    pairing_before = opc.pairing(pairing["pairing_id"])
    public_session_id = _pairing_session_id(opc, pairing)
    _expire_public_session(repository, public_session_id, status="active")

    changed = repository.cleanup_expired_public_account_sessions(NOW)

    assert changed == 1
    retained = repository.public_account_session_by_id(public_session_id)
    assert retained is not None
    assert retained.status == "expired"
    assert opc.pairing(pairing["pairing_id"]) == pairing_before


def test_cleanup_preserves_revoked_and_linked_opc_pairings(tmp_path) -> None:
    _clock, repository, _account, opc = _context(tmp_path)
    linked = _pair(opc, DeviceSigningKey.generate(), request_id="linked-cleanup")
    revoked = _pair(opc, DeviceSigningKey.generate(), request_id="revoked-cleanup")
    _set_pairing_status(repository, linked["pairing_id"], "linked")
    _set_pairing_status(repository, revoked["pairing_id"], "revoked")
    before = {
        pairing["pairing_id"]: opc.pairing(pairing["pairing_id"])
        for pairing in (linked, revoked)
    }
    session_ids = [
        _expire_public_session_by_access(
            repository, pairing, at=NOW + timedelta(minutes=11)
        )
        for pairing in (linked, revoked)
    ]

    assert repository.cleanup_expired_public_account_sessions(
        NOW + timedelta(minutes=11)
    ) == 0

    for pairing in (linked, revoked):
        assert opc.pairing(pairing["pairing_id"]) == before[pairing["pairing_id"]]
    assert all(
        repository.public_account_session_by_id(session_id) is not None
        for session_id in session_ids
    )


def test_cleanup_still_deletes_unreferenced_expired_public_session(tmp_path) -> None:
    _clock, repository, _account, _opc = _context(tmp_path)
    public_session = _public_session(
        repository, user_id="unreferenced-user", suffix="cleanup-expired"
    )
    _expire_public_session(
        repository,
        public_session.public_account_session_id,
        status="expired",
    )

    removed = repository.cleanup_expired_public_account_sessions(NOW)

    assert removed == 1
    assert (
        repository.public_account_session_by_id(public_session.public_account_session_id)
        is None
    )


def test_internal_session_post_succeeds_with_foreign_expired_opc_pairing(tmp_path) -> None:
    clock, repository, account, opc = _context(tmp_path)
    pairing = _pair(opc, DeviceSigningKey.generate(), request_id="foreign-expired")
    pairing_before = opc.pairing(pairing["pairing_id"])
    old_session_id = _expire_public_session_by_access(
        repository, pairing, at=NOW + timedelta(minutes=11)
    )
    assert pairing_before["target_user_id"] != "new-unbound-user"

    app = create_app(
        service=account,
        opc_service=opc,
        internal_token=INTERNAL_TOKEN,
        clock=clock,
        session_ttl=timedelta(minutes=15),
        audit_summary_reader=lambda _user_id, _limit: [],
        approval_targets={},
    )
    response = ASGIClient(app).post(
        "/internal/account-sessions",
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
        json={"user_id": "new-unbound-user"},
    )

    assert response.status_code == 201
    created = response.json()
    created_session = repository.public_account_session(
        hashlib.sha256(created["session_id"].encode()).hexdigest()
    )
    assert created_session is not None
    assert created_session.user_id == "new-unbound-user"
    assert repository.active_wallet_identities("new-unbound-user") == []
    assert repository.active_spending_grants("new-unbound-user", at=clock.value) == []
    assert repository.public_account_session_by_id(old_session_id) is not None
    assert opc.pairing(pairing["pairing_id"]) == pairing_before


def test_cleanup_supports_repository_without_opc_pairings_table(tmp_path) -> None:
    _clock, repository, _account, _opc = _context(tmp_path)
    public_session = _public_session(
        repository, user_id="standalone-user", suffix="without-opc-table"
    )
    _expire_public_session(
        repository,
        public_session.public_account_session_id,
        status="expired",
    )
    with repository.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE opc_pairings")
    assert not inspect(repository.engine).has_table("opc_pairings")

    removed = repository.cleanup_expired_public_account_sessions(NOW)

    assert removed == 1
    assert (
        repository.public_account_session_by_id(public_session.public_account_session_id)
        is None
    )
