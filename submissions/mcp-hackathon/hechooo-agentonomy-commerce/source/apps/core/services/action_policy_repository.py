from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    create_engine,
    event,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from services.account_service.repository import sqlite_immediate_session


class Base(DeclarativeBase):
    pass


class ActionIntentRow(Base):
    __tablename__ = "action_intents"
    __table_args__ = (
        CheckConstraint("length(action_id) > 0", name="ck_action_intent_id_nonempty"),
        CheckConstraint("length(state) > 0", name="ck_action_intent_state_nonempty"),
        Index("ix_action_intents_user_agent_created", "user_id", "agent_id", "created_at"),
    )

    action_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(96), index=True)
    agent_id: Mapped[str] = mapped_column(String(96), index=True)
    action_type: Mapped[str] = mapped_column(String(96), index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    policy_decision_id: Mapped[str | None] = mapped_column(String(96), index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ActionApprovalRow(Base):
    __tablename__ = "action_approvals"
    __table_args__ = (
        CheckConstraint(
            "proof_hash IS NULL OR (length(proof_hash) = 66 AND "
            "substr(proof_hash, 1, 2) = '0x' AND proof_hash = lower(proof_hash))",
            name="ck_action_approval_proof_hash_canonical",
        ),
        CheckConstraint("length(state) > 0", name="ck_action_approval_state_nonempty"),
        Index("ix_action_approvals_action_created", "action_id", "created_at"),
    )

    approval_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    action_id: Mapped[str] = mapped_column(
        ForeignKey("action_intents.action_id"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(96), index=True)
    agent_id: Mapped[str] = mapped_column(String(96), index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    proof_hash: Mapped[str | None] = mapped_column(String(66))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PolicyDecisionRow(Base):
    __tablename__ = "policy_decisions"
    __table_args__ = (
        CheckConstraint(
            "target_address IS NULL OR (length(target_address) = 42 AND "
            "substr(target_address, 1, 2) = '0x' AND "
            "target_address = lower(target_address))",
            name="ck_policy_decision_target_canonical",
        ),
        CheckConstraint(
            "chain IS NULL OR chain IN "
            "('eip155:137', 'eip155:8453', 'eip155:80002')",
            name="ck_policy_decision_chain_canonical",
        ),
        Index("ix_policy_decisions_action_evaluated", "action_id", "evaluated_at"),
    )

    policy_decision_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    action_id: Mapped[str | None] = mapped_column(String(96), index=True)
    user_id: Mapped[str] = mapped_column(String(96), index=True)
    agent_id: Mapped[str] = mapped_column(String(96), index=True)
    action_type: Mapped[str] = mapped_column(String(96), index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    target_address: Mapped[str | None] = mapped_column(String(42))
    chain: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ActionPolicyRepository:
    """Durable authority for Action, Approval, and Policy provenance."""

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
            Base.metadata.create_all(self.engine)

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    @contextmanager
    def _write_session(self):
        if self.engine.dialect.name == "sqlite":
            with sqlite_immediate_session(
                self.sessions, operation="sqlite action-policy write transaction"
            ) as session:
                yield session
            return
        with self.sessions.begin() as session:
            yield session

    def create_action_intent(self, payload: dict) -> dict:
        created_at = self._timestamp(payload["created_at"])
        try:
            with self._write_session() as session:
                session.add(
                    ActionIntentRow(
                        action_id=payload["action_id"],
                        user_id=payload["user_id"],
                        agent_id=payload["agent_id"],
                        action_type=payload["action_type"],
                        state=payload["state"],
                        policy_decision_id=payload.get("policy_decision_id"),
                        payload=deepcopy(payload),
                        created_at=created_at,
                        updated_at=self._timestamp(payload["updated_at"]),
                    )
                )
        except IntegrityError as exc:
            raise ValueError("action intent already exists") from exc
        return deepcopy(payload)

    def action_intent(self, action_id: str) -> dict | None:
        with self.sessions() as session:
            row = session.get(ActionIntentRow, action_id)
        return deepcopy(row.payload) if row is not None else None

    def update_action_intent(
        self, action_id: str, transform: Callable[[dict], dict]
    ) -> dict | None:
        with self._write_session() as session:
            row = self._locked(session, ActionIntentRow, action_id)
            if row is None:
                return None
            payload = transform(deepcopy(row.payload))
            self._assign_action(row, payload)
            return deepcopy(payload)

    def create_action_approval(self, payload: dict) -> dict:
        created_at = self._timestamp(payload["created_at"])
        try:
            with self._write_session() as session:
                session.add(
                    ActionApprovalRow(
                        approval_id=payload["approval_id"],
                        action_id=payload["action_id"],
                        user_id=payload["user_id"],
                        agent_id=payload["agent_id"],
                        state=payload["state"],
                        proof_hash=payload.get("proof_hash"),
                        payload=deepcopy(payload),
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
        except IntegrityError as exc:
            raise ValueError("action approval could not be persisted") from exc
        return deepcopy(payload)

    def action_approval(self, approval_id: str) -> dict | None:
        with self.sessions() as session:
            row = session.get(ActionApprovalRow, approval_id)
        return deepcopy(row.payload) if row is not None else None

    def update_action_approval(
        self, approval_id: str, transform: Callable[[dict], dict]
    ) -> dict | None:
        with self._write_session() as session:
            row = self._locked(session, ActionApprovalRow, approval_id)
            if row is None:
                return None
            payload = transform(deepcopy(row.payload))
            row.state = payload["state"]
            row.proof_hash = payload.get("proof_hash")
            row.payload = deepcopy(payload)
            row.version += 1
            row.updated_at = self._timestamp(payload["responded_at"])
            return deepcopy(payload)

    def create_policy_decision(self, payload: dict) -> dict:
        try:
            with self._write_session() as session:
                session.add(
                    PolicyDecisionRow(
                        policy_decision_id=payload["policy_decision_id"],
                        action_id=payload.get("action_id"),
                        user_id=payload["user_id"],
                        agent_id=payload["agent_id"],
                        action_type=payload["action_type"],
                        decision=payload["decision"],
                        target_address=payload.get("target_address"),
                        chain=payload.get("chain"),
                        payload=deepcopy(payload),
                        evaluated_at=self._timestamp(payload["evaluated_at"]),
                    )
                )
        except IntegrityError as exc:
            raise ValueError("policy decision could not be persisted") from exc
        return deepcopy(payload)

    def policy_decision(self, policy_decision_id: str) -> dict | None:
        with self.sessions() as session:
            row = session.get(PolicyDecisionRow, policy_decision_id)
        return deepcopy(row.payload) if row is not None else None

    def _locked(self, session: Session, model, primary_key: str):
        statement = select(model).where(model.__mapper__.primary_key[0] == primary_key)
        if self.engine.dialect.name != "sqlite":
            statement = statement.with_for_update()
        return session.scalar(statement)

    def _assign_action(self, row: ActionIntentRow, payload: dict) -> None:
        row.state = payload["state"]
        row.policy_decision_id = payload.get("policy_decision_id")
        row.payload = deepcopy(payload)
        row.version += 1
        row.updated_at = self._timestamp(payload["updated_at"])

    @staticmethod
    def _timestamp(value: str) -> datetime:
        timestamp = datetime.fromisoformat(value.removesuffix("Z"))
        return timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp
