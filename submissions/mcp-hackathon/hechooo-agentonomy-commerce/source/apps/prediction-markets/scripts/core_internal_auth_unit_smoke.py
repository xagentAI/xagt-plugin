from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.config import AppConfig
from shared.core_http import core_request_headers


def main() -> None:
    previous = os.environ.get("CLINK_CORE_INTERNAL_API_TOKEN")
    try:
        os.environ["CLINK_CORE_INTERNAL_API_TOKEN"] = "prediction-core-auth-test-token"
        config = AppConfig.from_env()
        assert config.clink_core_internal_api_token == "prediction-core-auth-test-token"
        assert core_request_headers(config) == {
            "Authorization": "Bearer prediction-core-auth-test-token"
        }
        assert config.is_core_service_url(config.clink_core_funding_service_url)
        assert not config.is_core_service_url(config.account_binding_url)
        assert config.describe()["clink_core_internal_api_token"] is True
    finally:
        if previous is None:
            os.environ.pop("CLINK_CORE_INTERNAL_API_TOKEN", None)
        else:
            os.environ["CLINK_CORE_INTERNAL_API_TOKEN"] = previous

    missing_token_config = AppConfig(clink_core_internal_api_token="")
    try:
        core_request_headers(missing_token_config)
    except RuntimeError as exc:
        assert "CLINK_CORE_INTERNAL_API_TOKEN is required" in str(exc)
    else:
        raise AssertionError("Core requests must fail closed when the internal token is missing")

    print('{"status":"ok"}')


if __name__ == "__main__":
    main()
