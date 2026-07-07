-- LOCAL DEVELOPMENT ONLY. Never run against a real Supabase project — Supabase already
-- provides a real `auth` schema with `auth.jwt()` / `auth.uid()`, and running this against
-- it would try to redefine functions Supabase owns.
--
-- This shim exists so Phase 1's RLS policies (which call auth.jwt()) can be exercised
-- against a plain local/CI PostgreSQL instance without a hosted Supabase project.
-- It reproduces Supabase's actual mechanism: PostgREST sets the GUC
-- `request.jwt.claims` to the caller's JWT claims (as JSON text) per request, and
-- `auth.jwt()` reads it back out. Tests set this per-transaction with:
--   set local request.jwt.claims = '{"org_id": "...", "role": "analyst"}';
--
-- scripts/migrate.py only applies this file when --local-dev-shim is passed, and refuses
-- to apply it when DATABASE_URL points at a *.supabase.co host.
create schema if not exists auth;

create or replace function auth.jwt() returns jsonb as $$
    select nullif(current_setting('request.jwt.claims', true), '')::jsonb;
$$ language sql stable;

create or replace function auth.uid() returns uuid as $$
    select nullif(auth.jwt() ->> 'sub', '')::uuid;
$$ language sql stable;

create or replace function auth.role() returns text as $$
    select auth.jwt() ->> 'role';
$$ language sql stable;
