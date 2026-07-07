-- Section 49 — LP Trust Layer access model. LP Viewer role scoped to specific deals via
-- this table. LP token can only query records where their user_id is in deal_lp_access.
-- Zero cross-deal visibility.
create table if not exists deal_lp_access (
    access_id uuid primary key default gen_random_uuid(),
    deal_id uuid not null references deals(deal_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    lp_user_id uuid not null,
    granted_at timestamptz not null default now(),
    granted_by_user_id uuid,

    unique (deal_id, lp_user_id)
);

create index if not exists idx_deal_lp_access_lp_user_id on deal_lp_access (lp_user_id);

select arx_apply_org_rls('deal_lp_access');
