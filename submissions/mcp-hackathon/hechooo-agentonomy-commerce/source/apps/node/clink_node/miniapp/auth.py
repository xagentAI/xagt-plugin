from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import parse_qsl

from .models import TelegramIdentity


BrowserTokenPurpose = Literal["session", "csrf"]

MAX_TELEGRAM_INIT_DATA_BYTES = 16 * 1024
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32}$", re.ASCII)
_SUBJECT_ID_PATTERN = re.compile(r"^telegram:[1-9][0-9]*$", re.ASCII)
_AUTH_DATE_PATTERN = re.compile(r"^[0-9]+$", re.ASCII)
_TELEGRAM_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_BROWSER_TOKEN_DOMAIN = b"clink-miniapp-browser-v1\x00"
_STORAGE_SCOPE_DOMAIN = (
    b"clink-miniapp-storage-scope-v1\x00local-storage\x00"
)
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


class MiniAppAuthError(ValueError):
    """A deliberately redacted Mini App authentication failure."""


def validate_telegram_init_data(
    init_data: str,
    *,
    bot_token: bytes,
    now: datetime,
    max_age_seconds: int,
) -> TelegramIdentity:
    try:
        return _validate_telegram_init_data(
            init_data,
            bot_token=bot_token,
            now=now,
            max_age_seconds=max_age_seconds,
        )
    except Exception:
        pass
    raise MiniAppAuthError("telegram_auth_failed") from None


def _validate_telegram_init_data(
    init_data: str,
    *,
    bot_token: bytes,
    now: datetime,
    max_age_seconds: int,
) -> TelegramIdentity:
    if not isinstance(init_data, str) or not init_data:
        raise ValueError
    if len(init_data) > MAX_TELEGRAM_INIT_DATA_BYTES:
        raise ValueError
    if len(init_data.encode("utf-8")) > MAX_TELEGRAM_INIT_DATA_BYTES:
        raise ValueError
    if not isinstance(bot_token, bytes) or not bot_token:
        raise ValueError
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise ValueError
    if (
        isinstance(max_age_seconds, bool)
        or not isinstance(max_age_seconds, int)
        or max_age_seconds < 0
    ):
        raise ValueError
    if _has_malformed_percent_encoding(init_data):
        raise ValueError

    pairs = parse_qsl(
        init_data,
        keep_blank_values=True,
        strict_parsing=True,
        encoding="utf-8",
        errors="strict",
        max_num_fields=32,
    )
    fields: dict[str, str] = {}
    for key, value in pairs:
        if not key or key in fields:
            raise ValueError
        fields[key] = value

    supplied_hash = fields.pop("hash", None)
    if supplied_hash is None or not _TELEGRAM_HASH_PATTERN.fullmatch(
        supplied_hash
    ):
        raise ValueError
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(fields.items())
    )
    webapp_secret = hmac.new(
        b"WebAppData",
        bot_token,
        hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        webapp_secret,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, supplied_hash):
        raise ValueError

    raw_auth_date = fields.get("auth_date")
    if raw_auth_date is None or not _AUTH_DATE_PATTERN.fullmatch(
        raw_auth_date
    ):
        raise ValueError
    auth_date = datetime.fromtimestamp(int(raw_auth_date), tz=UTC)
    current = now.astimezone(UTC)
    if auth_date > current:
        raise ValueError
    if (current - auth_date).total_seconds() > max_age_seconds:
        raise ValueError

    raw_user = fields.get("user")
    if raw_user is None:
        raise ValueError
    user = json.loads(raw_user)
    if not isinstance(user, dict):
        raise ValueError
    user_id = user.get("id")
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise ValueError
    if user_id <= 0:
        raise ValueError
    username = user.get("username")
    if username is not None and not isinstance(username, str):
        raise ValueError

    return TelegramIdentity(
        user_id=user_id,
        username=username,
        auth_date=auth_date,
        exchange_hash=hashlib.sha256(bytes.fromhex(supplied_hash)).hexdigest(),
    )


def new_browser_session_id() -> str:
    return secrets.token_urlsafe(24)


def derive_browser_token(
    secret: bytes,
    session_id: str,
    *,
    purpose: BrowserTokenPurpose,
) -> str:
    try:
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError
        if not isinstance(session_id, str) or not _SESSION_ID_PATTERN.fullmatch(
            session_id
        ):
            raise ValueError
        if purpose not in ("session", "csrf"):
            raise ValueError
        domain = (
            _BROWSER_TOKEN_DOMAIN
            + purpose.encode("ascii")
            + b"\x00"
            + session_id.encode("ascii")
        )
        digest = hmac.new(secret, domain, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    except Exception:
        pass
    raise MiniAppAuthError("browser_session_failed") from None


def derive_storage_scope(secret: bytes, subject_id: str) -> str:
    try:
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError
        if (
            not isinstance(subject_id, str)
            or _SUBJECT_ID_PATTERN.fullmatch(subject_id) is None
        ):
            raise ValueError
        digest = hmac.new(
            secret,
            _STORAGE_SCOPE_DOMAIN + subject_id.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    except Exception:
        pass
    raise MiniAppAuthError("browser_session_failed") from None


def hash_browser_token(token: str) -> str:
    try:
        if not isinstance(token, str) or not token:
            raise ValueError
        return hashlib.sha256(token.encode("ascii")).hexdigest()
    except Exception:
        pass
    raise MiniAppAuthError("browser_session_failed") from None


def _has_malformed_percent_encoding(value: str) -> bool:
    index = 0
    while index < len(value):
        if value[index] != "%":
            index += 1
            continue
        if index + 2 >= len(value):
            return True
        if value[index + 1] not in _HEX_DIGITS:
            return True
        if value[index + 2] not in _HEX_DIGITS:
            return True
        index += 3
    return False
