from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

import anyio
import httpx
import pytest

from services.audit_service.app import create_app
from services.audit_service.schemas import WriteAuditEventRequest
from services.audit_service.service import AuditService
from shared.config import AppConfig


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
INTERNAL_TOKEN = "audit-internal-token"


class ASGIClient:
    def __init__(self, app) -> None:
        self.app = app

    def request(self, method: str, url: str, **kwargs):
        async def send():
            transport = httpx.ASGITransport(
                app=self.app, raise_app_exceptions=False
            )
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.request(method, url, **kwargs)

        return anyio.run(send)

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)


def event(
    user_id: str,
    event_type: str,
    *,
    source_service: str = "account_service",
    payload: dict | None = None,
):
    return WriteAuditEventRequest(
        event_type=event_type,
        source_service=source_service,
        user_id=user_id,
        action_id=f"action_{user_id}",
        tx_hash="0x" + "ab" * 32,
        payload=payload or {},
    )


def test_user_summary_is_protected_exactly_scoped_and_payload_safe(tmp_path):
    current = NOW
    service = AuditService(
        storage_file=tmp_path / "audit.jsonl",
        clock=lambda: current,
    )
    service.write_event(event("user_1", "wallet_verified", payload={"secret": "never-public"}))
    current += timedelta(seconds=1)
    service.clock = lambda: current
    service.write_event(event("user_2", "grant_created", payload={"other": True}))
    current += timedelta(seconds=1)
    service.clock = lambda: current
    service.write_event(event("user_1", "grant_reduced", payload={"limit": "5"}))
    config = AppConfig(
        clink_internal_api_token=INTERNAL_TOKEN,
        audit_event_file=str(tmp_path / "audit.jsonl"),
    )
    client = ASGIClient(create_app(service=service, config=config))

    missing = client.get("/audit/summary?user_id=user_1&limit=8")
    response = client.get(
        "/audit/summary?user_id=user_1&limit=8",
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
    )

    assert missing.status_code == 401
    assert response.status_code == 200
    assert response.json() == [
        {
            "event": "Grant reduced",
            "summary": "Recorded by account service",
            "at": "2026-07-15T12:00:02Z",
        },
        {
            "event": "Wallet verified",
            "summary": "Recorded by account service",
            "at": "2026-07-15T12:00:00Z",
        },
    ]
    assert "user_2" not in response.text
    assert "never-public" not in response.text
    for forbidden in ("payload", "event_id", "action_id", "tx_hash", "user_id"):
        assert forbidden not in response.text


def test_user_summary_uses_generic_labels_for_unknown_internal_values(tmp_path):
    service = AuditService(storage_file=tmp_path / "audit.jsonl", clock=lambda: NOW)
    service.write_event(
        event(
            "user_1",
            "event_secret_private_key_123",
            source_service="service_secret_seed_phrase_456",
        )
    )

    summary = service.get_user_summary("user_1")

    assert [item.model_dump() for item in summary] == [
        {
            "event": "Account activity",
            "summary": "Recorded by Clink Core",
            "at": "2026-07-15T12:00:00Z",
        }
    ]
    serialized = str(summary)
    assert "private_key" not in serialized
    assert "seed_phrase" not in serialized


def test_database_is_authoritative_across_restarts_and_jsonl_is_legacy_read_only(
    tmp_path,
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'audit.sqlite3'}"
    legacy_file = tmp_path / "audit.jsonl"
    legacy_event = {
        "event_id": "audit_legacy",
        "event_type": "wallet_verified",
        "source_service": "account_service",
        "user_id": "legacy_user",
        "created_at": "2026-07-15T11:00:00Z",
    }
    legacy_file.write_text(json.dumps(legacy_event) + "\n")
    first = AuditService(
        database_url=database_url,
        storage_file=legacy_file,
        clock=lambda: NOW,
    )

    created = first.write_event(event("user_1", "grant_created"))
    restarted = AuditService(
        database_url=database_url,
        storage_file=legacy_file,
        clock=lambda: NOW,
    )

    assert restarted.get_event(created.event_id) == created
    assert restarted.get_event("audit_legacy").user_id == "legacy_user"
    assert legacy_file.read_text() == json.dumps(legacy_event) + "\n"


def test_explicit_audit_idempotency_returns_original_and_rejects_conflicts(tmp_path):
    current = NOW
    service = AuditService(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'audit.sqlite3'}",
        storage_file=tmp_path / "audit.jsonl",
        clock=lambda: current,
    )
    request = event("user_1", "grant_created").model_copy(
        update={"idempotency_key": "grant-created:user_1:grant_1"}
    )

    original = service.write_event(request)
    current += timedelta(minutes=1)
    replay = service.write_event(request)

    assert replay == original
    assert replay.created_at == "2026-07-15T12:00:00Z"
    assert len(service.repository.audit_events()) == 1
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        service.write_event(
            request.model_copy(update={"payload": {"status": "forged"}})
        )
    assert len(service.repository.audit_events()) == 1


def test_audit_http_idempotency_conflict_is_explicit_and_retry_safe(tmp_path):
    service = AuditService(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'audit.sqlite3'}",
        storage_file=tmp_path / "audit.jsonl",
        clock=lambda: NOW,
    )
    client = ASGIClient(
        create_app(
            service=service,
            config=AppConfig(clink_internal_api_token=INTERNAL_TOKEN),
        )
    )
    payload = event("user_1", "grant_created").model_dump()
    payload["idempotency_key"] = "grant-created:user_1:grant_1"
    headers = {"Authorization": f"Bearer {INTERNAL_TOKEN}"}

    original = client.post("/audit/events", headers=headers, json=payload)
    replay = client.post("/audit/events", headers=headers, json=payload)
    conflict = client.post(
        "/audit/events",
        headers=headers,
        json={**payload, "receipt_id": "receipt_forged"},
    )

    assert original.status_code == replay.status_code == 200
    assert replay.json() == original.json()
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "audit idempotency key conflicts"}
