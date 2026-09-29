"""记忆存储契约：v0.1 只要求会话历史与简单 KV，向量记忆是 v2。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from yai_core.types import ChatMessage


@runtime_checkable
class MemoryStore(Protocol):
    async def append_history(self, message: ChatMessage) -> None: ...

    def history(self) -> list[ChatMessage]: ...

    async def put(self, key: str, value: str) -> None: ...

    async def get(self, key: str) -> str | None: ...

    async def clear(self) -> None: ...
