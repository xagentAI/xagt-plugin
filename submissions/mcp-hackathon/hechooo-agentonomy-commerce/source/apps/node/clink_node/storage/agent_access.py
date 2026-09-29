from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterator

from sqlalchemy import select, update
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import IntegrityError

from .postgres import (
    agent_binding,
    agent_runtime_credential,
    agent_runtime_revocation,
)


class _AgentAccessRepositoryConflict(RuntimeError):
    pass


class _AgentAccessRepositoryNotFound(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AgentBindingRecord:
    agent_id: str
    user_id: str
    issuer: str
    subject_id: str
    external_agent_id: str
    current_credential_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeCredentialRecord:
    credential_id: str
    agent_id: str
    runtime_id: str
    request_id: str
    scope: str
    request_fingerprint: str
    secret_digest: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    replaced_credential_id: str | None


class AgentAccessRepository:
    """Durable storage for Agent bindings and runtime credentials.

    Node's versioned migration owns the table lifecycle. This repository only
    operates on an already migrated SQLAlchemy engine and deliberately never
    calls ``create_all``.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        if self.engine.dialect.name not in {"sqlite", "postgresql"}:
            raise RuntimeError("unsupported_storage_dialect")

    def register(
        self,
        *,
        agent_id: str,
        user_id: str,
        issuer: str,
        subject_id: str,
        external_agent_id: str,
        created_at: datetime,
    ) -> AgentBindingRecord:
        values = {
            "agent_id": agent_id,
            "user_id": user_id,
            "issuer": issuer,
            "subject_id": subject_id,
            "external_agent_id": external_agent_id,
            "current_credential_id": None,
            "created_at": _utc(created_at),
        }
        try:
            with self._write_transaction() as connection:
                by_subject = self._select_binding(
                    connection,
                    issuer=issuer,
                    subject_id=subject_id,
                    for_update=True,
                )
                if by_subject is not None:
                    if by_subject["external_agent_id"] == external_agent_id:
                        return _binding_from_row(by_subject)
                    raise _AgentAccessRepositoryConflict()

                by_external = self._select_binding(
                    connection,
                    issuer=issuer,
                    external_agent_id=external_agent_id,
                    for_update=True,
                )
                if by_external is not None:
                    raise _AgentAccessRepositoryConflict()

                connection.execute(agent_binding.insert().values(**values))
                return _binding_from_values(values)
        except IntegrityError as exc:
            existing = self._find_binding_by_identity(
                issuer=issuer,
                subject_id=subject_id,
            )
            if (
                existing is not None
                and existing.external_agent_id == external_agent_id
            ):
                return existing
            raise _AgentAccessRepositoryConflict() from exc

    def get_agent(
        self,
        agent_id: str,
        *,
        issuer: str | None = None,
    ) -> AgentBindingRecord | None:
        with self.engine.connect() as connection:
            statement = select(agent_binding).where(
                agent_binding.c.agent_id == agent_id
            )
            if issuer is not None:
                statement = statement.where(agent_binding.c.issuer == issuer)
            row = connection.execute(statement).mappings().first()
        return _binding_from_row(row) if row is not None else None

    def get_runtime_status(
        self,
        agent_id: str,
        *,
        issuer: str,
    ) -> tuple[AgentBindingRecord, RuntimeCredentialRecord | None] | None:
        """Read one issuer-scoped binding and its pointed credential snapshot.

        This is deliberately a single, unlocked left join.  The binding's
        current credential pointer is the only credential eligible for the
        status view; historical credentials and all secret-bearing columns are
        kept inside the repository boundary.
        """

        binding = agent_binding.c
        credential = agent_runtime_credential.c
        statement = (
            select(
                binding.agent_id.label("binding_agent_id"),
                binding.user_id.label("binding_user_id"),
                binding.issuer.label("binding_issuer"),
                binding.subject_id.label("binding_subject_id"),
                binding.external_agent_id.label("binding_external_agent_id"),
                binding.current_credential_id.label(
                    "binding_current_credential_id"
                ),
                binding.created_at.label("binding_created_at"),
                credential.credential_id.label("credential_id"),
                credential.agent_id.label("credential_agent_id"),
                credential.runtime_id.label("credential_runtime_id"),
                credential.request_id.label("credential_request_id"),
                credential.scope.label("credential_scope"),
                credential.request_fingerprint.label(
                    "credential_request_fingerprint"
                ),
                credential.secret_digest.label("credential_secret_digest"),
                credential.issued_at.label("credential_issued_at"),
                credential.expires_at.label("credential_expires_at"),
                credential.revoked_at.label("credential_revoked_at"),
                credential.replaced_credential_id.label(
                    "credential_replaced_credential_id"
                ),
            )
            .select_from(
                agent_binding.outerjoin(
                    agent_runtime_credential,
                    (credential.agent_id == binding.agent_id)
                    & (
                        credential.credential_id
                        == binding.current_credential_id
                    ),
                )
            )
            .where(
                binding.agent_id == agent_id,
                binding.issuer == issuer,
            )
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            return None

        binding_record = AgentBindingRecord(
            agent_id=str(row["binding_agent_id"]),
            user_id=str(row["binding_user_id"]),
            issuer=str(row["binding_issuer"]),
            subject_id=str(row["binding_subject_id"]),
            external_agent_id=str(row["binding_external_agent_id"]),
            current_credential_id=(
                str(row["binding_current_credential_id"])
                if row["binding_current_credential_id"] is not None
                else None
            ),
            created_at=_datetime(row["binding_created_at"]),
        )
        if row["credential_id"] is None:
            return binding_record, None
        return binding_record, RuntimeCredentialRecord(
            credential_id=str(row["credential_id"]),
            agent_id=str(row["credential_agent_id"]),
            runtime_id=str(row["credential_runtime_id"]),
            request_id=str(row["credential_request_id"]),
            scope=str(row["credential_scope"]),
            request_fingerprint=str(row["credential_request_fingerprint"]),
            secret_digest=str(row["credential_secret_digest"]),
            issued_at=_datetime(row["credential_issued_at"]),
            expires_at=_datetime(row["credential_expires_at"]),
            revoked_at=(
                _datetime(row["credential_revoked_at"])
                if row["credential_revoked_at"] is not None
                else None
            ),
            replaced_credential_id=(
                str(row["credential_replaced_credential_id"])
                if row["credential_replaced_credential_id"] is not None
                else None
            ),
        )

    def issue_credential(
        self,
        *,
        issuer: str,
        agent_id: str,
        runtime_id: str,
        request_id: str,
        scope: str,
        request_fingerprint: str,
        credential_id: str,
        secret_digest: str,
        issued_at: datetime,
        expires_at: datetime,
        replaces_credential_id: str | None,
    ) -> RuntimeCredentialRecord:
        issued_at = _utc(issued_at)
        expires_at = _utc(expires_at)
        with self._write_transaction() as connection:
            binding_row = self._select_binding(
                connection,
                agent_id=agent_id,
                issuer=issuer,
                for_update=True,
            )
            if binding_row is None:
                raise _AgentAccessRepositoryNotFound()

            existing_row = connection.execute(
                select(agent_runtime_credential)
                .where(
                    agent_runtime_credential.c.agent_id == agent_id,
                    agent_runtime_credential.c.request_id == request_id,
                )
                .with_for_update()
            ).mappings().first()
            if existing_row is not None:
                if existing_row["request_fingerprint"] == request_fingerprint:
                    return _credential_from_row(existing_row)
                raise _AgentAccessRepositoryConflict()

            revoked_runtime = connection.execute(
                select(agent_runtime_revocation)
                .where(
                    agent_runtime_revocation.c.agent_id == agent_id,
                    agent_runtime_revocation.c.runtime_id == runtime_id,
                )
                .with_for_update()
            ).first()
            if revoked_runtime is not None:
                raise _AgentAccessRepositoryConflict()

            current_credential_id = binding_row["current_credential_id"]
            previous_row: RowMapping | None = None
            if current_credential_id is None:
                historical_row = connection.execute(
                    select(agent_runtime_credential.c.credential_id)
                    .where(
                        agent_runtime_credential.c.agent_id == agent_id,
                        agent_runtime_credential.c.runtime_id == runtime_id,
                    )
                ).first()
                if historical_row is not None:
                    raise _AgentAccessRepositoryConflict()
                if replaces_credential_id is not None:
                    raise _AgentAccessRepositoryConflict()
            else:
                if replaces_credential_id != current_credential_id:
                    raise _AgentAccessRepositoryConflict()
                previous_row = connection.execute(
                    select(agent_runtime_credential)
                    .where(
                        agent_runtime_credential.c.credential_id
                        == current_credential_id,
                        agent_runtime_credential.c.agent_id == agent_id,
                    )
                    .with_for_update()
                ).mappings().first()
                if previous_row is None:
                    raise _AgentAccessRepositoryConflict()
                if previous_row["runtime_id"] != runtime_id:
                    historical_row = connection.execute(
                        select(agent_runtime_credential.c.credential_id)
                        .where(
                            agent_runtime_credential.c.agent_id == agent_id,
                            agent_runtime_credential.c.runtime_id
                            == runtime_id,
                        )
                    ).first()
                    if historical_row is not None:
                        raise _AgentAccessRepositoryConflict()

            values = {
                "credential_id": credential_id,
                "agent_id": agent_id,
                "runtime_id": runtime_id,
                "request_id": request_id,
                "scope": scope,
                "request_fingerprint": request_fingerprint,
                "secret_digest": secret_digest,
                "issued_at": issued_at,
                "expires_at": expires_at,
                "revoked_at": None,
                "replaced_credential_id": replaces_credential_id,
            }
            connection.execute(
                agent_runtime_credential.insert().values(**values)
            )
            if previous_row is not None and previous_row["revoked_at"] is None:
                connection.execute(
                    update(agent_runtime_credential)
                    .where(
                        agent_runtime_credential.c.credential_id
                        == current_credential_id
                    )
                    .values(revoked_at=issued_at)
                )
            connection.execute(
                update(agent_binding)
                .where(agent_binding.c.agent_id == agent_id)
                .values(current_credential_id=credential_id)
            )
            return _credential_from_values(values)

    def authenticate(
        self,
        *,
        secret_digest: str,
    ) -> tuple[AgentBindingRecord, RuntimeCredentialRecord] | None:
        with self.engine.connect() as connection:
            credential_row = connection.execute(
                select(agent_runtime_credential).where(
                    agent_runtime_credential.c.secret_digest == secret_digest
                )
            ).mappings().first()
            if credential_row is None:
                return None
            binding_row = connection.execute(
                select(agent_binding).where(
                    agent_binding.c.agent_id == credential_row["agent_id"],
                    agent_binding.c.current_credential_id
                    == credential_row["credential_id"],
                )
            ).mappings().first()
        if binding_row is None:
            return None
        return _binding_from_row(binding_row), _credential_from_row(
            credential_row
        )

    def revoke_runtime(
        self,
        *,
        issuer: str,
        agent_id: str,
        runtime_id: str,
        revoked_at: datetime,
    ) -> bool:
        revoked_at = _utc(revoked_at)
        with self._write_transaction() as connection:
            binding_row = self._select_binding(
                connection,
                agent_id=agent_id,
                issuer=issuer,
                for_update=True,
            )
            if binding_row is None:
                raise _AgentAccessRepositoryNotFound()

            tombstone = connection.execute(
                select(agent_runtime_revocation)
                .where(
                    agent_runtime_revocation.c.agent_id == agent_id,
                    agent_runtime_revocation.c.runtime_id == runtime_id,
                )
                .with_for_update()
            ).first()
            if tombstone is None:
                connection.execute(
                    agent_runtime_revocation.insert().values(
                        agent_id=agent_id,
                        runtime_id=runtime_id,
                        revoked_at=revoked_at,
                    )
                )

            current_credential_id = binding_row["current_credential_id"]
            if current_credential_id is None:
                return False
            credential_row = connection.execute(
                select(agent_runtime_credential)
                .where(
                    agent_runtime_credential.c.credential_id
                    == current_credential_id,
                    agent_runtime_credential.c.agent_id == agent_id,
                )
                .with_for_update()
            ).mappings().first()
            if credential_row is None:
                raise _AgentAccessRepositoryConflict()
            current_matches = credential_row["runtime_id"] == runtime_id
            connection.execute(
                update(agent_runtime_credential)
                .where(
                    agent_runtime_credential.c.agent_id == agent_id,
                    agent_runtime_credential.c.runtime_id == runtime_id,
                    agent_runtime_credential.c.revoked_at.is_(None),
                )
                .values(revoked_at=revoked_at)
            )
            return current_matches

    def _find_binding_by_identity(
        self,
        *,
        issuer: str,
        subject_id: str,
    ) -> AgentBindingRecord | None:
        with self.engine.connect() as connection:
            row = self._select_binding(
                connection,
                issuer=issuer,
                subject_id=subject_id,
            )
        return _binding_from_row(row) if row is not None else None

    @staticmethod
    def _select_binding(
        connection: Connection,
        *,
        agent_id: str | None = None,
        issuer: str | None = None,
        subject_id: str | None = None,
        external_agent_id: str | None = None,
        for_update: bool = False,
    ) -> RowMapping | None:
        conditions = []
        if agent_id is not None:
            conditions.append(agent_binding.c.agent_id == agent_id)
        if issuer is not None:
            conditions.append(agent_binding.c.issuer == issuer)
        if subject_id is not None:
            conditions.append(agent_binding.c.subject_id == subject_id)
        if external_agent_id is not None:
            conditions.append(
                agent_binding.c.external_agent_id == external_agent_id
            )
        statement = select(agent_binding).where(*conditions)
        if for_update:
            statement = statement.with_for_update()
        return connection.execute(statement).mappings().first()

    @contextmanager
    def _write_transaction(self) -> Iterator[Connection]:
        if self.engine.dialect.name == "sqlite":
            connection = self.engine.connect()
            try:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
            return

        with self.engine.begin() as connection:
            yield connection


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("datetime_required")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone_required")
    return value.astimezone(UTC)


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    raise RuntimeError("invalid_storage_timestamp")


def _binding_from_row(row: RowMapping) -> AgentBindingRecord:
    return AgentBindingRecord(
        agent_id=str(row["agent_id"]),
        user_id=str(row["user_id"]),
        issuer=str(row["issuer"]),
        subject_id=str(row["subject_id"]),
        external_agent_id=str(row["external_agent_id"]),
        current_credential_id=(
            str(row["current_credential_id"])
            if row["current_credential_id"] is not None
            else None
        ),
        created_at=_datetime(row["created_at"]),
    )


def _binding_from_values(values: dict[str, object]) -> AgentBindingRecord:
    return AgentBindingRecord(
        agent_id=str(values["agent_id"]),
        user_id=str(values["user_id"]),
        issuer=str(values["issuer"]),
        subject_id=str(values["subject_id"]),
        external_agent_id=str(values["external_agent_id"]),
        current_credential_id=None,
        created_at=_datetime(values["created_at"]),
    )


def _credential_from_row(row: RowMapping) -> RuntimeCredentialRecord:
    return RuntimeCredentialRecord(
        credential_id=str(row["credential_id"]),
        agent_id=str(row["agent_id"]),
        runtime_id=str(row["runtime_id"]),
        request_id=str(row["request_id"]),
        scope=str(row["scope"]),
        request_fingerprint=str(row["request_fingerprint"]),
        secret_digest=str(row["secret_digest"]),
        issued_at=_datetime(row["issued_at"]),
        expires_at=_datetime(row["expires_at"]),
        revoked_at=(
            _datetime(row["revoked_at"])
            if row["revoked_at"] is not None
            else None
        ),
        replaced_credential_id=(
            str(row["replaced_credential_id"])
            if row["replaced_credential_id"] is not None
            else None
        ),
    )


def _credential_from_values(
    values: dict[str, object],
) -> RuntimeCredentialRecord:
    return RuntimeCredentialRecord(
        credential_id=str(values["credential_id"]),
        agent_id=str(values["agent_id"]),
        runtime_id=str(values["runtime_id"]),
        request_id=str(values["request_id"]),
        scope=str(values["scope"]),
        request_fingerprint=str(values["request_fingerprint"]),
        secret_digest=str(values["secret_digest"]),
        issued_at=_datetime(values["issued_at"]),
        expires_at=_datetime(values["expires_at"]),
        revoked_at=None,
        replaced_credential_id=(
            str(values["replaced_credential_id"])
            if values["replaced_credential_id"] is not None
            else None
        ),
    )


__all__ = [
    "AgentAccessRepository",
    "AgentBindingRecord",
    "RuntimeCredentialRecord",
]
