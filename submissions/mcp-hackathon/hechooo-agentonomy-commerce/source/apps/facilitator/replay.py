from __future__ import annotations

import hashlib
from collections.abc import MutableMapping
from threading import RLock
from typing import Protocol

import redis


class ReplayUnavailable(RuntimeError):
    """The replay coordination dependency cannot make a safe decision."""


class ReplayCoordinator(Protocol):
    def consume_dpop_jti(
        self,
        *,
        tenant_id: str,
        node_id: str,
        credential_epoch: int,
        jti: str,
        ttl_seconds: int,
    ) -> bool: ...


class RedisReplayCoordinator:
    def __init__(
        self,
        redis_url: str,
        *,
        client: redis.Redis | None = None,
        key_prefix: str = "clink:hosted:dpop",
        socket_timeout: float = 1.0,
    ) -> None:
        if not isinstance(redis_url, str) or not redis_url.startswith(("redis://", "rediss://")):
            raise ValueError("Redis URL is required")
        self._client = client or redis.Redis.from_url(
            redis_url,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_timeout,
            decode_responses=False,
        )
        self._key_prefix = key_prefix

    def consume_dpop_jti(
        self,
        *,
        tenant_id: str,
        node_id: str,
        credential_epoch: int,
        jti: str,
        ttl_seconds: int,
    ) -> bool:
        if type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise ValueError("replay TTL is invalid")
        # Identifiers are intentionally bounded but may contain ':'; hashing
        # each scope component separately prevents delimiter-boundary aliases
        # such as (tenant='a:b', node='c') and (tenant='a', node='b:c').
        tenant_digest = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()
        node_digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()
        jti_digest = hashlib.sha256(jti.encode("utf-8")).hexdigest()
        key = ":".join(
            (
                self._key_prefix,
                tenant_digest,
                node_digest,
                str(credential_epoch),
                jti_digest,
            )
        )
        try:
            result = self._client.set(key, b"1", nx=True, ex=ttl_seconds)
        except Exception as exc:
            raise ReplayUnavailable("replay coordination unavailable") from exc
        if result is True:
            return True
        if result is False or result is None:
            return False
        raise ReplayUnavailable("replay coordination returned an invalid result")


class InMemoryReplayCoordinator:
    """Explicit test fake; never selected by production construction."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._entries: MutableMapping[tuple[str, str, int, str], int] = {}

    def consume_dpop_jti(
        self,
        *,
        tenant_id: str,
        node_id: str,
        credential_epoch: int,
        jti: str,
        ttl_seconds: int,
    ) -> bool:
        if type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise ValueError("replay TTL is invalid")
        key = (tenant_id, node_id, credential_epoch, jti)
        with self._lock:
            if key in self._entries:
                return False
            self._entries[key] = ttl_seconds
            return True
