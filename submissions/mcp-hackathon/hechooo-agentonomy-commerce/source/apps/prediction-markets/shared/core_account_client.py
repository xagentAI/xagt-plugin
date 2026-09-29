from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class CoreAccountClientError(RuntimeError):
    pass


class CoreAccountClient:
    def __init__(self, base_url: str, internal_token: str, timeout_seconds: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.internal_token = internal_token.strip()
        self.timeout_seconds = timeout_seconds

    def readiness(self, user_id: str) -> dict:
        query = urllib.parse.urlencode({"user_id": user_id})
        return self._request(f"/internal/account-readiness?{query}")

    def create_setup_link(self, user_id: str) -> dict:
        result = self._request("/internal/account-sessions", {"user_id": user_id})
        account_url = result.get("account_url")
        if not isinstance(account_url, str) or not account_url.startswith(("http://", "https://")):
            raise CoreAccountClientError("Core Account response did not include a valid public account URL")
        return result

    def _request(self, path: str, payload: dict | None = None) -> dict:
        if not self.base_url:
            raise CoreAccountClientError("CLINK_CORE_ACCOUNT_SERVICE_URL is required")
        if not self.internal_token:
            raise CoreAccountClientError("CLINK_CORE_INTERNAL_API_TOKEN is required")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Authorization": f"Bearer {self.internal_token}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method="POST" if payload is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise CoreAccountClientError(f"Core Account request failed with HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, ValueError, TypeError) as exc:
            raise CoreAccountClientError(f"Core Account service unavailable: {type(exc).__name__}") from exc
