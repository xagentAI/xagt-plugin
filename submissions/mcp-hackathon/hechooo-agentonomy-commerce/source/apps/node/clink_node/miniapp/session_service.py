from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable
from urllib.parse import urlsplit

from .auth import (
    MiniAppAuthError,
    derive_browser_token,
    derive_storage_scope,
    hash_browser_token,
    new_browser_session_id,
    validate_telegram_init_data,
)
from .models import TelegramIdentity
from ..storage.base import (
    MiniAppBrowserSession,
    MiniAppStorageConflict,
    NodeRepository,
)


_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{22}$", re.ASCII)
_BROWSER_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$", re.ASCII)


class MiniAppServiceError(RuntimeError):
    def __init__(self, reason: str, status_code: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class MiniAppSessionExchange:
    identity: TelegramIdentity
    session: MiniAppBrowserSession
    session_token: str
    csrf_token: str
    storage_scope: str
    max_age_seconds: int


class MiniAppSessionService:
    def __init__(
        self,
        *,
        repository: NodeRepository,
        telegram_bot_token: bytes,
        cookie_secret: bytes,
        allowed_origin: str,
        now: Callable[[], datetime] | None = None,
        auth_max_age_seconds: int = 300,
        session_ttl_seconds: int = 86_400,
    ) -> None:
        self.repository = repository
        self._telegram_bot_token = _bot_token_bytes(telegram_bot_token)
        self._cookie_secret = _secret_bytes(cookie_secret)
        self.allowed_origin = _normalize_origin(allowed_origin)
        self._now = now or (lambda: datetime.now(UTC))
        self.auth_max_age_seconds = _positive_int(auth_max_age_seconds)
        self.session_ttl_seconds = _positive_int(session_ttl_seconds)

    def current_time(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("miniapp_clock_invalid")
        return value.astimezone(UTC)

    def require_origin(self, values: list[str]) -> None:
        if len(values) != 1:
            raise MiniAppServiceError("miniapp_forbidden", 403)
        try:
            received = _normalize_origin(values[0])
        except ValueError:
            raise MiniAppServiceError("miniapp_forbidden", 403) from None
        if not hmac.compare_digest(received, self.allowed_origin):
            raise MiniAppServiceError("miniapp_forbidden", 403)

    def exchange_session(
        self,
        *,
        init_data: str,
        client_nonce: str,
    ) -> MiniAppSessionExchange:
        now = self.current_time()
        try:
            identity = validate_telegram_init_data(
                init_data,
                bot_token=self._telegram_bot_token,
                now=now,
                max_age_seconds=self.auth_max_age_seconds,
            )
            nonce = _decode_client_nonce(client_nonce)
            session_id = new_browser_session_id()
            session_token = derive_browser_token(
                self._cookie_secret,
                session_id,
                purpose="session",
            )
            csrf_token = derive_browser_token(
                self._cookie_secret,
                session_id,
                purpose="csrf",
            )
            proposed = MiniAppBrowserSession(
                session_id=session_id,
                telegram_user_id=str(identity.user_id),
                subject_id=f"telegram:{identity.user_id}",
                exchange_hash=identity.exchange_hash,
                client_nonce_hash=hashlib.sha256(nonce).hexdigest(),
                session_token_hash=hash_browser_token(session_token),
                csrf_token_hash=hash_browser_token(csrf_token),
                created_at=now,
                expires_at=now + timedelta(seconds=self.session_ttl_seconds),
                revoked_at=None,
            )
            stored = self.repository.exchange_miniapp_session(proposed)
            session_token = derive_browser_token(
                self._cookie_secret,
                stored.session_id,
                purpose="session",
            )
            csrf_token = derive_browser_token(
                self._cookie_secret,
                stored.session_id,
                purpose="csrf",
            )
            storage_scope = derive_storage_scope(
                self._cookie_secret,
                stored.subject_id,
            )
        except MiniAppStorageConflict:
            raise MiniAppServiceError("miniapp_conflict", 409) from None
        except (MiniAppAuthError, UnicodeError, ValueError):
            raise MiniAppServiceError("miniapp_unauthorized", 401) from None
        max_age = max(
            0,
            min(
                self.session_ttl_seconds,
                int((stored.expires_at - now).total_seconds()),
            ),
        )
        return MiniAppSessionExchange(
            identity=identity,
            session=stored,
            session_token=session_token,
            csrf_token=csrf_token,
            storage_scope=storage_scope,
            max_age_seconds=max_age,
        )

    def authenticate_session(self, session_token: str) -> MiniAppBrowserSession:
        if (
            not isinstance(session_token, str)
            or not _BROWSER_TOKEN_PATTERN.fullmatch(session_token)
        ):
            raise MiniAppServiceError("miniapp_unauthorized", 401)
        try:
            session = self.repository.get_miniapp_session(
                hash_browser_token(session_token),
                self.current_time(),
            )
        except (MiniAppAuthError, ValueError):
            session = None
        if session is None:
            raise MiniAppServiceError("miniapp_unauthorized", 401)
        return session

    def require_csrf(
        self,
        session: MiniAppBrowserSession,
        values: list[str],
    ) -> None:
        if len(values) != 1 or not _BROWSER_TOKEN_PATTERN.fullmatch(values[0]):
            raise MiniAppServiceError("miniapp_forbidden", 403)
        try:
            supplied_hash = hash_browser_token(values[0])
        except MiniAppAuthError:
            raise MiniAppServiceError("miniapp_forbidden", 403) from None
        if not hmac.compare_digest(supplied_hash, session.csrf_token_hash):
            raise MiniAppServiceError("miniapp_forbidden", 403)

    def revoke_session(self, session: MiniAppBrowserSession) -> None:
        if not self.repository.revoke_miniapp_session(
            session.session_token_hash,
            self.current_time(),
        ):
            raise MiniAppServiceError("miniapp_unauthorized", 401)


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("invalid Mini App setting")
    return value


def _secret_bytes(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) < 32:
        raise ValueError("invalid Mini App secret")
    return value


def _bot_token_bytes(value: object) -> bytes:
    if not isinstance(value, bytes) or not value or len(value) > 4096:
        raise ValueError("invalid Mini App credential")
    return value


def _decode_client_nonce(value: object) -> bytes:
    if not isinstance(value, str) or not _NONCE_PATTERN.fullmatch(value):
        raise ValueError
    decoded = base64.b64decode(
        value + "==",
        altchars=b"-_",
        validate=True,
    )
    if len(decoded) != 16:
        raise ValueError
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if not hmac.compare_digest(canonical, value):
        raise ValueError
    return decoded


def _normalize_origin(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("invalid Mini App origin")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("invalid Mini App origin") from None
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid Mini App origin")
    host = parsed.hostname.lower()
    if parsed.scheme == "http" and host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("invalid Mini App origin")
    default_port = 443 if parsed.scheme == "https" else 80
    authority = f"[{host}]" if ":" in host else host
    if port is not None and port != default_port:
        authority = f"{authority}:{port}"
    return f"{parsed.scheme}://{authority}"
