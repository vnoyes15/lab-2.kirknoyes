-- Arx Phase 1 — foundation helpers
-- gen_random_uuid() is built into PostgreSQL core since v13, no extension required.

-- Every table in Section 06 is org-scoped and RLS-isolated (Section 09, MT1, MT4/G-02).
-- This helper is applied once per table rather than hand-rolling four CREATE POLICY
-- statements per migration (N7: "build critical systems once, correctly").
--
-- Assumes an `auth.jwt()` function returning the caller's JWT claims as jsonb, with an
-- `org_id` claim. Supabase provides this natively in production. For local/sandbox
-- testing without a live Supabase project, db/local_dev/auth_shim.sql provides an
-- equivalent shim — never applied against a real Supabase database (see scripts/migrate.py).
create or replace function arx_apply_org_rls(target_table regclass) returns void as $$
begin
  execute format('alter table %s enable row level security', target_table);
  execute format('alter table %s force row level security', target_table);

  execute format(
    'create policy org_isolation_select on %s for select using (org_id = (auth.jwt() ->> ''org_id'')::uuid)',
    target_table
  );
  execute format(
    'create policy org_isolation_insert on %s for insert with check (org_id = (auth.jwt() ->> ''org_id'')::uuid)',
    target_table
  );
  execute format(
    'create policy org_isolation_update on %s for update using (org_id = (auth.jwt() ->> ''org_id'')::uuid) with check (org_id = (auth.jwt() ->> ''org_id'')::uuid)',
    target_table
  );
  execute format(
    'create policy org_isolation_delete on %s for delete using (org_id = (auth.jwt() ->> ''org_id'')::uuid)',
    target_table
  );
end;
$$ language plpgsql;

-- Reusable updated_at trigger (used by several Section 06 tables).
create or replace function arx_set_updated_at() returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;
