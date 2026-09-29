from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TelegramIdentity:
    user_id: int
    username: str | None
    auth_date: datetime
    exchange_hash: str
