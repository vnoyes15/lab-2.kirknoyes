-- Section 06/63 — scenario_models. Multiple named scenarios per deal. Scenarios are
-- analytical tools, not active versions — never confuse with deal_snapshots.
create table if not exists scenario_models (
    scenario_id uuid primary key default gen_random_uuid(),
    deal_id uuid not null references deals(deal_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    scenario_name text not null,
    assumption_overrides jsonb not null,
    output_payload jsonb,

    created_by_user_id uuid,
    created_at timestamptz not null default now()
);

create index if not exists idx_scenario_models_deal_id on scenario_models (deal_id);

select arx_apply_org_rls('scenario_models');
