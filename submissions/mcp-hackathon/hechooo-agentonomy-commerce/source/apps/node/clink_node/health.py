from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    status_code: int | None
    detail: str | None
    body: dict[str, Any] | None


class HttpHealthProbe:
    def __init__(self, timeout_seconds: float = 1.0) -> None:
        self.timeout_seconds = timeout_seconds

    def check(self, url: str) -> HealthResult:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "ClinkNode/0.1"},
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                raw = response.read()
                parsed = json.loads(raw) if raw else {}
                return HealthResult(
                    ok=200 <= response.status < 300,
                    status_code=response.status,
                    detail=None,
                    body=parsed if isinstance(parsed, dict) else None,
                )
        except urllib.error.HTTPError as exc:
            return HealthResult(
                ok=False,
                status_code=exc.code,
                detail=f"HTTP {exc.code}",
                body=None,
            )
        except (OSError, TimeoutError) as exc:
            return HealthResult(
                ok=False,
                status_code=None,
                detail=f"{type(exc).__name__}: {exc}",
                body=None,
            )
