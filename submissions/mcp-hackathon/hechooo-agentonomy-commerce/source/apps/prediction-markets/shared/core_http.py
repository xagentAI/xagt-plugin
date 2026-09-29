from __future__ import annotations

from shared.config import AppConfig


def core_request_headers(config: AppConfig, *, json_content: bool = False) -> dict[str, str]:
    token = config.clink_core_internal_api_token.strip()
    if not token:
        raise RuntimeError("CLINK_CORE_INTERNAL_API_TOKEN is required for Clink Core requests")
    headers = {"Authorization": f"Bearer {token}"}
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers
