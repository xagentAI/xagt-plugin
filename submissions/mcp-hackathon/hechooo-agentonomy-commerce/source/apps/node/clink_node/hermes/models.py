from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


class HermesError(RuntimeError):
    """Base class for deliberately redacted Hermes boundary failures."""


class HermesUnavailable(HermesError):
    def __init__(self) -> None:
        super().__init__("hermes_unavailable")


class HermesProtocolError(HermesError):
    def __init__(self) -> None:
        super().__init__("hermes_protocol_error")


class HermesResponseTooLarge(HermesError):
    def __init__(self) -> None:
        super().__init__("hermes_response_too_large")


class HermesNotFound(HermesError):
    def __init__(self) -> None:
        super().__init__("hermes_not_found")


class HermesConflict(HermesError):
    def __init__(self) -> None:
        super().__init__("hermes_conflict")


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _utf8_size(value: str) -> int:
    encoded: bytes | None = None
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        pass
    if encoded is None:
        raise ValueError("invalid Hermes text")
    return len(encoded)


@dataclass(frozen=True, slots=True)
class HermesConversationMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("invalid Hermes conversation role")
        if not isinstance(self.content, str):
            raise ValueError("invalid Hermes conversation content")
        if _utf8_size(self.content) > 64 * 1024:
            raise ValueError("Hermes conversation content is too large")


@dataclass(frozen=True, slots=True)
class HermesSession:
    id: str
    source: str | None = None
    title: str | None = None
    model: str | None = None
    started_at: float | None = None
    ended_at: float | None = None
    message_count: int | None = None
    last_active: float | None = None
    preview: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    hidden: bool | None = None
    has_system_prompt: bool = False
    has_model_config: bool = False


@dataclass(frozen=True, slots=True)
class HermesMessage:
    id: int | str | None
    session_id: str
    role: str
    content: str
    timestamp: float | None = None
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class HermesMessagesPage:
    session_id: str
    messages: tuple[HermesMessage, ...]
    limit: int
    offset: int
    order: str
    returned: int


@dataclass(frozen=True, slots=True)
class HermesRun:
    run_id: str
    status: str
    session_id: str | None = None
    created_at: float | None = None
    updated_at: float | None = None
    model: str | None = None
    last_event: str | None = None
    output: str | None = None
    error: str | None = None
    usage: Mapping[str, int] | None = None
    pending_steer: str | None = None

    def __post_init__(self) -> None:
        if self.usage is not None:
            object.__setattr__(self, "usage", _deep_freeze(self.usage))


@dataclass(frozen=True, slots=True)
class HermesSseEvent:
    event: str
    id: str | None
    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.data, Mapping):
            raise ValueError("invalid Hermes SSE data")
        object.__setattr__(self, "data", _deep_freeze(self.data))
