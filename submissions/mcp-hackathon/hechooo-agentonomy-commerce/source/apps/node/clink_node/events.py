from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import redis

from .storage.base import NodeRepository


class EventSink(Protocol):
    def publish(self, event: dict[str, Any]) -> None: ...


class MemoryEventSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class RedisEventSink:
    def __init__(
        self,
        url: str,
        *,
        channel: str = "clink.node.events",
        client: Any | None = None,
    ) -> None:
        self.channel = channel
        self.client = client or redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    def publish(self, event: dict[str, Any]) -> None:
        self.client.publish(
            self.channel,
            json.dumps(
                event,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )


@dataclass(frozen=True)
class DispatchReport:
    attempted: int
    published: int
    error: str | None


class OutboxDispatcher:
    def __init__(
        self,
        repository: NodeRepository,
        sink: EventSink,
    ) -> None:
        self.repository = repository
        self.sink = sink

    def dispatch(self, *, limit: int = 100) -> DispatchReport:
        events = self.repository.pending_events(limit)
        published = 0
        for event in events:
            try:
                self.sink.publish(event)
            except Exception as exc:
                return DispatchReport(
                    attempted=len(events),
                    published=published,
                    error=f"{type(exc).__name__}: {exc}",
                )
            self.repository.mark_event_published(event["event_id"])
            published += 1
        return DispatchReport(
            attempted=len(events),
            published=published,
            error=None,
        )
