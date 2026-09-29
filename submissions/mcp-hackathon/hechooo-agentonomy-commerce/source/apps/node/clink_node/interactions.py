from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .storage.base import InteractionSession, NodeRepository


@dataclass(frozen=True)
class InteractionLink:
    session_id: str
    token: str
    url: str
    expires_at: datetime


class InteractionService:
    def __init__(
        self,
        repository: NodeRepository,
        *,
        base_url: str,
        ttl_seconds: int = 900,
    ) -> None:
        self.repository = repository
        self.base_url = base_url.rstrip("/")
        self.ttl_seconds = ttl_seconds

    def create(
        self,
        kind: str,
        user_id: str,
        payload: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> InteractionLink:
        created_at = (now or datetime.now(UTC)).astimezone(UTC)
        expires_at = created_at + timedelta(seconds=self.ttl_seconds)
        session_id = f"int_{secrets.token_urlsafe(12)}"
        token = secrets.token_urlsafe(32)
        session = InteractionSession(
            session_id=session_id,
            kind=kind,
            user_id=user_id,
            token_hash=_token_hash(token),
            payload=payload,
            status="pending",
            created_at=created_at,
            expires_at=expires_at,
            consumed_at=None,
        )
        self.repository.create_interaction(session)
        self.repository.append_event(
            "interaction.created",
            session_id,
            {
                "kind": kind,
                "user_id": user_id,
                "expires_at": expires_at.isoformat(),
            },
        )
        return InteractionLink(
            session_id=session_id,
            token=token,
            url=f"{self.base_url}/interactions/{session_id}#token={token}",
            expires_at=expires_at,
        )

    def inspect(
        self,
        session_id: str,
        *,
        now: datetime | None = None,
    ) -> InteractionSession | None:
        session = self.repository.get_interaction(session_id)
        if session is None:
            return None
        current = (now or datetime.now(UTC)).astimezone(UTC)
        if session.status == "pending" and session.expires_at <= current:
            return None
        return session

    def consume(
        self,
        session_id: str,
        token: str,
        *,
        now: datetime | None = None,
    ) -> InteractionSession | None:
        consumed = self.repository.consume_interaction(
            session_id,
            _token_hash(token),
            now=(now or datetime.now(UTC)).astimezone(UTC),
        )
        if consumed:
            self.repository.append_event(
                "interaction.consumed",
                session_id,
                {"kind": consumed.kind, "user_id": consumed.user_id},
            )
        return consumed


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
