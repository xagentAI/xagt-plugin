from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hmac
import time
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    event,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
    create_engine,
    delete,
    exists,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError, OperationalError, PendingRollbackError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import TypeDecorator

from .authorization import (
    grant_authorization_hash,
    reviewed_scope_amendment_is_valid,
)
from .schemas import (
    MAX_UINT256,
    AccountSession,
    AssetAllowance,
    PublicAccountSession,
    SpendingGrant,
    SpendingGrantRequest,
    WalletIdentity,
)


SQLITE_WRITE_RETRY_ATTEMPTS = 5
SQLITE_WRITE_RETRY_DELAY_SECONDS = 0.02
GRANT_AUTHORITY_AUDIT_EVENTS = (
    "grant_created",
    "grant_amended",
    "grant_reduced",
    "grant_supersession_scheduled",
)


@contextmanager
def sqlite_immediate_session(sessions, *, operation: str):
    """Acquire a cross-process SQLite write transaction with bounded retries."""
    session = None
    for attempt in range(1, SQLITE_WRITE_RETRY_ATTEMPTS + 1):
        session = sessions()
        try:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            break
        except OperationalError as exc:
            session.close()
            session = None
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise
            if attempt == SQLITE_WRITE_RETRY_ATTEMPTS:
                raise ValueError(
                    f"{operation} busy after {SQLITE_WRITE_RETRY_ATTEMPTS} attempts"
                ) from exc
            time.sleep(SQLITE_WRITE_RETRY_DELAY_SECONDS * attempt)
    assert session is not None
    try:
        yield session
        session.flush()
        connection = session.connection()
        for attempt in range(1, SQLITE_WRITE_RETRY_ATTEMPTS + 1):
            try:
                # SQLite keeps a BUSY COMMIT transaction open for retry. An ORM
                # commit failure instead invalidates SQLAlchemy's transaction.
                connection.exec_driver_sql("COMMIT")
                break
            except OperationalError as exc:
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                if attempt == SQLITE_WRITE_RETRY_ATTEMPTS:
                    raise
                time.sleep(SQLITE_WRITE_RETRY_DELAY_SECONDS * attempt)
        # Finalize ORM state after the explicit SQLite transaction has committed.
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class Base(DeclarativeBase):
    pass


class UInt256Storage(TypeDecorator):
    """Store uint256 exactly as text on SQLite and NUMERIC on PostgreSQL."""

    impl = Numeric
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(78))
        return dialect.type_descriptor(Numeric(78, 0))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        decimal_value = Decimal(value)
        integer_value = int(decimal_value)
        if decimal_value != integer_value or not 0 <= integer_value <= MAX_UINT256:
            raise ValueError("atomic amount must be a uint256")
        return str(integer_value) if dialect.name == "sqlite" else Decimal(integer_value)

    def process_result_value(self, value, _dialect):
        return Decimal(value) if value is not None else None


class WalletIdentityRow(Base):
    __tablename__ = "wallet_identities"
    __table_args__ = (
        Index(
            "uq_wallet_identity_open_scope",
            "user_id",
            "chain_family",
            "wallet_address",
            unique=True,
            sqlite_where=text("status IN ('pending', 'active', 'suspended')"),
            postgresql_where=text("status IN ('pending', 'active', 'suspended')"),
        ),
        Index(
            "uq_wallet_identity_open_user",
            "user_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'active', 'suspended')"),
            postgresql_where=text("status IN ('pending', 'active', 'suspended')"),
        ),
    )

    wallet_identity_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(96), index=True)
    chain_family: Mapped[str] = mapped_column(String(32))
    wallet_address: Mapped[str] = mapped_column(String(42))
    status: Mapped[str] = mapped_column(String(16), index=True)
    proof_scheme: Mapped[str] = mapped_column(String(16))
    proof_hash: Mapped[str] = mapped_column(String(128))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccountWalletBootstrapStateRow(Base):
    """Track whether an account may bootstrap a fresh wallet generation."""

    __tablename__ = "account_wallet_bootstrap_states"
    __table_args__ = (
        CheckConstraint(
            "binding_state IN ('bound', 'unbound')",
            name="ck_account_wallet_bootstrap_binding_state",
        ),
        CheckConstraint(
            "(binding_state = 'bound' AND unbound_at IS NULL) OR "
            "(binding_state = 'unbound' AND unbound_at IS NOT NULL)",
            name="ck_account_wallet_bootstrap_unbound_at",
        ),
    )

    user_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    first_wallet_identity_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_identities.wallet_identity_id"), nullable=False
    )
    initialized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    binding_state: Mapped[str] = mapped_column(String(16), default="bound")
    binding_generation: Mapped[int] = mapped_column(Integer, default=0)
    unbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountSessionRow(Base):
    __tablename__ = "account_sessions"
    __table_args__ = (
        CheckConstraint(
            "purpose <> 'clink_wallet_identity' OR "
            "created_by_public_account_session_id IS NOT NULL",
            name="ck_wallet_challenge_creating_public_session",
        ),
    )

    account_session_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(96), index=True)
    wallet_address: Mapped[str] = mapped_column(String(42))
    nonce: Mapped[str] = mapped_column(String(128), unique=True)
    domain: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[str] = mapped_column(String(64))
    wallet_identity_id: Mapped[str | None] = mapped_column(
        ForeignKey("wallet_identities.wallet_identity_id"), index=True
    )
    created_by_public_account_session_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "public_account_sessions.public_account_session_id"
        ),
        index=True,
    )
    payload: Mapped[dict | None] = mapped_column(JSON)
    payload_hash: Mapped[str | None] = mapped_column(String(66))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PublicAccountSessionRow(Base):
    __tablename__ = "public_account_sessions"
    __table_args__ = (
        CheckConstraint(
            "length(token_digest) = 64 AND token_digest = lower(token_digest)",
            name="ck_public_account_session_digest",
        ),
        CheckConstraint(
            "browser_session_digest IS NULL OR "
            "(length(browser_session_digest) = 64 AND browser_session_digest = lower(browser_session_digest))",
            name="ck_public_account_browser_session_digest",
        ),
        CheckConstraint(
            "csrf_token_digest IS NULL OR "
            "(length(csrf_token_digest) = 64 AND csrf_token_digest = lower(csrf_token_digest))",
            name="ck_public_account_csrf_token_digest",
        ),
        CheckConstraint(
            "purpose = 'clink_account_console'",
            name="ck_public_account_session_purpose",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked', 'expired')",
            name="ck_public_account_session_status",
        ),
        CheckConstraint(
            "(authenticated_wallet_identity_id IS NULL AND authenticated_at IS NULL) OR "
            "(authenticated_wallet_identity_id IS NOT NULL AND authenticated_at IS NOT NULL)",
            name="ck_public_account_session_authentication",
        ),
    )

    public_account_session_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    browser_session_digest: Mapped[str | None] = mapped_column(String(64), unique=True)
    csrf_token_digest: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(String(96), index=True)
    purpose: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    exchanged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authenticated_wallet_identity_id: Mapped[str | None] = mapped_column(
        ForeignKey("wallet_identities.wallet_identity_id"), index=True
    )
    authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    audit_sequence_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    event_id: Mapped[str] = mapped_column(String(96), unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    event_type: Mapped[str] = mapped_column(String(96), index=True)
    source_service: Mapped[str] = mapped_column(String(96), index=True)
    action_id: Mapped[str | None] = mapped_column(String(96), index=True)
    user_id: Mapped[str | None] = mapped_column(String(96), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(96), index=True)
    policy_decision_id: Mapped[str | None] = mapped_column(String(96))
    payment_id: Mapped[str | None] = mapped_column(String(96))
    order_id: Mapped[str | None] = mapped_column(String(96))
    receipt_id: Mapped[str | None] = mapped_column(String(96))
    tx_hash: Mapped[str | None] = mapped_column(String(66))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SpendingGrantRow(Base):
    __tablename__ = "spending_grants"

    spending_grant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    wallet_identity_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_identities.wallet_identity_id"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(96), index=True)
    agent_id: Mapped[str] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(16), index=True)
    status_reason: Mapped[str | None] = mapped_column(String(64))
    max_amount_usdc: Mapped[Decimal] = mapped_column(Numeric(38, 6))
    per_transaction_limit_usdc: Mapped[Decimal] = mapped_column(Numeric(38, 6))
    hourly_limit_usdc: Mapped[Decimal] = mapped_column(Numeric(38, 6))
    daily_limit_usdc: Mapped[Decimal] = mapped_column(Numeric(38, 6))
    used_amount_usdc: Mapped[Decimal] = mapped_column(Numeric(38, 6))
    reserved_amount_usdc: Mapped[Decimal] = mapped_column(Numeric(38, 6))
    product_scopes: Mapped[list[str]] = mapped_column(JSON)
    venue_scopes: Mapped[list[str]] = mapped_column(JSON)
    merchant_scopes: Mapped[list[str]] = mapped_column(JSON)
    merchant_trust_scopes: Mapped[list[str]] = mapped_column(JSON)
    notification_mode: Mapped[str] = mapped_column(String(32))
    network_scopes: Mapped[list[str]] = mapped_column(JSON)
    asset_scopes: Mapped[list[str]] = mapped_column(JSON)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssetAllowanceRow(Base):
    __tablename__ = "asset_allowances"
    __table_args__ = (
        UniqueConstraint(
            "wallet_identity_id",
            "network",
            "token_address",
            "spender_address",
            name="uq_asset_allowance_scope",
        ),
        Index("ix_asset_allowances_wallet_status", "wallet_identity_id", "status"),
    )

    asset_allowance_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    wallet_identity_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_identities.wallet_identity_id"), index=True
    )
    network: Mapped[str] = mapped_column(String(64))
    token_address: Mapped[str] = mapped_column(String(42))
    token_symbol: Mapped[str] = mapped_column(String(32))
    token_decimals: Mapped[int] = mapped_column(Integer)
    spender_address: Mapped[str] = mapped_column(String(42))
    approved_amount_atomic: Mapped[Decimal] = mapped_column(UInt256Storage())
    observed_allowance_atomic: Mapped[Decimal] = mapped_column(UInt256Storage())
    allowance_tx_hash: Mapped[str | None] = mapped_column(String(66))
    status: Mapped[str] = mapped_column(String(16), index=True)
    confirmed_block: Mapped[int | None] = mapped_column(BigInteger)
    last_chain_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SpendingGrantDailyUsageRow(Base):
    __tablename__ = "spending_grant_daily_usage"
    __table_args__ = (
        UniqueConstraint("spending_grant_id", "usage_date", name="uq_grant_daily_usage"),
    )

    spending_grant_daily_usage_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    spending_grant_id: Mapped[str] = mapped_column(
        ForeignKey("spending_grants.spending_grant_id"), index=True
    )
    usage_date: Mapped[date] = mapped_column(Date)
    used_amount_usdc: Mapped[Decimal] = mapped_column(Numeric(38, 6))
    reserved_amount_usdc: Mapped[Decimal] = mapped_column(Numeric(38, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SpendingGrantRollingUsageRow(Base):
    __tablename__ = "spending_grant_rolling_usage"
    __table_args__ = (
        Index(
            "ix_grant_rolling_usage_window",
            "spending_grant_id",
            "occurred_at",
            "state",
        ),
    )

    reservation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    spending_grant_id: Mapped[str] = mapped_column(
        ForeignKey("spending_grants.spending_grant_id"), index=True
    )
    amount_usdc: Mapped[Decimal] = mapped_column(Numeric(38, 6))
    state: Mapped[str] = mapped_column(String(16), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def _utc_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class AccountRepository:
    def __init__(self, database_url: str):
        engine_options = (
            {"connect_args": {"timeout": 0}}
            if database_url.startswith("sqlite")
            else {}
        )
        self.engine = create_engine(database_url, **engine_options)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", self._enable_sqlite_foreign_keys)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        if self.engine.dialect.name == "sqlite":
            self.create_schema()

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def _write_session(self):
        if self.engine.dialect.name == "sqlite":
            with sqlite_immediate_session(
                self.sessions, operation="sqlite account write transaction"
            ) as session:
                yield session
            return
        with self.sessions.begin() as session:
            yield session

    def save_wallet_identity(self, identity: WalletIdentity) -> WalletIdentity:
        try:
            with self._write_session() as session:
                row = session.get(WalletIdentityRow, identity.wallet_identity_id)
                values = identity.model_dump()
                if row is None:
                    session.add(WalletIdentityRow(**values))
                else:
                    self._assign(row, values)
                self._ensure_wallet_bootstrap_state(
                    session,
                    user_id=identity.user_id,
                    wallet_identity_id=identity.wallet_identity_id,
                    initialized_at=identity.created_at,
                )
        except IntegrityError as exc:
            existing = self._wallet_identity_for_scope(identity)
            if existing == identity:
                return existing
            raise ValueError("wallet identity already exists") from exc
        return identity

    def save_account_session(self, account_session: AccountSession) -> AccountSession:
        try:
            with self._write_session() as session:
                if account_session.purpose == "clink_wallet_identity":
                    public_session_id = (
                        account_session.created_by_public_account_session_id
                    )
                    if public_session_id is None:
                        raise ValueError(
                            "wallet challenge requires a public account session binding"
                        )
                    public_session = self._locked_public_account_session(
                        session, public_session_id
                    )
                    if (
                        public_session is None
                        or public_session.user_id != account_session.user_id
                        or public_session.status != "active"
                        or self._required_utc(public_session.expires_at)
                        <= self._required_utc(account_session.created_at)
                    ):
                        raise ValueError(
                            "wallet challenge creating public account session is unavailable"
                        )
                row = session.get(AccountSessionRow, account_session.account_session_id)
                values = account_session.model_dump()
                if row is None:
                    session.add(AccountSessionRow(**values))
                else:
                    self._assign(row, values)
        except IntegrityError as exc:
            raise ValueError("account session could not be saved") from exc
        return account_session

    def account_session(self, account_session_id: str) -> AccountSession | None:
        attempts = (
            SQLITE_WRITE_RETRY_ATTEMPTS
            if self.engine.dialect.name == "sqlite"
            else 1
        )
        for attempt in range(1, attempts + 1):
            try:
                with self.sessions() as session:
                    row = session.get(AccountSessionRow, account_session_id)
                return self._account_session(row) if row else None
            except OperationalError as exc:
                if (
                    self.engine.dialect.name != "sqlite"
                    or "locked" not in str(exc).lower()
                    or attempt == attempts
                ):
                    raise
                time.sleep(SQLITE_WRITE_RETRY_DELAY_SECONDS * attempt)
        raise AssertionError("SQLite account session read retry did not return")

    def cancel_wallet_challenge(
        self,
        account_session_id: str,
        *,
        user_id: str,
        public_account_session_id: str,
        now: datetime,
    ) -> bool:
        now = _utc_timestamp(now)
        assert now is not None
        with self._write_session() as session:
            row = self._locked_account_session(
                session,
                account_session_id,
            )
            if (
                row is None
                or row.purpose != "clink_wallet_identity"
                or row.user_id != user_id
                or row.created_by_public_account_session_id
                != public_account_session_id
            ):
                return False
            if row.consumed_at is None:
                row.consumed_at = now
        return True

    def create_public_account_session(
        self, account_session: PublicAccountSession
    ) -> PublicAccountSession:
        try:
            with self._write_session() as session:
                session.add(PublicAccountSessionRow(**account_session.model_dump()))
        except IntegrityError as exc:
            raise ValueError("public account session could not be created") from exc
        return account_session

    def access_public_account_session(
        self, token_digest: str, now: datetime
    ) -> PublicAccountSession | None:
        now = self._required_utc(now)
        with self._write_session() as session:
            statement = select(PublicAccountSessionRow).where(
                PublicAccountSessionRow.token_digest == token_digest
            )
            if self.engine.dialect.name != "sqlite":
                statement = statement.with_for_update()
            row = session.scalar(statement)
            if row is None:
                return None
            if row.status == "active" and self._required_utc(row.expires_at) <= now:
                row.status = "expired"
                row.updated_at = now
            elif row.status == "active":
                row.last_accessed_at = now
                row.updated_at = now
            return self._public_account_session(row)

    def exchange_public_account_session(
        self,
        token_digest: str,
        browser_session_digest: str,
        csrf_token_digest: str,
        now: datetime,
        existing_browser_session_digest: str | None = None,
    ) -> PublicAccountSession | None:
        now = self._required_utc(now)
        with self._write_session() as session:
            statement = select(PublicAccountSessionRow).where(
                PublicAccountSessionRow.token_digest == token_digest
            )
            if self.engine.dialect.name != "sqlite":
                statement = statement.with_for_update()
            row = session.scalar(statement)
            if row is None:
                return None
            if row.status == "active" and self._required_utc(row.expires_at) <= now:
                row.status = "expired"
                row.updated_at = now
                return self._public_account_session(row)
            if row.status != "active" or row.exchanged_at is not None:
                return None

            inherited_wallet_identity_id: str | None = None
            if existing_browser_session_digest:
                source_statement = select(PublicAccountSessionRow).where(
                    PublicAccountSessionRow.browser_session_digest
                    == existing_browser_session_digest
                )
                if self.engine.dialect.name != "sqlite":
                    source_statement = source_statement.with_for_update()
                source = session.scalar(source_statement)
                if (
                    source is not None
                    and source.status == "active"
                    and self._required_utc(source.expires_at) <= now
                ):
                    source.status = "expired"
                    source.updated_at = now
                if (
                    source is not None
                    and source.status == "active"
                    and source.user_id == row.user_id
                    and source.authenticated_wallet_identity_id is not None
                ):
                    identity = self._locked_wallet_identity(
                        session, source.authenticated_wallet_identity_id
                    )
                    if (
                        identity is not None
                        and identity.status == "active"
                        and identity.user_id == row.user_id
                    ):
                        inherited_wallet_identity_id = identity.wallet_identity_id

            row.browser_session_digest = browser_session_digest
            row.csrf_token_digest = csrf_token_digest
            row.exchanged_at = now
            if inherited_wallet_identity_id is not None:
                row.authenticated_wallet_identity_id = inherited_wallet_identity_id
                row.authenticated_at = now
            row.last_accessed_at = now
            row.updated_at = now
            return self._public_account_session(row)

    def access_public_account_browser_session(
        self, browser_session_digest: str, now: datetime
    ) -> PublicAccountSession | None:
        now = self._required_utc(now)
        with self._write_session() as session:
            statement = select(PublicAccountSessionRow).where(
                PublicAccountSessionRow.browser_session_digest
                == browser_session_digest
            )
            if self.engine.dialect.name != "sqlite":
                statement = statement.with_for_update()
            row = session.scalar(statement)
            if row is None:
                return None
            if row.status == "active" and self._required_utc(row.expires_at) <= now:
                row.status = "expired"
                row.updated_at = now
            elif row.status == "active":
                row.last_accessed_at = now
                row.updated_at = now
            return self._public_account_session(row)

    def authenticate_public_account_browser_session(
        self,
        public_account_session_id: str,
        browser_session_digest: str,
        wallet_identity_id: str,
        now: datetime,
    ) -> PublicAccountSession:
        """Upgrade one exchanged browser session after current wallet ownership proof."""
        now = self._required_utc(now)
        with self._write_session() as session:
            statement = select(PublicAccountSessionRow).where(
                PublicAccountSessionRow.public_account_session_id
                == public_account_session_id,
                PublicAccountSessionRow.browser_session_digest
                == browser_session_digest,
            )
            if self.engine.dialect.name != "sqlite":
                statement = statement.with_for_update()
            row = session.scalar(statement)
            identity = self._locked_wallet_identity(session, wallet_identity_id)
            if (
                row is None
                or row.status != "active"
                or self._required_utc(row.expires_at) <= now
                or identity is None
                or identity.status != "active"
                or identity.user_id != row.user_id
            ):
                raise ValueError("public account session could not be authenticated")
            row.authenticated_wallet_identity_id = identity.wallet_identity_id
            row.authenticated_at = now
            row.last_accessed_at = now
            row.updated_at = now
            return self._public_account_session(row)

    def revoke_public_account_session(
        self, token_digest: str, now: datetime
    ) -> PublicAccountSession | None:
        now = self._required_utc(now)
        attempts = (
            SQLITE_WRITE_RETRY_ATTEMPTS
            if self.engine.dialect.name == "sqlite"
            else 1
        )
        for attempt in range(1, attempts + 1):
            try:
                with self._write_session() as session:
                    statement = select(PublicAccountSessionRow).where(
                        PublicAccountSessionRow.token_digest == token_digest
                    )
                    if self.engine.dialect.name != "sqlite":
                        statement = statement.with_for_update()
                    row = session.scalar(statement)
                    if row is None:
                        return None
                    if row.status == "active":
                        row.status = "revoked"
                        row.revoked_at = now
                        row.updated_at = now
                    result = self._public_account_session(row)
                return result
            except (OperationalError, PendingRollbackError):
                if self.engine.dialect.name != "sqlite" or attempt == attempts:
                    raise
                time.sleep(SQLITE_WRITE_RETRY_DELAY_SECONDS * attempt)
        raise AssertionError("SQLite public session revoke retry did not return")

    def cleanup_expired_public_account_sessions(self, now: datetime) -> int:
        now = self._required_utc(now)
        with self._write_session() as session:
            referenced_by_authority = exists().where(
                AccountSessionRow.created_by_public_account_session_id
                == PublicAccountSessionRow.public_account_session_id
            )
            # Standalone Account repositories may not include the OPC schema.
            if inspect(session.connection()).has_table("opc_pairings"):
                from .opc_service import OpcPairingRow

                referenced_by_authority = referenced_by_authority | exists().where(
                    OpcPairingRow.public_account_session_id
                    == PublicAccountSessionRow.public_account_session_id
                )
            expired_referenced = session.execute(
                PublicAccountSessionRow.__table__.update()
                .where(
                    PublicAccountSessionRow.status == "active",
                    PublicAccountSessionRow.expires_at <= now,
                    referenced_by_authority,
                )
                .values(status="expired", updated_at=now)
            )
            removed_unreferenced = session.execute(
                delete(PublicAccountSessionRow).where(
                    PublicAccountSessionRow.status == "expired",
                    ~referenced_by_authority,
                )
            )
            return (expired_referenced.rowcount or 0) + (
                removed_unreferenced.rowcount or 0
            )

    def public_account_session(
        self, token_digest: str
    ) -> PublicAccountSession | None:
        with self.sessions() as session:
            row = session.scalar(
                select(PublicAccountSessionRow).where(
                    PublicAccountSessionRow.token_digest == token_digest
                )
            )
        return self._public_account_session(row) if row else None

    def public_account_session_by_id(
        self, public_account_session_id: str
    ) -> PublicAccountSession | None:
        with self.sessions() as session:
            row = session.get(
                PublicAccountSessionRow, public_account_session_id
            )
        return self._public_account_session(row) if row else None

    def append_audit_event(self, **values) -> dict:
        idempotency_key = values.get("idempotency_key")
        try:
            with self._write_session() as session:
                if idempotency_key is not None:
                    existing = self._locked_audit_event_by_idempotency_key(
                        session, idempotency_key
                    )
                    if existing is not None:
                        if not self._audit_event_matches(existing, values):
                            raise ValueError("audit idempotency key conflicts")
                        return self._audit_event(existing)
                row = self._append_audit_event(session, **values)
                session.flush()
                result = self._audit_event(row)
        except IntegrityError as exc:
            if idempotency_key is not None:
                with self.sessions() as session:
                    existing = session.scalar(
                        select(AuditEventRow).where(
                            AuditEventRow.idempotency_key == idempotency_key
                        )
                    )
                if existing is not None:
                    if self._audit_event_matches(existing, values):
                        return self._audit_event(existing)
                    raise ValueError("audit idempotency key conflicts") from exc
            raise ValueError("audit event could not be persisted") from exc
        return result

    def audit_event(self, event_id: str) -> dict | None:
        with self.sessions() as session:
            row = session.scalar(
                select(AuditEventRow).where(AuditEventRow.event_id == event_id)
            )
        return self._audit_event(row) if row else None

    def audit_events(
        self,
        *,
        action_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
    ) -> list[dict]:
        statement = select(AuditEventRow)
        if action_id is not None:
            statement = statement.where(AuditEventRow.action_id == action_id)
        if user_id is not None:
            statement = statement.where(AuditEventRow.user_id == user_id)
        if agent_id is not None:
            statement = statement.where(AuditEventRow.agent_id == agent_id)
        statement = statement.order_by(AuditEventRow.audit_sequence_id)
        with self.sessions() as session:
            rows = session.scalars(statement).all()
        return [self._audit_event(row) for row in rows]

    def spending_grant_authority_revision(self, spending_grant_id: str) -> int:
        """Return the durable revision of a grant's signed authority terms."""

        with self.sessions() as session:
            return self._grant_authority_revision(session, spending_grant_id)

    @staticmethod
    def _grant_authority_revision(session: Session, spending_grant_id: str) -> int:
        statement = (
            select(AuditEventRow.audit_sequence_id)
            .where(
                AuditEventRow.event_type.in_(GRANT_AUTHORITY_AUDIT_EVENTS),
                AuditEventRow.payload["spending_grant_id"].as_string()
                == spending_grant_id,
            )
            .order_by(AuditEventRow.audit_sequence_id.desc())
            .limit(1)
        )
        sequence_id = session.scalar(statement)
        if sequence_id is not None:
            return int(sequence_id)
        # Grants created before grant-specific audit records existed have a
        # valid zero baseline; any subsequent account-service authority event
        # advances it and invalidates an older amendment challenge.
        return 0

    def _append_account_audit(
        self,
        session: Session,
        *,
        event_type: str,
        user_id: str,
        created_at: datetime,
        payload: dict,
        agent_id: str | None = None,
    ) -> AuditEventRow:
        return self._append_audit_event(
            session,
            event_id=f"audit_{uuid4().hex[:20]}",
            event_type=event_type,
            source_service="account_service",
            user_id=user_id,
            agent_id=agent_id,
            payload=payload,
            created_at=created_at,
        )

    def _append_audit_event(
        self,
        session: Session,
        *,
        event_id: str,
        event_type: str,
        source_service: str,
        created_at: datetime,
        idempotency_key: str | None = None,
        payload: dict | None = None,
        action_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        policy_decision_id: str | None = None,
        payment_id: str | None = None,
        order_id: str | None = None,
        receipt_id: str | None = None,
        tx_hash: str | None = None,
    ) -> AuditEventRow:
        row = AuditEventRow(
            event_id=event_id,
            idempotency_key=idempotency_key,
            event_type=event_type,
            source_service=source_service,
            action_id=action_id,
            user_id=user_id,
            agent_id=agent_id,
            policy_decision_id=policy_decision_id,
            payment_id=payment_id,
            order_id=order_id,
            receipt_id=receipt_id,
            tx_hash=tx_hash,
            payload=payload or {},
            created_at=self._required_utc(created_at),
        )
        session.add(row)
        return row

    def consume_wallet_challenge_and_activate_identity(
        self, account_session_id: str, identity: WalletIdentity, now: datetime
    ) -> WalletIdentity:
        """Consume one challenge while creating or reusing its active identity."""
        now = _utc_timestamp(now)
        assert now is not None
        attempts = (
            SQLITE_WRITE_RETRY_ATTEMPTS
            if self.engine.dialect.name == "sqlite"
            else 2
        )
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                return self._consume_wallet_challenge_and_activate_identity(
                    account_session_id, identity, now
                )
            except IntegrityError as exc:
                last_error = exc
            except (OperationalError, PendingRollbackError) as exc:
                if self.engine.dialect.name != "sqlite":
                    raise
                if isinstance(exc, OperationalError) and not any(
                    marker in str(exc).lower() for marker in ("locked", "busy")
                ):
                    raise
                last_error = exc
            if attempt < attempts:
                time.sleep(SQLITE_WRITE_RETRY_DELAY_SECONDS * attempt)
        raise ValueError("wallet identity could not be activated") from last_error

    def _consume_wallet_challenge_and_activate_identity(
        self, account_session_id: str, identity: WalletIdentity, now: datetime
    ) -> WalletIdentity:
        with self._write_session() as session:
            account_session = self._locked_account_session(session, account_session_id)
            if account_session is None:
                raise ValueError("wallet challenge was not found")
            if account_session.consumed_at is not None:
                raise ValueError("wallet challenge already consumed")
            if _utc_timestamp(account_session.expires_at) <= now:
                raise ValueError("wallet challenge expired")
            if (
                account_session.user_id != identity.user_id
                or account_session.wallet_address != identity.wallet_address
            ):
                raise ValueError("wallet challenge identity mismatch")
            if account_session.purpose != "clink_wallet_identity":
                raise ValueError("account session purpose mismatch")
            public_session_id = account_session.created_by_public_account_session_id
            if public_session_id is None:
                raise ValueError(
                    "wallet challenge is missing its creating public account session"
                )
            public_session = self._locked_public_account_session(
                session, public_session_id
            )
            if (
                public_session is None
                or public_session.status != "active"
                or self._required_utc(public_session.expires_at) <= now
                or public_session.user_id != account_session.user_id
                or public_session.user_id != identity.user_id
            ):
                raise ValueError("creating public account session is unavailable")

            existing = self._locked_wallet_identity_for_scope(session, identity)
            bootstrap_state = self._locked_wallet_bootstrap_state(
                session,
                identity.user_id,
            )
            if existing is None:
                existing = self._locked_wallet_identity_for_scope(
                    session,
                    identity,
                )
            open_identity = self._locked_open_wallet_identity_for_user(
                session,
                identity.user_id,
            )
            unbound_rebind = bool(
                bootstrap_state is not None
                and bootstrap_state.binding_state == "unbound"
            )
            authorized_by_wallet_identity_id = None
            cleanup_reauthorization = False
            if existing is not None:
                if existing.status == "suspended":
                    cleanup_reauthorization = True
                    session.execute(
                        update(PublicAccountSessionRow)
                        .where(
                            PublicAccountSessionRow.authenticated_wallet_identity_id
                            == existing.wallet_identity_id,
                            PublicAccountSessionRow.public_account_session_id
                            != public_session_id,
                        )
                        .values(
                            authenticated_wallet_identity_id=None,
                            authenticated_at=None,
                            updated_at=now,
                        )
                    )
                    result = self._wallet_identity(existing)
                elif existing.status != "active":
                    raise ValueError("wallet identity is not active")
                else:
                    self._ensure_wallet_bootstrap_state(
                        session,
                        user_id=existing.user_id,
                        wallet_identity_id=existing.wallet_identity_id,
                        initialized_at=existing.created_at,
                    )
                    result = self._wallet_identity(existing)
            else:
                if open_identity is not None:
                    raise ValueError(
                        "disconnect the active wallet before signing in"
                    )
                if bootstrap_state is not None and not unbound_rebind:
                    raise ValueError("wallet identity is not active")
                session.add(WalletIdentityRow(**identity.model_dump()))
                session.flush()
                if bootstrap_state is None:
                    session.add(
                        AccountWalletBootstrapStateRow(
                            user_id=identity.user_id,
                            first_wallet_identity_id=identity.wallet_identity_id,
                            initialized_at=now,
                        )
                    )
                elif unbound_rebind:
                    bootstrap_state.binding_state = "bound"
                    bootstrap_state.unbound_at = None
                result = identity
            account_session.consumed_at = now
            public_session.authenticated_wallet_identity_id = result.wallet_identity_id
            public_session.authenticated_at = now
            public_session.last_accessed_at = now
            public_session.updated_at = now
            audit_payload = {
                "wallet_identity_id": result.wallet_identity_id,
                "wallet_address": result.wallet_address,
                "status": result.status,
                "binding_generation": (
                    bootstrap_state.binding_generation
                    if bootstrap_state is not None
                    else 0
                ),
                "rebind": unbound_rebind,
            }
            if authorized_by_wallet_identity_id is not None:
                audit_payload["authorized_by_wallet_identity_id"] = (
                    authorized_by_wallet_identity_id
                )
            if cleanup_reauthorization:
                audit_payload["cleanup_only"] = True
            self._append_account_audit(
                session,
                event_type=(
                    "wallet_disconnect_cleanup_reauthorized"
                    if cleanup_reauthorization
                    else "wallet_verified"
                ),
                user_id=result.user_id,
                created_at=now,
                payload=audit_payload,
            )
        return result

    def revoke_wallet_identity_and_pause_active_grants(
        self, wallet_identity_id: str, now: datetime
    ) -> WalletIdentity:
        """Apply identity revocation and its grant safety cascade in one transaction."""
        now = _utc_timestamp(now)
        assert now is not None
        with self._write_session() as session:
            identity = self._locked_wallet_identity(session, wallet_identity_id)
            if identity is None:
                raise ValueError("wallet identity was not found")
            identity_changed = identity.status != "revoked"
            if identity_changed:
                identity.status = "revoked"
                identity.updated_at = now

            grants = select(SpendingGrantRow).where(
                SpendingGrantRow.wallet_identity_id == wallet_identity_id,
                SpendingGrantRow.status.in_(("active", "pending")),
            )
            if self.engine.dialect.name != "sqlite":
                grants = grants.with_for_update()
            for grant in session.scalars(grants):
                grant.status = "paused"
                grant.status_reason = "wallet_identity_revoked"
                grant.updated_at = now
                self._append_account_audit(
                    session,
                    event_type="grant_paused",
                    user_id=identity.user_id,
                    agent_id=grant.agent_id,
                    created_at=now,
                    payload={
                        "spending_grant_id": grant.spending_grant_id,
                        "wallet_identity_id": wallet_identity_id,
                        "status": "paused",
                        "status_reason": "wallet_identity_revoked",
                    },
                )
            if identity_changed:
                self._append_account_audit(
                    session,
                    event_type="wallet_revoked",
                    user_id=identity.user_id,
                    created_at=now,
                    payload={
                        "wallet_identity_id": wallet_identity_id,
                        "wallet_address": identity.wallet_address,
                        "status": "revoked",
                    },
                )
            result = self._wallet_identity(identity)
        return result

    def disconnect_wallet_identity(
        self,
        wallet_identity_id: str,
        now: datetime,
        *,
        require_prepared_allowances: bool = False,
        public_account_session_id: str | None = None,
    ) -> WalletIdentity:
        """Revoke one wallet identity and every grant that could remain usable."""
        now = _utc_timestamp(now)
        assert now is not None
        with self._write_session() as session:
            identity = self._locked_wallet_identity(session, wallet_identity_id)
            if identity is None:
                raise ValueError("wallet identity was not found")
            if require_prepared_allowances:
                if identity.status != "suspended":
                    raise ValueError(
                        "wallet identity is not prepared for disconnect"
                    )
                cleanup_session = (
                    self._locked_public_account_session(
                        session, public_account_session_id
                    )
                    if public_account_session_id is not None
                    else None
                )
                if (
                    cleanup_session is None
                    or cleanup_session.status != "active"
                    or self._required_utc(cleanup_session.expires_at)
                    <= now
                    or cleanup_session.user_id != identity.user_id
                    or cleanup_session.authenticated_wallet_identity_id
                    != wallet_identity_id
                ):
                    raise ValueError(
                        "wallet disconnect session is unavailable"
                    )
                allowances = select(AssetAllowanceRow).where(
                    AssetAllowanceRow.wallet_identity_id
                    == wallet_identity_id
                )
                if self.engine.dialect.name != "sqlite":
                    allowances = allowances.with_for_update()
                prepared_at = self._required_utc(identity.updated_at)
                for item in session.scalars(allowances):
                    last_check = _utc_timestamp(item.last_chain_check_at)
                    if (
                        item.status != "revoked"
                        or item.observed_allowance_atomic != 0
                        or last_check is None
                        or last_check < prepared_at
                    ):
                        raise ValueError(
                            "wallet allowances are not verified as revoked"
                        )
            identity_changed = identity.status != "revoked"
            if identity_changed:
                identity.status = "revoked"
                identity.updated_at = now
                session.execute(
                    update(PublicAccountSessionRow)
                    .where(
                        PublicAccountSessionRow.authenticated_wallet_identity_id
                        == wallet_identity_id
                    )
                    .values(
                        authenticated_wallet_identity_id=None,
                        authenticated_at=None,
                        updated_at=now,
                    )
                )
                session.execute(
                    update(AccountSessionRow)
                    .where(
                        AccountSessionRow.user_id == identity.user_id,
                        AccountSessionRow.purpose == "clink_wallet_identity",
                        AccountSessionRow.consumed_at.is_(None),
                        AccountSessionRow.created_at <= now,
                    )
                    .values(consumed_at=now)
                )

            grants = select(SpendingGrantRow).where(
                SpendingGrantRow.wallet_identity_id == wallet_identity_id,
                SpendingGrantRow.status.in_(("active", "pending", "paused")),
            )
            if self.engine.dialect.name != "sqlite":
                grants = grants.with_for_update()
            for grant in session.scalars(grants):
                grant.status = "revoked"
                grant.status_reason = "wallet_identity_disconnected"
                grant.updated_at = now
                self._append_account_audit(
                    session,
                    event_type="grant_revoked",
                    user_id=identity.user_id,
                    agent_id=grant.agent_id,
                    created_at=now,
                    payload={
                        "spending_grant_id": grant.spending_grant_id,
                        "wallet_identity_id": wallet_identity_id,
                        "status": "revoked",
                        "status_reason": "wallet_identity_disconnected",
                    },
                )
            if identity_changed:
                self._append_account_audit(
                    session,
                    event_type="wallet_revoked",
                    user_id=identity.user_id,
                    created_at=now,
                    payload={
                        "wallet_identity_id": wallet_identity_id,
                        "wallet_address": identity.wallet_address,
                        "status": "revoked",
                        "reason": "fully_disconnected",
                        "allowances_verified": require_prepared_allowances,
                    },
                )
                has_active_identity = bool(
                    session.scalar(
                        select(
                            exists().where(
                                WalletIdentityRow.user_id == identity.user_id,
                                WalletIdentityRow.wallet_identity_id
                                != wallet_identity_id,
                                WalletIdentityRow.status == "active",
                            )
                        )
                    )
                )
                if not has_active_identity:
                    bootstrap = self._locked_wallet_bootstrap_state(
                        session,
                        identity.user_id,
                    )
                    if bootstrap is None:
                        bootstrap = AccountWalletBootstrapStateRow(
                            user_id=identity.user_id,
                            first_wallet_identity_id=identity.wallet_identity_id,
                            initialized_at=identity.created_at,
                            binding_state="unbound",
                            binding_generation=1,
                            unbound_at=now,
                        )
                        session.add(bootstrap)
                    else:
                        bootstrap.binding_state = "unbound"
                        bootstrap.binding_generation += 1
                        bootstrap.unbound_at = now
                    self._append_account_audit(
                        session,
                        event_type="wallet_binding_reset",
                        user_id=identity.user_id,
                        created_at=now,
                        payload={
                            "wallet_identity_id": wallet_identity_id,
                            "binding_generation": bootstrap.binding_generation,
                        },
                    )
            result = self._wallet_identity(identity)
        return result

    def prepare_wallet_identity_disconnect(
        self,
        wallet_identity_id: str,
        public_account_session_id: str,
        now: datetime,
    ) -> WalletIdentity:
        """Stop new authority while retaining only browser cleanup access."""
        now = _utc_timestamp(now)
        assert now is not None
        with self._write_session() as session:
            identity = self._locked_wallet_identity(session, wallet_identity_id)
            if identity is None:
                raise ValueError("wallet identity was not found")
            cleanup_session = self._locked_public_account_session(
                session, public_account_session_id
            )
            if (
                cleanup_session is None
                or cleanup_session.status != "active"
                or self._required_utc(cleanup_session.expires_at) <= now
                or cleanup_session.user_id != identity.user_id
                or cleanup_session.authenticated_wallet_identity_id
                != wallet_identity_id
            ):
                raise ValueError("wallet disconnect session is unavailable")
            if identity.status not in {"active", "suspended"}:
                raise ValueError("wallet identity cannot be prepared for disconnect")
            prepared = identity.status != "suspended"
            if prepared:
                identity.status = "suspended"
                identity.updated_at = now
                session.execute(
                    update(PublicAccountSessionRow)
                    .where(
                        PublicAccountSessionRow.authenticated_wallet_identity_id
                        == wallet_identity_id,
                        PublicAccountSessionRow.public_account_session_id
                        != public_account_session_id,
                    )
                    .values(
                        authenticated_wallet_identity_id=None,
                        authenticated_at=None,
                        updated_at=now,
                    )
                )

            grants = select(SpendingGrantRow).where(
                SpendingGrantRow.wallet_identity_id == wallet_identity_id,
                SpendingGrantRow.status.in_(("active", "pending", "paused")),
            )
            if self.engine.dialect.name != "sqlite":
                grants = grants.with_for_update()
            for grant in session.scalars(grants):
                grant.status = "revoked"
                grant.status_reason = "wallet_disconnect_prepared"
                grant.updated_at = now
                self._append_account_audit(
                    session,
                    event_type="grant_revoked",
                    user_id=identity.user_id,
                    agent_id=grant.agent_id,
                    created_at=now,
                    payload={
                        "spending_grant_id": grant.spending_grant_id,
                        "wallet_identity_id": wallet_identity_id,
                        "status": "revoked",
                        "status_reason": "wallet_disconnect_prepared",
                    },
                )
            if prepared:
                self._append_account_audit(
                    session,
                    event_type="wallet_disconnect_prepared",
                    user_id=identity.user_id,
                    created_at=now,
                    payload={
                        "wallet_identity_id": wallet_identity_id,
                        "wallet_address": identity.wallet_address,
                        "status": "suspended",
                    },
                )
            result = self._wallet_identity(identity)
        return result

    def active_wallet_identities(self, user_id: str) -> list[WalletIdentity]:
        with self.sessions() as session:
            rows = session.scalars(
                select(WalletIdentityRow)
                .where(WalletIdentityRow.user_id == user_id, WalletIdentityRow.status == "active")
                .order_by(WalletIdentityRow.created_at, WalletIdentityRow.wallet_identity_id)
            ).all()
        return [self._wallet_identity(row) for row in rows]

    def wallet_identity(self, wallet_identity_id: str) -> WalletIdentity | None:
        with self.sessions() as session:
            row = session.get(WalletIdentityRow, wallet_identity_id)
        return self._wallet_identity(row) if row else None

    def wallet_identity_disconnect_complete(
        self, wallet_identity_id: str
    ) -> bool:
        with self.sessions() as session:
            identity = session.get(WalletIdentityRow, wallet_identity_id)
            if identity is None or identity.status != "revoked":
                return False
            events = session.scalars(
                select(AuditEventRow)
                .where(
                    AuditEventRow.user_id == identity.user_id,
                    AuditEventRow.event_type == "wallet_revoked",
                )
                .order_by(AuditEventRow.audit_sequence_id.desc())
            )
            return any(
                event.payload.get("wallet_identity_id")
                == wallet_identity_id
                and event.payload.get("allowances_verified") is True
                for event in events
            )

    def bootstrap_wallet_identity_id(self, user_id: str) -> str | None:
        with self.sessions() as session:
            row = session.get(AccountWalletBootstrapStateRow, user_id)
        return row.first_wallet_identity_id if row else None

    def consume_grant_challenge_and_create_grant(
        self,
        account_session_id: str,
        grant: SpendingGrant,
        now: datetime,
        payload_hash: str,
    ) -> SpendingGrant:
        """Consume one signed grant challenge and insert its exact grant atomically."""
        now = _utc_timestamp(now)
        assert now is not None
        try:
            with self._write_session() as session:
                account_session = self._locked_account_session(session, account_session_id)
                if account_session is None:
                    raise ValueError("spending grant challenge was not found")
                if account_session.purpose != "clink_spending_grant":
                    raise ValueError("account session purpose mismatch")
                if account_session.consumed_at is not None:
                    raise ValueError("spending grant challenge already consumed")
                if _utc_timestamp(account_session.expires_at) <= now:
                    raise ValueError("spending grant challenge expired")
                if account_session.payload_hash != payload_hash:
                    raise ValueError("spending grant challenge payload mismatch")
                if (
                    account_session.user_id != grant.user_id
                    or account_session.wallet_identity_id != grant.wallet_identity_id
                ):
                    raise ValueError("spending grant challenge identity mismatch")

                identity = self._locked_wallet_identity(session, grant.wallet_identity_id)
                if identity is None:
                    raise ValueError("wallet identity was not found")
                if identity.user_id != grant.user_id:
                    raise ValueError("spending grant user does not match wallet identity")
                if identity.wallet_address != account_session.wallet_address:
                    raise ValueError("spending grant wallet does not match identity")
                if identity.status != "active":
                    raise ValueError("wallet identity is not active")
                if self._locked_grant(session, grant.spending_grant_id) is not None:
                    raise ValueError("spending grant already exists")

                existing_statement = select(SpendingGrantRow).where(
                    SpendingGrantRow.user_id == grant.user_id,
                    SpendingGrantRow.wallet_identity_id == grant.wallet_identity_id,
                    SpendingGrantRow.agent_id == grant.agent_id,
                    SpendingGrantRow.status.in_(("active", "pending", "paused")),
                )
                if self.engine.dialect.name != "sqlite":
                    existing_statement = existing_statement.with_for_update()
                replacement_starts_at = self._required_utc(grant.starts_at)
                replacement_expires_at = self._required_utc(grant.expires_at)
                for existing in session.scalars(existing_statement).all():
                    if not set(existing.product_scopes).intersection(
                        grant.product_scopes
                    ):
                        continue
                    existing_starts_at = self._required_utc(existing.starts_at)
                    existing_expires_at = self._required_utc(existing.expires_at)
                    if (
                        existing_expires_at <= replacement_starts_at
                        or replacement_expires_at <= existing_starts_at
                    ):
                        continue
                    if (
                        replacement_starts_at > now
                        and existing_starts_at <= now < existing_expires_at
                        and existing.status in {"active", "paused"}
                    ):
                        existing.expires_at = replacement_starts_at
                        existing.updated_at = now
                        self._append_account_audit(
                            session,
                            event_type="grant_supersession_scheduled",
                            user_id=existing.user_id,
                            agent_id=existing.agent_id,
                            created_at=now,
                            payload={
                                "spending_grant_id": existing.spending_grant_id,
                                "replacement_spending_grant_id": grant.spending_grant_id,
                                "wallet_identity_id": existing.wallet_identity_id,
                                "effective_at": replacement_starts_at.isoformat(),
                            },
                        )
                        continue
                    existing.status = "revoked"
                    existing.status_reason = "superseded_by_signed_mandate"
                    existing.updated_at = now
                    from .opc_service import _invalidate_grant_installations

                    _invalidate_grant_installations(
                        self,
                        session,
                        spending_grant_id=existing.spending_grant_id,
                        now=now,
                    )
                    self._append_account_audit(
                        session,
                        event_type="grant_superseded",
                        user_id=existing.user_id,
                        agent_id=existing.agent_id,
                        created_at=now,
                        payload={
                            "spending_grant_id": existing.spending_grant_id,
                            "replacement_spending_grant_id": grant.spending_grant_id,
                            "wallet_identity_id": existing.wallet_identity_id,
                            "status": existing.status,
                        },
                    )

                session.add(SpendingGrantRow(**grant.model_dump()))
                session.flush()
                from .opc_service import _bind_new_grant_installation

                _bind_new_grant_installation(
                    self,
                    session,
                    account_session=account_session,
                    grant=self._required_locked_grant(
                        session, grant.spending_grant_id
                    ),
                    now=now,
                )
                account_session.consumed_at = now
                self._append_account_audit(
                    session,
                    event_type="grant_created",
                    user_id=grant.user_id,
                    agent_id=grant.agent_id,
                    created_at=now,
                    payload={
                        "spending_grant_id": grant.spending_grant_id,
                        "wallet_identity_id": grant.wallet_identity_id,
                        "status": grant.status,
                    },
                )
        except IntegrityError as exc:
            raise ValueError("spending grant could not be created") from exc
        return grant

    def consume_grant_challenge_and_amend_grant(
        self,
        account_session_id: str,
        request: SpendingGrantRequest,
        now: datetime,
        payload_hash: str,
    ) -> SpendingGrant:
        """Consume a signed challenge and amend one grant atomically."""
        grant_id = request.amends_spending_grant_id
        if grant_id is None:
            raise ValueError("spending grant amendment target is required")
        now = self._required_utc(now)
        with self._write_session() as session:
            account_session = self._locked_account_session(
                session, account_session_id
            )
            if account_session is None:
                raise ValueError("spending grant challenge was not found")
            if account_session.purpose != "clink_spending_grant":
                raise ValueError("account session purpose mismatch")
            if account_session.consumed_at is not None:
                raise ValueError("spending grant challenge already consumed")
            if self._required_utc(account_session.expires_at) <= now:
                raise ValueError("spending grant challenge expired")
            if account_session.payload_hash != payload_hash:
                raise ValueError("spending grant challenge payload mismatch")
            if (
                not account_session.payload
                or account_session.payload.get("spending_grant_id") != grant_id
            ):
                raise ValueError("spending grant amendment target mismatch")
            if (
                account_session.user_id != request.user_id
                or account_session.wallet_identity_id
                != request.wallet_identity_id
            ):
                raise ValueError("spending grant challenge identity mismatch")

            identity = self._locked_wallet_identity(
                session, request.wallet_identity_id
            )
            if identity is None:
                raise ValueError("wallet identity was not found")
            if identity.user_id != request.user_id:
                raise ValueError("spending grant user does not match wallet identity")
            if identity.wallet_address != account_session.wallet_address:
                raise ValueError("spending grant wallet does not match identity")
            if identity.status != "active":
                raise ValueError("wallet identity is not active")

            row = self._required_locked_grant(session, grant_id)
            if (
                row.user_id != request.user_id
                or row.wallet_identity_id != request.wallet_identity_id
                or row.agent_id != request.agent_id
            ):
                raise ValueError("spending grant amendment identity mismatch")
            if row.status != "active":
                raise ValueError("only an active spending grant can be amended")
            expected_base_authority_hash = (account_session.payload or {}).get(
                "base_authority_hash"
            )
            current_base_authority_hash = grant_authorization_hash(
                self._spending_grant(row)
            )
            if not isinstance(expected_base_authority_hash, str) or not hmac.compare_digest(
                expected_base_authority_hash, current_base_authority_hash
            ):
                raise ValueError("spending grant amendment base authority changed")
            expected_base_authority_revision = (account_session.payload or {}).get(
                "base_authority_revision"
            )
            current_base_authority_revision = self._grant_authority_revision(
                session, grant_id
            )
            if (
                isinstance(expected_base_authority_revision, bool)
                or not isinstance(expected_base_authority_revision, int)
                or expected_base_authority_revision != current_base_authority_revision
            ):
                raise ValueError("spending grant amendment base authority changed")
            if not reviewed_scope_amendment_is_valid(
                row.product_scopes,
                row.venue_scopes,
                request.product_scopes,
                request.venue_scopes,
            ):
                raise ValueError(
                    "signed amendment cannot change grant scope outside reviewed fields"
                )
            committed = row.used_amount_usdc + row.reserved_amount_usdc
            if request.max_amount_usdc < committed:
                raise ValueError(
                    "total grant cannot be amended below spent and pending amount"
                )

            limits = {
                "max_amount_usdc": request.max_amount_usdc,
                "per_transaction_limit_usdc": request.per_transaction_limit_usdc,
                "hourly_limit_usdc": request.hourly_limit_usdc,
                "daily_limit_usdc": request.daily_limit_usdc,
            }
            previous_scopes = {
                "product_scopes": list(row.product_scopes),
                "venue_scopes": list(row.venue_scopes),
            }
            scopes = {
                "product_scopes": list(request.product_scopes),
                "venue_scopes": list(request.venue_scopes),
            }
            self._assign(row, {**limits, **scopes})
            row.updated_at = now
            from .opc_service import _invalidate_grant_installations

            _invalidate_grant_installations(
                self,
                session,
                spending_grant_id=row.spending_grant_id,
                now=now,
            )
            account_session.consumed_at = now
            self._append_account_audit(
                session,
                event_type="grant_amended",
                user_id=row.user_id,
                agent_id=row.agent_id,
                created_at=now,
                payload={
                    "spending_grant_id": row.spending_grant_id,
                    "wallet_identity_id": row.wallet_identity_id,
                    "previous_product_scopes": previous_scopes["product_scopes"],
                    "previous_venue_scopes": previous_scopes["venue_scopes"],
                    "product_scopes": scopes["product_scopes"],
                    "venue_scopes": scopes["venue_scopes"],
                    **{field: str(value) for field, value in limits.items()},
                },
            )
            result = self._spending_grant(row)
        return result

    def save_spending_grant(self, grant: SpendingGrant) -> SpendingGrant:
        try:
            with self._write_session() as session:
                if grant.status in {"active", "pending"}:
                    identity = self._locked_wallet_identity(session, grant.wallet_identity_id)
                    if identity is None:
                        raise ValueError("spending grant could not be saved")
                    if identity.user_id != grant.user_id:
                        raise ValueError("spending grant user does not match wallet identity")
                    if identity.status != "active":
                        raise ValueError("wallet identity is not active")
                row = self._locked_grant(session, grant.spending_grant_id)
                values = grant.model_dump()
                if row is None:
                    session.add(SpendingGrantRow(**values))
                else:
                    self._assign(row, values)
        except IntegrityError as exc:
            existing = self._spending_grant_by_id(grant.spending_grant_id)
            if existing == grant:
                return existing
            raise ValueError("spending grant could not be saved") from exc
        return grant

    def active_spending_grants(
        self, user_id: str, at: datetime | None = None
    ) -> list[SpendingGrant]:
        at = self._required_utc(at or datetime.now(UTC))
        with self._write_session() as session:
            statement = (
                select(SpendingGrantRow)
                .where(
                    SpendingGrantRow.user_id == user_id,
                    SpendingGrantRow.status.in_(("active", "pending", "paused")),
                )
                .order_by(SpendingGrantRow.created_at, SpendingGrantRow.spending_grant_id)
            )
            if self.engine.dialect.name != "sqlite":
                statement = statement.with_for_update()
            rows = session.scalars(statement).all()
            active = []
            for row in rows:
                starts_at = self._required_utc(row.starts_at)
                expires_at = self._required_utc(row.expires_at)
                if at >= expires_at:
                    row.status = "expired"
                    row.status_reason = "grant_expired"
                    row.updated_at = at
                    continue
                if row.status == "pending" and starts_at <= at:
                    row.status = "active"
                    row.status_reason = None
                    row.updated_at = at
                if row.status == "active" and starts_at <= at < expires_at:
                    active.append(self._spending_grant(row))
            return active

    def spending_grants(
        self, user_id: str, *, status: str | None = None
    ) -> list[SpendingGrant]:
        with self.sessions() as session:
            statement = select(SpendingGrantRow).where(SpendingGrantRow.user_id == user_id)
            if status is not None:
                statement = statement.where(SpendingGrantRow.status == status)
            rows = session.scalars(
                statement.order_by(
                    SpendingGrantRow.created_at, SpendingGrantRow.spending_grant_id
                )
            ).all()
        return [self._spending_grant(row) for row in rows]

    def spending_grant(self, spending_grant_id: str) -> SpendingGrant | None:
        return self._spending_grant_by_id(spending_grant_id)

    def pause_spending_grant(self, spending_grant_id: str, now: datetime) -> SpendingGrant:
        now = self._required_utc(now)
        with self._write_session() as session:
            row = self._required_locked_grant(session, spending_grant_id)
            if row.status in {"active", "pending"}:
                row.status = "paused"
                row.status_reason = "user_paused"
                row.updated_at = now
                self._append_account_audit(
                    session,
                    event_type="grant_paused",
                    user_id=row.user_id,
                    agent_id=row.agent_id,
                    created_at=now,
                    payload={
                        "spending_grant_id": spending_grant_id,
                        "wallet_identity_id": row.wallet_identity_id,
                        "status": "paused",
                        "status_reason": "user_paused",
                    },
                )
            return self._spending_grant(row)

    def resume_spending_grant(self, spending_grant_id: str, now: datetime) -> SpendingGrant:
        now = self._required_utc(now)
        with self._write_session() as session:
            snapshot = session.get(SpendingGrantRow, spending_grant_id)
            if snapshot is None:
                raise ValueError("spending grant was not found")
            identity = self._locked_wallet_identity(session, snapshot.wallet_identity_id)
            row = self._required_locked_grant(session, spending_grant_id)
            if row.status == "revoked":
                raise ValueError("revoked grant cannot be resumed")
            if self._required_utc(row.expires_at) <= now:
                if row.status != "expired":
                    row.status = "expired"
                    row.status_reason = "grant_expired"
                    row.updated_at = now
                return self._spending_grant(row)
            if row.status in {"active", "pending"}:
                return self._spending_grant(row)
            if row.status_reason != "user_paused":
                raise ValueError("security-paused grant cannot be resumed")
            if identity is None or identity.status != "active":
                raise ValueError("wallet identity is not active")
            row.status = (
                "pending" if now < self._required_utc(row.starts_at) else "active"
            )
            row.status_reason = None
            row.updated_at = now
            self._append_account_audit(
                session,
                event_type="grant_resumed",
                user_id=row.user_id,
                agent_id=row.agent_id,
                created_at=now,
                payload={
                    "spending_grant_id": spending_grant_id,
                    "wallet_identity_id": row.wallet_identity_id,
                    "status": row.status,
                },
            )
            return self._spending_grant(row)

    def reduce_spending_grant(
        self,
        spending_grant_id: str,
        now: datetime,
        *,
        max_amount_usdc: Decimal | None = None,
        per_transaction_limit_usdc: Decimal | None = None,
        hourly_limit_usdc: Decimal | None = None,
        daily_limit_usdc: Decimal | None = None,
    ) -> SpendingGrant:
        now = self._required_utc(now)
        with self._write_session() as session:
            row = self._required_locked_grant(session, spending_grant_id)
            proposed = {
                "max_amount_usdc": Decimal(max_amount_usdc)
                if max_amount_usdc is not None
                else row.max_amount_usdc,
                "per_transaction_limit_usdc": Decimal(per_transaction_limit_usdc)
                if per_transaction_limit_usdc is not None
                else row.per_transaction_limit_usdc,
                "hourly_limit_usdc": Decimal(hourly_limit_usdc)
                if hourly_limit_usdc is not None
                else row.hourly_limit_usdc,
                "daily_limit_usdc": Decimal(daily_limit_usdc)
                if daily_limit_usdc is not None
                else row.daily_limit_usdc,
            }
            for field, value in proposed.items():
                if value <= 0:
                    raise ValueError("grant amounts must be positive")
                if value > getattr(row, field):
                    raise ValueError("spending grant limits cannot increase without a new challenge")
            if proposed["per_transaction_limit_usdc"] > proposed["max_amount_usdc"]:
                raise ValueError("per-transaction limit exceeds total grant")
            if proposed["per_transaction_limit_usdc"] > proposed["hourly_limit_usdc"]:
                raise ValueError("per-transaction limit exceeds hourly limit")
            if proposed["hourly_limit_usdc"] > proposed["daily_limit_usdc"]:
                raise ValueError("hourly limit exceeds daily limit")
            if proposed["daily_limit_usdc"] > proposed["max_amount_usdc"]:
                raise ValueError("daily limit exceeds total grant")
            if proposed["max_amount_usdc"] < row.used_amount_usdc + row.reserved_amount_usdc:
                raise ValueError("total grant cannot be reduced below committed amount")
            changed = any(proposed[field] != getattr(row, field) for field in proposed)
            if changed:
                self._assign(row, proposed)
                row.updated_at = now
                self._append_account_audit(
                    session,
                    event_type="grant_reduced",
                    user_id=row.user_id,
                    agent_id=row.agent_id,
                    created_at=now,
                    payload={
                        "spending_grant_id": spending_grant_id,
                        "wallet_identity_id": row.wallet_identity_id,
                        **{
                            field: str(value)
                            for field, value in proposed.items()
                        },
                    },
                )
            return self._spending_grant(row)

    def revoke_spending_grant(self, spending_grant_id: str, now: datetime) -> SpendingGrant:
        now = self._required_utc(now)
        with self._write_session() as session:
            row = self._required_locked_grant(session, spending_grant_id)
            if row.status != "revoked":
                row.status = "revoked"
                row.status_reason = "user_revoked"
                row.updated_at = now
                self._append_account_audit(
                    session,
                    event_type="grant_revoked",
                    user_id=row.user_id,
                    agent_id=row.agent_id,
                    created_at=now,
                    payload={
                        "spending_grant_id": spending_grant_id,
                        "wallet_identity_id": row.wallet_identity_id,
                        "status": "revoked",
                    },
                )
            return self._spending_grant(row)

    def save_asset_allowance(self, allowance: AssetAllowance) -> AssetAllowance:
        try:
            with self._write_session() as session:
                row = session.get(AssetAllowanceRow, allowance.asset_allowance_id)
                values = allowance.model_dump()
                if row is None:
                    session.add(AssetAllowanceRow(**values))
                else:
                    self._assign(row, values)
        except IntegrityError as exc:
            existing = self._asset_allowance_for_scope(allowance)
            if existing == allowance:
                return existing
            if existing is not None:
                raise ValueError("asset allowance already exists") from exc
            raise ValueError("asset allowance persistence failed") from exc
        return allowance

    def save_verified_asset_allowance(self, allowance: AssetAllowance) -> AssetAllowance:
        """Persist the latest independently verified proof for one allowance scope."""
        try:
            with self._write_session() as session:
                identity = self._locked_wallet_identity(session, allowance.wallet_identity_id)
                if identity is None:
                    raise ValueError("wallet identity was not found")
                if identity.status != "active":
                    raise ValueError("wallet identity is not active")
                existing = self._locked_asset_allowance_for_scope(session, allowance)
                if existing is not None:
                    same_proof = (
                        existing.allowance_tx_hash == allowance.allowance_tx_hash
                        and int(existing.approved_amount_atomic)
                        == allowance.approved_amount_atomic
                    )
                    if same_proof:
                        changed = (
                            int(existing.observed_allowance_atomic)
                            != allowance.observed_allowance_atomic
                            or existing.status != allowance.status
                        )
                        existing.observed_allowance_atomic = Decimal(
                            allowance.observed_allowance_atomic
                        )
                        existing.status = allowance.status
                        existing.confirmed_block = allowance.confirmed_block
                        existing.last_chain_check_at = allowance.last_chain_check_at
                        existing.updated_at = allowance.updated_at
                        if changed:
                            self._append_account_audit(
                                session,
                                event_type="allowance_refreshed",
                                user_id=identity.user_id,
                                created_at=allowance.updated_at,
                                payload={
                                    "asset_allowance_id": existing.asset_allowance_id,
                                    "wallet_identity_id": existing.wallet_identity_id,
                                    "network": existing.network,
                                    "token_address": existing.token_address,
                                    "status": existing.status,
                                    "observed_allowance_atomic": str(
                                        allowance.observed_allowance_atomic
                                    ),
                                },
                            )
                        return self._asset_allowance(existing)
                    existing_block = existing.confirmed_block
                    if (
                        allowance.confirmed_block is None
                        or (
                            existing_block is not None
                            and allowance.confirmed_block <= existing_block
                        )
                    ):
                        raise ValueError("proof conflicts with existing allowance")
                    existing.approved_amount_atomic = Decimal(
                        allowance.approved_amount_atomic
                    )
                    existing.observed_allowance_atomic = Decimal(
                        allowance.observed_allowance_atomic
                    )
                    existing.allowance_tx_hash = allowance.allowance_tx_hash
                    existing.status = allowance.status
                    existing.confirmed_block = allowance.confirmed_block
                    existing.last_chain_check_at = allowance.last_chain_check_at
                    existing.updated_at = allowance.updated_at
                    self._append_account_audit(
                        session,
                        event_type="allowance_verified",
                        user_id=identity.user_id,
                        created_at=allowance.updated_at,
                        payload={
                            "asset_allowance_id": existing.asset_allowance_id,
                            "wallet_identity_id": existing.wallet_identity_id,
                            "network": existing.network,
                            "token_address": existing.token_address,
                            "status": existing.status,
                            "observed_allowance_atomic": str(
                                allowance.observed_allowance_atomic
                            ),
                        },
                    )
                    return self._asset_allowance(existing)
                session.add(
                    AssetAllowanceRow(
                        **allowance.model_dump(
                            exclude={"approved_amount_atomic", "observed_allowance_atomic"}
                        ),
                        approved_amount_atomic=Decimal(allowance.approved_amount_atomic),
                        observed_allowance_atomic=Decimal(allowance.observed_allowance_atomic),
                    )
                )
                self._append_account_audit(
                    session,
                    event_type="allowance_verified",
                    user_id=identity.user_id,
                    created_at=allowance.updated_at,
                    payload={
                        "asset_allowance_id": allowance.asset_allowance_id,
                        "wallet_identity_id": allowance.wallet_identity_id,
                        "network": allowance.network,
                        "token_address": allowance.token_address,
                        "status": allowance.status,
                        "observed_allowance_atomic": str(
                            allowance.observed_allowance_atomic
                        ),
                    },
                )
        except IntegrityError as exc:
            existing = self._asset_allowance_for_scope(allowance)
            if existing is not None:
                return self.save_verified_asset_allowance(allowance)
            raise ValueError("proof conflicts with existing allowance") from exc
        return allowance

    def asset_allowances(self, wallet_identity_id: str) -> list[AssetAllowance]:
        with self.sessions() as session:
            rows = session.scalars(
                select(AssetAllowanceRow)
                .where(AssetAllowanceRow.wallet_identity_id == wallet_identity_id)
                .order_by(AssetAllowanceRow.created_at, AssetAllowanceRow.asset_allowance_id)
            ).all()
        return [self._asset_allowance(row) for row in rows]

    def asset_allowance(self, asset_allowance_id: str) -> AssetAllowance | None:
        with self.sessions() as session:
            row = session.get(AssetAllowanceRow, asset_allowance_id)
        return self._asset_allowance(row) if row else None

    def spending_grant_daily_usage(
        self, spending_grant_id: str, usage_date: date
    ) -> tuple[Decimal, Decimal]:
        with self.sessions() as session:
            row = session.scalar(
                select(SpendingGrantDailyUsageRow).where(
                    SpendingGrantDailyUsageRow.spending_grant_id == spending_grant_id,
                    SpendingGrantDailyUsageRow.usage_date == usage_date,
                )
            )
        if row is None:
            return Decimal("0"), Decimal("0")
        return row.used_amount_usdc, row.reserved_amount_usdc

    def spending_grant_rolling_hour_usage(
        self, spending_grant_id: str, now: datetime
    ) -> tuple[Decimal, Decimal]:
        cutoff = self._required_utc(now) - timedelta(hours=1)
        with self.sessions() as session:
            rows = session.scalars(
                select(SpendingGrantRollingUsageRow).where(
                    SpendingGrantRollingUsageRow.spending_grant_id
                    == spending_grant_id,
                    SpendingGrantRollingUsageRow.occurred_at > cutoff,
                    SpendingGrantRollingUsageRow.state.in_(("reserved", "used")),
                )
            ).all()
        used = sum(
            (item.amount_usdc for item in rows if item.state == "used"), Decimal("0")
        )
        reserved = sum(
            (item.amount_usdc for item in rows if item.state == "reserved"),
            Decimal("0"),
        )
        return used, reserved

    def refresh_asset_allowance(
        self,
        asset_allowance_id: str,
        *,
        observed_allowance_atomic: int,
        status: str,
        now: datetime,
    ) -> AssetAllowance:
        now = self._required_utc(now)
        with self._write_session() as session:
            row = self._required_locked_asset_allowance(session, asset_allowance_id)
            identity = self._locked_wallet_identity(session, row.wallet_identity_id)
            if identity is None:
                raise ValueError("wallet identity was not found")
            row.observed_allowance_atomic = Decimal(observed_allowance_atomic)
            row.status = status
            row.last_chain_check_at = now
            row.updated_at = now
            self._append_account_audit(
                session,
                event_type="allowance_refreshed",
                user_id=identity.user_id,
                created_at=now,
                payload={
                    "asset_allowance_id": asset_allowance_id,
                    "wallet_identity_id": row.wallet_identity_id,
                    "network": row.network,
                    "token_address": row.token_address,
                    "status": status,
                    "observed_allowance_atomic": str(observed_allowance_atomic),
                },
            )
            return self._asset_allowance(row)

    def mark_asset_allowance_stale(
        self, asset_allowance_id: str, now: datetime
    ) -> AssetAllowance:
        now = self._required_utc(now)
        with self._write_session() as session:
            row = self._required_locked_asset_allowance(session, asset_allowance_id)
            identity = self._locked_wallet_identity(session, row.wallet_identity_id)
            if identity is None:
                raise ValueError("wallet identity was not found")
            row.status = "stale"
            row.updated_at = now
            self._append_account_audit(
                session,
                event_type="allowance_refreshed",
                user_id=identity.user_id,
                created_at=now,
                payload={
                    "asset_allowance_id": asset_allowance_id,
                    "wallet_identity_id": row.wallet_identity_id,
                    "network": row.network,
                    "token_address": row.token_address,
                    "status": "stale",
                    "observed_allowance_atomic": str(
                        int(row.observed_allowance_atomic)
                    ),
                },
            )
            return self._asset_allowance(row)

    def _locked_grant(
        self, session: Session, spending_grant_id: str
    ) -> SpendingGrantRow | None:
        statement = select(SpendingGrantRow).where(
            SpendingGrantRow.spending_grant_id == spending_grant_id
        )
        if self.engine.dialect.name != "sqlite":
            statement = statement.with_for_update()
        return session.scalar(statement)

    def _required_locked_grant(
        self, session: Session, spending_grant_id: str
    ) -> SpendingGrantRow:
        row = self._locked_grant(session, spending_grant_id)
        if row is None:
            raise ValueError("spending grant was not found")
        return row

    def _locked_asset_allowance_for_scope(
        self, session: Session, allowance: AssetAllowance
    ) -> AssetAllowanceRow | None:
        statement = select(AssetAllowanceRow).where(
            AssetAllowanceRow.wallet_identity_id == allowance.wallet_identity_id,
            AssetAllowanceRow.network == allowance.network,
            AssetAllowanceRow.token_address == allowance.token_address,
            AssetAllowanceRow.spender_address == allowance.spender_address,
        )
        if self.engine.dialect.name != "sqlite":
            statement = statement.with_for_update()
        return session.scalar(statement)

    def _required_locked_asset_allowance(
        self, session: Session, asset_allowance_id: str
    ) -> AssetAllowanceRow:
        statement = select(AssetAllowanceRow).where(
            AssetAllowanceRow.asset_allowance_id == asset_allowance_id
        )
        if self.engine.dialect.name != "sqlite":
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None:
            raise ValueError("asset allowance was not found")
        return row

    def _locked_account_session(
        self, session: Session, account_session_id: str
    ) -> AccountSessionRow | None:
        statement = select(AccountSessionRow).where(
            AccountSessionRow.account_session_id == account_session_id
        )
        if self.engine.dialect.name != "sqlite":
            statement = statement.with_for_update()
        return session.scalar(statement)

    def _locked_public_account_session(
        self, session: Session, public_account_session_id: str
    ) -> PublicAccountSessionRow | None:
        statement = select(PublicAccountSessionRow).where(
            PublicAccountSessionRow.public_account_session_id
            == public_account_session_id
        )
        if self.engine.dialect.name != "sqlite":
            statement = statement.with_for_update()
        return session.scalar(statement)

    def _locked_wallet_identity(
        self, session: Session, wallet_identity_id: str
    ) -> WalletIdentityRow | None:
        statement = select(WalletIdentityRow).where(
            WalletIdentityRow.wallet_identity_id == wallet_identity_id
        )
        if self.engine.dialect.name != "sqlite":
            statement = statement.with_for_update()
        return session.scalar(statement)

    def _locked_wallet_identity_for_scope(
        self, session: Session, identity: WalletIdentity
    ) -> WalletIdentityRow | None:
        statement = (
            select(WalletIdentityRow)
            .where(
                WalletIdentityRow.user_id == identity.user_id,
                WalletIdentityRow.chain_family == identity.chain_family,
                WalletIdentityRow.wallet_address == identity.wallet_address,
                WalletIdentityRow.status != "revoked",
            )
            .order_by(
                WalletIdentityRow.created_at.desc(),
                WalletIdentityRow.wallet_identity_id.desc(),
            )
        )
        if self.engine.dialect.name != "sqlite":
            statement = statement.with_for_update()
        return session.scalar(statement)

    def _locked_open_wallet_identity_for_user(
        self,
        session: Session,
        user_id: str,
    ) -> WalletIdentityRow | None:
        statement = (
            select(WalletIdentityRow)
            .where(
                WalletIdentityRow.user_id == user_id,
                WalletIdentityRow.status.in_(
                    ("pending", "active", "suspended")
                ),
            )
            .order_by(
                WalletIdentityRow.created_at.desc(),
                WalletIdentityRow.wallet_identity_id.desc(),
            )
        )
        if self.engine.dialect.name != "sqlite":
            statement = statement.with_for_update()
        return session.scalar(statement)

    def _locked_audit_event_by_idempotency_key(
        self, session: Session, idempotency_key: str
    ) -> AuditEventRow | None:
        statement = select(AuditEventRow).where(
            AuditEventRow.idempotency_key == idempotency_key
        )
        if self.engine.dialect.name != "sqlite":
            statement = statement.with_for_update()
        return session.scalar(statement)

    @staticmethod
    def _audit_event_matches(row: AuditEventRow, values: dict) -> bool:
        fields = (
            "event_type",
            "source_service",
            "action_id",
            "user_id",
            "agent_id",
            "policy_decision_id",
            "payment_id",
            "order_id",
            "receipt_id",
            "tx_hash",
        )
        return all(getattr(row, field) == values.get(field) for field in fields) and (
            row.payload == (values.get("payload") or {})
        )

    def _locked_wallet_bootstrap_state(
        self, session: Session, user_id: str
    ) -> AccountWalletBootstrapStateRow | None:
        statement = select(AccountWalletBootstrapStateRow).where(
            AccountWalletBootstrapStateRow.user_id == user_id
        )
        if self.engine.dialect.name != "sqlite":
            statement = statement.with_for_update()
        return session.scalar(statement)

    def _ensure_wallet_bootstrap_state(
        self,
        session: Session,
        *,
        user_id: str,
        wallet_identity_id: str,
        initialized_at: datetime,
    ) -> None:
        if self._locked_wallet_bootstrap_state(session, user_id) is None:
            session.add(
                AccountWalletBootstrapStateRow(
                    user_id=user_id,
                    first_wallet_identity_id=wallet_identity_id,
                    initialized_at=self._required_utc(initialized_at),
                )
            )

    def _wallet_identity_for_scope(
        self, identity: WalletIdentity
    ) -> WalletIdentity | None:
        with self.sessions() as session:
            row = session.scalar(
                select(WalletIdentityRow).where(
                    WalletIdentityRow.user_id == identity.user_id,
                    WalletIdentityRow.chain_family == identity.chain_family,
                    WalletIdentityRow.wallet_address == identity.wallet_address,
                    WalletIdentityRow.status != "revoked",
                ).order_by(
                    WalletIdentityRow.created_at.desc(),
                    WalletIdentityRow.wallet_identity_id.desc(),
                )
            )
        return self._wallet_identity(row) if row else None

    def _spending_grant_by_id(self, spending_grant_id: str) -> SpendingGrant | None:
        with self.sessions() as session:
            row = session.get(SpendingGrantRow, spending_grant_id)
        return self._spending_grant(row) if row else None

    def _asset_allowance_for_scope(
        self, allowance: AssetAllowance
    ) -> AssetAllowance | None:
        with self.sessions() as session:
            row = session.scalar(
                select(AssetAllowanceRow).where(
                    AssetAllowanceRow.wallet_identity_id == allowance.wallet_identity_id,
                    AssetAllowanceRow.network == allowance.network,
                    AssetAllowanceRow.token_address == allowance.token_address,
                    AssetAllowanceRow.spender_address == allowance.spender_address,
                )
            )
        return self._asset_allowance(row) if row else None

    @staticmethod
    def _assign(row, values: dict) -> None:
        for key, value in values.items():
            setattr(row, key, value)

    @staticmethod
    def _required_utc(value: datetime) -> datetime:
        result = _utc_timestamp(value)
        if result is None:
            raise ValueError("timestamp is required")
        return result

    @staticmethod
    def _wallet_identity(row: WalletIdentityRow) -> WalletIdentity:
        values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        for field in ("verified_at", "created_at", "updated_at"):
            values[field] = _utc_timestamp(values[field])
        return WalletIdentity(**values)

    @staticmethod
    def _account_session(row: AccountSessionRow) -> AccountSession:
        values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        for field in ("expires_at", "consumed_at", "created_at"):
            values[field] = _utc_timestamp(values[field])
        return AccountSession(**values)

    @staticmethod
    def _public_account_session(row: PublicAccountSessionRow) -> PublicAccountSession:
        values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        for field in (
            "expires_at",
            "exchanged_at",
            "authenticated_at",
            "last_accessed_at",
            "revoked_at",
            "created_at",
            "updated_at",
        ):
            values[field] = _utc_timestamp(values[field])
        return PublicAccountSession(**values)

    @staticmethod
    def _audit_event(row: AuditEventRow) -> dict:
        values = {
            column.name: getattr(row, column.name)
            for column in row.__table__.columns
            if column.name not in {"audit_sequence_id", "idempotency_key"}
        }
        values["created_at"] = _utc_timestamp(values["created_at"])
        return values

    @staticmethod
    def _spending_grant(row: SpendingGrantRow) -> SpendingGrant:
        values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        for field in ("starts_at", "expires_at", "created_at", "updated_at"):
            values[field] = _utc_timestamp(values[field])
        return SpendingGrant(**values)

    @staticmethod
    def _asset_allowance(row: AssetAllowanceRow) -> AssetAllowance:
        values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        values["approved_amount_atomic"] = int(values["approved_amount_atomic"])
        values["observed_allowance_atomic"] = int(values["observed_allowance_atomic"])
        for field in ("last_chain_check_at", "created_at", "updated_at"):
            values[field] = _utc_timestamp(values[field])
        return AssetAllowance(**values)
