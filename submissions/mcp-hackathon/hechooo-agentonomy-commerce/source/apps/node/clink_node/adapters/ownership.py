"""Narrow object ownership checks for the authenticated shared Node ingress."""

import re
from typing import Any

from .http import DownstreamError


def object_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        raise ValueError("invalid object identifier")
    return value


def require_owner(
    payload: dict[str, Any], *, user_id: str, id_field: str,
    expected_id: str, service: str, agent_id: str | None = None,
) -> dict[str, Any]:
    if (
        payload.get("user_id") != user_id
        or payload.get(id_field) != expected_id
        or (agent_id is not None and payload.get("agent_id") != agent_id)
    ):
        # Do not reveal whether a foreign object exists, or include its body.
        raise DownstreamError(service, 404, "owned object not found")
    return payload
