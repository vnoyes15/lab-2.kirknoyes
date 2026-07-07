-- Section 70 — JV & Complex Equity Structure Modeling. Every waterfall run is stored,
-- not just returned and discarded — same "human decision worth a record" reasoning as
-- scenario_models (Section 63). structure_type distinguishes the five supported
-- structures; inputs/outputs are stored as jsonb since each structure has its own
-- input schema and output format (Section 70), not a shared fixed column set.
create table if not exists equity_waterfalls (
    waterfall_id uuid primary key default gen_random_uuid(),
    deal_id uuid not null references deals(deal_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    structure_type text not null check (structure_type in (
        'simple_lp_gp', 'preferred_equity', 'jv_co_gp', 'mezzanine', 'ground_lease'
    )),
    inputs jsonb not null,
    outputs jsonb not null,

    created_by_user_id uuid,
    created_at timestamptz not null default now()
);

create index if not exists idx_equity_waterfalls_deal_id on equity_waterfalls (deal_id, created_at);

select arx_apply_org_rls('equity_waterfalls');
