#!/usr/bin/env sh
set -eu

: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_MIGRATION_PASSWORD:?POSTGRES_MIGRATION_PASSWORD is required}"
: "${POSTGRES_API_PASSWORD:?POSTGRES_API_PASSWORD is required}"
: "${POSTGRES_WORKER_PASSWORD:?POSTGRES_WORKER_PASSWORD is required}"

psql \
  --set=ON_ERROR_STOP=1 \
  --set=database_name="${POSTGRES_DB}" \
  --set=migration_password="${POSTGRES_MIGRATION_PASSWORD}" \
  --set=api_password="${POSTGRES_API_PASSWORD}" \
  --set=worker_password="${POSTGRES_WORKER_PASSWORD}" \
  --username "${POSTGRES_USER}" \
  --dbname "${POSTGRES_DB}" <<'SQL'
SELECT format(
  'CREATE ROLE clink_marketplace_migrate LOGIN NOINHERIT PASSWORD %L',
  :'migration_password'
) WHERE NOT EXISTS (
  SELECT 1 FROM pg_roles WHERE rolname = 'clink_marketplace_migrate'
) \gexec
SELECT format(
  'CREATE ROLE clink_marketplace_api LOGIN NOINHERIT PASSWORD %L',
  :'api_password'
) WHERE NOT EXISTS (
  SELECT 1 FROM pg_roles WHERE rolname = 'clink_marketplace_api'
) \gexec
SELECT format(
  'CREATE ROLE clink_marketplace_worker LOGIN NOINHERIT PASSWORD %L',
  :'worker_password'
) WHERE NOT EXISTS (
  SELECT 1 FROM pg_roles WHERE rolname = 'clink_marketplace_worker'
) \gexec

ALTER ROLE clink_marketplace_migrate PASSWORD :'migration_password';
ALTER ROLE clink_marketplace_api PASSWORD :'api_password';
ALTER ROLE clink_marketplace_worker PASSWORD :'worker_password';

ALTER DATABASE :"database_name" OWNER TO clink_marketplace_migrate;
REVOKE CREATE ON DATABASE :"database_name" FROM PUBLIC;
GRANT CONNECT, CREATE ON DATABASE :"database_name" TO clink_marketplace_migrate;
GRANT CONNECT ON DATABASE :"database_name" TO clink_marketplace_api;
GRANT CONNECT ON DATABASE :"database_name" TO clink_marketplace_worker;

ALTER SCHEMA public OWNER TO clink_marketplace_migrate;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO clink_marketplace_api;
GRANT USAGE ON SCHEMA public TO clink_marketplace_worker;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
  TO clink_marketplace_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
  TO clink_marketplace_worker;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public
  TO clink_marketplace_api;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public
  TO clink_marketplace_worker;

ALTER DEFAULT PRIVILEGES FOR ROLE clink_marketplace_migrate IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO clink_marketplace_api;
ALTER DEFAULT PRIVILEGES FOR ROLE clink_marketplace_migrate IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO clink_marketplace_worker;
ALTER DEFAULT PRIVILEGES FOR ROLE clink_marketplace_migrate IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO clink_marketplace_api;
ALTER DEFAULT PRIVILEGES FOR ROLE clink_marketplace_migrate IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO clink_marketplace_worker;
SQL
