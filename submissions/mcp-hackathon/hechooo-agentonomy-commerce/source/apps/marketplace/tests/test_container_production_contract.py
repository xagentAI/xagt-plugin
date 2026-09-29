from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "scripts" / "container-entrypoint.sh"
SMOKE = ROOT / "scripts" / "container_smoke.sh"


def _production_env() -> dict[str, str]:
    return {
        "PATH": os.environ["PATH"],
        "MARKETPLACE_DEPLOYMENT_MODE": "production",
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PORT": "5432",
        "POSTGRES_USER": "clink@operator",
        "POSTGRES_PASSWORD": "pa@ss: cash$money with space",
        "POSTGRES_DB": "clink marketplace",
        "POSTGRES_ADMIN_PASSWORD": "admin@pass: cash$money with space",
        "POSTGRES_MIGRATION_PASSWORD": "migrate@pass: cash$money with space",
        "POSTGRES_API_PASSWORD": "api@pass: cash$money with space",
        "POSTGRES_WORKER_PASSWORD": "worker@pass: cash$money with space",
        "REDIS_URL": "redis://redis:6379/1",
        "MARKETPLACE_INTERNAL_API_TOKEN": "marketplace@internal: token$money with spaces-32",
        "CLINK_CORE_INTERNAL_API_TOKEN": "core@internal: token$money with spaces-at-least-32",
        "CLINK_CORE_ACTION_SERVICE_URL": "http://core:8016",
        "CLINK_CORE_POLICY_SERVICE_URL": "http://core:8015",
        "CLINK_CORE_AUDIT_SERVICE_URL": "http://core:8017",
        "CLINK_CORE_FUNDING_SERVICE_URL": "http://core:8018",
        "MARKETPLACE_ADMIN_WALLETS": "0x1111111111111111111111111111111111111111",
        "MARKETPLACE_ADMIN_DISABLED": "false",
        "MARKETPLACE_SIWE_ALLOWED_DOMAINS": "marketplace.example",
    }


def test_database_url_builder_preserves_special_characters(monkeypatch):
    container_config = importlib.import_module("shared.container_config")
    values = _production_env()
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    parsed = make_url(container_config.build_database_url())

    assert parsed.username == values["POSTGRES_USER"]
    assert parsed.password == values["POSTGRES_PASSWORD"]
    assert parsed.host == values["POSTGRES_HOST"]
    assert parsed.port == 5432
    assert parsed.database == values["POSTGRES_DB"]


def test_alembic_url_escaping_preserves_percent_encoded_database_password():
    container_config = importlib.import_module("shared.container_config")
    raw_url = container_config.build_database_url(_production_env())
    alembic_config = Config()

    alembic_config.set_main_option(
        "sqlalchemy.url", container_config.escape_alembic_url(raw_url)
    )

    assert alembic_config.get_main_option("sqlalchemy.url") == raw_url


def test_container_preflight_accepts_explicit_admin_disabled_mode():
    environment = _production_env()
    environment["MARKETPLACE_ADMIN_WALLETS"] = ""
    environment["MARKETPLACE_ADMIN_DISABLED"] = "true"
    result = subprocess.run(
        [str(ENTRYPOINT), "preflight", "api"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("MARKETPLACE_INTERNAL_API_TOKEN", ""),
        ("CLINK_CORE_INTERNAL_API_TOKEN", "replace-with-the-same-secret-as-clink-core"),
        ("POSTGRES_PASSWORD", "short"),
    ],
)
def test_container_preflight_rejects_missing_or_weak_production_secrets(field, value):
    environment = _production_env()
    environment[field] = value

    result = subprocess.run(
        [str(ENTRYPOINT), "preflight", "api"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert field in result.stderr


def test_container_preflight_requires_explicit_admin_disable():
    environment = _production_env()
    environment["MARKETPLACE_ADMIN_WALLETS"] = ""
    environment["MARKETPLACE_ADMIN_DISABLED"] = "false"

    result = subprocess.run(
        [str(ENTRYPOINT), "preflight", "api"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "MARKETPLACE_ADMIN_WALLETS" in result.stderr


def test_mcp_preflight_only_requires_its_api_and_listener_configuration():
    environment = {
        "PATH": os.environ["PATH"],
        "MARKETPLACE_DEPLOYMENT_MODE": "production",
        "MARKETPLACE_INTERNAL_API_TOKEN": "mcp-to-api-token-at-least-32-characters",
        "MARKETPLACE_REGISTRY_HOST": "marketplace-api",
        "MARKETPLACE_REGISTRY_PORT": "8050",
        "MARKETPLACE_MCP_HOST": "0.0.0.0",
        "MARKETPLACE_MCP_PORT": "9050",
    }

    result = subprocess.run(
        [str(ENTRYPOINT), "preflight", "mcp"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_worker_preflight_only_requires_database_and_core_token():
    environment = {
        key: value
        for key, value in _production_env().items()
        if key not in {
            "MARKETPLACE_INTERNAL_API_TOKEN",
            "MARKETPLACE_ADMIN_WALLETS",
            "MARKETPLACE_ADMIN_DISABLED",
        }
    }

    result = subprocess.run(
        [str(ENTRYPOINT), "preflight", "worker"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_migrate_preflight_only_requires_database_configuration():
    environment = {
        "PATH": os.environ["PATH"],
        "MARKETPLACE_DEPLOYMENT_MODE": "production",
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PORT": "5432",
        "POSTGRES_USER": "clink",
        "POSTGRES_PASSWORD": "migration-password-at-least-16",
        "POSTGRES_DB": "clink_marketplace",
    }

    result = subprocess.run(
        [str(ENTRYPOINT), "preflight", "migrate"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker compose CLI unavailable")
def test_compose_preserves_special_env_values_without_embedding_password_in_yaml(tmp_path):
    env_file = tmp_path / "marketplace.env"
    values = _production_env()
    env_file.write_text(
        "\n".join(f"{key}='{value}'" for key, value in values.items() if key != "PATH")
        + "\nMARKETPLACE_API_PUBLISHED_PORT=18050\n"
        + "MARKETPLACE_MCP_PUBLISHED_PORT=19050\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "--file",
            str(ROOT / "docker-compose.yml"),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    image_roles = (
        "migrate",
        "marketplace-api",
        "marketplace-worker",
        "marketplace-mcp",
    )
    assert len({services[name]["image"] for name in image_roles}) == 1
    assert {name for name in image_roles if services[name].get("build")} == {
        "marketplace-api"
    }
    postgres_environment = services["postgres"]["environment"]
    assert postgres_environment["POSTGRES_PASSWORD"].replace("$$", "$") == values["POSTGRES_ADMIN_PASSWORD"]
    for name in (
        "POSTGRES_MIGRATION_PASSWORD",
        "POSTGRES_API_PASSWORD",
        "POSTGRES_WORKER_PASSWORD",
    ):
        assert postgres_environment[name].replace("$$", "$") == values[name]
    assert "MARKETPLACE_INTERNAL_API_TOKEN" not in postgres_environment
    assert "CLINK_CORE_INTERNAL_API_TOKEN" not in postgres_environment
    migrate_environment = services["migrate"]["environment"]
    assert migrate_environment["POSTGRES_USER"] == "clink_marketplace_migrate"
    assert migrate_environment["POSTGRES_PASSWORD"].replace("$$", "$") == values["POSTGRES_MIGRATION_PASSWORD"]
    for forbidden in (
        "MARKETPLACE_INTERNAL_API_TOKEN",
        "CLINK_CORE_INTERNAL_API_TOKEN",
        "MARKETPLACE_ADMIN_WALLETS",
        "MARKETPLACE_ADMIN_DISABLED",
        "REDIS_URL",
    ):
        assert forbidden not in migrate_environment

    mcp_environment = services["marketplace-mcp"]["environment"]
    assert mcp_environment["MARKETPLACE_INTERNAL_API_TOKEN"].replace("$$", "$") == values["MARKETPLACE_INTERNAL_API_TOKEN"]
    for forbidden in (
        "POSTGRES_PASSWORD",
        "POSTGRES_USER",
        "POSTGRES_DB",
        "REDIS_URL",
        "CLINK_CORE_INTERNAL_API_TOKEN",
        "CLINK_CORE_ACTION_SERVICE_URL",
        "CLINK_CORE_POLICY_SERVICE_URL",
        "CLINK_CORE_AUDIT_SERVICE_URL",
        "CLINK_CORE_FUNDING_SERVICE_URL",
        "MARKETPLACE_ADMIN_WALLETS",
        "MARKETPLACE_ADMIN_DISABLED",
    ):
        assert forbidden not in mcp_environment

    worker_environment = services["marketplace-worker"]["environment"]
    assert worker_environment["POSTGRES_USER"] == "clink_marketplace_worker"
    assert worker_environment["POSTGRES_PASSWORD"].replace("$$", "$") == values["POSTGRES_WORKER_PASSWORD"]
    assert worker_environment["CLINK_CORE_INTERNAL_API_TOKEN"].replace("$$", "$") == values["CLINK_CORE_INTERNAL_API_TOKEN"]
    for forbidden in (
        "MARKETPLACE_INTERNAL_API_TOKEN",
        "MARKETPLACE_ADMIN_WALLETS",
        "MARKETPLACE_ADMIN_DISABLED",
    ):
        assert forbidden not in worker_environment

    api_environment = services["marketplace-api"]["environment"]
    assert api_environment["POSTGRES_USER"] == "clink_marketplace_api"
    assert api_environment["POSTGRES_PASSWORD"].replace("$$", "$") == values["POSTGRES_API_PASSWORD"]
    for name in (
        "POSTGRES_PASSWORD",
        "MARKETPLACE_INTERNAL_API_TOKEN",
        "CLINK_CORE_INTERNAL_API_TOKEN",
        "MARKETPLACE_ADMIN_WALLETS",
    ):
        assert name in api_environment

    for role in ("migrate", "marketplace-api", "marketplace-worker", "marketplace-mcp"):
        assert "MARKETPLACE_DATABASE_URL" not in services[role]["environment"]
    assert len({
        migrate_environment["POSTGRES_PASSWORD"],
        api_environment["POSTGRES_PASSWORD"],
        worker_environment["POSTGRES_PASSWORD"],
    }) == 3
    assert values["POSTGRES_PASSWORD"] not in (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def test_smoke_diagnostics_ignore_external_production_project_name():
    script = SMOKE.read_text(encoding="utf-8")
    assert "--print-project-name" in script
    assert "compose build marketplace-api" in script
    assert "compose up --detach --no-build --pull never" in script
    assert "compose logs postgres migrate" in script
    environment = os.environ.copy()
    environment["COMPOSE_PROJECT_NAME"] = "clink-marketplace"

    result = subprocess.run(
        [str(SMOKE), "--print-project-name"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("clink-marketplace-smoke-")
    assert result.stdout.strip() != "clink-marketplace"


def test_smoke_cleanup_guard_rejects_production_project_name_without_docker():
    script = SMOKE.read_text(encoding="utf-8")
    assert "--check-cleanup-project" in script
    result = subprocess.run(
        [str(SMOKE), "--check-cleanup-project", "clink-marketplace"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "refusing volume cleanup" in result.stderr.lower()


def test_container_smoke_checks_runtime_web_assets_and_non_root_user():
    script = SMOKE.read_text(encoding="utf-8")

    for asset in (
        "/app/web/merchant.html",
        "/app/web/admin.html",
        "/app/web/assets/merchant.js",
        "/app/web/assets/admin.js",
        "/app/web/assets/console.css",
    ):
        assert asset in script
    assert "id -u" in script
    assert '"${runtime_uid}" == "0"' in script


def test_runtime_image_uses_allowlist_copy_and_ignores_common_secret_files():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "COPY --chown=clink:clink . ." not in dockerfile
    for required in (
        "adapters",
        "clink_middleware",
        "mcp_servers",
        "migrations",
        "services",
        "shared",
        "storage",
        "web",
        "alembic.ini",
        "scripts/container-entrypoint.sh",
    ):
        assert required in dockerfile
    for pattern in (
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "credentials*.json",
        "secrets",
    ):
        assert pattern in dockerignore
