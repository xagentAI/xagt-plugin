#!/usr/bin/env sh
set -eu

role="${1:-api}"

prepare_runtime() {
  runtime_role="$1"
  python -m shared.container_config preflight "${runtime_role}"
  case "${runtime_role}" in
    api|worker|migrate)
      MARKETPLACE_DATABASE_URL="$(python -m shared.container_config database-url)"
      export MARKETPLACE_DATABASE_URL
      ;;
  esac
  case "${runtime_role}" in
    api|worker)
      export MARKETPLACE_REDIS_URL="${REDIS_URL}"
      ;;
  esac
  export MARKETPLACE_PROCESS_ROLE="${runtime_role}"
}

case "${role}" in
  api)
    prepare_runtime api
    exec uvicorn services.marketplace_app:app \
      --host "${MARKETPLACE_REGISTRY_HOST:-0.0.0.0}" \
      --port "${MARKETPLACE_REGISTRY_PORT:-8050}"
    ;;
  worker)
    prepare_runtime worker
    exec python -m services.marketplace_worker
    ;;
  mcp)
    prepare_runtime mcp
    exec python -m mcp_servers.marketplace_server
    ;;
  migrate)
    prepare_runtime migrate
    exec python -m alembic upgrade head
    ;;
  preflight)
    prepare_runtime "${2:?container role is required}"
    ;;
  health-api)
    exec python -c 'import os, urllib.request; port=os.getenv("MARKETPLACE_REGISTRY_PORT", "8050"); urllib.request.urlopen(f"http://127.0.0.1:{port}/livez", timeout=2).read()'
    ;;
  health-mcp)
    exec python -c 'import http.client, os; port=int(os.getenv("MARKETPLACE_MCP_PORT", "9050")); connection=http.client.HTTPConnection("127.0.0.1", port, timeout=2); connection.request("HEAD", "/mcp/"); response=connection.getresponse(); response.read(); connection.close(); assert response.status in {200, 307, 405, 406}, response.status'
    ;;
  *)
    exec "$@"
    ;;
esac
