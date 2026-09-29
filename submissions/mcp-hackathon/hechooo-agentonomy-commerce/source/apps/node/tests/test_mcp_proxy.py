from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

import anyio

from apps.node.clink_node import mcp_proxy


class _Context:
    def __init__(
        self,
        name: str,
        events: list[str],
        value: object,
        task_ids: dict[str, int] | None = None,
        *,
        use_task_group: bool = False,
        exit_error: BaseException | None = None,
    ) -> None:
        self.name = name
        self.events = events
        self.value = value
        self.task_ids = task_ids
        self.use_task_group = use_task_group
        self.exit_error = exit_error
        self.task_group: anyio.abc.TaskGroup | None = None

    async def __aenter__(self) -> object:
        if self.use_task_group:
            self.task_group = anyio.create_task_group()
            await self.task_group.__aenter__()
        if self.task_ids is not None:
            self.task_ids[f"{self.name}:enter"] = anyio.get_current_task().id
        self.events.append(f"{self.name}:enter")
        return self.value

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self.task_ids is not None:
            self.task_ids[f"{self.name}:exit"] = anyio.get_current_task().id
        self.events.append(f"{self.name}:exit")
        task_group, self.task_group = self.task_group, None
        if task_group is not None:
            await task_group.__aexit__(exc_type, exc, traceback)
        if self.exit_error is not None:
            raise self.exit_error


class _ClientSession(_Context):
    def __init__(
        self,
        events: list[str],
        initialize_error: BaseException | None = None,
        *,
        started: anyio.Event | None = None,
        task_ids: dict[str, int] | None = None,
        use_task_group: bool = False,
    ) -> None:
        super().__init__(
            "session",
            events,
            self,
            task_ids,
            use_task_group=use_task_group,
        )
        self.initialize_error = initialize_error
        self.started = started

    async def initialize(self) -> None:
        self.events.append("session:initialize")
        if self.started is not None:
            self.started.set()
            await anyio.sleep_forever()
        if self.initialize_error is not None:
            raise self.initialize_error


def _session_with_fake_contexts(
    events: list[str],
    initialize_error: BaseException | None = None,
):
    client = _Context("client", events, object())
    transport = _Context("transport", events, (object(), object(), object()))
    session = _ClientSession(events, initialize_error)
    patches = (
        patch.object(mcp_proxy.httpx, "AsyncClient", return_value=client),
        patch.object(mcp_proxy, "streamable_http_client", return_value=transport),
        patch.object(mcp_proxy, "ClientSession", return_value=session),
    )
    return mcp_proxy._McpSession("https://downstream.test/mcp", {}, 1), patches, session


class McpSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_error_unwinds_all_entered_contexts_and_preserves_error(
        self,
    ) -> None:
        events: list[str] = []
        error = RuntimeError("initialize failed")
        wrapper, patches, _session = _session_with_fake_contexts(events, error)

        with patches[0], patches[1], patches[2]:
            with self.assertRaises(RuntimeError) as caught:
                await wrapper.__aenter__()

        self.assertIs(caught.exception, error)
        self.assertEqual(
            events,
            [
                "client:enter",
                "transport:enter",
                "session:enter",
                "session:initialize",
                "session:exit",
                "transport:exit",
                "client:exit",
            ],
        )

    async def test_initialize_cancellation_unwinds_all_entered_contexts(
        self,
    ) -> None:
        events: list[str] = []
        wrapper, patches, _session = _session_with_fake_contexts(
            events,
            asyncio.CancelledError(),
        )

        with patches[0], patches[1], patches[2]:
            with self.assertRaises(asyncio.CancelledError):
                await wrapper.__aenter__()

        self.assertEqual(
            events,
            [
                "client:enter",
                "transport:enter",
                "session:enter",
                "session:initialize",
                "session:exit",
                "transport:exit",
                "client:exit",
            ],
        )

    async def test_initialize_error_notes_cleanup_exception_type_only(self) -> None:
        events: list[str] = []
        original_error = RuntimeError("initialize failed")
        cleanup_error = ValueError("cleanup secret")
        client = _Context(
            "client",
            events,
            object(),
            exit_error=cleanup_error,
        )
        transport = _Context("transport", events, (object(), object(), object()))
        session = _ClientSession(events, original_error)
        wrapper = mcp_proxy._McpSession("https://downstream.test/mcp", {}, 1)

        with (
            patch.object(mcp_proxy.httpx, "AsyncClient", return_value=client),
            patch.object(
                mcp_proxy,
                "streamable_http_client",
                return_value=transport,
            ),
            patch.object(mcp_proxy, "ClientSession", return_value=session),
        ):
            with self.assertRaises(RuntimeError) as caught:
                await wrapper.__aenter__()

        self.assertIs(caught.exception, original_error)
        self.assertEqual(
            caught.exception.__notes__,
            ["AsyncExitStack cleanup failed: ValueError"],
        )
        self.assertNotIn("cleanup secret", " ".join(caught.exception.__notes__))

    async def test_successful_session_is_closed_by_aexit(self) -> None:
        events: list[str] = []
        wrapper, patches, session = _session_with_fake_contexts(events)

        with patches[0], patches[1], patches[2]:
            async with wrapper as entered:
                self.assertIs(entered, session)

        self.assertEqual(
            events,
            [
                "client:enter",
                "transport:enter",
                "session:enter",
                "session:initialize",
                "session:exit",
                "transport:exit",
                "client:exit",
            ],
        )

    async def test_anyio_task_cancellation_unwinds_lifo_in_the_same_task(self) -> None:
        events: list[str] = []
        task_ids: dict[str, int] = {}
        started = anyio.Event()
        client = _Context("client", events, object(), task_ids)
        transport = _Context(
            "transport",
            events,
            (object(), object(), object()),
            task_ids,
            use_task_group=True,
        )
        session = _ClientSession(
            events,
            started=started,
            task_ids=task_ids,
            use_task_group=True,
        )
        wrapper = mcp_proxy._McpSession("https://downstream.test/mcp", {}, 1)
        caught: list[BaseException] = []

        async def enter() -> None:
            try:
                await wrapper.__aenter__()
            except BaseException as error:
                caught.append(error)

        with (
            patch.object(mcp_proxy.httpx, "AsyncClient", return_value=client),
            patch.object(
                mcp_proxy,
                "streamable_http_client",
                return_value=transport,
            ),
            patch.object(mcp_proxy, "ClientSession", return_value=session),
        ):
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(enter)
                await started.wait()
                task_group.cancel_scope.cancel()

        self.assertEqual(len(caught), 1)
        self.assertIsInstance(caught[0], asyncio.CancelledError)
        self.assertEqual(
            events,
            [
                "client:enter",
                "transport:enter",
                "session:enter",
                "session:initialize",
                "session:exit",
                "transport:exit",
                "client:exit",
            ],
        )
        for name in ("client", "transport", "session"):
            self.assertEqual(task_ids[f"{name}:enter"], task_ids[f"{name}:exit"])


if __name__ == "__main__":
    unittest.main()
