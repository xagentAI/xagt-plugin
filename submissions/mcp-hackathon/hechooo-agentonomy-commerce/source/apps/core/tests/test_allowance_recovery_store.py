"""Focused contract tests for durable allowance recovery metadata."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from threading import Barrier

import pytest
from sqlalchemy.dialects import postgresql

from services.account_service.repository import AccountRepository
from services.account_service.schemas import MAX_UINT256, WalletIdentity


NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
NETWORK = "eip155:137"
TOKEN = "0x" + "ab" * 20
SPENDER = "0x" + "cd" * 20
HASH = "0x" + "12" * 32
OTHER_HASH = "0x" + "34" * 32
REQUEST_KEY = "ab" * 32


def _store_class():
    from services.account_service.allowance_recovery import AllowanceRecoveryStore

    return AllowanceRecoveryStore


def _identity(
    wallet_identity_id: str = "wallet-1",
    user_id: str = "user-1",
    status: str = "active",
    address: str = "0x" + "ef" * 20,
) -> WalletIdentity:
    return WalletIdentity(
        wallet_identity_id=wallet_identity_id,
        user_id=user_id,
        wallet_address=address,
        status=status,
        proof_hash="proof",
        verified_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _repository_and_store(tmp_path: Path):
    # Import the model before AccountRepository constructs SQLite metadata.
    store_class = _store_class()
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}")
    identity = _identity()
    repository.save_wallet_identity(identity)
    return repository, store_class(repository), identity


def _begin(store, identity, **overrides):
    values = {
        "user_id": identity.user_id,
        "wallet_identity_id": identity.wallet_identity_id,
        "network": NETWORK,
        "token_address": TOKEN,
        "spender_address": SPENDER,
        "amount_atomic": "2000000",
        "request_key": REQUEST_KEY,
        "now": NOW,
    }
    values.update(overrides)
    return store.begin(**values)


def test_store_module_is_available_before_repository_construction():
    assert importlib.util.find_spec("services.account_service.allowance_recovery") is not None


def test_attempt_persists_across_repository_restart_and_redacts_internal_fields(tmp_path):
    repository, store, identity = _repository_and_store(tmp_path)

    created = _begin(store, identity)
    record = created["attempt"]

    assert created["created"] is True
    assert record["amount_atomic"] == "2000000"
    assert record["token_address"] == TOKEN
    assert record["spender_address"] == SPENDER
    assert record["status"] == "awaiting_wallet"
    assert record["allowance_tx_hash"] is None
    assert record["next_check_at"] is None
    assert "request_key" not in str(record)
    assert "request_key_digest" not in record
    assert "check_count" not in record

    with repository.engine.connect() as connection:
        digest = connection.exec_driver_sql(
            "SELECT request_key_digest FROM allowance_recovery_attempts"
        ).scalar_one()
    assert digest is not None
    assert digest != REQUEST_KEY
    assert len(digest) == 64

    reopened_repository = AccountRepository(
        f"sqlite+pysqlite:///{tmp_path / 'core.sqlite3'}"
    )
    reopened_store = _store_class()(reopened_repository)
    assert reopened_store.get(
        user_id=identity.user_id, attempt_id=record["attempt_id"]
    ) == record


def test_begin_exact_replay_is_idempotent_but_changed_payload_and_open_scope_conflict(
    tmp_path,
):
    _repository, store, identity = _repository_and_store(tmp_path)

    first = _begin(store, identity)
    replay = _begin(store, identity)
    assert replay == {"created": False, "attempt": first["attempt"]}

    with pytest.raises(ValueError, match="conflict") as changed:
        _begin(store, identity, amount_atomic="2000001")
    assert REQUEST_KEY not in str(changed.value)

    with pytest.raises(ValueError, match="conflict"):
        _begin(store, identity, request_key="cd" * 32)


def test_submitted_hash_is_exactly_correlated_immutable_and_terminal_states_do_not_regress(
    tmp_path,
):
    _repository, store, identity = _repository_and_store(tmp_path)
    attempt = _begin(store, identity)["attempt"]

    submitted = store.submitted(
        user_id=identity.user_id,
        attempt_id=attempt["attempt_id"],
        request_key=REQUEST_KEY,
        allowance_tx_hash=HASH.upper(),
        now=NOW,
    )
    assert submitted["status"] == "pending"
    assert submitted["allowance_tx_hash"] == HASH
    assert submitted["next_check_at"] == NOW.isoformat()
    assert store.submitted(
        user_id=identity.user_id,
        attempt_id=attempt["attempt_id"],
        request_key=REQUEST_KEY,
        allowance_tx_hash=HASH,
        now=NOW + timedelta(seconds=1),
    ) == submitted

    with pytest.raises(ValueError, match="conflict"):
        store.submitted(
            user_id=identity.user_id,
            attempt_id=attempt["attempt_id"],
            request_key=REQUEST_KEY,
            allowance_tx_hash=OTHER_HASH,
            now=NOW,
        )
    with pytest.raises(ValueError, match="cannot be rejected"):
        store.rejected(
            user_id=identity.user_id,
            attempt_id=attempt["attempt_id"],
            request_key=REQUEST_KEY,
            now=NOW,
        )

    verified = store.result(
        attempt_id=attempt["attempt_id"],
        status="verified",
        reason_code="rpc_unavailable",
        now=NOW + timedelta(seconds=2),
    )
    assert verified["status"] == "verified"
    assert verified["reason_code"] is None
    assert verified["next_check_at"] is None
    assert store.result(
        attempt_id=attempt["attempt_id"],
        status="pending",
        reason_code="rpc_unavailable",
        now=NOW + timedelta(seconds=3),
    ) == verified


def test_locked_attempt_refreshes_identity_map_after_the_discovery_read(tmp_path):
    repository, store, identity = _repository_and_store(tmp_path)
    attempt = _begin(store, identity)["attempt"]

    # A discovery read is necessary before the identity lock, but it must not
    # leave a stale ORM object in place if the lock waited on another writer.
    with repository.sessions() as session:
        row = store._attempt(session, attempt["attempt_id"])
        assert row.status == "awaiting_wallet"
        row.status = "pending"
        with session.no_autoflush:
            refreshed = store._attempt(session, attempt["attempt_id"], lock=True)
        assert refreshed.status == "awaiting_wallet"


def test_locked_attempt_builds_fresh_postgres_row_lock_statement():
    store_class = _store_class()
    repository = SimpleNamespace(
        engine=SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql"),
        )
    )
    store = store_class(repository)
    captured = {}

    class Session:
        def scalar(self, statement):
            captured["statement"] = statement
            return None

    assert store._attempt(Session(), "attempt-1", lock=True) is None
    statement = captured["statement"]
    assert statement.get_execution_options()["populate_existing"] is True
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))


def test_rejection_requires_matching_key_releases_only_unknown_attempt(tmp_path):
    _repository, store, identity = _repository_and_store(tmp_path)
    attempt = _begin(store, identity)["attempt"]

    with pytest.raises(ValueError, match="unavailable"):
        store.rejected(
            user_id=identity.user_id,
            attempt_id=attempt["attempt_id"],
            request_key="cd" * 32,
            now=NOW,
        )
    rejected = store.rejected(
        user_id=identity.user_id,
        attempt_id=attempt["attempt_id"],
        request_key=REQUEST_KEY,
        now=NOW + timedelta(seconds=1),
    )
    assert rejected["status"] == "rejected"
    assert rejected["allowance_tx_hash"] is None
    assert store.rejected(
        user_id=identity.user_id,
        attempt_id=attempt["attempt_id"],
        request_key=REQUEST_KEY,
        now=NOW + timedelta(seconds=2),
    ) == rejected

    replacement = _begin(store, identity, request_key="ef" * 32)
    assert replacement["created"] is True


def test_records_and_get_are_exact_owner_scoped_without_requiring_active_identity(
    tmp_path,
):
    repository, store, identity = _repository_and_store(tmp_path)
    attempt = _begin(store, identity)["attempt"]
    other = _identity("wallet-2", "user-2", address="0x" + "11" * 20)
    repository.save_wallet_identity(other)

    assert store.records(user_id="user-2", wallet_identity_id=identity.wallet_identity_id) == []
    assert store.get(user_id="user-2", attempt_id=attempt["attempt_id"]) is None
    with pytest.raises(ValueError, match="unavailable"):
        store.submitted(
            user_id="user-2",
            attempt_id=attempt["attempt_id"],
            request_key=REQUEST_KEY,
            allowance_tx_hash=HASH,
            now=NOW,
        )

    repository.revoke_wallet_identity_and_pause_active_grants(identity.wallet_identity_id, NOW)
    assert store.records(user_id=identity.user_id, wallet_identity_id=identity.wallet_identity_id)
    assert store.get(user_id=identity.user_id, attempt_id=attempt["attempt_id"])
    with pytest.raises(ValueError, match="not active"):
        _begin(store, identity, request_key="cd" * 32)


def test_unknown_attempt_never_expires_and_legacy_proof_cannot_claim_it(tmp_path):
    _repository, store, identity = _repository_and_store(tmp_path)
    attempt = _begin(store, identity)["attempt"]

    assert store.due(now=NOW + timedelta(days=365)) == []
    with pytest.raises(ValueError, match="conflict"):
        store.register_proof(
            user_id=identity.user_id,
            wallet_identity_id=identity.wallet_identity_id,
            network=NETWORK,
            token_address=TOKEN,
            spender_address=SPENDER,
            allowance_tx_hash=HASH,
            now=NOW + timedelta(days=365),
        )
    assert store.get(user_id=identity.user_id, attempt_id=attempt["attempt_id"])[
        "allowance_tx_hash"
    ] is None


def test_legacy_proof_is_idempotent_and_stores_null_amount(tmp_path):
    _repository, store, identity = _repository_and_store(tmp_path)
    proof = store.register_proof(
        user_id=identity.user_id,
        wallet_identity_id=identity.wallet_identity_id,
        network=NETWORK,
        token_address=TOKEN,
        spender_address=SPENDER,
        allowance_tx_hash=HASH,
        now=NOW,
    )
    assert proof["amount_atomic"] is None
    assert proof["status"] == "pending"
    assert store.register_proof(
        user_id=identity.user_id,
        wallet_identity_id=identity.wallet_identity_id,
        network=NETWORK,
        token_address=TOKEN,
        spender_address=SPENDER,
        allowance_tx_hash=HASH.upper(),
        now=NOW + timedelta(seconds=1),
    ) == proof
    with pytest.raises(ValueError, match="conflict"):
        store.register_proof(
            user_id=identity.user_id,
            wallet_identity_id=identity.wallet_identity_id,
            network=NETWORK,
            token_address=TOKEN,
            spender_address=SPENDER,
            allowance_tx_hash=OTHER_HASH,
            now=NOW,
        )


def test_due_claim_is_a_lease_and_result_uses_capped_exponential_retry_backoff(tmp_path):
    _repository, store, identity = _repository_and_store(tmp_path)
    attempt = _begin(store, identity)["attempt"]
    submitted = store.submitted(
        user_id=identity.user_id,
        attempt_id=attempt["attempt_id"],
        request_key=REQUEST_KEY,
        allowance_tx_hash=HASH,
        now=NOW,
    )

    claimed = store.due(now=NOW)
    assert [row["attempt_id"] for row in claimed] == [attempt["attempt_id"]]
    assert store.due(now=NOW) == []

    pending = store.result(
        attempt_id=attempt["attempt_id"],
        status="pending",
        reason_code="rpc_unavailable",
        now=NOW,
    )
    assert pending["next_check_at"] == (NOW + timedelta(seconds=3)).isoformat()
    assert store.due(now=NOW + timedelta(seconds=2)) == []
    assert store.due(now=NOW + timedelta(seconds=3))[0]["attempt_id"] == attempt[
        "attempt_id"
    ]

    current = pending
    current_time = NOW + timedelta(seconds=3)
    for _ in range(8):
        current = store.result(
            attempt_id=attempt["attempt_id"],
            status="pending",
            reason_code="chain_pending",
            now=current_time,
        )
        current_time += timedelta(seconds=1)
    assert (
        datetime.fromisoformat(current["next_check_at"]) - current_time
    ).total_seconds() == 299

    # A new store instance sees the same durable record and lease state.
    assert store.get(user_id=identity.user_id, attempt_id=attempt["attempt_id"])[
        "status"
    ] == "pending"


def test_retry_backoff_caps_before_exponentiating_a_large_persisted_count(tmp_path):
    repository, store, identity = _repository_and_store(tmp_path)
    attempt = _begin(store, identity)["attempt"]
    store.submitted(
        user_id=identity.user_id,
        attempt_id=attempt["attempt_id"],
        request_key=REQUEST_KEY,
        allowance_tx_hash=HASH,
        now=NOW,
    )

    from services.account_service.allowance_recovery import AllowanceRecoveryRow

    with repository._write_session() as session:
        row = session.get(AllowanceRecoveryRow, attempt["attempt_id"])
        row.check_count = 2**63 - 2

    pending = store.result(
        attempt_id=attempt["attempt_id"],
        status="pending",
        reason_code="chain_pending",
        now=NOW + timedelta(seconds=1),
    )
    assert pending["next_check_at"] == (NOW + timedelta(seconds=301)).isoformat()
    with repository.sessions() as session:
        row = session.get(AllowanceRecoveryRow, attempt["attempt_id"])
        assert row.check_count == 2**63 - 1


def test_concurrent_begin_serializes_on_wallet_identity(tmp_path):
    store_class = _store_class()
    database_url = f"sqlite+pysqlite:///{tmp_path / 'concurrent.sqlite3'}"
    first_repository = AccountRepository(database_url)
    identity = _identity()
    first_repository.save_wallet_identity(identity)
    second_repository = AccountRepository(database_url)
    stores = [store_class(first_repository), store_class(second_repository)]
    barrier = Barrier(2)

    def create(store):
        barrier.wait()
        try:
            request_key = "cd" * 32 if store is stores[0] else "ef" * 32
            return ("created", _begin(store, identity, request_key=request_key))
        except ValueError as exc:
            return ("error", str(exc))

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(create, stores))
    assert [kind for kind, _value in outcomes].count("created") == 1
    assert [kind for kind, _value in outcomes].count("error") == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("network", "eip155:1"),
        ("token_address", "0x" + "99" * 19),
        ("spender_address", "0x" + "gg" * 20),
        ("amount_atomic", "0"),
        ("amount_atomic", "01"),
        ("amount_atomic", str(MAX_UINT256 + 1)),
        ("request_key", "AB" * 32),
    ],
)
def test_begin_rejects_noncanonical_or_nonpositive_inputs(tmp_path, field, value):
    _repository, store, identity = _repository_and_store(tmp_path)
    with pytest.raises(ValueError):
        _begin(store, identity, **{field: value})


def test_records_are_newest_first_and_bounded_to_twenty(tmp_path):
    _repository, store, identity = _repository_and_store(tmp_path)
    for index in range(21):
        token = "0x" + f"{index + 1:040x}"
        _begin(
            store,
            identity,
            token_address=token,
            request_key=f"{index + 1:064x}",
            now=NOW + timedelta(seconds=index),
        )
    rows = store.records(
        user_id=identity.user_id, wallet_identity_id=identity.wallet_identity_id
    )
    # Open records are never hidden by the terminal-history cap.
    assert len(rows) == 21
    assert rows[0]["created_at"] == (NOW + timedelta(seconds=20)).isoformat()


def test_records_keep_old_open_attempt_visible_ahead_of_terminal_history(tmp_path):
    _repository, store, identity = _repository_and_store(tmp_path)
    old_open = _begin(store, identity)["attempt"]
    for index in range(21):
        token = "0x" + f"{index + 1:040x}"
        request_key = f"{index + 1:064x}"
        attempt = _begin(
            store,
            identity,
            token_address=token,
            request_key=request_key,
            now=NOW + timedelta(seconds=index + 1),
        )["attempt"]
        store.rejected(
            user_id=identity.user_id,
            attempt_id=attempt["attempt_id"],
            request_key=request_key,
            now=NOW + timedelta(seconds=index + 1),
        )

    rows = store.records(
        user_id=identity.user_id, wallet_identity_id=identity.wallet_identity_id
    )
    assert rows[0]["attempt_id"] == old_open["attempt_id"]
    assert rows[0]["status"] == "awaiting_wallet"
    assert len(rows) == 21
    assert all(row["status"] == "rejected" for row in rows[1:])
