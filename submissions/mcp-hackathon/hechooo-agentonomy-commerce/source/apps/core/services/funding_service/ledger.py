from __future__ import annotations
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import re
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from services.account_service.repository import (
    AuditEventRow,
    AssetAllowanceRow,
    SpendingGrantDailyUsageRow,
    SpendingGrantRollingUsageRow,
    SpendingGrantRow,
    WalletIdentityRow,
    sqlite_immediate_session,
)
from services.account_service.opc_service import OpcInstallationRow
from services.action_policy_repository import ActionIntentRow, PolicyDecisionRow
from services.action_service.schemas import AgentActionIntent
from services.policy_service.schemas import PolicyDecision
from shared.payment_capability import PaymentCapabilityV1
from shared.hosted_facilitator_protocol import HostedExecutionResponse


TRANSACTION_HASH_PATTERN = re.compile(r"^0[xX]([0-9a-fA-F]{64})$")
RFC3339_UTC_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
LEGACY_READ_ONLY_ERROR = "legacy spending authorizations are read-only"
LEGACY_EXTERNAL_PAYMENT_FIELD = "external_payment_response"
LEGACY_SIGNED_TRANSACTION_FIELD = "settlement_raw_transaction"
PAYMENT_CAPABILITY_RECORD_TYPE = "payment_capability"
UNIFIED_RESERVATION_PROVENANCE_FIELDS = (
    "reservation_id",
    "wallet_identity_id",
    "spending_grant_id",
    "authorization_rail",
    "product",
    "network",
    "token_address",
    "token_symbol",
    "token_decimals",
)
NATIVE_ALLOWANCE_PROVENANCE_FIELDS = ("asset_allowance_id", "spender_address")
EXTERNAL_X402_PROVENANCE_FIELDS = ("token_address", "token_symbol", "token_decimals")
RESERVATION_IMMUTABLE_FIELDS: tuple[str, ...] = (
    "reservation_id",
    "purchase_id",
    "idempotency_key",
    "user_id",
    "agent_id",
    "action_id",
    "policy_decision_id",
    "quote_hash",
    "product",
    "single_submission",
    "venue",
    "merchant_id",
    "destination",
    "resource",
    "network",
    "asset",
    "token_address",
    "token_symbol",
    "token_decimals",
    "spender_address",
    "wallet_identity_id",
    "spending_grant_id",
    "asset_allowance_id",
    "opc_installation_id",
    "amount_usdc",
    "amount_atomic",
    "authorization_rail",
    "authorization_path",
    "authorization_source",
    "spending_authorization_id",
    "usage_date",
    "nonce",
    "valid_after",
    "valid_before",
    "settlement_transaction",
)
SINGLE_SUBMISSION_CANONICAL_FIELDS: tuple[str, ...] = (
    "tx_hash",
    "settlement_sender",
    "settlement_nonce",
    "settlement_transaction",
)


def require_unified_reservation(row: dict) -> None:
    if not isinstance(row, dict) or row.get("authorization_path") != "unified_grant":
        raise ValueError(LEGACY_READ_ONLY_ERROR)
    if any(row.get(field) in {None, ""} for field in UNIFIED_RESERVATION_PROVENANCE_FIELDS):
        raise ValueError("unified authorization references are incomplete")
    single_submission = row.get("single_submission", False)
    if not isinstance(single_submission, bool):
        raise ValueError("single-submission provenance is invalid")
    if row.get("product") == "prediction_markets" and single_submission is not True:
        raise ValueError("prediction-markets reservations require single submission")
    replacement_forbidden = row.get("replacement_forbidden", False)
    if not isinstance(replacement_forbidden, bool):
        raise ValueError("single-submission replacement state is invalid")
    rail = row.get("authorization_rail")
    if rail in {"native_allowance", "clink_payer_proxy"}:
        if any(
            row.get(field) in {None, ""}
            for field in NATIVE_ALLOWANCE_PROVENANCE_FIELDS
        ):
            raise ValueError("native allowance provenance is incomplete")
    elif rail == "external_x402":
        if row.get("asset_allowance_id") is not None or row.get("spender_address") is not None:
            raise ValueError("external x402 must not contain allowance provenance")
        if any(
            row.get(field) in {None, ""}
            for field in EXTERNAL_X402_PROVENANCE_FIELDS
        ):
            raise ValueError("external x402 asset provenance is incomplete")
    else:
        raise ValueError("unified reservation authorization rail is invalid")


def require_matching_reservation_immutable_fields(
    stored: Mapping[str, object], replacement: Mapping[str, object]
) -> None:
    changed = tuple(
        field
        for field in RESERVATION_IMMUTABLE_FIELDS
        if stored.get(field) != replacement.get(field)
        # The exact native transaction is sealed only when submission begins.
        and not (
            field == "settlement_transaction"
            and stored.get(field) is None
            and isinstance(replacement.get(field), dict)
        )
        # A proven on-chain failure or definite node rejection resets the
        # reservation before a fresh submission; unknown transactions stay sealed.
        and not (
            field == "settlement_transaction"
            and replacement.get("state") == "spending_reserved"
            and replacement.get(field) is None
            and stored.get("single_submission") is not True
        )
    )
    if stored.get("single_submission") is True:
        changed += tuple(
            field
            for field in SINGLE_SUBMISSION_CANONICAL_FIELDS
            if stored.get(field) is not None
            and stored.get(field) != replacement.get(field)
            and field not in changed
        )
        if (
            stored.get("replacement_forbidden") is True
            and replacement.get("replacement_forbidden") is not True
        ):
            changed += ("replacement_forbidden",)
        stored_evidence = stored.get("failed_submission_evidence", [])
        replacement_evidence = replacement.get("failed_submission_evidence", [])
        if isinstance(stored_evidence, list) and isinstance(
            replacement_evidence, list
        ):
            evidence_changed = (
                replacement_evidence[: len(stored_evidence)] != stored_evidence
            )
        else:
            evidence_changed = stored_evidence != replacement_evidence
        if evidence_changed:
            changed += ("failed_submission_evidence",)
    if changed:
        raise ValueError(
            "immutable reservation provenance or spend scope changed: "
            + ", ".join(changed)
        )


def canonicalize_transaction_hash(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("transaction hash must be a string")
    match = TRANSACTION_HASH_PATTERN.fullmatch(value)
    if not match:
        raise ValueError("transaction hash must be 0x followed by 64 hex characters")
    return "0x" + match.group(1).lower()


def redact_external_payment_payload(payload: Mapping[str, object]) -> dict:
    safe = dict(payload)
    safe.pop(LEGACY_EXTERNAL_PAYMENT_FIELD, None)
    safe.pop(LEGACY_SIGNED_TRANSACTION_FIELD, None)
    return safe

class Base(DeclarativeBase): pass
class LockRow(Base):
    __tablename__="funding_locks";lock_id:Mapped[int]=mapped_column(Integer,primary_key=True)
class RelayerNonceRow(Base):
    __tablename__ = "funding_relayer_nonces"
    network: Mapped[str] = mapped_column(String(64), primary_key=True)
    relayer_address: Mapped[str] = mapped_column(String(42), primary_key=True)
    next_nonce: Mapped[Decimal] = mapped_column(Numeric(20, 0))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("next_nonce >= 0", name="ck_funding_relayer_nonce_nonnegative"),
        CheckConstraint(
            "length(relayer_address) = 42 AND "
            "substr(relayer_address, 1, 2) = '0x' AND "
            "relayer_address = lower(relayer_address)",
            name="ck_funding_relayer_address_canonical",
        ),
    )
class TransactionBindingRow(Base):
    __tablename__="funding_transaction_bindings"
    tx_hash:Mapped[str]=mapped_column(String(66),primary_key=True)
    reservation_id:Mapped[str]=mapped_column(String(96),index=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    __table_args__=(
        CheckConstraint(
            "length(tx_hash) = 66 AND substr(tx_hash, 1, 2) = '0x' "
            "AND tx_hash = lower(tx_hash)",
            name="ck_funding_transaction_binding_hash_canonical",
        ),
    )
class LedgerRow(Base):
    __tablename__="funding_ledger_records"
    record_id:Mapped[str]=mapped_column(String(96),primary_key=True)
    record_type:Mapped[str]=mapped_column(String(32),index=True)
    purchase_id:Mapped[str|None]=mapped_column(String(96),unique=True,index=True)
    idempotency_key:Mapped[str|None]=mapped_column(String(128),unique=True)
    action_id:Mapped[str|None]=mapped_column(String(96),unique=True)
    policy_decision_id:Mapped[str|None]=mapped_column(String(96),unique=True)
    reservation_id:Mapped[str|None]=mapped_column(String(96),unique=True)
    tx_hash:Mapped[str|None]=mapped_column(String(80),unique=True)
    token_address:Mapped[str|None]=mapped_column(String(42))
    payload:Mapped[dict]=mapped_column(JSON)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "tx_hash IS NULL OR (length(tx_hash) = 66 AND "
            "substr(tx_hash, 1, 2) = '0x' AND tx_hash = lower(tx_hash))",
            name="ck_funding_ledger_tx_hash_canonical",
        ),
        Index(
            "uq_funding_ledger_tx_hash_normalized",
            func.lower(tx_hash),
            unique=True,
            sqlite_where=tx_hash.is_not(None),
            postgresql_where=tx_hash.is_not(None),
        ),
    )


class PaymentCapabilityConflictError(ValueError):
    """A safe domain error for an immutable capability binding conflict."""


class PaymentCapabilityRow(Base):
    """Append-only durable projection of one Core payment capability."""

    __tablename__ = "funding_payment_capabilities"
    __table_args__ = (
        UniqueConstraint("capability_hash", name="uq_payment_capability_hash"),
        UniqueConstraint("reservation_id", name="uq_payment_capability_reservation"),
        UniqueConstraint(
            "idempotency_key", name="uq_payment_capability_idempotency"
        ),
        CheckConstraint(
            "capability_version = 'clink-payment-capability-v1'",
            name="ck_payment_capability_version",
        ),
        CheckConstraint(
            "length(capability_hash) = 66 AND substr(capability_hash, 1, 2) = '0x' "
            "AND capability_hash = lower(capability_hash)",
            name="ck_payment_capability_hash_canonical",
        ),
        CheckConstraint(
            "issued_at > 0 AND expires_at > issued_at",
            name="ck_payment_capability_lifetime",
        ),
        Index(
            "ix_payment_capability_reservation",
            "reservation_id",
        ),
        Index(
            "ix_payment_capability_idempotency",
            "idempotency_key",
        ),
    )

    capability_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    capability_version: Mapped[str] = mapped_column(String(64), nullable=False)
    capability_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    reservation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False)
    node_id: Mapped[str] = mapped_column(String(256), nullable=False)
    wallet_binding_id: Mapped[str] = mapped_column(String(256), nullable=False)
    wallet_identity_id: Mapped[str] = mapped_column(String(96), nullable=False)
    canonical_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    issued_at: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class FundingLedger:
    def __init__(self,url):
        engine_options={"connect_args":{"timeout":0}} if url.startswith("sqlite") else {}
        self.engine=create_engine(url,**engine_options);self.sessions=sessionmaker(self.engine,expire_on_commit=False)
        if url.startswith("sqlite"):
            self.create_schema()
        else:
            self.validate_global_lock()
    def create_schema(self):
        Base.metadata.create_all(self.engine)
        with self.sessions.begin() as s:
            if not s.get(LockRow,1):s.add(LockRow(lock_id=1))
    def validate_global_lock(self):
        try:
            with self.sessions() as s:
                lock_id=s.scalar(select(LockRow.lock_id).where(LockRow.lock_id==1))
        except SQLAlchemyError as exc:
            raise RuntimeError("global funding lock is unavailable") from exc
        if lock_id != 1:
            raise RuntimeError("global funding lock is missing")
    def list_records(self,record_type):
        if record_type == PAYMENT_CAPABILITY_RECORD_TYPE:
            raise ValueError("payment capabilities require the dedicated ledger API")
        with self.sessions() as s:
            rows=s.scalars(
                select(LedgerRow)
                .where(LedgerRow.record_type==record_type)
                .order_by(LedgerRow.updated_at,LedgerRow.record_id)
            ).all()
        return [
            (
                row.record_id,
                redact_external_payment_payload(row.payload)
                if row.record_type == "reservation"
                else row.payload,
            )
            for row in rows
        ]
    @contextmanager
    def transaction(self):
        if self.engine.dialect.name == "sqlite":
            with sqlite_immediate_session(
                self.sessions, operation="sqlite funding write transaction"
            ) as s:
                if s.get(LockRow, 1) is None:
                    raise RuntimeError("global funding lock is missing")
                yield FundingTransaction(s, self.engine.dialect.name)
            return
        with self.sessions.begin() as s:
            stmt=select(LockRow).where(LockRow.lock_id==1).with_for_update()
            if s.scalar(stmt) is None:
                raise RuntimeError("global funding lock is missing")
            yield FundingTransaction(s, self.engine.dialect.name)

class FundingTransaction:
    def __init__(self,session,dialect_name):self.s=session;self.dialect_name=dialect_name

    def locked_payment_authorities(
        self, action_id: str, policy_decision_id: str
    ) -> tuple[AgentActionIntent | None, PolicyDecision | None]:
        action_statement = select(ActionIntentRow).where(
            ActionIntentRow.action_id == action_id
        )
        policy_statement = select(PolicyDecisionRow).where(
            PolicyDecisionRow.policy_decision_id == policy_decision_id
        )
        if self.dialect_name != "sqlite":
            action_statement = action_statement.with_for_update()
            policy_statement = policy_statement.with_for_update()
        action_row = self.s.scalar(action_statement)
        policy_row = self.s.scalar(policy_statement)
        if action_row is None or policy_row is None:
            return None, None
        try:
            action = AgentActionIntent.model_validate(
                deepcopy(action_row.payload), strict=True
            )
            policy = PolicyDecision.model_validate(
                deepcopy(policy_row.payload), strict=True
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("payment authorization records are invalid") from exc
        if (
            action.action_id != action_id
            or policy.policy_decision_id != policy_decision_id
        ):
            raise ValueError("payment authorization record identity mismatch")
        return action, policy
    def get(self,record_id):
        statement=select(LedgerRow).where(LedgerRow.record_id==record_id)
        if self.dialect_name != "sqlite":statement=statement.with_for_update()
        row=self.s.scalar(statement)
        if row is None:
            return None
        return (
            redact_external_payment_payload(row.payload)
            if row.record_type == "reservation"
            else row.payload
        )
    def by_purchase(self,purchase_id):
        row=self.s.scalar(select(LedgerRow).where(LedgerRow.purchase_id==purchase_id))
        return redact_external_payment_payload(row.payload) if row else None
    def by_tx_hash(self,tx_hash):
        canonical_hash=canonicalize_transaction_hash(tx_hash)
        binding=self.s.get(TransactionBindingRow,canonical_hash)
        if binding:
            row=self.s.get(LedgerRow,binding.reservation_id);return redact_external_payment_payload(row.payload) if row else {"reservation_id":binding.reservation_id,"tx_hash":canonical_hash}
        row=self.s.scalar(select(LedgerRow).where(func.lower(LedgerRow.tx_hash)==canonical_hash));return redact_external_payment_payload(row.payload) if row else None
    def list(self,record_type):
        if record_type == PAYMENT_CAPABILITY_RECORD_TYPE:
            raise ValueError("payment capabilities require the dedicated ledger API")
        rows=self.s.scalars(select(LedgerRow).where(LedgerRow.record_type==record_type)).all()
        return [
            redact_external_payment_payload(row.payload)
            if row.record_type == "reservation"
            else row.payload
            for row in rows
        ]

    def payment_capability_for_reservation(
        self, reservation_id: str
    ) -> PaymentCapabilityV1 | None:
        if not isinstance(reservation_id, str) or not reservation_id:
            raise PaymentCapabilityConflictError("payment capability reservation is invalid")
        statement = select(PaymentCapabilityRow).where(
            PaymentCapabilityRow.reservation_id == reservation_id
        )
        if self.dialect_name != "sqlite":
            statement = statement.with_for_update()
        row = self.s.scalar(statement)
        if row is None:
            return None
        return self._payment_capability_from_row(row)

    def put_payment_capability(
        self,
        capability: PaymentCapabilityV1 | Mapping[str, object],
        *,
        idempotency_key: str,
    ) -> PaymentCapabilityV1:
        """Insert one immutable capability or return its exact replay."""

        try:
            canonical = PaymentCapabilityV1.model_validate(capability, strict=True)
        except (TypeError, ValueError) as exc:
            raise PaymentCapabilityConflictError(
                "payment capability payload is invalid"
            ) from exc
        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key
            or len(idempotency_key) > 128
            or any(ord(character) < 32 or ord(character) == 127 for character in idempotency_key)
        ):
            raise PaymentCapabilityConflictError(
                "payment capability idempotency key is invalid"
            )

        payload = deepcopy(canonical.model_dump(mode="json"))
        statement = select(PaymentCapabilityRow).where(
            PaymentCapabilityRow.reservation_id == canonical.reservation_id
        )
        if self.dialect_name != "sqlite":
            statement = statement.with_for_update()
        existing = self.s.scalar(statement)
        if existing is not None:
            self._require_matching_payment_capability(
                existing, canonical, payload, idempotency_key
            )
            return self._payment_capability_from_row(existing)

        row = PaymentCapabilityRow(
            capability_id=canonical.capability_id,
            capability_version=canonical.capability_version,
            capability_hash=canonical.capability_hash,
            reservation_id=canonical.reservation_id,
            idempotency_key=idempotency_key,
            tenant_id=canonical.tenant_id,
            node_id=canonical.node_id,
            wallet_binding_id=canonical.wallet_binding_id,
            wallet_identity_id=canonical.wallet_identity_id,
            canonical_payload=payload,
            issued_at=canonical.issued_at,
            expires_at=canonical.expires_at,
            created_at=datetime.now(UTC),
        )
        try:
            # A concurrent PostgreSQL/SQLite writer may win one of the unique
            # bindings after the first lookup.  Keep that failure inside a
            # savepoint so the outer funding transaction remains usable.
            with self.s.begin_nested():
                self.s.add(row)
                self.s.flush()
        except IntegrityError as exc:
            existing = self.s.scalar(
                select(PaymentCapabilityRow).where(
                    PaymentCapabilityRow.reservation_id == canonical.reservation_id
                )
            )
            if existing is not None:
                self._require_matching_payment_capability(
                    existing, canonical, payload, idempotency_key
                )
                return self._payment_capability_from_row(existing)
            raise PaymentCapabilityConflictError(
                "payment capability uniqueness conflict"
            ) from exc
        return canonical

    @staticmethod
    def _payment_capability_from_row(row: PaymentCapabilityRow) -> PaymentCapabilityV1:
        try:
            capability = PaymentCapabilityV1.model_validate(
                deepcopy(row.canonical_payload), strict=True
            )
        except (TypeError, ValueError) as exc:
            raise PaymentCapabilityConflictError(
                "stored payment capability payload is invalid"
            ) from exc
        if (
            row.capability_id != capability.capability_id
            or row.capability_version != capability.capability_version
            or row.capability_hash != capability.capability_hash
            or row.reservation_id != capability.reservation_id
            or row.tenant_id != capability.tenant_id
            or row.node_id != capability.node_id
            or row.wallet_binding_id != capability.wallet_binding_id
            or row.wallet_identity_id != capability.wallet_identity_id
            or row.issued_at != capability.issued_at
            or row.expires_at != capability.expires_at
        ):
            raise PaymentCapabilityConflictError(
                "stored payment capability identity is inconsistent"
            )
        return capability

    @staticmethod
    def _require_matching_payment_capability(
        row: PaymentCapabilityRow,
        capability: PaymentCapabilityV1,
        payload: dict,
        idempotency_key: str,
    ) -> None:
        if (
            row.idempotency_key != idempotency_key
            or row.capability_id != capability.capability_id
            or row.capability_version != capability.capability_version
            or row.capability_hash != capability.capability_hash
            or row.reservation_id != capability.reservation_id
            or row.tenant_id != capability.tenant_id
            or row.node_id != capability.node_id
            or row.wallet_binding_id != capability.wallet_binding_id
            or row.wallet_identity_id != capability.wallet_identity_id
            or row.canonical_payload != payload
            or row.issued_at != capability.issued_at
            or row.expires_at != capability.expires_at
        ):
            raise PaymentCapabilityConflictError(
                "immutable payment capability scope changed"
            )
    def put(self,record_type,record_id,payload,**identity):
        if record_type == PAYMENT_CAPABILITY_RECORD_TYPE:
            raise ValueError("payment capabilities require the dedicated ledger API")
        payload=dict(payload)
        if record_type == "reservation":
            payload = redact_external_payment_payload(payload)
        row=self.s.get(LedgerRow,record_id)
        if record_type == "reservation":
            self._validate_reservation_write(
                record_id,
                payload,
                identity,
                stored_payload=row.payload if row else None,
            )
        if identity.get("tx_hash") is not None:
            canonical_hash=canonicalize_transaction_hash(identity["tx_hash"])
            identity["tx_hash"]=canonical_hash
            payload["tx_hash"]=canonical_hash
            reservation_id=identity.get("reservation_id") or payload.get("reservation_id")
            if record_type=="reservation" and reservation_id:
                binding=self.s.get(TransactionBindingRow,canonical_hash)
                if binding and binding.reservation_id!=reservation_id:
                    raise ValueError("transaction is already bound to another reservation")
                if not binding:
                    self.s.add(TransactionBindingRow(tx_hash=canonical_hash,reservation_id=reservation_id,created_at=datetime.now(UTC)))
        values=dict(
            record_type=record_type,
            token_address=payload.get("token_address"),
            payload=payload,
            updated_at=datetime.now(UTC),
            **identity,
        )
        if row:
            for k,v in values.items():setattr(row,k,v)
        else:self.s.add(LedgerRow(record_id=record_id,**values))
        self.s.flush();return payload

    def _validate_reservation_write(
        self, record_id, payload, ledger_identity, *, stored_payload=None
    ):
        if payload.get("authorization_path") != "unified_grant":
            require_unified_reservation(payload)
        if payload["reservation_id"] != record_id:
            raise ValueError("reservation record identity mismatch")
        for field in (
            "purchase_id",
            "idempotency_key",
            "action_id",
            "policy_decision_id",
            "reservation_id",
        ):
            if ledger_identity.get(field) != payload.get(field):
                raise ValueError(f"reservation {field} identity mismatch")
        if stored_payload is not None:
            require_matching_reservation_immutable_fields(stored_payload, payload)
        require_unified_reservation(payload)
        if payload.get("single_submission") is True:
            if (
                any(
                    payload.get(field) is not None
                    for field in SINGLE_SUBMISSION_CANONICAL_FIELDS
                )
                and (
                    stored_payload is None
                    or all(
                        stored_payload.get(field) is None
                        for field in SINGLE_SUBMISSION_CANONICAL_FIELDS
                    )
                )
            ):
                self._validate_single_submission_transaction_binding(payload)
            self._validate_single_submission_state(payload)
        self.unified_authorization_scope(payload)

    @classmethod
    def _validate_single_submission_state(cls, payload):
        evidence = payload.get("failed_submission_evidence", [])
        if not isinstance(evidence, list):
            raise ValueError("single-submission failure evidence is invalid")
        # Hosted owns the transaction envelope and relayer nonce.  Core only
        # receives a transaction hash after the independent watcher has
        # observed it, so a hosted reservation cannot require the native
        # pre-broadcast transaction projection here.
        if payload.get("settlement_rail") == "hosted":
            state = payload.get("state")
            hosted_execution_id = payload.get("hosted_execution_id")
            if state in {"payment_submitted", "settled", "finalized", "reorg_review"}:
                if (
                    not isinstance(hosted_execution_id, str)
                    or not hosted_execution_id
                    or payload.get("replacement_forbidden") is True
                    or evidence
                ):
                    raise ValueError("hosted single-submission state is invalid")
            elif state in {"spending_reserved", "released"}:
                if payload.get("replacement_forbidden") is True or evidence:
                    raise ValueError("hosted single-submission failure state is invalid")
            else:
                raise ValueError("hosted single-submission state is invalid")
            return
        populated = tuple(
            payload.get(field) is not None
            for field in SINGLE_SUBMISSION_CANONICAL_FIELDS
        )
        if any(populated) and not all(populated):
            raise ValueError("single-submission transaction binding is incomplete")
        canonical_complete = all(populated)
        replacement_forbidden = payload.get("replacement_forbidden") is True
        state = payload.get("state")
        if state in {"payment_submitted", "settled", "finalized"}:
            if replacement_forbidden or evidence:
                raise ValueError("single-submission failure state is invalid")
            if not canonical_complete:
                raise ValueError("single-submission transaction state is invalid")
        elif state in {"spending_reserved", "released"}:
            if canonical_complete:
                if not replacement_forbidden or len(evidence) != 1:
                    raise ValueError("single-submission failure state is invalid")
            elif replacement_forbidden or evidence:
                raise ValueError("single-submission failure state is invalid")
        else:
            raise ValueError("single-submission transaction state is invalid")
        cls._validate_single_submission_failure_evidence(payload)

    def validate_single_submission_state(self, payload):
        if payload.get("single_submission") is True:
            self._validate_single_submission_state(payload)
            if all(
                payload.get(field) is not None
                for field in SINGLE_SUBMISSION_CANONICAL_FIELDS
            ):
                self._validate_single_submission_transaction_binding(payload)

    @staticmethod
    def _validate_single_submission_transaction_binding(payload):
        if any(payload.get(field) is None for field in SINGLE_SUBMISSION_CANONICAL_FIELDS):
            raise ValueError("single-submission transaction binding is incomplete")
        canonical_hash = canonicalize_transaction_hash(payload["tx_hash"])
        if payload["tx_hash"] != canonical_hash:
            raise ValueError("single-submission transaction hash is not canonical")
        sender = str(payload["settlement_sender"]).lower()
        if re.fullmatch(r"0x[0-9a-f]{40}", sender) is None:
            raise ValueError("single-submission relayer identity is invalid")
        nonce = payload["settlement_nonce"]
        if (
            not isinstance(nonce, int)
            or isinstance(nonce, bool)
            or not 0 <= nonce < 2**64
        ):
            raise ValueError("single-submission nonce is invalid")
        projection = payload["settlement_transaction"]
        if set(projection) != {
            "chainId",
            "from",
            "to",
            "value",
            "data",
            "nonce",
            "gasPrice",
            "gas",
        }:
            raise ValueError("single-submission transaction projection is invalid")
        if str(projection.get("from", "")).lower() != sender:
            raise ValueError("single-submission relayer binding is inconsistent")
        if projection.get("nonce") != nonce:
            raise ValueError("single-submission nonce binding is inconsistent")

    @staticmethod
    def _validate_single_submission_failure_evidence(payload):
        evidence = payload.get("failed_submission_evidence", [])
        if not isinstance(evidence, list):
            raise ValueError("single-submission failure evidence is invalid")
        sealed = payload.get("replacement_forbidden") is True
        if not evidence and not sealed:
            return
        if (
            len(evidence) != 1
            or not sealed
            or payload.get("state") not in {"spending_reserved", "released"}
            or payload.get("reconciliation_status") != "failed"
            or payload.get("next_action") != "release_reservation"
        ):
            raise ValueError("single-submission failure state is invalid")
        allowed_reasons = {
            "definite_rpc_rejection": {
                "insufficient_funds",
                "intrinsic_gas_too_low",
                "invalid_sender",
                "transaction_type_not_supported",
            },
            "failed_receipt": {"onchain_revert"},
        }
        for item in evidence:
            if not isinstance(item, dict) or set(item) != {
                "kind",
                "reason_code",
                "tx_hash",
                "relayer",
                "nonce",
                "recorded_at",
            }:
                raise ValueError("single-submission failure evidence is invalid")
            if canonicalize_transaction_hash(item.get("tx_hash")) != payload.get(
                "tx_hash"
            ):
                raise ValueError("single-submission failure transaction drift")
            if item.get("relayer") != payload.get("settlement_sender"):
                raise ValueError("single-submission failure relayer drift")
            if item.get("nonce") != payload.get("settlement_nonce"):
                raise ValueError("single-submission failure nonce drift")
            kind = item.get("kind")
            reason_code = item.get("reason_code")
            recorded_at = item.get("recorded_at")
            if (
                kind not in allowed_reasons
                or reason_code not in allowed_reasons[kind]
                or not isinstance(recorded_at, str)
                or RFC3339_UTC_PATTERN.fullmatch(recorded_at) is None
            ):
                raise ValueError("single-submission failure evidence is invalid")
            try:
                parsed = datetime.fromisoformat(recorded_at.removesuffix("Z"))
            except ValueError:
                raise ValueError(
                    "single-submission failure evidence is invalid"
                ) from None
            if parsed.tzinfo is not None or parsed.isoformat() + "Z" != recorded_at:
                raise ValueError("single-submission failure evidence is invalid")

    def reserve_unified_budget(
        self,
        request,
        *,
        actor_user_id,
        actor_agent_id,
        amount,
        now,
        reservation_id,
        expected_selection=None,
        external_token_decimals=6,
        external_token_symbol="USDC",
        canonical_token_address=None,
    ):
        now = self._utc(now)
        trusted_spender = None
        if (
            expected_selection is not None
            and request.authorization_rail in {"native_allowance", "clink_payer_proxy"}
        ):
            trusted_allowance = self._locked(
                AssetAllowanceRow, expected_selection["asset_allowance_id"]
            )
            if trusted_allowance is None:
                raise ValueError("authorization resolution is stale")
            if (
                trusted_allowance.network != request.network
                or trusted_allowance.token_address != canonical_token_address
            ):
                raise ValueError("canonical asset pair required before reservation")
            trusted_spender = trusted_allowance.spender_address
        identities = self._locked_rows(
            select(WalletIdentityRow).where(
                WalletIdentityRow.user_id == actor_user_id,
                WalletIdentityRow.status == "active",
            ),
            WalletIdentityRow.wallet_identity_id,
        )
        if not identities:
            raise ValueError("WALLET_IDENTITY_REQUIRED: active wallet identity required")
        identity_ids = {item.wallet_identity_id for item in identities}
        grants = self._locked_rows(
            select(SpendingGrantRow).where(
                SpendingGrantRow.user_id == actor_user_id,
                SpendingGrantRow.agent_id == actor_agent_id,
                SpendingGrantRow.wallet_identity_id.in_(identity_ids),
                SpendingGrantRow.status == "active",
            ),
            SpendingGrantRow.spending_grant_id,
        )
        grants = [
            item
            for item in grants
            if self._utc(item.starts_at) <= now < self._utc(item.expires_at)
        ]
        if not grants:
            raise ValueError("SPENDING_GRANT_REQUIRED: active spending grant required")

        scope_stages = (
            ("PRODUCT_SCOPE_MISMATCH", lambda item: request.product in item.product_scopes),
            ("VENUE_SCOPE_MISMATCH", lambda item: not item.venue_scopes or request.venue in item.venue_scopes),
            ("MERCHANT_SCOPE_MISMATCH", lambda item: not item.merchant_scopes or request.merchant_id in item.merchant_scopes),
            (
                "MERCHANT_TRUST_SCOPE_MISMATCH",
                lambda item: (
                    request.product != "marketplace"
                    and request.merchant_trust_tier is None
                )
                or request.merchant_trust_tier in item.merchant_trust_scopes,
            ),
            ("NETWORK_SCOPE_MISMATCH", lambda item: request.network in item.network_scopes),
            ("PER_TRANSACTION_LIMIT_EXCEEDED", lambda item: amount <= item.per_transaction_limit_usdc),
            ("BUDGET_EXCEEDED", lambda item: item.used_amount_usdc + item.reserved_amount_usdc + amount <= item.max_amount_usdc),
        )
        for reason, predicate in scope_stages:
            grants = [item for item in grants if predicate(item)]
            if not grants:
                raise ValueError(reason)

        usage_date = now.date()
        grants_with_usage = []
        for item in grants:
            usage = self._locked_daily_usage(item.spending_grant_id, usage_date)
            used = usage.used_amount_usdc if usage is not None else Decimal("0")
            reserved = usage.reserved_amount_usdc if usage is not None else Decimal("0")
            if used + reserved + amount <= item.daily_limit_usdc:
                grants_with_usage.append((item, usage))
        if not grants_with_usage:
            raise ValueError("DAILY_LIMIT_EXCEEDED")

        grants_with_hourly_usage = []
        cutoff = now - timedelta(hours=1)
        for item, usage in grants_with_usage:
            rolling_rows = self._locked_rows(
                select(SpendingGrantRollingUsageRow).where(
                    SpendingGrantRollingUsageRow.spending_grant_id
                    == item.spending_grant_id,
                    SpendingGrantRollingUsageRow.occurred_at > cutoff,
                    SpendingGrantRollingUsageRow.state.in_(("reserved", "used")),
                ),
                SpendingGrantRollingUsageRow.reservation_id,
            )
            rolling_total = sum(
                (row.amount_usdc for row in rolling_rows), Decimal("0")
            )
            if rolling_total + amount <= item.hourly_limit_usdc:
                grants_with_hourly_usage.append((item, usage))
        if not grants_with_hourly_usage:
            raise ValueError("HOURLY_LIMIT_EXCEEDED")

        atomic = self._atomic_amount(request.amount_atomic)
        if request.authorization_rail == "external_x402":
            token_address = str(request.token_address or "").lower()
            if token_address != canonical_token_address:
                raise ValueError("canonical asset pair required before reservation")
            candidates = [
                (grant.spending_grant_id, grant.wallet_identity_id, grant, usage)
                for grant, usage in grants_with_hourly_usage
                if token_address in {asset.lower() for asset in grant.asset_scopes}
            ]
            if not candidates:
                raise ValueError("ASSET_SCOPE_MISMATCH")
            required_atomic = amount * (Decimal(10) ** external_token_decimals)
            if (
                required_atomic != required_atomic.to_integral_value()
                or atomic != int(required_atomic)
            ):
                raise ValueError("amount_atomic does not match amount_usdc and token decimals")
            _, _, grant, usage = min(candidates)
            selection = {
                "wallet_identity_id": grant.wallet_identity_id,
                "spending_grant_id": grant.spending_grant_id,
                "asset_allowance_id": None,
            }
            if expected_selection is not None and selection != expected_selection:
                raise ValueError("authorization resolution is stale")
            self._require_opc_installation_authority(
                request.opc_installation_id,
                actor_user_id=actor_user_id,
                grant=grant,
                now=now,
            )
            return self._commit_budget_reservation(
                grant,
                usage,
                amount=amount,
                now=now,
                reservation_id=reservation_id,
                usage_date=usage_date,
                selection={
                    **selection,
                    "token_address": token_address,
                    "token_decimals": external_token_decimals,
                    "token_symbol": external_token_symbol,
                    "spender_address": None,
                },
            )

        eligible_identity_ids = {
            item.wallet_identity_id for item, _usage in grants_with_hourly_usage
        }
        allowance_statement = select(AssetAllowanceRow).where(
            AssetAllowanceRow.wallet_identity_id.in_(eligible_identity_ids),
            AssetAllowanceRow.status == "active",
            AssetAllowanceRow.network == request.network,
            AssetAllowanceRow.token_address == canonical_token_address,
        )
        if trusted_spender is not None:
            allowance_statement = allowance_statement.where(
                AssetAllowanceRow.spender_address == trusted_spender
            )
        allowances = self._locked_rows(
            allowance_statement,
            AssetAllowanceRow.asset_allowance_id,
        )
        candidates = []
        asset_match_found = False
        atomic_match_found = False
        for grant, usage in grants_with_hourly_usage:
            for allowance in allowances:
                if allowance.wallet_identity_id != grant.wallet_identity_id:
                    continue
                if allowance.token_address not in grant.asset_scopes:
                    continue
                if request.asset.lower() not in {
                    allowance.token_symbol.lower(),
                    allowance.token_address.lower(),
                }:
                    continue
                asset_match_found = True
                required_atomic = amount * (Decimal(10) ** allowance.token_decimals)
                if (
                    required_atomic != required_atomic.to_integral_value()
                    or atomic != int(required_atomic)
                ):
                    continue
                atomic_match_found = True
                if int(allowance.observed_allowance_atomic) < atomic:
                    continue
                candidates.append(
                    (
                        grant.spending_grant_id,
                        allowance.asset_allowance_id,
                        grant.wallet_identity_id,
                        grant,
                        allowance,
                        usage,
                    )
                )
        if asset_match_found and not atomic_match_found:
            raise ValueError("amount_atomic does not match amount_usdc and token decimals")
        if not candidates:
            raise ValueError("ASSET_ALLOWANCE_REQUIRED: matching allowance required")
        _, _, _, grant, allowance, usage = min(candidates)
        selection = {
            "wallet_identity_id": grant.wallet_identity_id,
            "spending_grant_id": grant.spending_grant_id,
            "asset_allowance_id": allowance.asset_allowance_id,
        }
        if expected_selection is not None and selection != expected_selection:
            raise ValueError("authorization resolution is stale")

        self._require_opc_installation_authority(
            request.opc_installation_id,
            actor_user_id=actor_user_id,
            grant=grant,
            now=now,
        )

        return self._commit_budget_reservation(
            grant,
            usage,
            amount=amount,
            now=now,
            reservation_id=reservation_id,
            usage_date=usage_date,
            selection={
                **selection,
                "token_address": allowance.token_address,
                "token_decimals": allowance.token_decimals,
                "token_symbol": allowance.token_symbol,
                "spender_address": allowance.spender_address,
            },
        )

    def _commit_budget_reservation(
        self, grant, usage, *, amount, now, usage_date, reservation_id, selection
    ):
        if usage is None:
            digest = hashlib.sha256(
                f"{grant.spending_grant_id}:{usage_date.isoformat()}".encode()
            ).hexdigest()
            usage = SpendingGrantDailyUsageRow(
                spending_grant_daily_usage_id=f"grant_daily_{digest}",
                spending_grant_id=grant.spending_grant_id,
                usage_date=usage_date,
                used_amount_usdc=Decimal("0"),
                reserved_amount_usdc=Decimal("0"),
                created_at=now,
                updated_at=now,
            )
            self.s.add(usage)
        if usage.used_amount_usdc + usage.reserved_amount_usdc + amount > grant.daily_limit_usdc:
            raise ValueError("DAILY_LIMIT_EXCEEDED")

        grant.reserved_amount_usdc += amount
        grant.updated_at = now
        usage.reserved_amount_usdc += amount
        usage.updated_at = now
        self.s.add(
            SpendingGrantRollingUsageRow(
                reservation_id=reservation_id,
                spending_grant_id=grant.spending_grant_id,
                amount_usdc=amount,
                state="reserved",
                occurred_at=now,
                updated_at=now,
            )
        )
        self.s.flush()
        return {
            **selection,
            "usage_date": usage_date,
        }

    def _require_opc_installation_authority(
        self,
        installation_id,
        *,
        actor_user_id,
        grant,
        now,
    ):
        if installation_id is None:
            return
        installation = self._locked(OpcInstallationRow, installation_id)
        if (
            installation is None
            or installation.status != "active"
            or installation.scope != "payments"
            or installation.user_id != actor_user_id
            or installation.wallet_identity_id != grant.wallet_identity_id
            or installation.spending_grant_id != grant.spending_grant_id
            or installation.approved_at is None
            or installation.consent_expires_at is None
            or self._utc(installation.consent_expires_at) <= now
            or self._utc(installation.consent_expires_at)
            > self._utc(grant.expires_at)
        ):
            raise ValueError(
                "OPC installation authority is unavailable for this spending grant"
            )

    def allocate_relayer_nonce(
        self, row, *, network, relayer_address, chain_pending_nonce, now
    ):
        require_unified_reservation(row)
        if row["authorization_rail"] not in {"native_allowance", "clink_payer_proxy"}:
            raise ValueError("relayer nonce allocation requires an allowance-backed rail")
        if row["network"] != network:
            raise ValueError("relayer nonce network does not match reservation")
        canonical_relayer = str(relayer_address).lower()
        if re.fullmatch(r"0x[0-9a-f]{40}", canonical_relayer) is None:
            raise ValueError("relayer address is invalid")
        if (
            not isinstance(chain_pending_nonce, int)
            or isinstance(chain_pending_nonce, bool)
            or not 0 <= chain_pending_nonce < 2**64
        ):
            raise ValueError("chain pending nonce is invalid")

        owned_nonce = row.get("settlement_nonce")
        owned_sender = row.get("settlement_sender")
        if owned_nonce is not None or owned_sender is not None:
            if owned_nonce is None or owned_sender is None:
                raise ValueError("reservation nonce ownership is incomplete")
            if str(owned_sender).lower() != canonical_relayer:
                raise ValueError("reservation nonce belongs to another relayer")
            owned_nonce = int(owned_nonce)
            if not 0 <= owned_nonce < 2**64:
                raise ValueError("reservation nonce ownership is invalid")
            return owned_nonce

        statement = select(RelayerNonceRow).where(
            RelayerNonceRow.network == network,
            RelayerNonceRow.relayer_address == canonical_relayer,
        )
        if self.dialect_name != "sqlite":
            statement = statement.with_for_update()
        allocator = self.s.scalar(statement)
        timestamp = self._utc(now)
        if allocator is None:
            allocator = RelayerNonceRow(
                network=network,
                relayer_address=canonical_relayer,
                next_nonce=Decimal(chain_pending_nonce),
                updated_at=timestamp,
            )
            self.s.add(allocator)
            self.s.flush()
        nonce = max(int(allocator.next_nonce), chain_pending_nonce)
        if nonce >= 2**64:
            raise ValueError("relayer nonce space is exhausted")
        allocator.next_nonce = Decimal(nonce + 1)
        allocator.updated_at = timestamp
        self.s.flush()
        return nonce

    def release_unified_budget(self, row, *, now):
        require_unified_reservation(row)
        if row.get("budget_accounting_state") == "released":
            return row
        if row.get("budget_accounting_state") != "reserved":
            raise ValueError("reservation budget is not releasable")
        amount = Decimal(row["amount_usdc"])
        grant = self._required_locked_grant(row["spending_grant_id"])
        usage = self._required_locked_daily_usage(
            grant.spending_grant_id, datetime.fromisoformat(row["usage_date"]).date()
        )
        if grant.reserved_amount_usdc < amount or usage.reserved_amount_usdc < amount:
            raise ValueError("reserved budget accounting is inconsistent")
        grant.reserved_amount_usdc -= amount
        usage.reserved_amount_usdc -= amount
        rolling = self._locked(
            SpendingGrantRollingUsageRow, row["reservation_id"]
        )
        if rolling is not None:
            rolling.state = "released"
            rolling.updated_at = self._utc(now)
        timestamp = self._utc(now)
        grant.updated_at = timestamp
        usage.updated_at = timestamp
        if (
            grant.status == "exhausted"
            and grant.status_reason == "budget_exhausted"
            and grant.used_amount_usdc + grant.reserved_amount_usdc < grant.max_amount_usdc
        ):
            identity = self._locked(WalletIdentityRow, grant.wallet_identity_id)
            if (
                identity is not None
                and identity.status == "active"
                and self._utc(grant.starts_at) <= timestamp < self._utc(grant.expires_at)
            ):
                grant.status = "active"
                grant.status_reason = None
        return {**row, "budget_accounting_state": "released"}

    def settle_unified_budget(self, row, *, now):
        require_unified_reservation(row)
        if row.get("budget_accounting_state") == "settled":
            return row
        if row.get("budget_accounting_state") != "reserved":
            raise ValueError("reservation budget is not settleable")
        amount = Decimal(row["amount_usdc"])
        grant = self._required_locked_grant(row["spending_grant_id"])
        usage = self._required_locked_daily_usage(
            grant.spending_grant_id, datetime.fromisoformat(row["usage_date"]).date()
        )
        if grant.reserved_amount_usdc < amount or usage.reserved_amount_usdc < amount:
            raise ValueError("reserved budget accounting is inconsistent")
        grant.reserved_amount_usdc -= amount
        grant.used_amount_usdc += amount
        usage.reserved_amount_usdc -= amount
        usage.used_amount_usdc += amount
        rolling = self._locked(
            SpendingGrantRollingUsageRow, row["reservation_id"]
        )
        if rolling is not None:
            rolling.state = "used"
            rolling.updated_at = self._utc(now)
        timestamp = self._utc(now)
        grant.updated_at = timestamp
        usage.updated_at = timestamp
        if (
            grant.status in {"active", "exhausted"}
            and grant.status_reason in {None, "budget_exhausted"}
            and grant.used_amount_usdc + grant.reserved_amount_usdc >= grant.max_amount_usdc
        ):
            grant.status = "exhausted"
            grant.status_reason = "budget_exhausted"
        return {**row, "budget_accounting_state": "settled"}

    def record_hosted_watcher_evidence(self, row, evidence: Mapping[str, object], *, now):
        """Persist one immutable watcher projection and its audit link.

        This is deliberately a ledger operation: callers must invoke it in
        the same transaction that moves the reservation budget.  A different
        projection for the same reservation is a reorg/evidence conflict and
        therefore fails closed.
        """
        require_unified_reservation(row)
        if not isinstance(evidence, Mapping):
            raise ValueError("hosted watcher evidence is invalid")
        canonical = deepcopy(dict(evidence))
        if any(
            isinstance(value, (bytes, bytearray))
            for value in canonical.values()
        ):
            raise ValueError("hosted watcher evidence is invalid")
        previous = row.get("hosted_watcher_evidence")
        if previous is not None and previous != canonical:
            raise ValueError("hosted watcher evidence changed")
        try:
            encoded = json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("hosted watcher evidence is invalid") from exc
        evidence_hash = "0x" + hashlib.sha256(encoded).hexdigest()
        updated = {
            **row,
            "hosted_watcher_evidence": canonical,
            "hosted_watcher_evidence_hash": evidence_hash,
        }
        event_id = "audit_hosted_watcher_" + hashlib.sha256(
            f"{row['reservation_id']}:{evidence_hash}".encode("utf-8")
        ).hexdigest()[:32]
        if self.s.scalar(
            select(AuditEventRow).where(AuditEventRow.event_id == event_id)
        ) is None:
            identity, grant, _allowance = self.unified_authorization_scope(row)
            timestamp = self._utc(now)
            self.s.add(
                AuditEventRow(
                    event_id=event_id,
                    idempotency_key=event_id,
                    event_type="hosted_watcher_evidence_recorded",
                    source_service="funding_service",
                    action_id=row.get("action_id"),
                    user_id=identity.user_id,
                    agent_id=grant.agent_id,
                    policy_decision_id=row.get("policy_decision_id"),
                    payment_id=row.get("reservation_id"),
                    order_id=row.get("purchase_id"),
                    receipt_id=row.get("receipt_id"),
                    tx_hash=row.get("tx_hash"),
                    payload={
                        "reservation_id": row["reservation_id"],
                        "hosted_execution_id": row.get("hosted_execution_id"),
                        "evidence_hash": evidence_hash,
                        "watcher_version": canonical.get("watcher_version"),
                        "state": canonical.get("state"),
                    },
                    created_at=timestamp,
                )
            )
        return updated

    def record_hosted_watcher_release_evidence(
        self, row, evidence: Mapping[str, object], *, now
    ):
        """Persist the immutable proof that a reverted execution is releasable.

        This proof is intentionally separate from the first reverted watcher
        projection.  Releasing a reservation therefore cannot overwrite the
        original failure evidence or be replayed with a different proof.
        """
        require_unified_reservation(row)
        if not isinstance(evidence, Mapping):
            raise ValueError("hosted watcher release evidence is invalid")
        try:
            release_response = HostedExecutionResponse.model_validate(
                deepcopy(dict(evidence)), strict=True
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("hosted watcher release evidence is invalid") from exc
        if release_response.state != "released":
            raise ValueError("hosted watcher release evidence is invalid")
        canonical = release_response.model_dump(mode="json")
        previous = row.get("hosted_watcher_release_evidence")
        if previous is not None and previous != canonical:
            raise ValueError("hosted watcher release evidence changed")
        try:
            encoded = json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("hosted watcher release evidence is invalid") from exc
        evidence_hash = "0x" + hashlib.sha256(encoded).hexdigest()
        updated = {
            **row,
            "hosted_watcher_release_evidence": canonical,
            "hosted_watcher_release_evidence_hash": evidence_hash,
        }
        event_id = "audit_hosted_watcher_release_" + hashlib.sha256(
            f"{row['reservation_id']}:{evidence_hash}".encode("utf-8")
        ).hexdigest()[:32]
        if self.s.scalar(
            select(AuditEventRow).where(AuditEventRow.event_id == event_id)
        ) is None:
            identity, grant, _allowance = self.unified_authorization_scope(row)
            timestamp = self._utc(now)
            self.s.add(
                AuditEventRow(
                    event_id=event_id,
                    idempotency_key=event_id,
                    event_type="hosted_watcher_release_evidence_recorded",
                    source_service="funding_service",
                    action_id=row.get("action_id"),
                    user_id=identity.user_id,
                    agent_id=grant.agent_id,
                    policy_decision_id=row.get("policy_decision_id"),
                    payment_id=row.get("reservation_id"),
                    order_id=row.get("purchase_id"),
                    receipt_id=row.get("receipt_id"),
                    tx_hash=row.get("tx_hash"),
                    payload={
                        "reservation_id": row["reservation_id"],
                        "hosted_execution_id": row.get("hosted_execution_id"),
                        "release_evidence_hash": evidence_hash,
                        "state": "released",
                    },
                    created_at=timestamp,
                )
            )
        return updated

    def require_no_durable_transaction_evidence(self, reservation_id: str) -> None:
        # get() intentionally redacts legacy signature/receipt material. Check
        # the original locked storage row; absence from a public view is not
        # proof that no signed transaction exists.
        stored = self._locked(LedgerRow, reservation_id)
        if stored is None or stored.record_type != "reservation":
            raise ValueError("Hosted unsigned expiry reservation is unavailable")
        binding = self.s.scalar(select(TransactionBindingRow).where(
            TransactionBindingRow.reservation_id == reservation_id
        ).limit(1))
        if (
            stored.tx_hash is not None
            or binding is not None
            or stored.payload.get(LEGACY_SIGNED_TRANSACTION_FIELD) is not None
            or stored.payload.get(LEGACY_EXTERNAL_PAYMENT_FIELD) is not None
        ):
            raise ValueError("Hosted unsigned expiry conflicts with durable transaction evidence")

    def record_hosted_unsigned_expiry_evidence(self, row, evidence: Mapping[str, object], *, now):
        """Record the immutable signed unsigned-expiry proof before budget release.

        The caller verifies response authority and capability binding and holds
        the reservation lock. Proof, audit, and accounting commit atomically.
        """
        require_unified_reservation(row)
        self.require_no_durable_transaction_evidence(row["reservation_id"])
        response = HostedExecutionResponse.model_validate(deepcopy(dict(evidence)), strict=True)
        if (
            response.state != "expired"
            or response.failure_reason_code != "UNSIGNED_EXECUTION_EXPIRED"
            or response.reservation_id != row["reservation_id"]
            or response.execution_id != row.get("hosted_execution_id")
            or not response.deadline <= (response.expired_at or 0) <= int(self._utc(now).timestamp())
        ):
            raise ValueError("Hosted unsigned expiry evidence is invalid")
        canonical = response.model_dump(mode="json")
        # The response-signing key can rotate. Execution creation/expiry times
        # and all other authority/proof fields remain immutable.
        canonical.pop("server_key_id")
        previous = row.get("hosted_unsigned_expiry_evidence")
        if previous is not None and previous != canonical:
            raise ValueError("Hosted unsigned expiry evidence changed")
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        evidence_hash = "0x" + hashlib.sha256(encoded).hexdigest()
        event_id = "audit_hosted_unsigned_expiry_" + hashlib.sha256(row["reservation_id"].encode("utf-8")).hexdigest()[:32]
        event = self.s.scalar(select(AuditEventRow).where(AuditEventRow.event_id == event_id))
        if event is not None and event.payload.get("evidence_hash") != evidence_hash:
            raise ValueError("Hosted unsigned expiry audit evidence changed")
        if event is None:
            identity, grant, _allowance = self.unified_authorization_scope(row)
            self.s.add(AuditEventRow(
                event_id=event_id, idempotency_key=event_id,
                event_type="hosted_unsigned_expiry_evidence_recorded", source_service="funding_service",
                action_id=row.get("action_id"), user_id=identity.user_id, agent_id=grant.agent_id,
                policy_decision_id=row.get("policy_decision_id"), payment_id=row["reservation_id"],
                order_id=row.get("purchase_id"), receipt_id=None, tx_hash=None,
                payload={"reservation_id": row["reservation_id"], "hosted_execution_id": response.execution_id,
                         "evidence_hash": evidence_hash, "state": "expired",
                         "failure_reason_code": "UNSIGNED_EXECUTION_EXPIRED"},
                created_at=self._utc(now),
            ))
        return {**row, "hosted_unsigned_expiry_evidence": canonical,
                "hosted_unsigned_expiry_evidence_hash": evidence_hash}

    def record_hosted_watcher_reorg_evidence(
        self, row, evidence: Mapping[str, object], *, now
    ):
        """Append a changed canonical watcher projection for reorg review.

        A finalized reservation cannot silently replace its original chain
        evidence.  When the independent watcher reports a canonicality
        change, retain both projections and leave settlement decisions to an
        operator.
        """
        require_unified_reservation(row)
        if not isinstance(evidence, Mapping):
            raise ValueError("hosted watcher evidence is invalid")
        canonical = deepcopy(dict(evidence))
        previous = row.get("hosted_watcher_evidence")
        if previous is None or previous == canonical:
            return self.record_hosted_watcher_evidence(row, canonical, now=now)
        try:
            encoded = json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("hosted watcher evidence is invalid") from exc
        evidence_hash = "0x" + hashlib.sha256(encoded).hexdigest()
        history = row.get("hosted_watcher_evidence_history", [])
        if not isinstance(history, list):
            raise ValueError("hosted watcher evidence history is invalid")
        history = deepcopy(history)
        if not history or history[-1] != previous:
            history.append(deepcopy(previous))
        if history[-1] != canonical:
            history.append(canonical)
        updated = {
            **row,
            "hosted_watcher_evidence": canonical,
            "hosted_watcher_evidence_hash": evidence_hash,
            "hosted_watcher_evidence_history": history,
        }
        event_id = "audit_hosted_watcher_reorg_" + hashlib.sha256(
            f"{row['reservation_id']}:{evidence_hash}".encode("utf-8")
        ).hexdigest()[:32]
        if self.s.scalar(
            select(AuditEventRow).where(AuditEventRow.event_id == event_id)
        ) is None:
            identity, grant, _allowance = self.unified_authorization_scope(row)
            timestamp = self._utc(now)
            self.s.add(
                AuditEventRow(
                    event_id=event_id,
                    idempotency_key=event_id,
                    event_type="hosted_watcher_reorg_evidence_recorded",
                    source_service="funding_service",
                    action_id=row.get("action_id"),
                    user_id=identity.user_id,
                    agent_id=grant.agent_id,
                    policy_decision_id=row.get("policy_decision_id"),
                    payment_id=row.get("reservation_id"),
                    order_id=row.get("purchase_id"),
                    receipt_id=row.get("receipt_id"),
                    tx_hash=row.get("tx_hash"),
                    payload={
                        "reservation_id": row["reservation_id"],
                        "hosted_execution_id": row.get("hosted_execution_id"),
                        "previous_evidence_hash": row.get(
                            "hosted_watcher_evidence_hash"
                        ),
                        "evidence_hash": evidence_hash,
                        "watcher_version": canonical.get("watcher_version"),
                        "state": canonical.get("state"),
                    },
                    created_at=timestamp,
                )
            )
        return updated

    def record_external_reconciliation_after_revocation(self, row, *, now):
        identity, grant, _allowance = self.unified_authorization_scope(row)
        revocations = []
        if identity.status == "revoked":
            revocations.append("wallet_identity")
        if grant.status == "revoked":
            revocations.append("spending_grant")
        elif (
            grant.status == "paused"
            and grant.status_reason == "wallet_identity_revoked"
        ):
            revocations.append("spending_grant_identity_cascade")
        if not revocations:
            return []

        event_id = "audit_x402_revoked_" + hashlib.sha256(
            row["reservation_id"].encode()
        ).hexdigest()[:32]
        if self.s.scalar(
            select(AuditEventRow).where(AuditEventRow.event_id == event_id)
        ) is None:
            timestamp = self._utc(now)
            self.s.add(
                AuditEventRow(
                    event_id=event_id,
                    event_type=(
                        "external_payment_reconciled_after_authorization_revocation"
                    ),
                    source_service="funding_service",
                    action_id=row.get("action_id"),
                    user_id=identity.user_id,
                    agent_id=grant.agent_id,
                    policy_decision_id=row.get("policy_decision_id"),
                    payment_id=row.get("reservation_id"),
                    order_id=None,
                    receipt_id=row.get("receipt_id"),
                    tx_hash=row.get("tx_hash"),
                    payload={
                        "reservation_id": row["reservation_id"],
                        "wallet_identity_id": identity.wallet_identity_id,
                        "spending_grant_id": grant.spending_grant_id,
                        "network": row["network"],
                        "token_address": row["token_address"],
                        "revoked_authorizations": revocations,
                    },
                    created_at=timestamp,
                )
            )
        return revocations

    def validate_unified_lifecycle(
        self, row, *, now, payment_already_executed=False
    ):
        identity, grant, allowance = self.unified_authorization_scope(row)
        if (
            not payment_already_executed
            and row.get("product") == "marketplace"
            and row.get("merchant_trust_tier") is None
        ):
            raise ValueError("MERCHANT_TRUST_SCOPE_MISMATCH")
        timestamp = self._utc(now)
        if identity.status != "active":
            raise ValueError("active wallet identity required before payment submission")
        if (
            grant.status != "active"
            or not self._utc(grant.starts_at) <= timestamp < self._utc(grant.expires_at)
        ):
            raise ValueError("active spending grant required before payment submission")
        if allowance is not None and allowance.status != "active":
            raise ValueError("active asset allowance required before payment submission")
        return identity, grant, allowance

    def observe_allowance_before_submission(
        self, row, *, observed_allowance_atomic=None, stale=False, now
    ):
        if row.get("authorization_rail") not in {"native_allowance", "clink_payer_proxy"}:
            raise ValueError("allowance refresh requires an allowance-backed rail")
        identity, grant, allowance = self.unified_authorization_scope(row)
        timestamp = self._utc(now)
        if stale:
            allowance.status = "stale"
            allowance.updated_at = timestamp
        else:
            observed = self._atomic_amount(str(observed_allowance_atomic))
            allowance.observed_allowance_atomic = Decimal(observed)
            allowance.last_chain_check_at = timestamp
            allowance.updated_at = timestamp
            if observed == 0:
                allowance.status = "revoked"
            else:
                allowance.status = "active"
        self.s.add(
            AuditEventRow(
                event_id=f"audit_{uuid4().hex[:20]}",
                event_type="allowance_refreshed",
                source_service="funding_service",
                action_id=row.get("action_id"),
                user_id=identity.user_id,
                agent_id=grant.agent_id,
                policy_decision_id=row.get("policy_decision_id"),
                payment_id=None,
                order_id=None,
                receipt_id=None,
                tx_hash=None,
                payload={
                    "asset_allowance_id": allowance.asset_allowance_id,
                    "wallet_identity_id": identity.wallet_identity_id,
                    "spending_grant_id": grant.spending_grant_id,
                    "reservation_id": row.get("reservation_id"),
                    "network": allowance.network,
                    "token_address": allowance.token_address,
                    "status": allowance.status,
                    "observed_allowance_atomic": str(
                        int(allowance.observed_allowance_atomic)
                    ),
                },
                created_at=timestamp,
            )
        )
        return allowance.status

    def unified_authorization_scope(self, row):
        require_unified_reservation(row)
        identity = self._locked(WalletIdentityRow, row["wallet_identity_id"])
        grant = self._locked(SpendingGrantRow, row["spending_grant_id"])
        allowance = (
            self._locked(AssetAllowanceRow, row["asset_allowance_id"])
            if row["authorization_rail"] in {"native_allowance", "clink_payer_proxy"}
            else None
        )
        if identity is None or grant is None or (
            row["authorization_rail"] in {"native_allowance", "clink_payer_proxy"}
            and allowance is None
        ):
            raise ValueError("unified authorization references are unavailable")
        if (
            grant.wallet_identity_id != identity.wallet_identity_id
            or grant.user_id != identity.user_id
            or (
                allowance is not None
                and allowance.wallet_identity_id != identity.wallet_identity_id
            )
        ):
            raise ValueError("unified authorization references do not share an identity")
        if (
            row.get("product") not in grant.product_scopes
            or row.get("network") not in grant.network_scopes
            or (
                row.get("merchant_trust_tier") is not None
                and row.get("merchant_trust_tier")
                not in grant.merchant_trust_scopes
            )
            or str(row.get("token_address", "")).lower()
            not in {asset.lower() for asset in grant.asset_scopes}
            or (
                allowance is not None
                and (
                    allowance.network != row.get("network")
                    or allowance.token_address.lower()
                    != str(row.get("token_address", "")).lower()
                    or allowance.token_symbol != row.get("token_symbol")
                    or allowance.token_decimals != row.get("token_decimals")
                    or allowance.spender_address.lower()
                    != str(row.get("spender_address", "")).lower()
                )
            )
        ):
            raise ValueError("immutable allowance scope changed after reservation")
        return identity, grant, allowance

    def _locked(self, model, primary_key):
        statement = select(model).where(next(iter(model.__table__.primary_key.columns)) == primary_key)
        if self.dialect_name != "sqlite":
            statement = statement.with_for_update()
        return self.s.scalar(statement)

    def _locked_rows(self, statement, order_column):
        statement = statement.order_by(order_column)
        if self.dialect_name != "sqlite":
            statement = statement.with_for_update()
        return self.s.scalars(statement).all()

    def _locked_daily_usage(self, spending_grant_id, usage_date):
        statement = select(SpendingGrantDailyUsageRow).where(
            SpendingGrantDailyUsageRow.spending_grant_id == spending_grant_id,
            SpendingGrantDailyUsageRow.usage_date == usage_date,
        )
        if self.dialect_name != "sqlite":
            statement = statement.with_for_update()
        return self.s.scalar(statement)

    def _required_locked_grant(self, spending_grant_id):
        row = self._locked(SpendingGrantRow, spending_grant_id)
        if row is None:
            raise ValueError("spending grant was not found")
        return row

    def _required_locked_daily_usage(self, spending_grant_id, usage_date):
        row = self._locked_daily_usage(spending_grant_id, usage_date)
        if row is None:
            raise ValueError("daily usage was not found")
        return row

    @staticmethod
    def _atomic_amount(value):
        if not isinstance(value, str) or not value.isdigit():
            raise ValueError("amount_atomic must be a non-negative base-10 integer")
        return int(value)

    @staticmethod
    def _utc(value):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
