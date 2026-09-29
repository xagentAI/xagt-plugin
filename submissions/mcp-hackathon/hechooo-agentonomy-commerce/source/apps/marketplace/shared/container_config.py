from __future__ import annotations

import os
import sys
from collections.abc import Mapping

from sqlalchemy.engine import URL


PRODUCTION_ROLES = frozenset({"api", "worker", "mcp"})
DATABASE_ROLES = frozenset({"api", "worker", "migrate"})
CORE_SERVICE_URLS = (
    "CLINK_CORE_ACTION_SERVICE_URL",
    "CLINK_CORE_POLICY_SERVICE_URL",
    "CLINK_CORE_AUDIT_SERVICE_URL",
    "CLINK_CORE_FUNDING_SERVICE_URL",
)
PLACEHOLDER_MARKERS = (
    "change-me",
    "changeme",
    "replace-with",
    "example-secret",
    "local-development-secret",
)


class ContainerConfigurationError(ValueError):
    """Raised when a container cannot start safely with its current environment."""


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "")
    if not value:
        raise ContainerConfigurationError(f"{name} must be configured")
    return value


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"password", "secret", "token"} or any(
        marker in normalized for marker in PLACEHOLDER_MARKERS
    )


def parse_boolean(value: str, *, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off", ""}:
        return False
    raise ContainerConfigurationError(f"{name} must be true or false")


def build_database_url(environ: Mapping[str, str] | None = None) -> str:
    """Build a safely escaped SQLAlchemy URL from standard PostgreSQL variables."""

    values = environ or os.environ
    try:
        port = int(values.get("POSTGRES_PORT", "5432"))
    except ValueError as exc:
        raise ContainerConfigurationError("POSTGRES_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ContainerConfigurationError("POSTGRES_PORT must be between 1 and 65535")

    url = URL.create(
        "postgresql+psycopg",
        username=_required(values, "POSTGRES_USER"),
        password=_required(values, "POSTGRES_PASSWORD"),
        host=_required(values, "POSTGRES_HOST"),
        port=port,
        database=_required(values, "POSTGRES_DB"),
    )
    return url.render_as_string(hide_password=False)


def escape_alembic_url(url: str) -> str:
    """Escape ConfigParser interpolation without changing the database URL."""

    return url.replace("%", "%%")


def validate_container_environment(
    role: str, environ: Mapping[str, str] | None = None
) -> None:
    values = environ or os.environ
    if role not in PRODUCTION_ROLES | {"migrate"}:
        raise ContainerConfigurationError(f"unsupported container role: {role}")

    deployment_mode = values.get("MARKETPLACE_DEPLOYMENT_MODE", "development").lower()
    if deployment_mode not in {"development", "test", "production"}:
        raise ContainerConfigurationError(
            "MARKETPLACE_DEPLOYMENT_MODE must be development, test, or production"
        )
    if role in DATABASE_ROLES:
        build_database_url(values)
        if deployment_mode == "production":
            database_password = _required(values, "POSTGRES_PASSWORD")
            if len(database_password) < 16 or _is_placeholder(database_password):
                raise ContainerConfigurationError(
                    "POSTGRES_PASSWORD must be at least 16 characters and not a placeholder"
                )

    if deployment_mode != "production":
        return

    if role == "migrate":
        return

    if role == "mcp":
        required = (
            "MARKETPLACE_INTERNAL_API_TOKEN",
            "MARKETPLACE_REGISTRY_HOST",
            "MARKETPLACE_REGISTRY_PORT",
            "MARKETPLACE_MCP_HOST",
            "MARKETPLACE_MCP_PORT",
        )
        for name in required:
            value = _required(values, name)
            if name == "MARKETPLACE_INTERNAL_API_TOKEN" and (
                len(value) < 32 or _is_placeholder(value)
            ):
                raise ContainerConfigurationError(
                    f"{name} must be at least 32 characters and not a placeholder"
                )
        return

    _required(values, "REDIS_URL")
    for name in CORE_SERVICE_URLS:
        _required(values, name)
    for name in ("CLINK_CORE_INTERNAL_API_TOKEN",):
        secret = _required(values, name)
        if len(secret) < 32 or _is_placeholder(secret):
            raise ContainerConfigurationError(
                f"{name} must be at least 32 characters and not a placeholder"
            )

    if role == "worker":
        return

    marketplace_token = _required(values, "MARKETPLACE_INTERNAL_API_TOKEN")
    if len(marketplace_token) < 32 or _is_placeholder(marketplace_token):
        raise ContainerConfigurationError(
            "MARKETPLACE_INTERNAL_API_TOKEN must be at least 32 characters and not a placeholder"
        )

    admin_disabled = parse_boolean(
        values.get("MARKETPLACE_ADMIN_DISABLED", "false"),
        name="MARKETPLACE_ADMIN_DISABLED",
    )
    admin_wallets = tuple(
        value.strip()
        for value in values.get("MARKETPLACE_ADMIN_WALLETS", "").split(",")
        if value.strip()
    )
    if not admin_disabled and not admin_wallets:
        raise ContainerConfigurationError(
            "MARKETPLACE_ADMIN_WALLETS must be configured unless "
            "MARKETPLACE_ADMIN_DISABLED=true"
        )


def _main(argv: list[str]) -> int:
    try:
        if argv == ["database-url"]:
            print(build_database_url())
            return 0
        if len(argv) == 2 and argv[0] == "preflight":
            validate_container_environment(argv[1])
            return 0
        raise ContainerConfigurationError(
            "usage: python -m shared.container_config database-url | preflight ROLE"
        )
    except ContainerConfigurationError as exc:
        print(f"container configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
