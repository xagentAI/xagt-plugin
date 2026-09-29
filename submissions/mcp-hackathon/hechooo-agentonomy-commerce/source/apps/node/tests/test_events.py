from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apps.node.clink_node.events import (
    MemoryEventSink,
    OutboxDispatcher,
    RedisEventSink,
)
from apps.node.clink_node.storage.sqlite import SQLiteNodeRepository


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[tuple[str, str]] = []

    def publish(self, channel: str, message: str) -> int:
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.messages.append((channel, message))
        return 1


class EventDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = SQLiteNodeRepository(
            Path(self.temporary.name) / "node.db"
        )
        self.repository.migrate()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_memory_sink_publishes_and_marks_outbox(self) -> None:
        event_id = self.repository.append_event(
            "interaction.created",
            "session_1",
            {"status": "pending"},
        )
        sink = MemoryEventSink()

        report = OutboxDispatcher(self.repository, sink).dispatch()

        self.assertEqual(report.published, 1)
        self.assertIsNone(report.error)
        self.assertEqual(sink.events[0]["event_id"], event_id)
        self.assertEqual(self.repository.pending_events(), [])

    def test_redis_sink_publishes_canonical_json(self) -> None:
        client = FakeRedis()
        sink = RedisEventSink(
            "redis://ignored/0",
            channel="clink.node.events",
            client=client,
        )

        sink.publish(
            {
                "event_id": 7,
                "event_type": "purchase.updated",
                "payload": {"state": "delivered"},
            }
        )

        channel, raw = client.messages[0]
        self.assertEqual(channel, "clink.node.events")
        self.assertEqual(json.loads(raw)["event_id"], 7)

    def test_failed_publish_leaves_event_pending_for_retry(self) -> None:
        self.repository.append_event(
            "purchase.updated",
            "purchase_1",
            {"state": "payment_submitted"},
        )
        sink = RedisEventSink(
            "redis://ignored/0",
            client=FakeRedis(fail=True),
        )

        report = OutboxDispatcher(self.repository, sink).dispatch()

        self.assertEqual(report.published, 0)
        self.assertIn("redis unavailable", report.error or "")
        self.assertEqual(len(self.repository.pending_events()), 1)


if __name__ == "__main__":
    unittest.main()
