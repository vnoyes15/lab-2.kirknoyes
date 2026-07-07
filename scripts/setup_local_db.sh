#!/usr/bin/env bash
# Local-only Postgres bootstrap for Section 86's setup guide (S1-S10), for developers
# without a hosted Supabase project handy yet. Idempotent — safe to re-run.
#
# Creates:
#   - database arx_dev
#   - role `arx` (NOSUPERUSER, NOBYPASSRLS) — the RLS-bound role APP_DATABASE_URL points
#     at. This is the single most important role in this script: a superuser or
#     BYPASSRLS connection makes every RLS policy in arx/db/migrations/ silently do
#     nothing, which is exactly the bug this script exists to make impossible to
#     reintroduce by accident.
#
# Then applies migrations (with the local auth.jwt() shim) and grants the `arx` role
# what it needs to actually query the resulting tables.
#
# Requires: a local Postgres superuser reachable as `postgres`/`postgres` on
# 127.0.0.1:5432 (matches .env.example). Adjust PGHOST/PGUSER/PGPASSWORD below for a
# different local setup.
set -euo pipefail

PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
PGSUPERUSER="${PGSUPERUSER:-postgres}"
export PGPASSWORD="${PGSUPERUSER_PASSWORD:-postgres}"

psql -h "$PGHOST" -p "$PGPORT" -U "$PGSUPERUSER" -d postgres -v ON_ERROR_STOP=1 <<'SQL'
do $$
begin
  if not exists (select from pg_roles where rolname = 'arx') then
    create role arx with login password 'arx' nosuperuser nobypassrls;
  end if;
end
$$;

select 'CREATE DATABASE arx_dev'
where not exists (select from pg_database where datname = 'arx_dev')
\gexec
SQL

psql -h "$PGHOST" -p "$PGPORT" -U "$PGSUPERUSER" -d arx_dev -v ON_ERROR_STOP=1 <<'SQL'
grant all on schema public to arx;
alter default privileges in schema public grant all on tables to arx;
alter default privileges in schema public grant all on sequences to arx;
SQL

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATABASE_URL="postgresql://${PGSUPERUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/arx_dev"

python3 "$REPO_ROOT/scripts/migrate.py" --local-dev-shim --database-url "$DATABASE_URL"

psql -h "$PGHOST" -p "$PGPORT" -U "$PGSUPERUSER" -d arx_dev -v ON_ERROR_STOP=1 <<'SQL'
grant usage on schema auth to arx;
grant execute on all functions in schema auth to arx;
grant usage on schema public to arx;
grant all on all tables in schema public to arx;
SQL

echo
echo "Local arx_dev database ready."
echo "  DATABASE_URL     (migrations/scripts, bypasses RLS): $DATABASE_URL"
echo "  APP_DATABASE_URL (running API, RLS-bound):           postgresql://arx:arx@${PGHOST}:${PGPORT}/arx_dev"
echo
echo "Next: DATABASE_URL=\"$DATABASE_URL\" python3 scripts/seed_org.py"
