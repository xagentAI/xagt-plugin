#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.yml"
SMOKE_PROJECT_PREFIX="clink-marketplace-smoke-"

new_suffix() {
  python3 -c 'import secrets; print(secrets.token_hex(8))'
}

safe_smoke_project() {
  [[ "$1" =~ ^clink-marketplace-smoke-[0-9a-f]{16}$ ]]
}

require_safe_cleanup_project() {
  if ! safe_smoke_project "$1"; then
    printf 'Refusing volume cleanup for unsafe Compose project: %s\n' "$1" >&2
    return 1
  fi
}

# Diagnostic modes intentionally run before Docker or temporary-file setup.
if [[ "${1:-}" == "--print-project-name" ]]; then
  printf '%s%s\n' "${SMOKE_PROJECT_PREFIX}" "$(new_suffix)"
  exit 0
fi
if [[ "${1:-}" == "--check-cleanup-project" ]]; then
  require_safe_cleanup_project "${2:-}"
  exit 0
fi
if [[ $# -gt 0 ]]; then
  printf 'usage: %s [--print-project-name | --check-cleanup-project NAME]\n' "$0" >&2
  exit 2
fi

suffix="$(new_suffix)"
# Never inherit an operator's production project name.
COMPOSE_PROJECT_NAME="${SMOKE_PROJECT_PREFIX}${suffix}"
require_safe_cleanup_project "${COMPOSE_PROJECT_NAME}"

random_port() {
  python3 -c 'import socket; sock=socket.socket(); sock.bind(("127.0.0.1", 0)); print(sock.getsockname()[1]); sock.close()'
}

api_port="${MARKETPLACE_SMOKE_API_PORT:-$(random_port)}"
mcp_port="${MARKETPLACE_SMOKE_MCP_PORT:-$(random_port)}"
while [[ "${mcp_port}" == "${api_port}" ]]; do
  mcp_port="$(random_port)"
done

umask 077
TEMP_DIR="$(mktemp -d)"
TEMP_ENV="${TEMP_DIR}/marketplace.env"
SENTINEL_FILE="${ROOT_DIR}/container-smoke-secret-${suffix}.pem"
STARTED=0

export COMPOSE_PROJECT_NAME
export MARKETPLACE_API_PUBLISHED_PORT="${api_port}"
export MARKETPLACE_MCP_PUBLISHED_PORT="${mcp_port}"
export MARKETPLACE_IMAGE_TAG="container-smoke-${suffix}"

compose() {
  docker compose --env-file "${TEMP_ENV}" --file "${COMPOSE_FILE}" "$@"
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  if [[ "${STARTED}" == "1" ]]; then
    if require_safe_cleanup_project "${COMPOSE_PROJECT_NAME}"; then
      compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    fi
  fi
  rm -f "${SENTINEL_FILE}"
  rm -rf "${TEMP_DIR}"
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

cat >"${TEMP_ENV}" <<EOF
MARKETPLACE_DEPLOYMENT_MODE=production
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=clink_marketplace
POSTGRES_ADMIN_PASSWORD='container@admin: cash\$money with space'
POSTGRES_MIGRATION_PASSWORD='container@migrate: cash\$money with space'
POSTGRES_API_PASSWORD='container@api: cash\$money with space'
POSTGRES_WORKER_PASSWORD='container@worker: cash\$money with space'
REDIS_URL=redis://127.0.0.1:6379/1
MARKETPLACE_IMAGE_TAG=${MARKETPLACE_IMAGE_TAG}
MARKETPLACE_API_PUBLISHED_PORT=${MARKETPLACE_API_PUBLISHED_PORT}
MARKETPLACE_MCP_PUBLISHED_PORT=${MARKETPLACE_MCP_PUBLISHED_PORT}
MARKETPLACE_INTERNAL_API_TOKEN=container-smoke-marketplace-token-at-least-32-characters
CLINK_CORE_INTERNAL_API_TOKEN=container-smoke-core-token-at-least-32-characters
MARKETPLACE_ADMIN_WALLETS=
MARKETPLACE_ADMIN_DISABLED=true
MARKETPLACE_NATIVE_PROVIDER_IDS=
MARKETPLACE_SIWE_ALLOWED_DOMAINS=marketplace.clink.local
MARKETPLACE_PEER_REGISTRIES_JSON=[]
MARKETPLACE_EIP3009_DOMAINS_JSON={}
MARKETPLACE_BAZAAR_SYNC_QUERIES=container-smoke-no-match
MARKETPLACE_WORKER_CYCLE_INTERVAL_SECONDS=300
MARKETPLACE_WORKER_STAGE_TIMEOUT_SECONDS=120
MARKETPLACE_WORKER_HEARTBEAT_TIMEOUT_SECONDS=600
CLINK_CORE_ACTION_SERVICE_URL=http://host.docker.internal:8016
CLINK_CORE_POLICY_SERVICE_URL=http://host.docker.internal:8015
CLINK_CORE_AUDIT_SERVICE_URL=http://host.docker.internal:8017
CLINK_CORE_FUNDING_SERVICE_URL=http://host.docker.internal:8018
EOF

printf 'do-not-copy-this-secret\n' >"${SENTINEL_FILE}"

required_services=(postgres redis migrate marketplace-api marketplace-worker marketplace-mcp)
rendered_services="$(compose config --services)"
for service in "${required_services[@]}"; do
  if ! grep -qx "${service}" <<<"${rendered_services}"; then
    printf 'missing Compose service: %s\n' "${service}" >&2
    exit 1
  fi
done

compose config >/dev/null
compose config --format json >"${TEMP_DIR}/compose.json"
python3 - "${TEMP_DIR}/compose.json" "${api_port}" "${mcp_port}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)

api_port = int(sys.argv[2])
mcp_port = int(sys.argv[3])
services = config["services"]
for service in ("postgres", "redis"):
    assert not services[service].get("ports"), f"{service} must not publish host ports"

for service, target, published_port in (
    ("marketplace-api", 8050, api_port),
    ("marketplace-mcp", 9050, mcp_port),
):
    published = services[service].get("ports", [])
    assert len(published) == 1, f"{service} must publish exactly one port"
    assert published[0].get("host_ip") == "127.0.0.1"
    assert int(published[0].get("target")) == target
    assert int(published[0].get("published")) == published_port

images = {
    services[name]["image"]
    for name in ("migrate", "marketplace-api", "marketplace-worker", "marketplace-mcp")
}
assert len(images) == 1, "all Marketplace roles must share one image"
assert {
    name
    for name in ("migrate", "marketplace-api", "marketplace-worker", "marketplace-mcp")
    if services[name].get("build")
} == {"marketplace-api"}, "the shared image must be built exactly once"

for name in ("marketplace-api", "marketplace-worker", "marketplace-mcp"):
    dependencies = services[name]["depends_on"]
    assert dependencies["migrate"]["condition"] == "service_completed_successfully"
    assert dependencies["postgres"]["condition"] == "service_healthy"
    assert dependencies["redis"]["condition"] == "service_healthy"

migrate = services["migrate"]["environment"]
assert migrate["POSTGRES_HOST"] == "postgres"
assert migrate["POSTGRES_USER"] == "clink_marketplace_migrate"
assert "REDIS_URL" not in migrate
assert "MARKETPLACE_INTERNAL_API_TOKEN" not in migrate
assert "CLINK_CORE_INTERNAL_API_TOKEN" not in migrate
assert "MARKETPLACE_ADMIN_WALLETS" not in migrate
assert "MARKETPLACE_ADMIN_DISABLED" not in migrate

api = services["marketplace-api"]["environment"]
assert api["POSTGRES_HOST"] == "postgres"
assert api["POSTGRES_USER"] == "clink_marketplace_api"
assert api["REDIS_URL"] == "redis://redis:6379/1"
assert api["MARKETPLACE_INTERNAL_API_TOKEN"]
assert api["CLINK_CORE_INTERNAL_API_TOKEN"]

worker = services["marketplace-worker"]["environment"]
assert worker["POSTGRES_HOST"] == "postgres"
assert worker["POSTGRES_USER"] == "clink_marketplace_worker"
assert worker["REDIS_URL"] == "redis://redis:6379/1"
assert worker["CLINK_CORE_INTERNAL_API_TOKEN"]
assert "MARKETPLACE_INTERNAL_API_TOKEN" not in worker
assert "MARKETPLACE_ADMIN_WALLETS" not in worker
assert "MARKETPLACE_ADMIN_DISABLED" not in worker

mcp = services["marketplace-mcp"]["environment"]
assert mcp["MARKETPLACE_INTERNAL_API_TOKEN"]
for forbidden in (
    "POSTGRES_PASSWORD",
    "REDIS_URL",
    "CLINK_CORE_INTERNAL_API_TOKEN",
    "CLINK_CORE_ACTION_SERVICE_URL",
    "CLINK_CORE_POLICY_SERVICE_URL",
    "CLINK_CORE_AUDIT_SERVICE_URL",
    "CLINK_CORE_FUNDING_SERVICE_URL",
    "MARKETPLACE_ADMIN_WALLETS",
    "MARKETPLACE_ADMIN_DISABLED",
):
    assert forbidden not in mcp

for name in ("migrate", "marketplace-api", "marketplace-worker", "marketplace-mcp"):
    assert "MARKETPLACE_DATABASE_URL" not in services[name]["environment"]

assert services["postgres"]["environment"]["POSTGRES_USER"] == "clink_marketplace_admin"
assert services["redis"]["command"] == ["redis-server", "--save", "", "--appendonly", "no"]
assert services["redis"].get("tmpfs")
assert not services["redis"].get("volumes")
assert services["marketplace-mcp"]["environment"]["MARKETPLACE_REGISTRY_HOST"] == "marketplace-api"
PY

STARTED=1
compose build marketplace-api
if ! compose up --detach --no-build --pull never; then
  compose logs postgres migrate >&2 || true
  exit 1
fi

runtime_uid="$(docker run --rm --entrypoint sh "clink-marketplace:${MARKETPLACE_IMAGE_TAG}" -c 'id -u')"
if [[ "${runtime_uid}" == "0" || ! "${runtime_uid}" =~ ^[0-9]+$ ]]; then
  printf 'runtime image must not run as root\n' >&2
  exit 1
fi
docker run --rm --entrypoint sh "clink-marketplace:${MARKETPLACE_IMAGE_TAG}" \
  -eu -c '
    for asset in \
      /app/web/merchant.html \
      /app/web/admin.html \
      /app/web/assets/merchant.js \
      /app/web/assets/admin.js \
      /app/web/assets/console.css
    do
      test -r "${asset}"
    done
    test ! -e "/app/$1"
  ' image-contract "$(basename "${SENTINEL_FILE}")"

migrate_id="$(compose ps --all --quiet migrate)"
if [[ -z "${migrate_id}" ]]; then
  printf 'migrate container was not created\n' >&2
  exit 1
fi
for _ in $(seq 1 60); do
  migrate_status="$(docker inspect --format '{{.State.Status}}' "${migrate_id}")"
  if [[ "${migrate_status}" == "exited" || "${migrate_status}" == "dead" ]]; then
    break
  fi
  sleep 1
done
if [[ "${migrate_status:-unknown}" != "exited" ]]; then
  printf 'migrate container did not finish successfully (status: %s)\n' "${migrate_status:-unknown}" >&2
  compose logs migrate >&2
  exit 1
fi
if [[ "$(docker inspect --format '{{.State.ExitCode}}' "${migrate_id}")" != "0" ]]; then
  compose logs migrate >&2
  exit 1
fi

role_contract="$(compose exec -T postgres psql \
  --username clink_marketplace_admin \
  --dbname clink_marketplace \
  --tuples-only --no-align \
  --command "SELECT rolname || ':' || rolsuper::text || ':' || rolcreatedb::text || ':' || rolcreaterole::text FROM pg_roles WHERE rolname IN ('clink_marketplace_api', 'clink_marketplace_migrate', 'clink_marketplace_worker') ORDER BY rolname")"
grep -qx 'clink_marketplace_api:false:false:false' <<<"${role_contract}"
grep -qx 'clink_marketplace_worker:false:false:false' <<<"${role_contract}"
grep -qx 'clink_marketplace_migrate:false:false:false' <<<"${role_contract}"

database_owner="$(compose exec -T postgres psql \
  --username clink_marketplace_admin \
  --dbname clink_marketplace \
  --tuples-only --no-align \
  --command "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()")"
[[ "${database_owner}" == "clink_marketplace_migrate" ]]

for runtime_role in clink_marketplace_api clink_marketplace_worker; do
  schema_create="$(compose exec -T postgres psql \
    --username clink_marketplace_admin \
    --dbname clink_marketplace \
    --tuples-only --no-align \
    --command "SELECT has_schema_privilege('${runtime_role}', 'public', 'CREATE')")"
  [[ "${schema_create}" == "f" ]]
  table_dml="$(compose exec -T postgres psql \
    --username clink_marketplace_admin \
    --dbname clink_marketplace \
    --tuples-only --no-align \
    --command "SELECT has_table_privilege('${runtime_role}', 'providers', 'SELECT, INSERT, UPDATE, DELETE')")"
  [[ "${table_dml}" == "t" ]]
done

curl --fail --silent --show-error --retry 30 --retry-delay 2 \
  --retry-connrefused "http://127.0.0.1:${api_port}/livez" >/dev/null
curl --fail --silent --show-error --head --retry 30 --retry-delay 2 \
  --retry-connrefused "http://127.0.0.1:${mcp_port}/mcp/" >/dev/null

running_services="$(compose ps --status running --services)"
grep -qx 'marketplace-worker' <<<"${running_services}"
grep -qx 'marketplace-api' <<<"${running_services}"
grep -qx 'marketplace-mcp' <<<"${running_services}"

printf 'Clink Marketplace container smoke passed (project %s).\n' "${COMPOSE_PROJECT_NAME}"
