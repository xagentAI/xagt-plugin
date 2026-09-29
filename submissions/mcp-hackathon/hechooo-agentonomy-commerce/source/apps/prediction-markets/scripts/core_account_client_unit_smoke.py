from __future__ import annotations

import json
import sys
from pathlib import Path
import urllib.request

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.core_account_client import CoreAccountClient


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        del exc_type, exc_value, traceback

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def main() -> None:
    requests: list[dict] = []
    original_urlopen = urllib.request.urlopen

    def fake_urlopen(request, timeout):
        del timeout
        captured = {
            "method": request.method,
            "url": request.full_url,
            "authorization": request.get_header("Authorization"),
        }
        if request.data is not None:
            captured["body"] = json.loads(request.data)
        requests.append(captured)
        if request.method == "POST":
            return FakeResponse(
                {
                    "session_id": "account_session_123",
                    "account_url": "https://account.example/account/token-123",
                    "expires_at": "2026-07-17T12:00:00Z",
                }
            )
        return FakeResponse(
            {
                "user_id": "telegram_demo_user",
                "wallet_bound": False,
                "spending_grant_active": False,
                "ready": False,
            }
        )

    try:
        urllib.request.urlopen = fake_urlopen
        client = CoreAccountClient(
            base_url="http://core-account.internal:8019",
            internal_token="internal-secret",
        )
        readiness = client.readiness("telegram_demo_user")
        link = client.create_setup_link("telegram_demo_user")
    finally:
        urllib.request.urlopen = original_urlopen

    assert readiness["wallet_bound"] is False
    assert link["account_url"] == "https://account.example/account/token-123"
    assert requests == [
        {
            "method": "GET",
            "url": "http://core-account.internal:8019/internal/account-readiness?user_id=telegram_demo_user",
            "authorization": "Bearer internal-secret",
        },
        {
            "method": "POST",
            "url": "http://core-account.internal:8019/internal/account-sessions",
            "authorization": "Bearer internal-secret",
            "body": {"user_id": "telegram_demo_user"},
        },
    ]
    print(json.dumps({"status": "ok"}, indent=2))


if __name__ == "__main__":
    main()
