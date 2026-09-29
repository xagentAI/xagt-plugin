from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

import services.account_service.repository as account_repository_module
from services.account_service import (
    AccountRepository,
    SpendingGrant,
    WalletIdentity,
)
from services.account_service.repository import (
    AccountSessionRow,
    AccountWalletBootstrapStateRow,
    PublicAccountSessionRow,
    SpendingGrantRow,
    sqlite_immediate_session,
)
from services.account_service.schemas import PublicAccountSession
from services.account_service.service import AccountService
from services.audit_service.service import AuditService


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
DOMAIN = "accounts.clink.example"


class Clock:
    def __init__(self, value: datetime = NOW):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def wallet_account():
    return Account.create()


@pytest.fixture
def service(tmp_path):
    clock = Clock()
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'core.db'}")
    account_service = AccountService(repository, domain=DOMAIN, clock=clock)
    create_wallet_challenge = account_service.create_wallet_challenge
    session_number = 0

    def create_bound_wallet_challenge(user_id, wallet_address, *args, **kwargs):
        """Give legacy unit scenarios a real browser session, never an unbound bypass."""
        nonlocal session_number
        if kwargs.get("created_by_public_account_session_id") is None:
            session_number += 1
            public_session = _public_session(
                repository,
                user_id,
                label=f"fixture-{session_number}",
            )
            kwargs["created_by_public_account_session_id"] = (
                public_session.public_account_session_id
            )
        return create_wallet_challenge(user_id, wallet_address, *args, **kwargs)

    account_service.create_wallet_challenge = create_bound_wallet_challenge
    return account_service, clock, repository


def _signature(account, message: str) -> str:
    return Account.sign_message(encode_defunct(text=message), account.key).signature.hex()


def _public_session(
    repository: AccountRepository, user_id: str, *, label: str
) -> PublicAccountSession:
    digest = hashlib.sha256(label.encode()).hexdigest()
    session = PublicAccountSession(
        public_account_session_id=f"public_{label}",
        token_digest=digest,
        browser_session_digest=hashlib.sha256(f"browser:{label}".encode()).hexdigest(),
        csrf_token_digest=hashlib.sha256(f"csrf:{label}".encode()).hexdigest(),
        user_id=user_id,
        expires_at=NOW + timedelta(minutes=30),
        exchanged_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    return repository.create_public_account_session(session)


def _concurrent_outcomes(*operations):
    barrier = Barrier(len(operations))

    def execute(operation):
        barrier.wait()
        try:
            return "success", operation()
        except ValueError as exc:
            return "error", str(exc)

    with ThreadPoolExecutor(max_workers=len(operations)) as executor:
        return [future.result() for future in [executor.submit(execute, op) for op in operations]]


def test_sqlite_immediate_session_retries_a_locked_commit(tmp_path, monkeypatch):
    database_path = tmp_path / "locked-commit.sqlite3"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}", connect_args={"timeout": 0}
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=DELETE")
        connection.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)"))

    sessions = sessionmaker(engine, expire_on_commit=False)
    reader = sessions()
    reader.connection().exec_driver_sql("BEGIN")
    reader.execute(text("SELECT * FROM items")).all()
    sleeps = []

    def release_reader(delay):
        sleeps.append(delay)
        if len(sleeps) == 1:
            reader.rollback()

    monkeypatch.setattr(account_repository_module.time, "sleep", release_reader)
    try:
        with sqlite_immediate_session(sessions, operation="test transaction") as session:
            session.execute(text("INSERT INTO items (value) VALUES ('committed')"))
    finally:
        reader.close()

    assert sleeps
    with engine.connect() as connection:
        assert connection.execute(text("SELECT value FROM items")).all() == [
            ("committed",)
        ]


def test_sqlite_immediate_session_rolls_back_after_locked_commit_exhaustion(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "locked-commit-exhausted.sqlite3"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}", connect_args={"timeout": 0}
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=DELETE")
        connection.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)"))

    sessions = sessionmaker(engine, expire_on_commit=False)
    reader = sessions()
    reader.connection().exec_driver_sql("BEGIN")
    reader.execute(text("SELECT * FROM items")).all()
    sleeps = []
    monkeypatch.setattr(
        account_repository_module.time, "sleep", lambda delay: sleeps.append(delay)
    )

    try:
        with pytest.raises(OperationalError, match="database is locked"):
            with sqlite_immediate_session(sessions, operation="test transaction") as session:
                session.execute(text("INSERT INTO items (value) VALUES ('rolled back')"))
    finally:
        reader.rollback()
        reader.close()

    assert len(sleeps) == 4
    with engine.connect() as connection:
        assert connection.execute(text("SELECT * FROM items")).all() == []

    with sqlite_immediate_session(sessions, operation="test transaction") as session:
        session.execute(text("INSERT INTO items (value) VALUES ('after release')"))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT value FROM items")).all() == [
            ("after release",)
        ]


def _active_grant(wallet_identity_id: str, now: datetime) -> SpendingGrant:
    return SpendingGrant(
        spending_grant_id="grant_1",
        wallet_identity_id=wallet_identity_id,
        user_id="u",
        agent_id="hermes",
        status="active",
        max_amount_usdc=Decimal("10"),
        per_transaction_limit_usdc=Decimal("2"),
        daily_limit_usdc=Decimal("5"),
        product_scopes=["marketplace"],
        network_scopes=["eip155:8453"],
        asset_scopes=["0x" + "1" * 40],
        starts_at=now,
        expires_at=now + timedelta(days=1),
        created_at=now,
        updated_at=now,
    )


def test_wallet_challenge_message_is_canonical_and_verifies_identity(service, wallet_account):
    account_service, _clock, repository = service

    challenge = account_service.create_wallet_challenge("u", wallet_account.address)
    signature = _signature(wallet_account, challenge.message_to_sign)
    identity = account_service.verify_wallet_challenge(
        challenge.session_id, challenge.message_to_sign, signature
    )

    assert challenge.expires_at.tzinfo is not None
    assert challenge.message_to_sign == (
        "Clink Wallet Identity\n"
        f"Domain: {DOMAIN}\n"
        "User ID: u\n"
        f"Wallet Address: {wallet_account.address.lower()}\n"
        f"Session ID: {challenge.session_id}\n"
        "Nonce: " + challenge.nonce + "\n"
        "Issued At: 2026-07-15T12:00:00Z\n"
        "Expiration Time: 2026-07-15T12:10:00Z\n"
        "Purpose: clink_wallet_identity"
    )
    assert identity.status == "active"
    assert identity.wallet_address == wallet_account.address.lower()
    assert identity.proof_hash == "0x" + keccak(bytes.fromhex(signature)).hex()
    assert identity.proof_hash != signature
    assert repository.active_wallet_identities("u") == [identity]
    events = AuditService(database_url=str(repository.engine.url)).get_trail(
        user_id="u"
    ).events
    assert [(event.event_type, event.payload["wallet_identity_id"]) for event in events] == [
        ("wallet_verified", identity.wallet_identity_id)
    ]


def test_wallet_challenge_requires_the_creating_public_session(service, wallet_account):
    _account_service, clock, repository = service
    account_service = AccountService(repository, domain=DOMAIN, clock=clock)

    with pytest.raises(ValueError, match="public account session binding"):
        account_service.create_wallet_challenge("u", wallet_account.address)


def test_database_rejects_an_unbound_wallet_identity_challenge(service):
    _account_service, _clock, repository = service

    with pytest.raises(IntegrityError):
        with repository.sessions.begin() as session:
            session.add(
                AccountSessionRow(
                    account_session_id="unbound_wallet_challenge",
                    user_id="u",
                    wallet_address="0x" + "1" * 40,
                    nonce="unbound-wallet-challenge-nonce",
                    domain=DOMAIN,
                    purpose="clink_wallet_identity",
                    wallet_identity_id=None,
                    created_by_public_account_session_id=None,
                    payload=None,
                    payload_hash=None,
                    expires_at=NOW + timedelta(minutes=10),
                    consumed_at=None,
                    created_at=NOW,
                )
            )


def test_wallet_verification_authenticates_only_the_creating_public_session(
    service, wallet_account
):
    account_service, _clock, repository = service
    creating_session = _public_session(repository, "u", label="creating")
    other_session = _public_session(repository, "u", label="other")
    challenge = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
        created_by_public_account_session_id=creating_session.public_account_session_id,
    )

    identity = account_service.verify_wallet_challenge(
        challenge.session_id,
        challenge.message_to_sign,
        _signature(wallet_account, challenge.message_to_sign),
    )

    with repository.sessions() as session:
        creating = session.get(
            PublicAccountSessionRow, creating_session.public_account_session_id
        )
        other = session.get(PublicAccountSessionRow, other_session.public_account_session_id)
    assert creating.authenticated_wallet_identity_id == identity.wallet_identity_id
    assert creating.authenticated_at.replace(tzinfo=UTC) == NOW
    assert other.authenticated_wallet_identity_id is None


def test_wallet_verification_rejects_a_revoked_creating_public_session(
    service, wallet_account
):
    account_service, _clock, repository = service
    creating_session = _public_session(repository, "u", label="revoked-origin")
    challenge = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
        created_by_public_account_session_id=creating_session.public_account_session_id,
    )
    repository.revoke_public_account_session(creating_session.token_digest, NOW)

    with pytest.raises(ValueError, match="creating public account session"):
        account_service.verify_wallet_challenge(
            challenge.session_id,
            challenge.message_to_sign,
            _signature(wallet_account, challenge.message_to_sign),
        )

    assert repository.active_wallet_identities("u") == []
    assert repository.account_session(challenge.session_id).consumed_at is None


def test_wallet_verification_and_creating_session_revoke_are_serialized(
    service, wallet_account
):
    account_service, _clock, repository = service
    creating_session = _public_session(repository, "u", label="concurrent-origin")
    challenge = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
        created_by_public_account_session_id=creating_session.public_account_session_id,
    )

    outcomes = _concurrent_outcomes(
        lambda: account_service.verify_wallet_challenge(
            challenge.session_id,
            challenge.message_to_sign,
            _signature(wallet_account, challenge.message_to_sign),
        ),
        lambda: repository.revoke_public_account_session(
            creating_session.token_digest, NOW
        ),
    )

    verification_outcome, verification_value = outcomes[0]
    persisted_challenge = repository.account_session(challenge.session_id)
    persisted_session = repository.public_account_session(creating_session.token_digest)
    assert persisted_session.status == "revoked"
    if verification_outcome == "success":
        assert persisted_challenge.consumed_at == NOW
        assert repository.active_wallet_identities("u") == [verification_value]
        assert (
            persisted_session.authenticated_wallet_identity_id
            == verification_value.wallet_identity_id
        )
    else:
        assert "creating public account session" in verification_value
        assert persisted_challenge.consumed_at is None
        assert repository.active_wallet_identities("u") == []


def test_wallet_challenge_rejects_wrong_signer(service, wallet_account):
    account_service, _clock, _repository = service
    challenge = account_service.create_wallet_challenge("u", wallet_account.address)

    with pytest.raises(ValueError, match="does not match"):
        account_service.verify_wallet_challenge(
            challenge.session_id, challenge.message_to_sign, _signature(Account.create(), challenge.message_to_sign)
        )


def test_wallet_challenge_rejects_altered_message(service, wallet_account):
    account_service, _clock, _repository = service
    challenge = account_service.create_wallet_challenge("u", wallet_account.address)
    signature = _signature(wallet_account, challenge.message_to_sign)

    with pytest.raises(ValueError, match="message does not match"):
        account_service.verify_wallet_challenge(
            challenge.session_id, challenge.message_to_sign + "\nextra", signature
        )


def test_wallet_challenge_rejects_expired_session(service, wallet_account):
    account_service, clock, _repository = service
    challenge = account_service.create_wallet_challenge("u", wallet_account.address)
    clock.value = challenge.expires_at

    with pytest.raises(ValueError, match="expired"):
        account_service.verify_wallet_challenge(
            challenge.session_id, challenge.message_to_sign, _signature(wallet_account, challenge.message_to_sign)
        )


def test_wallet_challenge_cannot_be_replayed(service, wallet_account):
    account_service, _clock, _repository = service
    challenge = account_service.create_wallet_challenge("u", wallet_account.address)
    signature = _signature(wallet_account, challenge.message_to_sign)

    account_service.verify_wallet_challenge(challenge.session_id, challenge.message_to_sign, signature)

    with pytest.raises(ValueError, match="already consumed"):
        account_service.verify_wallet_challenge(challenge.session_id, challenge.message_to_sign, signature)


def test_wallet_challenge_cannot_be_replayed_for_another_user(service, wallet_account):
    account_service, _clock, repository = service
    first = account_service.create_wallet_challenge("first-user", wallet_account.address)
    second = account_service.create_wallet_challenge("second-user", wallet_account.address)
    signature = _signature(wallet_account, first.message_to_sign)

    with pytest.raises(ValueError, match="message does not match"):
        account_service.verify_wallet_challenge(second.session_id, first.message_to_sign, signature)

    assert repository.active_wallet_identities("second-user") == []


def test_wallet_challenge_rejects_service_domain_mismatch(service, wallet_account):
    account_service, clock, repository = service
    challenge = account_service.create_wallet_challenge("u", wallet_account.address)
    mismatched_domain_service = AccountService(repository, domain="other.clink.example", clock=clock)

    with pytest.raises(ValueError, match="domain mismatch"):
        mismatched_domain_service.verify_wallet_challenge(
            challenge.session_id,
            challenge.message_to_sign,
            _signature(wallet_account, challenge.message_to_sign),
        )


@pytest.mark.parametrize("user_id", ["u\nrole=admin", "u\rrole=admin", "u\x00role=admin"])
def test_wallet_challenge_rejects_control_characters_in_user_id(service, wallet_account, user_id):
    account_service, _clock, _repository = service

    with pytest.raises(ValueError, match="control characters"):
        account_service.create_wallet_challenge(user_id, wallet_account.address)


@pytest.mark.parametrize("domain", ["accounts\n.attacker.example", "accounts\r.attacker.example"])
def test_wallet_challenge_rejects_control_characters_in_domain(service, domain):
    _account_service, clock, repository = service

    with pytest.raises(ValueError, match="control characters"):
        AccountService(repository, domain=domain, clock=clock)


def test_active_identity_is_idempotent_for_a_new_valid_challenge(service, wallet_account):
    account_service, _clock, _repository = service
    first = account_service.create_wallet_challenge("u", wallet_account.address)
    identity = account_service.verify_wallet_challenge(
        first.session_id, first.message_to_sign, _signature(wallet_account, first.message_to_sign)
    )
    second = account_service.create_wallet_challenge("u", wallet_account.address)

    repeated = account_service.verify_wallet_challenge(
        second.session_id, second.message_to_sign, _signature(wallet_account, second.message_to_sign)
    )

    assert repeated == identity


def test_cancel_wallet_login_challenge_is_idempotent_and_prevents_verification(
    service,
    wallet_account,
):
    account_service, clock, repository = service
    challenge = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
    )
    stored = repository.account_session(challenge.session_id)

    assert account_service.cancel_wallet_challenge(
        challenge.session_id,
        user_id="u",
        public_account_session_id=(
            stored.created_by_public_account_session_id
        ),
    ) is True
    assert account_service.cancel_wallet_challenge(
        challenge.session_id,
        user_id="u",
        public_account_session_id=(
            stored.created_by_public_account_session_id
        ),
    ) is True

    with pytest.raises(ValueError, match="wallet challenge already consumed"):
        account_service.verify_wallet_challenge(
            challenge.session_id,
            challenge.message_to_sign,
            _signature(wallet_account, challenge.message_to_sign),
        )
    with repository.sessions() as session:
        consumed_at = session.get(
            AccountSessionRow,
            challenge.session_id,
        ).consumed_at
        assert consumed_at.replace(tzinfo=UTC) == clock()


def test_cancel_wallet_login_challenge_rejects_another_browser_session(
    service,
    wallet_account,
):
    account_service, _clock, repository = service
    challenge = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
    )
    other_session = _public_session(
        repository,
        "u",
        label="challenge-cancel-other",
    )

    assert account_service.cancel_wallet_challenge(
        challenge.session_id,
        user_id="u",
        public_account_session_id=(
            other_session.public_account_session_id
        ),
    ) is False
    assert repository.account_session(challenge.session_id).consumed_at is None


def test_active_identity_blocks_an_additional_wallet_login(
    service,
    wallet_account,
):
    account_service, _clock, repository = service
    first = account_service.create_wallet_challenge("u", wallet_account.address)
    authorizer = account_service.verify_wallet_challenge(
        first.session_id,
        first.message_to_sign,
        _signature(wallet_account, first.message_to_sign),
    )
    additional_wallet = Account.create()
    additional = account_service.create_wallet_challenge(
        "u",
        additional_wallet.address,
        authorizing_wallet_identity_id=authorizer.wallet_identity_id,
    )

    with pytest.raises(
        ValueError,
        match="disconnect the active wallet before signing in",
    ):
        account_service.verify_wallet_challenge(
            additional.session_id,
            additional.message_to_sign,
            _signature(additional_wallet, additional.message_to_sign),
        )

    assert repository.active_wallet_identities("u") == [authorizer]


def test_additional_wallet_requires_an_authenticated_authorizer(
    service, wallet_account
):
    account_service, _clock, repository = service
    first = account_service.create_wallet_challenge("u", wallet_account.address)
    authorizer = account_service.verify_wallet_challenge(
        first.session_id,
        first.message_to_sign,
        _signature(wallet_account, first.message_to_sign),
    )
    additional_wallet = Account.create()
    additional = account_service.create_wallet_challenge(
        "u", additional_wallet.address
    )

    with pytest.raises(
        ValueError,
        match="disconnect the active wallet before signing in",
    ):
        account_service.verify_wallet_challenge(
            additional.session_id,
            additional.message_to_sign,
            _signature(additional_wallet, additional.message_to_sign),
        )

    assert repository.active_wallet_identities("u") == [authorizer]


@pytest.mark.parametrize("status", ["revoked", "suspended"])
def test_nonactive_authorizer_cannot_activate_an_additional_wallet(
    service, wallet_account, status
):
    account_service, clock, repository = service
    first = account_service.create_wallet_challenge("u", wallet_account.address)
    authorizer = account_service.verify_wallet_challenge(
        first.session_id,
        first.message_to_sign,
        _signature(wallet_account, first.message_to_sign),
    )
    additional_wallet = Account.create()
    additional = account_service.create_wallet_challenge(
        "u",
        additional_wallet.address,
        authorizing_wallet_identity_id=authorizer.wallet_identity_id,
    )
    repository.save_wallet_identity(
        authorizer.model_copy(update={"status": status, "updated_at": clock()})
    )

    with pytest.raises(
        ValueError,
        match=(
            "wallet identity is not active"
            if status == "revoked"
            else "disconnect the active wallet before signing in"
        ),
    ):
        account_service.verify_wallet_challenge(
            additional.session_id,
            additional.message_to_sign,
            _signature(additional_wallet, additional.message_to_sign),
        )

    assert repository.active_wallet_identities("u") == []


@pytest.mark.parametrize("status", ["revoked", "suspended"])
def test_nonactive_existing_identity_cannot_bootstrap_a_different_wallet(
    service, wallet_account, status
):
    account_service, clock, repository = service
    first = account_service.create_wallet_challenge("u", wallet_account.address)
    original = account_service.verify_wallet_challenge(
        first.session_id, first.message_to_sign, _signature(wallet_account, first.message_to_sign)
    )
    repository.save_wallet_identity(
        original.model_copy(update={"status": status, "updated_at": clock()})
    )
    attacker = Account.create()
    challenge = account_service.create_wallet_challenge("u", attacker.address)

    with pytest.raises(
        ValueError,
        match=(
            "wallet identity is not active"
            if status == "revoked"
            else "disconnect the active wallet before signing in"
        ),
    ):
        account_service.verify_wallet_challenge(
            challenge.session_id,
            challenge.message_to_sign,
            _signature(attacker, challenge.message_to_sign),
        )

    assert repository.active_wallet_identities("u") == []
    assert repository.bootstrap_wallet_identity_id("u") == original.wallet_identity_id


def test_concurrent_different_first_wallet_proofs_activate_exactly_one_identity(service):
    account_service, _clock, repository = service
    first_wallet = Account.create()
    second_wallet = Account.create()
    first = account_service.create_wallet_challenge("u", first_wallet.address)
    second = account_service.create_wallet_challenge("u", second_wallet.address)

    outcomes = _concurrent_outcomes(
        lambda: account_service.verify_wallet_challenge(
            first.session_id,
            first.message_to_sign,
            _signature(first_wallet, first.message_to_sign),
        ),
        lambda: account_service.verify_wallet_challenge(
            second.session_id,
            second.message_to_sign,
            _signature(second_wallet, second.message_to_sign),
        ),
    )

    successes = [value for outcome, value in outcomes if outcome == "success"]
    assert len(successes) == 1
    assert [message for outcome, message in outcomes if outcome == "error"] == [
        "disconnect the active wallet before signing in"
    ]
    assert repository.active_wallet_identities("u") == successes
    assert repository.bootstrap_wallet_identity_id("u") == successes[0].wallet_identity_id


def test_revoking_identity_pauses_all_active_grants_atomically(service, wallet_account):
    account_service, clock, repository = service
    challenge = account_service.create_wallet_challenge("u", wallet_account.address)
    identity = account_service.verify_wallet_challenge(
        challenge.session_id, challenge.message_to_sign, _signature(wallet_account, challenge.message_to_sign)
    )
    repository.save_spending_grant(_active_grant(identity.wallet_identity_id, clock()))

    revoked = account_service.revoke_wallet_identity(identity.wallet_identity_id)

    assert revoked.status == "revoked"
    assert repository.active_spending_grants("u", clock()) == []
    with repository.sessions() as session:
        grant = session.get(SpendingGrantRow, "grant_1")
    assert grant.status == "paused"
    assert grant.status_reason == "wallet_identity_revoked"
    events = AuditService(database_url=str(repository.engine.url)).get_trail(
        user_id="u"
    ).events
    assert [event.event_type for event in events] == [
        "wallet_verified",
        "grant_paused",
        "wallet_revoked",
    ]


def test_disconnect_last_wallet_locks_sessions_invalidates_challenges_and_opens_rebind(
    service,
    wallet_account,
):
    account_service, clock, repository = service
    first_public_session = _public_session(
        repository,
        "u",
        label="disconnect-reset-first",
    )
    first = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
        created_by_public_account_session_id=(
            first_public_session.public_account_session_id
        ),
    )
    owner = account_service.verify_wallet_challenge(
        first.session_id,
        first.message_to_sign,
        _signature(wallet_account, first.message_to_sign),
    )
    second_public_session = _public_session(
        repository,
        "u",
        label="disconnect-reset-second",
    )
    second = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
        created_by_public_account_session_id=(
            second_public_session.public_account_session_id
        ),
    )
    assert account_service.verify_wallet_challenge(
        second.session_id,
        second.message_to_sign,
        _signature(wallet_account, second.message_to_sign),
    ).wallet_identity_id == owner.wallet_identity_id
    pending = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
        created_by_public_account_session_id=(
            first_public_session.public_account_session_id
        ),
    )

    repository.disconnect_wallet_identity(
        owner.wallet_identity_id,
        clock(),
    )

    with repository.sessions() as session:
        stored_first_session = session.get(
            PublicAccountSessionRow,
            first_public_session.public_account_session_id,
        )
        stored_second_session = session.get(
            PublicAccountSessionRow,
            second_public_session.public_account_session_id,
        )
        stored_challenge = session.get(
            AccountSessionRow,
            pending.session_id,
        )
        bootstrap = session.get(
            AccountWalletBootstrapStateRow,
            "u",
        )
        assert stored_first_session.authenticated_wallet_identity_id is None
        assert stored_first_session.authenticated_at is None
        assert stored_second_session.authenticated_wallet_identity_id is None
        assert stored_second_session.authenticated_at is None
        assert stored_challenge.consumed_at is not None
        assert bootstrap.binding_state == "unbound"
        assert bootstrap.binding_generation == 1
        assert bootstrap.unbound_at is not None

    events = AuditService(database_url=str(repository.engine.url)).get_trail(
        user_id="u"
    ).events
    assert [event.event_type for event in events][-2:] == [
        "wallet_revoked",
        "wallet_binding_reset",
    ]


def test_repeated_disconnect_does_not_advance_wallet_binding_generation(
    service,
    wallet_account,
):
    account_service, clock, repository = service
    challenge = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
    )
    identity = account_service.verify_wallet_challenge(
        challenge.session_id,
        challenge.message_to_sign,
        _signature(wallet_account, challenge.message_to_sign),
    )

    repository.disconnect_wallet_identity(identity.wallet_identity_id, clock())
    repository.disconnect_wallet_identity(identity.wallet_identity_id, clock())

    with repository.sessions() as session:
        bootstrap = session.get(AccountWalletBootstrapStateRow, "u")
        assert bootstrap.binding_state == "unbound"
        assert bootstrap.binding_generation == 1


def test_disconnect_rolls_back_identity_grants_sessions_challenges_and_bootstrap(
    service,
    wallet_account,
    monkeypatch,
):
    account_service, clock, repository = service
    public_session = _public_session(
        repository,
        "u",
        label="disconnect-rollback",
    )
    challenge = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
        created_by_public_account_session_id=(
            public_session.public_account_session_id
        ),
    )
    identity = account_service.verify_wallet_challenge(
        challenge.session_id,
        challenge.message_to_sign,
        _signature(wallet_account, challenge.message_to_sign),
    )
    repository.save_spending_grant(
        _active_grant(identity.wallet_identity_id, clock())
    )
    pending = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
        created_by_public_account_session_id=(
            public_session.public_account_session_id
        ),
    )
    append_audit = repository._append_account_audit

    def fail_binding_reset_audit(*args, **kwargs):
        if kwargs.get("event_type") == "wallet_binding_reset":
            raise RuntimeError("audit insert failed")
        return append_audit(*args, **kwargs)

    monkeypatch.setattr(
        repository,
        "_append_account_audit",
        fail_binding_reset_audit,
    )

    with pytest.raises(RuntimeError, match="audit insert failed"):
        repository.disconnect_wallet_identity(
            identity.wallet_identity_id,
            clock(),
        )

    assert repository.wallet_identity(identity.wallet_identity_id).status == "active"
    assert repository.spending_grant("grant_1").status == "active"
    with repository.sessions() as session:
        stored_public_session = session.get(
            PublicAccountSessionRow,
            public_session.public_account_session_id,
        )
        stored_challenge = session.get(
            AccountSessionRow,
            pending.session_id,
        )
        bootstrap = session.get(AccountWalletBootstrapStateRow, "u")
        assert stored_public_session.authenticated_wallet_identity_id == (
            identity.wallet_identity_id
        )
        assert stored_challenge.consumed_at is None
        assert bootstrap.binding_state == "bound"
        assert bootstrap.binding_generation == 0
        assert bootstrap.unbound_at is None


def test_same_address_rebind_creates_new_identity_generation_without_old_grants(
    service,
    wallet_account,
):
    account_service, clock, repository = service
    first_challenge = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
    )
    first_identity = account_service.verify_wallet_challenge(
        first_challenge.session_id,
        first_challenge.message_to_sign,
        _signature(
            wallet_account,
            first_challenge.message_to_sign,
        ),
    )
    repository.save_spending_grant(
        _active_grant(first_identity.wallet_identity_id, clock())
    )
    repository.disconnect_wallet_identity(
        first_identity.wallet_identity_id,
        clock(),
    )

    second_challenge = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
    )
    second_identity = account_service.verify_wallet_challenge(
        second_challenge.session_id,
        second_challenge.message_to_sign,
        _signature(
            wallet_account,
            second_challenge.message_to_sign,
        ),
    )

    assert (
        second_identity.wallet_identity_id
        != first_identity.wallet_identity_id
    )
    assert repository.wallet_identity(
        first_identity.wallet_identity_id
    ).status == "revoked"
    assert repository.wallet_identity(
        second_identity.wallet_identity_id
    ).status == "active"
    assert repository.spending_grant("grant_1").status == "revoked"
    assert repository.active_spending_grants("u", clock()) == []
    events = AuditService(database_url=str(repository.engine.url)).get_trail(
        user_id="u"
    ).events
    assert events[-1].event_type == "wallet_verified"
    assert events[-1].payload["binding_generation"] == 1
    assert events[-1].payload["rebind"] is True


def test_unbound_account_can_rebind_a_different_wallet_address(
    service,
    wallet_account,
):
    account_service, clock, repository = service
    first_challenge = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
    )
    first_identity = account_service.verify_wallet_challenge(
        first_challenge.session_id,
        first_challenge.message_to_sign,
        _signature(wallet_account, first_challenge.message_to_sign),
    )
    repository.disconnect_wallet_identity(
        first_identity.wallet_identity_id,
        clock(),
    )
    replacement_wallet = Account.create()
    replacement_challenge = account_service.create_wallet_challenge(
        "u",
        replacement_wallet.address,
    )

    replacement_identity = account_service.verify_wallet_challenge(
        replacement_challenge.session_id,
        replacement_challenge.message_to_sign,
        _signature(
            replacement_wallet,
            replacement_challenge.message_to_sign,
        ),
    )

    assert replacement_identity.wallet_address == replacement_wallet.address.lower()
    assert replacement_identity.wallet_identity_id != first_identity.wallet_identity_id
    assert repository.active_wallet_identities("u") == [replacement_identity]
    with repository.sessions() as session:
        bootstrap = session.get(AccountWalletBootstrapStateRow, "u")
        assert bootstrap.first_wallet_identity_id == (
            first_identity.wallet_identity_id
        )
        assert bootstrap.binding_state == "bound"
        assert bootstrap.binding_generation == 1
        assert bootstrap.unbound_at is None


def test_concurrent_same_address_rebind_challenges_create_one_active_generation(
    service,
    wallet_account,
):
    account_service, clock, repository = service
    first_challenge = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
    )
    first_identity = account_service.verify_wallet_challenge(
        first_challenge.session_id,
        first_challenge.message_to_sign,
        _signature(wallet_account, first_challenge.message_to_sign),
    )
    repository.disconnect_wallet_identity(
        first_identity.wallet_identity_id,
        clock(),
    )
    first_rebind = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
    )
    second_rebind = account_service.create_wallet_challenge(
        "u",
        wallet_account.address,
    )

    outcomes = _concurrent_outcomes(
        lambda: account_service.verify_wallet_challenge(
            first_rebind.session_id,
            first_rebind.message_to_sign,
            _signature(wallet_account, first_rebind.message_to_sign),
        ),
        lambda: account_service.verify_wallet_challenge(
            second_rebind.session_id,
            second_rebind.message_to_sign,
            _signature(wallet_account, second_rebind.message_to_sign),
        ),
    )

    assert [outcome for outcome, _ in outcomes] == ["success", "success"]
    assert outcomes[0][1].wallet_identity_id == outcomes[1][1].wallet_identity_id
    assert outcomes[0][1].wallet_identity_id != first_identity.wallet_identity_id
    assert repository.active_wallet_identities("u") == [outcomes[0][1]]


def test_account_mutation_rolls_back_when_atomic_audit_write_fails(
    service, wallet_account, monkeypatch
):
    account_service, clock, repository = service
    challenge = account_service.create_wallet_challenge("u", wallet_account.address)
    identity = account_service.verify_wallet_challenge(
        challenge.session_id,
        challenge.message_to_sign,
        _signature(wallet_account, challenge.message_to_sign),
    )
    repository.save_spending_grant(_active_grant(identity.wallet_identity_id, clock()))

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("audit insert failed")

    monkeypatch.setattr(repository, "_append_account_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit insert failed"):
        account_service.pause_spending_grant("grant_1")

    assert repository.spending_grant("grant_1").status == "active"


def test_concurrent_verification_consumes_one_session_once(service, wallet_account):
    account_service, _clock, repository = service
    challenge = account_service.create_wallet_challenge("u", wallet_account.address)
    signature = _signature(wallet_account, challenge.message_to_sign)

    outcomes = _concurrent_outcomes(
        lambda: account_service.verify_wallet_challenge(
            challenge.session_id, challenge.message_to_sign, signature
        ),
        lambda: account_service.verify_wallet_challenge(
            challenge.session_id, challenge.message_to_sign, signature
        ),
    )

    assert [outcome for outcome, _ in outcomes].count("success") == 1
    assert [message for outcome, message in outcomes if outcome == "error"] == [
        "wallet challenge already consumed"
    ]
    assert len(repository.active_wallet_identities("u")) == 1
    with repository.sessions() as session:
        assert session.get(AccountSessionRow, challenge.session_id).consumed_at is not None


def test_concurrent_challenges_reuse_one_identity_and_consume_both_sessions(service, wallet_account):
    account_service, _clock, repository = service
    first = account_service.create_wallet_challenge("u", wallet_account.address)
    second = account_service.create_wallet_challenge("u", wallet_account.address)

    outcomes = _concurrent_outcomes(
        lambda: account_service.verify_wallet_challenge(
            first.session_id, first.message_to_sign, _signature(wallet_account, first.message_to_sign)
        ),
        lambda: account_service.verify_wallet_challenge(
            second.session_id, second.message_to_sign, _signature(wallet_account, second.message_to_sign)
        ),
    )

    assert [outcome for outcome, _ in outcomes] == ["success", "success"]
    assert outcomes[0][1].wallet_identity_id == outcomes[1][1].wallet_identity_id
    with repository.sessions() as session:
        assert session.get(AccountSessionRow, first.session_id).consumed_at is not None
        assert session.get(AccountSessionRow, second.session_id).consumed_at is not None


def test_concurrent_additional_wallet_challenges_cannot_create_a_second_identity(
    service, wallet_account
):
    account_service, _clock, repository = service
    bootstrap = account_service.create_wallet_challenge("u", wallet_account.address)
    authorizer = account_service.verify_wallet_challenge(
        bootstrap.session_id,
        bootstrap.message_to_sign,
        _signature(wallet_account, bootstrap.message_to_sign),
    )
    additional_wallet = Account.create()
    first = account_service.create_wallet_challenge(
        "u",
        additional_wallet.address,
        authorizing_wallet_identity_id=authorizer.wallet_identity_id,
    )
    second = account_service.create_wallet_challenge(
        "u",
        additional_wallet.address,
        authorizing_wallet_identity_id=authorizer.wallet_identity_id,
    )

    outcomes = _concurrent_outcomes(
        lambda: account_service.verify_wallet_challenge(
            first.session_id,
            first.message_to_sign,
            _signature(additional_wallet, first.message_to_sign),
        ),
        lambda: account_service.verify_wallet_challenge(
            second.session_id,
            second.message_to_sign,
            _signature(additional_wallet, second.message_to_sign),
        ),
    )

    assert [outcome for outcome, _ in outcomes] == ["error", "error"]
    assert {
        message for _outcome, message in outcomes
    } == {"disconnect the active wallet before signing in"}
    assert repository.active_wallet_identities("u") == [authorizer]


def test_wallet_rebind_generation_migration_allows_history_but_one_open_scope(
    tmp_path,
):
    database = tmp_path / "wallet-rebind-generation.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database}")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite+pysqlite:///{database}")
    inspector = inspect(engine)
    bootstrap_columns = {
        item["name"]
        for item in inspector.get_columns("account_wallet_bootstrap_states")
    }
    assert {
        "binding_state",
        "binding_generation",
        "unbound_at",
    } <= bootstrap_columns

    indexes = {
        item["name"]: item for item in inspector.get_indexes("wallet_identities")
    }
    assert bool(indexes["uq_wallet_identity_open_scope"]["unique"]) is True
    assert bool(indexes["uq_wallet_identity_open_user"]["unique"]) is True

    address = "0x" + "1" * 40
    with engine.begin() as connection:
        for suffix in ("old", "new"):
            connection.execute(
                text(
                    "INSERT INTO wallet_identities "
                    "(wallet_identity_id, user_id, chain_family, wallet_address, "
                    "status, proof_scheme, proof_hash, verified_at, created_at, updated_at) "
                    "VALUES (:id, 'u', 'evm', :address, 'revoked', 'eip191', "
                    ":proof, :now, :now, :now)"
                ),
                {
                    "id": f"wallet_identity_{suffix}",
                    "address": address,
                    "proof": f"0x{suffix}",
                    "now": NOW,
                },
            )

        connection.execute(
            text(
                "INSERT INTO wallet_identities "
                "(wallet_identity_id, user_id, chain_family, wallet_address, "
                "status, proof_scheme, proof_hash, verified_at, created_at, updated_at) "
                "VALUES ('wallet_identity_active', 'u', 'evm', :address, "
                "'active', 'eip191', '0xactive', :now, :now, :now)"
            ),
            {"address": address, "now": NOW},
        )

        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO wallet_identities "
                    "(wallet_identity_id, user_id, chain_family, wallet_address, "
                    "status, proof_scheme, proof_hash, verified_at, created_at, updated_at) "
                    "VALUES ('wallet_identity_duplicate', 'u', 'evm', :address, "
                    "'active', 'eip191', '0xduplicate', :now, :now, :now)"
                ),
                {"address": address, "now": NOW},
            )


def test_bootstrap_state_migration_backfills_identities_and_downgrades(tmp_path):
    database = tmp_path / "bootstrap-state-migration.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database}")
    command.upgrade(config, "20260716_0009")

    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        for wallet_identity_id, wallet_address, created_at in (
            ("wallet_identity_old", "0x" + "1" * 40, NOW - timedelta(days=1)),
            ("wallet_identity_new", "0x" + "2" * 40, NOW),
        ):
            connection.execute(
                text(
                    "INSERT INTO wallet_identities "
                    "(wallet_identity_id, user_id, chain_family, wallet_address, status, "
                    "proof_scheme, proof_hash, verified_at, created_at, updated_at) "
                    "VALUES (:wallet_identity_id, :user_id, :chain_family, :wallet_address, "
                    ":status, :proof_scheme, :proof_hash, :verified_at, :created_at, :updated_at)"
                ),
                {
                    "wallet_identity_id": wallet_identity_id,
                    "user_id": "legacy-user",
                    "chain_family": "evm",
                    "wallet_address": wallet_address,
                    "status": "revoked",
                    "proof_scheme": "eip191",
                    "proof_hash": "0xproof",
                    "verified_at": created_at,
                    "created_at": created_at,
                    "updated_at": created_at,
                },
            )
        connection.execute(
            text(
                "INSERT INTO asset_allowances "
                "(asset_allowance_id, wallet_identity_id, network, token_address, "
                "token_symbol, token_decimals, spender_address, approved_amount_atomic, "
                "observed_allowance_atomic, allowance_tx_hash, status, confirmed_block, "
                "last_chain_check_at, created_at, updated_at) "
                "VALUES (:asset_allowance_id, :wallet_identity_id, :network, :token_address, "
                ":token_symbol, :token_decimals, :spender_address, :approved_amount_atomic, "
                ":observed_allowance_atomic, :allowance_tx_hash, :status, :confirmed_block, "
                ":last_chain_check_at, :created_at, :updated_at)"
            ),
            {
                "asset_allowance_id": "asset_allowance_legacy_partial",
                "wallet_identity_id": "wallet_identity_old",
                "network": "eip155:137",
                "token_address": "0x" + "3" * 40,
                "token_symbol": "USDC",
                "token_decimals": 6,
                "spender_address": "0x" + "4" * 40,
                "approved_amount_atomic": "2000000",
                "observed_allowance_atomic": "1500000",
                "allowance_tx_hash": "0x" + "5" * 64,
                "status": "insufficient",
                "confirmed_block": 100,
                "last_chain_check_at": NOW,
                "created_at": NOW,
                "updated_at": NOW,
            },
        )

    command.upgrade(config, "head")

    assert inspect(engine).has_table("account_wallet_bootstrap_states")
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT user_id, first_wallet_identity_id, binding_state, "
                "binding_generation, unbound_at "
                "FROM account_wallet_bootstrap_states"
            )
        ).all()
        allowance_status = connection.execute(
            text(
                "SELECT status FROM asset_allowances "
                "WHERE asset_allowance_id = 'asset_allowance_legacy_partial'"
            )
        ).scalar_one()
    assert rows == [
        (
            "legacy-user",
            "wallet_identity_old",
            "unbound",
            1,
            "2026-07-15 12:00:00.000000",
        )
    ]
    assert allowance_status == "active"

    command.downgrade(config, "20260716_0009")
    assert inspect(engine).has_table("account_wallet_bootstrap_states") is False
