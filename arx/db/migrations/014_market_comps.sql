-- Section 17 — Market Data Layer. "Phase 1: manual comp entry to market_comps table."
-- No comp data = explicit statement in agent output, never silence, never fabricated
-- (enforced in agent schemas starting Phase 2 — see A-02 no_comp_disclaimer, Section 87).
create table if not exists market_comps (
    comp_id uuid primary key default gen_random_uuid(),
    org_id uuid not null references orgs(org_id) on delete cascade,

    submarket text not null,
    asset_type text,
    cap_rate numeric check (cap_rate is null or cap_rate > 0),
    price_per_unit numeric,
    sale_date date,
    source text,
    entered_by_user_id uuid,

    created_at timestamptz not null default now()
);

create index if not exists idx_market_comps_org_submarket on market_comps (org_id, submarket, sale_date desc);

select arx_apply_org_rls('market_comps');
