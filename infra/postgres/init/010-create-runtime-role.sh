#!/bin/sh
set -eu

psql \
  --username "$POSTGRES_USER" \
  --dbname postgres \
  --set=app_user="$PRIVEXA_APP_DB_USER" \
  --set=app_password="$PRIVEXA_APP_DB_PASSWORD" \
  --set=owner_user="$POSTGRES_USER" \
  --set=test_database="$PRIVEXA_TEST_DB" <<'SQL'
SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
    :'app_user',
    :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec

-- Reassert the security posture for an existing development role as well. The application also
-- verifies these attributes at startup, so a bypass-capable role cannot fail open silently.
SELECT format(
    'ALTER ROLE %I NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
    :'app_user'
)
\gexec

SELECT format(
    'CREATE DATABASE %I OWNER %I',
    :'test_database',
    :'owner_user'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'test_database')
\gexec
SQL

for database_name in "$POSTGRES_DB" "$PRIVEXA_TEST_DB"; do
  psql \
    --username "$POSTGRES_USER" \
    --dbname "$database_name" \
    --set=app_user="$PRIVEXA_APP_DB_USER" \
    --set=owner_user="$POSTGRES_USER" <<'SQL'
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'app_user')
\gexec

SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'app_user')
\gexec

SELECT format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
    :'owner_user',
    :'app_user'
)
\gexec
SQL
done
