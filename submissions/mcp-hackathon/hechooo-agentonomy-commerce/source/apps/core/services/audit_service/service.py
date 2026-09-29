import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from services.account_service.repository import AccountRepository
from services.audit_service.schemas import (
    AuditEvent,
    AuditSummaryEvent,
    AuditTrail,
    WriteAuditEventRequest,
)
from shared.config import AppConfig


PUBLIC_EVENT_LABELS = {
    "action_intent_created": "Action requested",
    "allowance_revoked": "Chain allowance revoked",
    "allowance_refreshed": "Chain allowance refreshed",
    "allowance_verified": "Chain allowance verified",
    "grant_created": "Permission created",
    "grant_amended": "Spending limit changed",
    "grant_paused": "Permission paused",
    "grant_reduced": "Grant reduced",
    "grant_resumed": "Permission resumed",
    "grant_revoked": "Permission revoked",
    "external_payment_reconciled_after_authorization_revocation": (
        "External payment reconciled after permission revocation"
    ),
    "marketplace_purchase_policy_evaluated": "Marketplace purchase reviewed",
    "prediction_market_funding_policy_evaluated": "Prediction market funding reviewed",
    "wallet_revoked": "Wallet revoked",
    "wallet_verified": "Wallet verified",
}
PUBLIC_SOURCE_LABELS = {
    "account_service": "account service",
    "audit_service": "audit service",
    "clink_marketplace": "Clink Marketplace",
    "clink_prediction_markets": "Clink Prediction Markets",
    "funding_service": "funding service",
}


class AuditService:
    """Append-only audit trail for Clink Core actions."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        storage_file: str | Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = AppConfig.from_env()
        default_file = Path(__file__).resolve().parent / "audit_events.jsonl"
        configured_file = os.getenv(
            "AUDIT_EVENT_FILE", self.config.audit_event_file or str(default_file)
        )
        self.storage_file = Path(storage_file or configured_file)
        configured_database_url = os.getenv("CLINK_FUNDING_DATABASE_URL")
        if database_url is not None:
            authoritative_database_url = database_url
        elif configured_database_url:
            authoritative_database_url = configured_database_url
        elif storage_file is not None or "AUDIT_EVENT_FILE" in os.environ:
            legacy_path = self.storage_file.with_suffix(".sqlite3")
            authoritative_database_url = f"sqlite+pysqlite:///{legacy_path}"
        else:
            authoritative_database_url = self.config.funding_database_url
        self.repository = AccountRepository(authoritative_database_url)
        self.clock = clock or (lambda: datetime.now(UTC))

    def write_event(self, request: WriteAuditEventRequest) -> AuditEvent:
        created_at = self._utc_now()
        event = AuditEvent(
            event_id=f"audit_{uuid4().hex[:12]}",
            event_type=request.event_type,
            source_service=request.source_service,
            action_id=request.action_id,
            user_id=request.user_id,
            agent_id=request.agent_id,
            policy_decision_id=request.policy_decision_id,
            payment_id=request.payment_id,
            order_id=request.order_id,
            receipt_id=request.receipt_id,
            tx_hash=request.tx_hash,
            payload=request.payload,
            created_at=self._format_time(created_at),
        )
        values = event.model_dump(exclude={"created_at"})
        persisted = self.repository.append_audit_event(
            **values,
            idempotency_key=request.idempotency_key,
            created_at=created_at,
        )
        return self._event_from_database(persisted)

    def get_event(self, event_id: str) -> AuditEvent | None:
        persisted = self.repository.audit_event(event_id)
        if persisted is not None:
            return self._event_from_database(persisted)
        for event in self._load_events():
            if event.event_id == event_id:
                return event
        return None

    def get_trail(
        self,
        action_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
    ) -> AuditTrail:
        events = []
        for event in self._load_events():
            if action_id and event.action_id != action_id:
                continue
            if user_id and event.user_id != user_id:
                continue
            if agent_id and event.agent_id != agent_id:
                continue
            events.append(event)
        return AuditTrail(action_id=action_id, user_id=user_id, agent_id=agent_id, events=events)

    def get_user_summary(
        self, user_id: str, limit: int = 8
    ) -> list[AuditSummaryEvent]:
        if not user_id:
            raise ValueError("user_id is required")
        if not 1 <= limit <= 50:
            raise ValueError("audit summary limit must be between 1 and 50")
        events = [event for event in self._load_events() if event.user_id == user_id]
        return [
            AuditSummaryEvent(
                event=PUBLIC_EVENT_LABELS.get(event.event_type, "Account activity"),
                summary=(
                    "Recorded by "
                    + PUBLIC_SOURCE_LABELS.get(event.source_service, "Clink Core")
                ),
                at=event.created_at,
            )
            for event in reversed(events[-limit:])
        ]

    def _load_events(self) -> list[AuditEvent]:
        events_by_id = {
            event.event_id: event for event in self._load_legacy_events()
        }
        for row in self.repository.audit_events():
            event = self._event_from_database(row)
            events_by_id[event.event_id] = event
        return list(events_by_id.values())

    def _load_legacy_events(self) -> list[AuditEvent]:
        if not self.storage_file.exists():
            return []
        events = []
        with self.storage_file.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                events.append(AuditEvent(**json.loads(line)))
        return events

    def import_legacy_events(self) -> int:
        imported = 0
        for event in self._load_legacy_events():
            if self.repository.audit_event(event.event_id) is not None:
                continue
            values = event.model_dump(exclude={"created_at"})
            created_at = datetime.fromisoformat(
                event.created_at.removesuffix("Z") + "+00:00"
            )
            self.repository.append_audit_event(**values, created_at=created_at)
            imported += 1
        return imported

    def _utc_now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @classmethod
    def _event_from_database(cls, values: dict) -> AuditEvent:
        return AuditEvent(
            **{
                **values,
                "created_at": cls._format_time(values["created_at"]),
            }
        )
